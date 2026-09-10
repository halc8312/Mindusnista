# SPDX-License-Identifier: GPL-3.0-only
"""P-05 real-World workload, measurement accounting and failure regressions."""
from __future__ import annotations

import ast
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("world_profile_tool", ROOT / "tools/profile_world.py")
p = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(p)
m = p.load_runtime(ROOT / "mindustry_pythonista.py")


class WorldProfileTests(unittest.TestCase):
    def test_fixture_exact_counts_order_and_round_trip(self):
        for preset, cfg in p.PRESETS.items():
            for scenario in p.SCENARIOS:
                with self.subTest(preset=preset, scenario=scenario):
                    world, info = p.build_fixture(m, scenario, preset)
                    expected = 1 + cfg["battle_turrets"] if scenario == "battle" else 1 + cfg["lanes"] * (cfg["belt_length"] + 3)
                    self.assertEqual(len(world.buildings), expected)
                    self.assertEqual(len(world.enemies), 0 if scenario == "transport" else cfg["enemies"])
                    self.assertEqual(list(world.buildings), list(range(1, expected + 1)))
                    self.assertEqual(world.rng_state, p.SEED)
                    self.assertTrue(world.sandbox)
                    self.assertEqual(world.content, m.DEFAULT_CONTENT)
                    self.assertEqual(world.digest(), m.World.from_dict(world.to_dict()).digest())
                    self.assertEqual(info["initial_counts"], p.counts(world))

    def test_fixture_repeatability_and_unknown_rejection(self):
        a, info_a = p.build_fixture(m, "mixed", "small")
        b, info_b = p.build_fixture(m, "mixed", "small")
        self.assertEqual(info_a, info_b)
        self.assertEqual(a.digest(), b.digest())
        for scenario, preset in (("unknown", "small"), ("mixed", "huge")):
            with self.assertRaises(ValueError):
                p.build_fixture(m, scenario, preset)
        with mock.patch.object(m.World, "place", return_value=None):
            with self.assertRaisesRegex(ValueError, "placement failed"):
                p.build_fixture(m, "mixed", "small")

    def test_commands_preserve_rotation_cargo_and_apply_place_remove(self):
        world, info = p.build_fixture(m, "transport", "small")
        self.assertEqual(p.apply_commands(world, info["commands"], 1), [])
        events = p.apply_commands(world, info["commands"], 2)
        wall_id = events[0]["entity_id"]
        self.assertEqual(world.at(1, 1).id, wall_id)
        self.assertEqual(p.apply_commands(world, info["commands"], 4)[0]["entity_id"], wall_id)
        self.assertIsNone(world.at(1, 1))
        belt = world.buildings[info["commands"][2]["id"]]
        cargo = copy.deepcopy(belt.belt)
        p.apply_commands(world, info["commands"], 6)
        self.assertEqual(belt.rotation, 1)
        p.apply_commands(world, info["commands"], 8)
        self.assertEqual(belt.rotation, 0)
        self.assertEqual(belt.belt, cargo)
        self.assertTrue(world._path_dirty)

    def test_invalid_commands_are_errors_not_dropped(self):
        world, info = p.build_fixture(m, "transport", "small")
        for command in (
            {"tick": 1, "op": "remove", "x": 1, "y": 1},
            {"tick": 1, "op": "place", "kind": "duo", "x": -1, "y": -1},
            {"tick": 1, "op": "rotate", "id": 999999, "rotation": 0},
            {"tick": 1, "op": "unknown"},
        ):
            with self.subTest(command=command), self.assertRaises(ValueError):
                p.apply_commands(world, [command], 1)

    def test_nested_inclusive_exclusive_exact_clock(self):
        class Example:
            def step(self):
                return self.child(7)
            def child(self, value):
                return value * 2
        world = Example()
        clock = iter((0, 10, 30, 50))
        with p.MethodProfiler(world, ("step", "child"), lambda: next(clock)) as profiler:
            self.assertEqual(world.step(), 14)
            self.assertEqual(profiler.data["step"], {"calls": 1, "inclusive_ns": 50,
                                                      "exclusive_ns": 30, "failed_calls": 0})
            self.assertEqual(profiler.data["child"]["exclusive_ns"], 20)
            self.assertEqual(sum(v["exclusive_ns"] for v in profiler.data.values()), 50)
        self.assertEqual(world.__dict__, {})

    def test_profiler_exception_accounting_and_original_method_restoration(self):
        class Example:
            def step(self):
                return self.child()
            def child(self):
                raise RuntimeError("worker")
        world = Example()
        original = lambda: (_ for _ in ()).throw(RuntimeError("instance"))
        world.child = original
        with p.MethodProfiler(world, ("step", "child")) as profiler:
            with self.assertRaisesRegex(RuntimeError, "instance"):
                world.step()
            self.assertEqual(profiler.stack, [])
            self.assertTrue(all(v["failed_calls"] == 1 for v in profiler.data.values()))
            profiler.reset()
            self.assertTrue(all(v["calls"] == 0 for v in profiler.data.values()))
        self.assertIs(world.child, original)
        self.assertNotIn("step", world.__dict__)
        with self.assertRaises(AttributeError):
            with p.MethodProfiler(world, ("step", "missing")):
                pass
        self.assertNotIn("step", world.__dict__)

    def test_real_steps_full_state_and_nested_accounting(self):
        for scenario in p.SCENARIOS:
            with self.subTest(scenario=scenario):
                result = p.run_scenario(m, scenario, "small", ticks=8, warmups=0)
                self.assertEqual(result["status"], "passed", result.get("error"))
                self.assertEqual(len(result["samples"]), 9)
                self.assertEqual(len(result["checkpoint"]["continuation"]), 3)
                self.assertTrue(result["input"]["unchanged"])
                self.assertTrue(result["checkpoint"]["unchanged"])
                self.assertNotIn("failed_attempt", result)
                for index, row in enumerate(result["samples"]):
                    self.assertEqual(row["tick"], index + 1)
                    self.assertTrue(row["verified"])
                    self.assertEqual(row["methods"]["step"]["calls"], 1)
                    self.assertEqual(sum(v["exclusive_ns"] for v in row["methods"].values()),
                                     row["methods"]["step"]["inclusive_ns"])
                    self.assertTrue(all(v["exclusive_ns"] >= 0 and v["failed_calls"] == 0
                                        for v in row["methods"].values()))
                    self.assertEqual(row["methods"]["_tick_conveyor"]["calls"],
                                     row["counts_before"]["building_kinds"].get("conveyor", 0))
                    self.assertEqual(row["methods"]["_tick_enemy"]["calls"], row["counts_before"]["enemies"])
                self.assertEqual(result["summary"]["warmup"]["normal"]["status"], "not_run")
                if scenario != "transport":
                    self.assertEqual(result["samples"][0]["methods"]["rebuild_path"]["calls"], 1)
                    self.assertEqual(result["samples"][2]["methods"]["rebuild_path"]["calls"], 0)
                    self.assertEqual(result["samples"][3]["methods"]["rebuild_path"]["calls"], 1)
                    self.assertEqual(result["checkpoint"]["continuation"][0]["methods"]["rebuild_path"]["calls"], 1)
                    self.assertFalse(result["checkpoint"]["source_path_dirty"])
                    self.assertTrue(result["checkpoint"]["restored_path_dirty"])
                else:
                    self.assertEqual(result["summary"]["steady"]["methods"]["rebuild_path"]["status"], "not_run")

    def test_comparison_detects_saved_order_and_non_saved_cache_difference(self):
        original, _ = p.build_fixture(m, "transport", "small")
        a, b = m.World.from_dict(original.to_dict()), m.World.from_dict(original.to_dict())
        self.assertEqual(p.compare_worlds(a, b), a.digest())
        ids = list(b.buildings)
        value = b.buildings.pop(ids[0])
        b.buildings[ids[0]] = value
        with self.assertRaisesRegex(AssertionError, "saved World"):
            p.compare_worlds(a, b)
        b = m.World.from_dict(original.to_dict())
        b._neighbors[999] = []
        with self.assertRaisesRegex(AssertionError, "cache state"):
            p.compare_worlds(a, b)
        self.assertEqual(p.compare_worlds(a, b, include_cache=False), a.digest())

    def test_cache_infinity_sign_and_new_state_are_not_ignored(self):
        original, _ = p.build_fixture(m, "transport", "small")
        a, b = m.World.from_dict(original.to_dict()), m.World.from_dict(original.to_dict())
        b._distance[0] = float("-inf")
        with self.assertRaisesRegex(AssertionError, "cache state"):
            p.compare_worlds(a, b)
        b._distance[0] = float("inf")
        b.future_state = 7
        with self.assertRaisesRegex(AssertionError, "Unclassified runtime state"):
            p.compare_worlds(a, b)

    def test_comparison_failure_preserves_only_completed_samples(self):
        real = p.compare_worlds
        calls = 0
        def compare(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 3:  # initial check, first tick, then second tick
                raise RuntimeError("comparison failed")
            return real(*args, **kwargs)
        with mock.patch.object(p, "compare_worlds", side_effect=compare):
            result = p.run_scenario(m, "transport", ticks=8, warmups=0)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["phase"], "steps")
        self.assertEqual(len(result["samples"]), 1)
        self.assertEqual(result["failed_attempt"]["tick"], 2)
        self.assertNotIn("verified", result["failed_attempt"])
        self.assertEqual(result["checkpoint"]["status"], "not_run")

    def test_step_failure_and_game_over_are_not_successful_ticks(self):
        real = m.World.step
        calls = 0
        def fail_profiled(world, *args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("step failure")
            return real(world, *args, **kwargs)
        with mock.patch.object(m.World, "step", fail_profiled):
            result = p.run_scenario(m, "transport", ticks=8, warmups=0)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["samples"], [])
        self.assertEqual(result["error"]["message"], "step failure")
        self.assertEqual(result["failed_attempt"]["methods"]["step"]["failed_calls"], 1)
        with mock.patch.object(m.World, "step", lambda world: None):
            result = p.run_scenario(m, "transport", ticks=8, warmups=0)
        self.assertEqual(result["status"], "failed")
        self.assertIn("did not execute", result["error"]["message"])

    def test_save_and_load_failures_leave_phase_evidence(self):
        real_save = m.World.save
        calls = 0
        def fail_second_save(world, path):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("checkpoint write")
            return real_save(world, path)
        with mock.patch.object(m.World, "save", fail_second_save):
            result = p.run_scenario(m, "transport", ticks=8, warmups=0)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["phase"], "checkpoint")
        self.assertEqual(result["checkpoint"]["status"], "failed")
        self.assertEqual(len(result["samples"]), 9)
        with mock.patch.object(m.World, "load", side_effect=ValueError("load failed")):
            result = p.run_scenario(m, "transport", ticks=8, warmups=0)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["samples"], [])
        self.assertIsNone(result["input"]["unchanged"])

    def test_input_save_mutation_is_detected_and_temporary_files_removed(self):
        real_load = m.World.load
        def mutating_load(path):
            world = real_load(path)
            with path.open("ab") as handle:
                handle.write(b" ")
            return world
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(m.World, "load", side_effect=mutating_load):
                result = p.run_scenario(m, "transport", ticks=8, warmups=0, temp_parent=directory)
            self.assertEqual(list(Path(directory).iterdir()), [])
        self.assertEqual(result["status"], "failed")
        self.assertIn("input/checkpoint changed", result["error"]["message"])

    def test_parameter_rejection_never_clips_or_omits_commands(self):
        for ticks, warmups in ((7, 0), (0, 0), (8, -1), (True, 0), (8, False)):
            with self.subTest(ticks=ticks, warmups=warmups), self.assertRaises(ValueError):
                p.run_scenario(m, "transport", ticks=ticks, warmups=warmups)
        for resume in (0, -1, True):
            with self.assertRaises(ValueError):
                p.run_scenario(m, "transport", ticks=8, warmups=0, resume_ticks=resume)

    def test_summary_counts_percentiles_and_no_data(self):
        self.assertEqual(p.summarize([]), {"status": "not_run", "count": 0})
        self.assertEqual(p.summarize([100, 1, 20])["p50_ns"], 20)
        self.assertEqual(p.summarize([100, 1, 20])["p95_ns"], 100)
        result = p.frame_summary([])
        self.assertTrue(all(v["profiled_over_normal_p50"] is None for v in result.values()))
        self.assertTrue(all(v["normal"]["status"] == "not_run" for v in result.values()))

    def test_cli_new_output_failure_json_and_existing_output_protection(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            args = ["--runtime", str(Path(directory) / "missing.py"), "--output", str(path), "--ticks", "8"]
            self.assertEqual(p.main(args), 1)
            result = json.loads(path.read_text())
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["scenarios"], [])
            original = path.read_bytes()
            with mock.patch.object(p, "run_suite", side_effect=AssertionError("must not run")):
                self.assertEqual(p.main(args), 2)
            self.assertEqual(path.read_bytes(), original)
            bad = Path(directory) / "bad.json"
            self.assertEqual(p.main(["--output", str(bad), "--ticks", "1"]), 2)
            self.assertFalse(bad.exists())

    def test_standalone_cli_and_python310_syntax(self):
        source = (ROOT / "tools/profile_world.py").read_text()
        ast.parse(source, feature_version=(3, 10))
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            (target / "profile_world.py").write_text(source)
            (target / "mindustry_pythonista.py").write_bytes((ROOT / "mindustry_pythonista.py").read_bytes())
            command = [sys.executable, "profile_world.py", "--scenario", "battle", "--ticks", "8",
                       "--warmups", "0", "--output", "result.json"]
            process = subprocess.run(command, cwd=target, capture_output=True, text=True, timeout=30)
            self.assertEqual(process.returncode, 0, process.stderr)
            report = json.loads((target / "result.json").read_text())
            self.assertEqual(report["status"], "passed")
            self.assertEqual(report["runtime"]["sha256"], p.sha256((ROOT / "mindustry_pythonista.py").read_bytes()))
            self.assertEqual(report["scenarios"][0]["fixture"]["scenario"], "battle")
            self.assertEqual(report["runtime"]["save_schema"], 1)


if __name__ == "__main__":
    unittest.main()
