# SPDX-License-Identifier: GPL-3.0-only
"""v159.7 cache timing, insertion order and schema 1 continuation regressions."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import mindustry_pythonista as m


def junction():
    world = m.World(24, 24)
    world.sandbox = True
    world.place("core-shard", 2, 2, free=True)
    target = world.place("conveyor", 10, 10, 0, free=True)
    rear = world.place("router", 9, 10, free=True)
    side = world.place("router", 10, 9, free=True)
    opposite = world.place("router", 10, 11, free=True)
    return world, target, rear, side, opposite


def without_caches(data):
    old = copy.deepcopy(data)
    for building in old["buildings"]:
        building.pop("conveyor_minitem", None)
        building.pop("conveyor_mid", None)
    return old


class ConveyorCacheTests(unittest.TestCase):
    def test_rear_then_side_uses_previous_update_cache_and_keeps_array_order(self):
        world, target, rear, side, _ = junction()
        self.assertTrue(world.receive(target, rear, "copper"))
        self.assertTrue(world.receive(target, side, "lead"))
        self.assertEqual([(p.item, p.y) for p in target.belt], [("lead", .5), ("copper", 0)])
        self.assertEqual((target.conveyor_minitem, target.conveyor_mid), (1, 0))

    def test_multiple_rear_arrivals_insert_at_zero_until_capacity(self):
        world, target, rear, _, _ = junction()
        for item in ("copper", "lead", "copper"):
            self.assertTrue(world.receive(target, rear, item))
        self.assertEqual([p.item for p in target.belt], ["copper", "lead", "copper"])
        self.assertFalse(world.receive(target, rear, "lead"))
        world._tick_conveyor(target)
        self.assertEqual(target.conveyor_minitem, 0)
        self.assertFalse(world.accepts(target, rear, "lead"))

    def test_opposite_sides_insert_before_earlier_arrival(self):
        world, target, _, side, opposite = junction()
        self.assertTrue(world.receive(target, side, "copper"))
        self.assertTrue(world.receive(target, opposite, "lead"))
        self.assertEqual([(p.item, p.x) for p in target.belt], [("lead", 1), ("copper", -1)])

    def test_cached_minimum_can_reject_despite_open_positions(self):
        world, target, rear, _, _ = junction()
        target.belt = [m.BeltItem("copper", .9)]
        target.conveyor_minitem = .2
        self.assertFalse(world.accepts(target, rear, "lead"))
        world._tick_conveyor(target)
        self.assertAlmostEqual(target.conveyor_minitem, .946)
        self.assertTrue(world.accepts(target, rear, "lead"))

    def test_aligned_backpressure_reads_target_cache(self):
        world, target, _, _, _ = junction()
        receiver = world.place("conveyor", 11, 10, 0, free=True)
        target.belt = [m.BeltItem("lead", .99, .6)]
        receiver.belt = [m.BeltItem("copper", 0)]
        receiver.conveyor_minitem = 1
        world._tick_conveyor(target)
        self.assertFalse(target.belt)
        self.assertEqual([p.item for p in receiver.belt], ["lead", "copper"])
        self.assertAlmostEqual(receiver.belt[0].x, .508)
        self.assertEqual(receiver.conveyor_minitem, 1)

    def test_empty_update_resets_cache(self):
        world, target, _, _, _ = junction()
        target.conveyor_minitem = .2
        world._tick_conveyor(target)
        self.assertEqual((target.conveyor_minitem, target.conveyor_mid), (1, 0))

    def test_update_computes_mid_with_strict_half_threshold(self):
        for middle, expected in ((.4, 1), (.5, 0)):
            with self.subTest(middle=middle):
                world, target, _, _, _ = junction()
                target.belt = [m.BeltItem("copper", y) for y in (.1, middle, .9)]
                world._tick_conveyor(target)
                self.assertEqual(target.conveyor_mid, expected)
                self.assertAlmostEqual(target.conveyor_minitem, min(p.y for p in target.belt))

    def test_side_input_uses_cached_mid_without_sorting(self):
        # Artificial insertion-API boundary, not an ordinary generated cache.
        world, target, _, side, _ = junction()
        target.belt = [m.BeltItem("copper", .8)]
        target.conveyor_minitem = 1
        target.conveyor_mid = 1
        self.assertTrue(world.receive(target, side, "lead"))
        self.assertEqual([(p.item, p.y) for p in target.belt], [("copper", .8), ("lead", .5)])
        self.assertEqual(target.conveyor_mid, 1)

    def test_cache_tracks_only_items_remaining_after_pass(self):
        world, target, _, _, _ = junction()
        receiver = world.place("conveyor", 11, 10, 0, free=True)
        target.belt = [m.BeltItem("lead", .99)]
        world._tick_conveyor(target)
        self.assertFalse(target.belt)
        self.assertEqual((target.conveyor_minitem, target.conveyor_mid), (1, 0))
        self.assertEqual(len(receiver.belt), 1)


class ConveyorCacheSaveTests(unittest.TestCase):
    def test_disk_resume_preserves_unsorted_arrivals_and_next_acceptance(self):
        world, target, rear, side, opposite = junction()
        world.receive(target, rear, "copper")
        world.receive(target, side, "lead")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "save.json"
            world.save(path)
            restored = m.World.load(path)
        self.assertEqual(world.digest(), restored.digest())
        self.assertEqual(restored.to_dict()["schema"], 1)
        self.assertTrue(world.receive(target, opposite, "copper"))
        self.assertTrue(restored.receive(restored.buildings[target.id],
                                         restored.buildings[opposite.id], "copper"))
        for _ in range(80):
            self.assertEqual(world.digest(), restored.digest())
            world.step()
            restored.step()
        self.assertEqual(world.digest(), restored.digest())
        self.assertEqual(sum(len(b.belt) for b in world.buildings.values()), 3)

    def test_old_schema_one_migration_preserves_state_and_does_not_tick(self):
        world, target, _, _, _ = junction()
        target.belt = [m.BeltItem("copper", y) for y in (.1, .4, .9)]
        old = without_caches(world.to_dict())
        before = copy.deepcopy(old)
        restored = m.World.from_dict(old)
        self.assertEqual(old, before)
        self.assertEqual(without_caches(restored.to_dict()), old)
        self.assertEqual((restored.buildings[target.id].conveyor_minitem,
                          restored.buildings[target.id].conveyor_mid), (.1, 1))
        self.assertEqual(restored.digest(), m.World.from_dict(old).digest())
        resaved = m.World.from_dict(json.loads(json.dumps(restored.to_dict())))
        for _ in range(50):
            restored.step()
            resaved.step()
            self.assertEqual(restored.digest(), resaved.digest())

    def test_old_migration_mid_threshold_does_not_move_cargo(self):
        for middle, expected in ((.5, 1), (.500001, 0)):
            with self.subTest(middle=middle):
                world, target, _, _, _ = junction()
                target.belt = [m.BeltItem("lead", y) for y in (.1, middle, .9)]
                restored = m.World.from_dict(without_caches(world.to_dict()))
                self.assertEqual(restored.buildings[target.id].conveyor_mid, expected)
                self.assertEqual([p.y for p in restored.buildings[target.id].belt], [.1, middle, .9])

    def test_old_empty_conveyor_and_other_buildings_get_neutral_cache(self):
        world, _, _, _, _ = junction()
        restored = m.World.from_dict(without_caches(world.to_dict()))
        for building in restored.buildings.values():
            self.assertEqual((building.conveyor_minitem, building.conveyor_mid), (1, 0))

    def test_saved_stale_cache_is_preserved_without_recomputation(self):
        world, target, rear, _, _ = junction()
        target.belt = [m.BeltItem("lead", .9)]
        target.conveyor_minitem = .2
        restored = m.World.from_dict(world.to_dict())
        self.assertEqual(restored.buildings[target.id].conveyor_minitem, .2)
        self.assertFalse(restored.accepts(restored.buildings[target.id], restored.buildings[rear.id], "lead"))

    def test_partial_or_invalid_cache_is_rejected_without_mutating_input(self):
        world, target, _, _, _ = junction()
        target.belt = [m.BeltItem("lead", .8)]
        base = world.to_dict()
        bad_values = {"conveyor_minitem": (None, True, "1", float("nan"), float("inf"), -.1, 1.1),
                      "conveyor_mid": (None, True, "0", .5, -1, 2)}
        for key, values in bad_values.items():
            for value in values:
                with self.subTest(key=key, value=value):
                    data = copy.deepcopy(base)
                    row = next(b for b in data["buildings"] if b["id"] == target.id)
                    row[key] = value
                    before = json.dumps(data, sort_keys=True)
                    with self.assertRaises(ValueError):
                        m.World.from_dict(data)
                    self.assertEqual(json.dumps(data, sort_keys=True), before)
            data = copy.deepcopy(base)
            next(b for b in data["buildings"] if b["id"] == target.id).pop(key)
            with self.assertRaises(ValueError):
                m.World.from_dict(data)

    def test_mid_cannot_exceed_length_or_appear_on_nonconveyor(self):
        world, target, rear, _, _ = junction()
        for uid, key, value in ((target.id, "conveyor_mid", 1),
                                (rear.id, "conveyor_minitem", .2),
                                (rear.id, "conveyor_mid", 1)):
            with self.subTest(uid=uid, key=key):
                data = world.to_dict()
                next(b for b in data["buildings"] if b["id"] == uid)[key] = value
                with self.assertRaises(ValueError):
                    m.World.from_dict(data)

    def test_legacy_unsorted_cargo_is_still_rejected(self):
        world, target, _, _, _ = junction()
        target.belt = [m.BeltItem("lead", .5), m.BeltItem("copper", 0)]
        with self.assertRaises(ValueError):
            m.World.from_dict(without_caches(world.to_dict()))

    def test_cache_does_not_relax_item_coordinate_or_capacity_validation(self):
        world, target, _, _, _ = junction()
        invalid = [[{"item": "unknown", "y": 0, "x": 0}],
                   [{"item": "lead", "y": 1.1, "x": 0}],
                   [{"item": "lead", "y": 0, "x": 2}],
                   [{"item": "lead", "y": 0, "x": 0}] * 4]
        for belt in invalid:
            with self.subTest(belt=belt):
                data = world.to_dict()
                next(b for b in data["buildings"] if b["id"] == target.id)["belt"] = belt
                with self.assertRaises(ValueError):
                    m.World.from_dict(data)


class ConveyorCacheReferenceTests(unittest.TestCase):
    def test_reference_checks_detect_cache_only_changes(self):
        from tools import check_conveyor_reference as ref
        cases = ref.load_fixtures(ref.FIXTURES)["cases"]
        original = ref.python_traces(cases[:1])
        for field, value in (("minitem", .123), ("mid", 1), ("lastInserted", 1)):
            with self.subTest(field=field):
                changed = copy.deepcopy(original)
                belt = next(iter(changed[0]["frames"][0]["belts"].values()))
                belt["cache"][field] = value
                self.assertTrue(any(x["field"] == "cache." + field
                                    for x in ref.compare_traces(original, changed)))

    def test_all_explicit_traces_preserve_cargo_and_include_unsorted_arrival(self):
        from tools import check_conveyor_reference as ref
        cases = ref.load_fixtures(ref.FIXTURES)["cases"]
        traces = ref.python_traces(cases)
        ref.validate_traces(cases, traces)
        orders = [[item["y"] for item in belt["items"]]
                  for trace in traces for frame in trace["frames"] for belt in frame["belts"].values()]
        self.assertTrue(any(ys != sorted(ys) for ys in orders))

    def test_reference_rejects_nonfinite_and_out_of_range_cache(self):
        from tools import check_conveyor_reference as ref
        cases = ref.load_fixtures(ref.FIXTURES)["cases"][:1]
        original = ref.python_traces(cases)
        for field, value in (("minitem", float("nan")), ("mid", True), ("mid", 2)):
            with self.subTest(field=field):
                changed = copy.deepcopy(original)
                next(iter(changed[0]["frames"][0]["belts"].values()))["cache"][field] = value
                with self.assertRaises(ValueError):
                    ref.validate_traces(cases, changed)


if __name__ == "__main__":
    unittest.main()
