# SPDX-License-Identifier: GPL-3.0-only
"""Real receiver and source-derived integrated transport regressions."""
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


def router_world(rotation=0):
    world = m.World(32, 24)
    world.sandbox = True
    world.place("core-shard", 2, 2, free=True)
    router = world.place("router", 10, 10, rotation=rotation, free=True)
    east = world.place("conveyor", 11, 10, rotation=0, free=True)
    north = world.place("conveyor", 10, 11, rotation=1, free=True)
    return world, router, east, north


class RouterIntegrationTests(unittest.TestCase):
    def test_placement_rotation_selects_first_neighbor(self):
        world, router, east, north = router_world(1)
        router.inventory = {"copper": 1}
        self.assertEqual(world.neighbors(router), [east, north])
        world._tick_router(router)
        self.assertEqual([p.item for p in north.belt], ["copper"])
        self.assertEqual(east.belt, [])
        self.assertEqual((router.rotation, router.cursor), (0, 0))

    def test_legacy_cursor_is_preserved_but_not_the_router_selector(self):
        world, router, east, north = router_world()
        router.cursor = 37
        router.inventory = {"lead": 1}
        world._tick_router(router)
        self.assertEqual([p.item for p in east.belt], ["lead"])
        self.assertEqual(north.belt, [])
        self.assertEqual((router.rotation, router.cursor), (1, 37))

    def test_success_advances_rotation_before_real_receiver_handles_item(self):
        world, router, east, north = router_world()
        east.belt = [m.BeltItem("lead", 0)]
        east.conveyor_minitem = 0
        world.place("copper-wall", 9, 10, free=True)
        router.inventory = {"copper": 1}
        # Observe the real receiver's cargo insertion, without substituting
        # its acceptance rule or changing the offered result.
        observed = []
        class ObservedCargo(list):
            def insert(self, index, cargo):
                observed.append((router.rotation, router.cursor))
                super().insert(index, cargo)
        north.belt = ObservedCargo()
        world._tick_router(router)
        self.assertEqual(observed, [(2, 0)])
        self.assertEqual([p.item for p in north.belt], ["copper"])

    def test_delayed_first_router_does_not_fall_through_to_conveyor(self):
        world, router, east, north = router_world()
        world.remove(east, refund=False)
        target = world.place("router", 11, 10, free=True)
        world.neighbors = lambda source: [target, north] if source is router else []
        router.inventory = {"copper": 1}
        for _ in range(7):
            world._tick_router(router)
        self.assertEqual((router.inventory, router.rotation, router.router_time), ({"copper": 1}, 0, 0.875))
        self.assertEqual((target.inventory, north.belt), ({}, []))
        world._tick_router(router)
        self.assertEqual((router.inventory, target.inventory, router.rotation), ({}, {"copper": 1}, 1))

    def test_normal_source_is_allowed_as_output(self):
        world = m.World(32, 24)
        source = world.place("router", 10, 10, free=True)
        target = world.place("router", 11, 10, free=True)
        self.assertTrue(world.receive(target, source, "lead"))
        for _ in range(8):
            world._tick_router(target)
        self.assertEqual(source.inventory, {"lead": 1})
        self.assertEqual(target.inventory, {})
        self.assertEqual(target.last_input, source.id)

    def test_rejection_and_empty_router_do_not_advance_rotation(self):
        world, router, east, north = router_world(3)
        router.cursor = 19
        for belt in (east, north):
            belt.belt = [m.BeltItem("lead", 0)]
            belt.conveyor_minitem = 0
        world._tick_router(router)
        self.assertEqual((router.router_time, router.rotation), (0, 3))
        router.inventory = {"copper": 1}
        world._tick_router(router)
        self.assertEqual((router.rotation, router.cursor), (3, 19))
        self.assertEqual(router.inventory, {"copper": 1})

    def test_schema_one_round_trip_preserves_both_fields_and_continuation(self):
        world, router, east, north = router_world(1)
        router.inventory = {"lead": 1}
        router.cursor = 37
        router.router_time = 0.625
        router.last_input = east.id
        restored = m.World.from_dict(json.loads(json.dumps(world.to_dict())))
        current = restored.buildings[router.id]
        self.assertEqual((current.rotation, current.cursor, current.router_time, current.last_input),
                         (1, 37, 0.625, east.id))
        world._tick_router(router)
        restored._tick_router(current)
        self.assertEqual(world.to_dict(), restored.to_dict())


class IntegratedReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tools import check_integrated_transport as check
        cls.check = check
        cls.fixture = check.load_fixtures()
        cls.traces = check.python_traces(cls.fixture["cases"])

    def invalid_fixture(self, data):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(ValueError):
                self.check.load_fixtures(path)

    def test_real_receiver_traces_cover_all_declared_updates_and_conserve_items(self):
        self.check.validate_traces(self.fixture["cases"], self.traces)
        self.assertEqual(len(self.traces), 14)
        self.assertEqual(sum(len(case["frames"]) for case in self.traces), 985)
        self.assertEqual(self.check.compare_traces(self.traces, self.traces), [])
        standard = next(case for case in self.fixture["cases"] if case["name"] == "drill_belt_router_standard_speed")
        self.assertEqual(standard["speed"], m.DEFAULT_CONTENT["conveyor"]["speed"])

    def test_protocol_contains_every_seed_neighbor_and_update(self):
        protocol = self.check.protocol_input(self.fixture["cases"])
        lines = protocol.splitlines()
        self.assertEqual(sum(line.startswith("C\t") for line in lines), 14)
        self.assertEqual(sum(line.startswith("U\t") for line in lines), 985)
        self.assertEqual(sum(line.startswith("N\t") for line in lines),
                         sum(len(case["buildings"]) for case in self.fixture["cases"]))
        for line in lines:
            if line.startswith("B\t"):
                fields = line.split("\t")
                self.assertEqual(len(fields), 19 + int(fields[18]) * 3)

    def test_missing_frames_are_rejected(self):
        traces = copy.deepcopy(self.traces)
        traces[0]["frames"].pop()
        with self.assertRaises(ValueError):
            self.check.validate_traces(self.fixture["cases"], traces)

    def test_nan_and_float_discrete_fields_are_rejected(self):
        for field, value in (("rotation", 0.0), ("minitem", float("nan")), ("cursor", True)):
            with self.subTest(field=field):
                traces = copy.deepcopy(self.traces)
                traces[0]["frames"][0]["buildings"]["r"][field] = value
                with self.assertRaises(ValueError):
                    self.check.validate_traces(self.fixture["cases"], traces)

    def test_produced_cargo_item_substitution_is_rejected(self):
        traces = copy.deepcopy(self.traces)
        case = next(case for case in traces if case["name"] == "drill_belt_router_forward")
        frame = case["frames"][0]
        self.assertEqual(frame["mined"], 1)
        belt = frame["buildings"]["belt"]
        self.assertEqual(belt["belt"][0]["item"], "copper")
        belt["belt"][0]["item"] = "lead"
        belt["inventory"] = {"copper": 0, "lead": 1}
        with self.assertRaisesRegex(ValueError, "per-item cargo"):
            self.check.validate_traces(self.fixture["cases"], traces)

    def test_production_on_router_update_is_rejected(self):
        traces = copy.deepcopy(self.traces)
        traces[0]["frames"][0]["mined"] = 1
        with self.assertRaisesRegex(ValueError, "non-mining"):
            self.check.validate_traces(self.fixture["cases"], traces)

    def test_tolerance_never_absorbs_rotation_or_transfer_update_differences(self):
        traces = copy.deepcopy(self.traces)
        frame = traces[0]["frames"][0]
        frame["buildings"]["r"]["routerTime"] += self.check.TOLERANCE / 2
        self.assertEqual(self.check.compare_traces(self.traces, traces), [])
        frame["buildings"]["r"]["rotation"] = 1
        self.assertTrue(self.check.compare_traces(self.traces, traces))
        traces = copy.deepcopy(self.traces)
        traces[0]["frames"][0]["deliveries"] = []
        self.assertTrue(self.check.compare_traces(self.traces, traces))

    def test_fixture_rejects_missing_neighbor_overlap_and_unbounded_work(self):
        for change in ("neighbor", "overlap", "progress", "ore", "duplicate", "nonfinite"):
            with self.subTest(change=change):
                data = copy.deepcopy(self.fixture)
                case = data["cases"][0]
                if change == "neighbor":
                    case["neighbors"]["r"].pop()
                elif change == "overlap":
                    case["buildings"][1]["x"] = 10
                elif change == "progress":
                    case["buildings"][0]["progress"] = 10**12
                elif change == "ore":
                    data["cases"][6]["buildings"][0]["ore_count"] = 0
                elif change == "duplicate":
                    case["neighbors"]["r"].append("east")
                else:
                    case["speed"] = float("nan")
                self.invalid_fixture(data)

    def test_missing_jdk_is_not_a_successful_comparison(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.json"
            with patch.object(self.check, "diagnose_tool", return_value={"available": False}), redirect_stdout(io.StringIO()):
                result = self.check.main(["--output", str(path)])
            report = json.loads(path.read_text())
            self.assertEqual(result, 2)
            self.assertEqual((report["status"], report["comparison"]), ("error", "not_run"))
            self.assertNotIn("mismatch_count", report)

    def test_existing_report_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.json"
            path.write_text("existing report", encoding="utf-8")
            with patch("sys.stderr", io.StringIO()), self.assertRaises(SystemExit):
                self.check.main(["--output", str(path)])
            self.assertEqual(path.read_text(), "existing report")


if __name__ == "__main__":
    unittest.main()
