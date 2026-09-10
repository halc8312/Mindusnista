# SPDX-License-Identifier: GPL-3.0-only
"""Production delivery regressions against the fixed v159.7 boundary."""
import copy
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import mindustry_pythonista as m


def drill_world(ore="copper"):
    world = m.World(32, 24)
    world.sandbox = True
    world.place("core-shard", 2, 2, free=True)
    for x, y in ((10, 10), (11, 10), (10, 11), (11, 11)):
        world.ore[world.index(x, y)] = ore
    drill = world.place("mechanical-drill", 10, 10, free=True)
    drill.warmup = 1.0
    return world, drill


def cargo(world):
    return sum(sum(b.inventory.values()) + len(b.belt) for b in world.buildings.values())


class DrillOffloadTests(unittest.TestCase):
    def test_no_neighbor_keeps_produced_item_and_cursor(self):
        world, drill = drill_world()
        drill.cursor = 17
        drill.inventory = {"lead": 2}
        self.assertFalse(world.offload(drill, "copper"))
        self.assertEqual(drill.inventory, {"lead": 2, "copper": 1})
        self.assertEqual(drill.cursor, 17)

    def test_all_rejection_normalizes_cursor_and_stores_one_item(self):
        world, drill = drill_world()
        world.place("copper-wall", 12, 10, free=True)
        world.place("copper-wall", 10, 12, free=True)
        drill.cursor = 7
        self.assertFalse(world.offload(drill, "lead"))
        self.assertEqual((drill.cursor, drill.inventory), (1, {"lead": 1}))

    def test_cursor_advances_before_each_real_receiver_attempt(self):
        world, drill = drill_world()
        wall = world.place("copper-wall", 12, 10, free=True)
        router = world.place("router", 10, 12, free=True)
        world.place("copper-wall", 9, 10, free=True)
        receive = world.receive
        attempts = []

        def traced_receive(target, source, item):
            attempts.append((target.id, source.cursor))
            return receive(target, source, item)

        world.receive = traced_receive
        self.assertTrue(world.offload(drill, "copper"))
        self.assertEqual(attempts, [(wall.id, 1), (router.id, 2)])
        self.assertEqual((drill.cursor, router.inventory), (2, {"copper": 1}))
        self.assertEqual(drill.inventory, {})

    def test_offload_sends_new_item_without_removing_existing_inventory(self):
        world, drill = drill_world("lead")
        router = world.place("router", 12, 10, free=True)
        drill.inventory = {"copper": 9, "lead": 1}
        self.assertTrue(world.offload(drill, "lead"))
        self.assertEqual(drill.inventory, {"copper": 9, "lead": 1})
        self.assertEqual(router.inventory, {"lead": 1})

    def test_offload_fallback_has_no_individual_capacity_guard(self):
        world, drill = drill_world()
        drill.inventory = {"copper": 10}
        self.assertFalse(world.offload(drill, "copper"))
        self.assertEqual(drill.inventory, {"copper": 11})

    def test_batch_completions_are_not_lost_at_capacity_boundary(self):
        world, drill = drill_world()
        drill.inventory = {"copper": 9}
        drill.progress = 1949
        world._tick_drill(drill)
        self.assertEqual(drill.inventory, {"copper": 12})
        self.assertEqual(world.stats["mined"], 3)
        self.assertEqual(drill.progress, 3)

    def test_batch_delivers_until_receiver_full_then_preserves_remainder(self):
        world, drill = drill_world("lead")
        router = world.place("router", 12, 10, free=True)
        drill.inventory = {"copper": 9}
        drill.progress = 1949
        world._tick_drill(drill)
        self.assertEqual(router.inventory, {"lead": 1})
        self.assertEqual(drill.inventory, {"copper": 9, "lead": 2})
        self.assertEqual((world.stats["mined"], cargo(world)), (3, 12))

    def test_capacity_guard_before_batch_retains_progress(self):
        world, drill = drill_world()
        drill.inventory = {"copper": 10}
        drill.progress = 1949
        world._tick_drill(drill)
        self.assertEqual((drill.progress, world.stats["mined"]), (1949, 0))
        self.assertEqual(drill.inventory, {"copper": 10})
        self.assertLess(drill.warmup, 1)

    def test_periodic_dump_precedes_capacity_check_and_new_production(self):
        world, drill = drill_world("lead")
        router = world.place("router", 12, 10, free=True)
        drill.inventory = {"copper": 9, "lead": 1}
        drill.progress = 1949
        drill.dump_ticks = 4
        events = []
        original_dump, original_offload = world.dump, world.offload

        def dump(source, item=None):
            events.append(("dump", item, source.progress))
            return original_dump(source, item)

        def offload(source, item):
            events.append(("offload", item, source.progress))
            return original_offload(source, item)

        world.dump, world.offload = dump, offload
        world._tick_drill(drill)
        self.assertEqual(events[:2], [("dump", "lead", 1949), ("offload", "lead", 1953)])
        self.assertEqual(router.inventory, {"lead": 1})
        self.assertEqual(drill.inventory, {"copper": 9, "lead": 3})
        self.assertEqual((drill.progress, drill.dump_ticks, world.stats["mined"]), (3, 0, 3))

    def test_remainder_is_applied_after_production_delivery(self):
        world, drill = drill_world()
        world.place("router", 12, 10, free=True)
        world.place("router", 10, 12, free=True)
        drill.progress = 1299
        observed = []
        original = world.receive

        def receive(target, source, item):
            observed.append(source.progress)
            return original(target, source, item)

        world.receive = receive
        world._tick_drill(drill)
        self.assertEqual(observed, [1303, 1303])
        self.assertEqual((drill.progress, world.stats["mined"]), (3, 2))

    def test_large_blocked_batch_preserves_every_item_without_repeated_scans(self):
        world, drill = drill_world()
        world.place("copper-wall", 12, 10, free=True)
        drill.inventory = {"copper": 9}
        drill.progress = 10**12
        drill.cursor = 17
        expected_amount, expected_progress = divmod(10**12 + 4, 650)
        original = world.receive
        calls = []

        def receive(target, source, item):
            calls.append(item)
            self.assertLessEqual(len(calls), 2, "blocked batch must use conserved arithmetic")
            return original(target, source, item)

        world.receive = receive
        world._tick_drill(drill)
        self.assertEqual(drill.inventory, {"copper": 9 + expected_amount})
        self.assertEqual((drill.progress, world.stats["mined"]), (expected_progress, expected_amount))
        self.assertEqual(len(calls), 1)
        self.assertEqual(drill.cursor, 0)
        self.assertEqual(world.digest(), m.World.from_dict(world.to_dict()).digest())

    def test_large_batch_keeps_successful_prefix_before_blocked_tail(self):
        world, drill = drill_world("lead")
        router = world.place("router", 12, 10, free=True)
        drill.inventory = {"copper": 9}
        drill.progress = 10**12
        amount, remainder = divmod(10**12 + 4, 650)
        original = world.receive
        received = []

        def receive(target, source, item):
            self.assertLess(len(received), 2, "only one successful and one rejected offer")
            result = original(target, source, item)
            received.append(result)
            return result

        world.receive = receive
        world._tick_drill(drill)
        self.assertEqual(received, [True, False])
        self.assertEqual(router.inventory, {"lead": 1})
        self.assertEqual(drill.inventory, {"copper": 9, "lead": amount - 1})
        self.assertEqual((drill.progress, world.stats["mined"]), (remainder, amount))
        self.assertEqual(world.digest(), m.World.from_dict(world.to_dict()).digest())

    def test_two_receipts_precede_aggregated_tail_in_rotated_neighbor_order(self):
        world, drill = drill_world("lead")
        east = world.place("router", 12, 10, free=True)
        north = world.place("router", 10, 12, free=True)
        wall = world.place("copper-wall", 9, 10, free=True)
        drill.inventory = {"copper": 9}
        drill.progress = 3249
        drill.cursor = 7
        attempts = []
        original = world.receive

        def receive(target, source, item):
            result = original(target, source, item)
            attempts.append((target.id, source.cursor, result))
            return result

        world.receive = receive
        world._tick_drill(drill)
        self.assertEqual(attempts, [(north.id, 2, True), (wall.id, 0, False),
                                   (east.id, 1, True), (north.id, 2, False),
                                   (wall.id, 0, False), (east.id, 1, False)])
        self.assertEqual(drill.inventory, {"copper": 9, "lead": 3})
        self.assertEqual((drill.cursor, drill.progress, world.stats["mined"]), (1, 3, 5))
        self.assertEqual(cargo(world), 14)

    def test_preexisting_schema_one_progress_resumes_through_overflow(self):
        world, drill = drill_world()
        drill.inventory = {"copper": 9}
        drill.progress = 1949
        data = world.to_dict()
        original = copy.deepcopy(data)
        resumed = m.World.from_dict(data)
        self.assertEqual(data, original)
        self.assertEqual(data["schema"], 1)
        resumed._tick_drill(resumed.buildings[drill.id])
        self.assertEqual(resumed.buildings[drill.id].inventory, {"copper": 12})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "save.json"
            resumed.save(path)
            restored = m.World.load(path)
        self.assertEqual(resumed.digest(), restored.digest())
        for _ in range(20):
            resumed._tick_drill(resumed.buildings[drill.id])
            restored._tick_drill(restored.buildings[drill.id])
        self.assertEqual(resumed.digest(), restored.digest())

    def test_drill_overflow_inventory_round_trips_without_new_size_ceiling(self):
        world, drill = drill_world()
        drill.inventory = {"copper": 2**31 + 1, "lead": 3}
        data = world.to_dict()
        restored = m.World.from_dict(data)
        self.assertEqual(restored.buildings[drill.id].inventory, drill.inventory)
        self.assertEqual(data["schema"], 1)

    def test_inventory_type_and_other_block_capacity_checks_remain(self):
        world, drill = drill_world()
        for invalid in (True, 0, -1, 1.5, "12"):
            with self.subTest(value=invalid):
                drill.inventory = {"copper": invalid}
                with self.assertRaises(ValueError):
                    m.World.from_dict(world.to_dict())
        drill.inventory = {}
        router = world.place("router", 12, 10, free=True)
        router.inventory = {"copper": 2}
        with self.assertRaises(ValueError):
            m.World.from_dict(world.to_dict())

    def test_real_drill_belt_router_explicit_order_and_save_resume(self):
        world, drill = drill_world("lead")
        belt = world.place("conveyor", 12, 10, 0, free=True)
        router = world.place("router", 13, 10, free=True)
        drill.inventory = {"copper": 1, "lead": 1}
        drill.progress = 649
        drill.dump_ticks = 4
        resumed = m.World.from_dict(copy.deepcopy(world.to_dict()))
        for current in (world, resumed):
            current._tick_drill(current.buildings[drill.id])
            current._tick_conveyor(current.buildings[belt.id])
            current._tick_router(current.buildings[router.id])
        self.assertEqual([p.item for p in belt.belt], ["lead", "lead"])
        self.assertEqual(drill.inventory, {"copper": 1})
        self.assertEqual((world.stats["mined"], cargo(world)), (1, 3))
        self.assertEqual(world.digest(), resumed.digest())
        world.step(60)
        resumed.step(60)
        self.assertEqual(world.digest(), resumed.digest())
        self.assertEqual(router.inventory, {"lead": 1})
        self.assertEqual(cargo(world), 3 + world.stats["mined"] - 1)


class DrillOffloadReferenceTests(unittest.TestCase):
    def test_reference_traces_validate_conservation_and_all_boundary_fields(self):
        from tools import check_offload_reference as ref
        cases = ref.load_fixtures(ref.FIXTURES)["cases"]
        traces = ref.python_traces(cases)
        ref.validate_traces(cases, traces)
        self.assertEqual(ref.compare_traces(traces, copy.deepcopy(traces)), [])
        empty = next(t for t in traces if t["name"] == "empty_dump_preserves_oversized_cursor")
        self.assertEqual([frame["cursor"] for frame in empty["frames"]], [17, 17])

    def test_fixture_rejects_unscoped_cursor_progress_and_item_count(self):
        from tools import check_offload_reference as ref
        original = ref.load_fixtures(ref.FIXTURES)
        for field, value in (("cursor", 2**31 - 1), ("progress", .5), ("ore_count", 5)):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                changed = copy.deepcopy(original)
                changed["cases"][0][field] = value
                path = Path(directory) / "fixture.json"
                path.write_text(json.dumps(changed), encoding="utf-8")
                with self.assertRaises(ValueError):
                    ref.load_fixtures(path)

    def test_validator_rejects_cargo_attempt_and_event_corruption(self):
        from tools import check_offload_reference as ref
        cases = ref.load_fixtures(ref.FIXTURES)["cases"]
        original = ref.python_traces(cases)
        for change in ("cargo", "cursor", "acceptance", "events"):
            with self.subTest(change=change):
                altered = copy.deepcopy(original)
                frame = next(frame for trace in altered for frame in trace["frames"]
                             if frame["call"] in ref.ITEMS and frame["offload_attempts"])
                if change == "cargo":
                    frame["inventory"]["copper"] += 1
                elif change == "cursor":
                    frame["offload_attempts"][0]["cursor_before"] += 1
                elif change == "acceptance":
                    frame["offload_attempts"][0]["accepted"] = not frame["offload_attempts"][0]["accepted"]
                else:
                    frame["events"] = ["dump", "offload"]
                with self.assertRaises(ValueError):
                    ref.validate_traces(cases, altered)
        # Swapping one unobserved later receipt with a stored item preserves
        # total cargo; the validator must still reject the wrong produced item.
        case = copy.deepcopy(next(case for case in cases if case["name"] == "batch_round_robin"))
        case["inventory"]["lead"] = 1
        changed = ref.python_traces([case])
        frame = changed[0]["frames"][0]
        frame["receipts"]["one"]["copper"] -= 1
        frame["receipts"]["one"]["lead"] += 1
        frame["inventory"]["lead"] -= 1
        frame["inventory"]["copper"] += 1
        with self.assertRaises(ValueError):
            ref.validate_traces([case], changed)

    def test_comparison_detects_progress_and_production_receipt_changes(self):
        from tools import check_offload_reference as ref
        cases = ref.load_fixtures(ref.FIXTURES)["cases"]
        original = ref.python_traces(cases)
        altered = copy.deepcopy(original)
        frame = next(frame for trace in altered for frame in trace["frames"]
                     if frame["mined"] > 1 and frame["receipts"])
        frame["progress"] += 1
        next(iter(frame["receipts"].values()))["lead"] += 1
        mismatches = ref.compare_traces(original, altered)
        self.assertEqual({change["field"] for change in mismatches}, {"progress", "receipts"})

    def test_missing_java_is_not_reported_as_passed(self):
        from tools import check_offload_reference as ref
        unavailable = {"available": False, "path": None, "reason": "test double: absent toolchain"}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            with patch.object(ref, "diagnose_tool", return_value=unavailable), redirect_stdout(io.StringIO()):
                result = ref.main(["--output", str(path)])
            report = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(result, 2)
        self.assertEqual(report["status"], "unavailable_toolchain")
        self.assertEqual(report["java_comparison"], "not run")
        self.assertNotIn("mismatch_count", report)


if __name__ == "__main__":
    unittest.main()
