# SPDX-License-Identifier: GPL-3.0-only
"""Periodic drill dumping at the fixed v159.7 method boundary."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import mindustry_pythonista as m


def drill_world(ore=""):
    world = m.World(32, 24)
    world.sandbox = True
    world.place("core-shard", 2, 2, free=True)
    for x, y in ((10, 10), (11, 10), (10, 11), (11, 11)):
        world.ore[world.index(x, y)] = ore or "copper"
    drill = world.place("mechanical-drill", 10, 10, free=True)
    # Existing drills can outlive their ore. Placement itself needs ore.
    if not ore:
        for x, y in world.tiles(drill):
            world.ore[world.index(x, y)] = ""
    return world, drill


def periodic_dump(world, drill):
    drill.dump_ticks = 4
    world._tick_drill(drill)


class DrillDumpTests(unittest.TestCase):
    def test_stocked_dominant_item_precedes_inventory_insertion_order(self):
        world, drill = drill_world("lead")
        router = world.place("router", 12, 10, free=True)
        drill.inventory = {"copper": 1, "lead": 1}
        periodic_dump(world, drill)
        self.assertEqual(router.inventory, {"lead": 1})
        self.assertEqual(drill.inventory, {"copper": 1})

    def test_rejected_stocked_dominant_does_not_fall_back_to_other_item(self):
        world, drill = drill_world("lead")
        duo = world.place("duo", 12, 10, free=True)
        drill.inventory = {"lead": 1, "copper": 1}
        periodic_dump(world, drill)
        self.assertEqual(duo.ammo, 0)
        self.assertEqual(drill.inventory, {"lead": 1, "copper": 1})

    def test_unstocked_dominant_uses_available_item(self):
        world, drill = drill_world("lead")
        router = world.place("router", 12, 10, free=True)
        drill.inventory = {"copper": 1}
        periodic_dump(world, drill)
        self.assertEqual(router.inventory, {"copper": 1})
        self.assertEqual(drill.inventory, {})

    def test_no_dominant_uses_content_id_before_inventory_order(self):
        world, drill = drill_world()
        router = world.place("router", 12, 10, free=True)
        drill.inventory = {"lead": 1, "copper": 1}
        periodic_dump(world, drill)
        self.assertEqual(router.inventory, {"copper": 1})
        self.assertEqual(drill.inventory, {"lead": 1})

    def test_fallback_visits_neighbor_before_next_item(self):
        world, drill = drill_world()
        duo = world.place("duo", 12, 10, free=True)
        router = world.place("router", 10, 12, free=True)
        drill.inventory = {"lead": 1, "copper": 1}
        self.assertEqual([b.id for b in world.neighbors(drill)], [duo.id, router.id])
        periodic_dump(world, drill)
        self.assertEqual(duo.ammo, 2)
        self.assertEqual(router.inventory, {})
        self.assertEqual(drill.inventory, {"lead": 1})
        self.assertEqual(drill.cursor, 1)

    def test_failed_scan_normalizes_oversized_saved_cursor(self):
        world, drill = drill_world()
        world.place("copper-wall", 12, 10, free=True)
        world.place("copper-wall", 10, 12, free=True)
        drill.inventory = {"copper": 1}
        drill.cursor = 7
        periodic_dump(world, drill)
        self.assertEqual(drill.cursor, 1)
        self.assertEqual(drill.inventory, {"copper": 1})

    def test_failed_scan_preserves_normal_cursor(self):
        world, drill = drill_world()
        world.place("copper-wall", 12, 10, free=True)
        world.place("copper-wall", 10, 12, free=True)
        drill.inventory = {"lead": 1}
        drill.cursor = 1
        periodic_dump(world, drill)
        self.assertEqual(drill.cursor, 1)
        self.assertEqual(drill.inventory, {"lead": 1})

    def test_dump_guards_leave_cursor_untouched(self):
        for inventory, requested, neighbor in (({}, None, True),
                                                ({"lead": 1}, "copper", True),
                                                ({"copper": 1}, None, False)):
            with self.subTest(inventory=inventory, requested=requested, neighbor=neighbor):
                world, drill = drill_world()
                if neighbor:
                    world.place("router", 12, 10, free=True)
                drill.inventory = inventory.copy()
                drill.cursor = 17
                self.assertFalse(world.dump(drill, requested))
                self.assertEqual(drill.cursor, 17)
                self.assertEqual(drill.inventory, inventory)

    def test_fixed_start_visits_each_neighbor_after_rejection(self):
        world, drill = drill_world()
        world.place("copper-wall", 12, 10, free=True)
        world.place("copper-wall", 10, 12, free=True)
        router = world.place("router", 9, 10, free=True)
        drill.inventory = {"lead": 2}
        drill.cursor = 1
        self.assertTrue(world.dump(drill))
        self.assertEqual(router.inventory, {"lead": 1})
        self.assertEqual(drill.inventory, {"lead": 1})
        self.assertEqual(drill.cursor, 0)

    def test_successful_dump_decrements_only_one_and_rotates_target(self):
        world, drill = drill_world()
        first = world.place("router", 12, 10, free=True)
        second = world.place("router", 10, 12, free=True)
        drill.inventory = {"copper": 3}
        self.assertTrue(world.dump(drill, "copper"))
        self.assertEqual((drill.inventory, drill.cursor), ({"copper": 2}, 1))
        self.assertTrue(world.dump(drill, "copper"))
        self.assertEqual((drill.inventory, drill.cursor), ({"copper": 1}, 0))
        self.assertEqual(first.inventory, {"copper": 1})
        self.assertEqual(second.inventory, {"copper": 1})

    def test_dump_uses_conveyor_cached_acceptance_and_preserves_cargo(self):
        world, drill = drill_world("lead")
        belt = world.place("conveyor", 12, 10, 0, free=True)
        drill.inventory = {"lead": 2}
        belt.conveyor_minitem = .2
        self.assertFalse(world.dump(drill, "lead"))
        self.assertEqual(drill.inventory, {"lead": 2})
        world._tick_conveyor(belt)
        self.assertTrue(world.dump(drill, "lead"))
        self.assertEqual([(p.item, p.y) for p in belt.belt], [("lead", 0)])
        self.assertEqual(drill.inventory, {"lead": 1})

    def test_production_offload_is_separate_from_inventory_dump(self):
        world, drill = drill_world("lead")
        router = world.place("router", 12, 10, free=True)
        drill.inventory = {"copper": 1}
        drill.progress = 649
        drill.warmup = 1
        world._tick_drill(drill)
        self.assertEqual(router.inventory, {"lead": 1})
        self.assertEqual(drill.inventory, {"copper": 1})
        self.assertEqual(world.stats["mined"], 1)

    def test_dump_timer_four_then_five_ticks(self):
        world, drill = drill_world("lead")
        router = world.place("router", 12, 10, free=True)
        drill.inventory = {"copper": 1, "lead": 1}
        for _ in range(4):
            world._tick_drill(drill)
        self.assertEqual(router.inventory, {})
        self.assertEqual(drill.dump_ticks, 4)
        world._tick_drill(drill)
        self.assertEqual(router.inventory, {"lead": 1})
        self.assertEqual(drill.dump_ticks, 0)

    def test_save_restart_preserves_selector_cursor_and_cargo(self):
        world, drill = drill_world("lead")
        router = world.place("router", 12, 10, free=True)
        world.place("router", 10, 12, free=True)
        drill.inventory = {"copper": 2, "lead": 2}
        drill.dump_ticks = 4
        drill.cursor = 0
        data = world.to_dict()
        untouched = copy.deepcopy(data)
        restored = m.World.from_dict(data)
        self.assertEqual(data, untouched)
        self.assertEqual(data["schema"], 1)
        self.assertEqual(world.digest(), restored.digest())
        world._tick_drill(drill)
        restored._tick_drill(restored.buildings[drill.id])
        self.assertEqual(restored.buildings[router.id].inventory, {"lead": 1})
        self.assertEqual(world.digest(), restored.digest())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "save.json"
            restored.save(path)
            resumed = m.World.load(path)
        for _ in range(20):
            world._tick_drill(drill)
            resumed._tick_drill(resumed.buildings[drill.id])
        self.assertEqual(world.digest(), resumed.digest())
        cargo = sum(sum(b.inventory.values()) + len(b.belt) for b in world.buildings.values())
        self.assertEqual(cargo, 4)


class DrillDumpReferenceTests(unittest.TestCase):
    def test_fixture_rejects_java_cursor_overflow_scope(self):
        from tools import check_dump_reference as ref
        fixture = ref.load_fixtures(ref.FIXTURES)
        fixture["cases"][0]["cursor"] = 2**31 - 1
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.json"
            path.write_text(json.dumps(fixture), encoding="utf-8")
            with self.assertRaises(ValueError):
                ref.load_fixtures(path)

    def test_reference_traces_account_for_every_receipt_and_repeated_call(self):
        from tools import check_dump_reference as ref
        cases = ref.load_fixtures(ref.FIXTURES)["cases"]
        traces = ref.python_traces(cases)
        ref.validate_traces(cases, traces)
        self.assertTrue(any(not frame["result"] for trace in traces for frame in trace["frames"]))
        self.assertTrue(any(frame["result"] for trace in traces for frame in trace["frames"]))
        self.assertTrue(any(len(frame["attempts"]) > 1 for trace in traces for frame in trace["frames"]))

    def test_comparison_detects_selector_cursor_and_attempt_order_changes(self):
        from tools import check_dump_reference as ref
        cases = ref.load_fixtures(ref.FIXTURES)["cases"]
        original = ref.python_traces(cases)
        for field, value in (("selected", "copper"), ("cursor", 99), ("attempts", [])):
            with self.subTest(field=field):
                changed = copy.deepcopy(original)
                changed[0]["frames"][0][field] = value
                self.assertTrue(any(row["field"] == field for row in ref.compare_traces(original, changed)))

    def test_validator_rejects_missing_calls_lost_cargo_and_false_receipts(self):
        from tools import check_dump_reference as ref
        cases = ref.load_fixtures(ref.FIXTURES)["cases"][:1]
        original = ref.python_traces(cases)
        changes = (lambda trace: trace[0]["frames"].pop(),
                   lambda trace: trace[0]["frames"][0]["inventory"].update(copper=0),
                   lambda trace: trace[0]["frames"][0]["attempts"][0].update(accepted=False),
                   lambda trace: trace[0]["frames"][0].update(cursor=True))
        for change in changes:
            changed = copy.deepcopy(original)
            change(changed)
            with self.assertRaises(ValueError):
                ref.validate_traces(cases, changed)


if __name__ == "__main__":
    unittest.main()
