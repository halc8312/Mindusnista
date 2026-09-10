# SPDX-License-Identifier: GPL-3.0-only
"""Integrated handoff regressions from Conveyor.java v159.7, not a full-game oracle."""
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import mindustry_pythonista as m


def pair(rotation=0, target_rotation=None):
    world = m.World(24, 24)
    world.sandbox = True
    world.place("core-shard", 2, 2, free=True)
    source = world.place("conveyor", 10, 10, rotation, free=True)
    dx, dy = m.DIRECTIONS[rotation]
    target = world.place("conveyor", 10 + dx, 10 + dy,
                         rotation if target_rotation is None else target_rotation, free=True)
    source.belt = [m.BeltItem("copper", .58, .6), m.BeltItem("lead", .99, .6)]
    return world, source, target


class ConveyorTransferTests(unittest.TestCase):
    def test_departing_head_releases_follower_in_same_update_all_rotations(self):
        # Upstream updateTile changes len immediately after a successful pass.
        # The follower becomes the last item and can move .046, rather than .02.
        for rotation in range(4):
            with self.subTest(rotation=rotation):
                world, source, target = pair(rotation)
                world._tick_conveyor(source)
                self.assertEqual([p.item for p in source.belt], ["copper"])
                self.assertEqual([p.item for p in target.belt], ["lead"])
                self.assertAlmostEqual(source.belt[0].y, .626)
                self.assertEqual(target.belt[0].y, 0)
                self.assertAlmostEqual(source.belt[0].x, .508)
                self.assertAlmostEqual(target.belt[0].x, .508)

    def test_rejected_handoff_keeps_head_and_follower_spacing(self):
        world, source, target = pair(target_rotation=1)
        target.belt = [m.BeltItem("lead", y) for y in (.2, .6, 1)]
        before = [(p.item, p.y, p.x) for p in target.belt]
        world._tick_conveyor(source)
        self.assertEqual([p.item for p in source.belt], ["copper", "lead"])
        self.assertAlmostEqual(source.belt[0].y, .6)
        self.assertEqual(source.belt[1].y, 1)
        self.assertEqual([(p.item, p.y, p.x) for p in target.belt], before)

    def test_aligned_next_belt_retains_backpressure(self):
        world, source, target = pair()
        source.belt = [m.BeltItem("copper", .39), m.BeltItem("lead", .79)]
        target.belt = [m.BeltItem("copper", .2)]
        world._tick_conveyor(source)
        self.assertEqual(len(source.belt) + len(target.belt), 3)
        self.assertAlmostEqual(source.belt[0].y, .4)
        self.assertAlmostEqual(source.belt[1].y, .8)
        self.assertEqual(target.belt[0].y, .2)

    def test_turn_uses_side_entry_position_instead_of_aligned_x(self):
        for rotation in range(4):
            with self.subTest(rotation=rotation):
                world, source, target = pair(rotation, (rotation + 1) % 4)
                world._tick_conveyor(source)
                self.assertEqual([p.item for p in target.belt], ["lead"])
                self.assertEqual((target.belt[0].y, target.belt[0].x), (.5, 1.0))
                self.assertAlmostEqual(source.belt[0].y, .626)

    def test_facing_belts_keep_their_items(self):
        world, source, target = pair(target_rotation=2)
        world._tick_conveyor(source)
        self.assertFalse(target.belt)
        self.assertEqual([p.item for p in source.belt], ["copper", "lead"])
        self.assertAlmostEqual(source.belt[0].y, .6)
        self.assertEqual(source.belt[1].y, 1)

    def test_explicit_update_order_controls_arrival_movement(self):
        for target_first in (False, True):
            with self.subTest(target_first=target_first):
                world, source, target = pair()
                for building in ((target, source) if target_first else (source, target)):
                    world._tick_conveyor(building)
                self.assertAlmostEqual(source.belt[0].y, .626)
                self.assertAlmostEqual(target.belt[0].y, 0 if target_first else .046)
                self.assertAlmostEqual(target.belt[0].x, .508 if target_first else .416)

    def test_schema_one_roundtrip_continues_after_handoff(self):
        world, source, target = pair()
        world._tick_conveyor(source)
        data = json.loads(json.dumps(world.to_dict()))
        self.assertEqual(data["schema"], 1)
        restored = m.World.from_dict(data)
        self.assertEqual(world.digest(), restored.digest())
        for _ in range(80):
            world.step()
            restored.step()
            self.assertEqual(world.digest(), restored.digest())
        self.assertEqual(sorted(p.item for b in world.buildings.values() for p in b.belt),
                         ["copper", "lead"])


if __name__ == "__main__":
    unittest.main()
