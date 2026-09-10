# SPDX-License-Identifier: GPL-3.0-only
"""P-05 hand-derived target boundaries and complete World equivalence."""
from __future__ import annotations

import ast
import copy
from dataclasses import asdict
import importlib.util
import math
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("target_selection_tool", ROOT / "tools/check_target_selection.py")
t = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(t)
m = t.p.load_runtime(ROOT / "mindustry_pythonista.py")


def fixture(entries=(), ammo=2, reload=20.0, angle=0.0):
    world = m.World(64, 48)
    world.sandbox = True
    world.place("core-shard", 2, 2, free=True)
    gun = world.place("duo", 30, 20, free=True)
    gun.ammo, gun.reload, gun.angle = ammo, reload, angle
    world.content["duo"]["range"] = 5.0
    x, y = world.center(gun)
    for uid, dx, dy, hp in entries:
        world.enemies[uid] = m.Enemy(uid, x + dx, y + dy, hp=hp)
    world.next_id = max([world.next_id] + [e.id + 1 for e in world.enemies.values()])
    return world, gun.id


class TargetSelectionTests(unittest.TestCase):
    def compare_tick(self, world, gun_id):
        baseline, candidate = copy.deepcopy(world), copy.deepcopy(world)
        t.bind_pair(m, baseline, candidate)
        baseline._tick_turret(baseline.buildings[gun_id])
        candidate._tick_turret(candidate.buildings[gun_id])
        t.p.compare_worlds(baseline, candidate)
        return candidate, candidate.buildings[gun_id]

    def test_frozen_baseline_integrity(self):
        self.assertEqual(t.p.sha256(t.BASELINE_SOURCE.encode()),
                         "f06cb4e4bdfafc0d418068dd17b63628cc6b8a761a2bbb6ccd132a6bcd2e8248")
        with mock.patch.object(t, "BASELINE_SOURCE", t.BASELINE_SOURCE + "\n"):
            with self.assertRaisesRegex(AssertionError, "baseline source hash"):
                t.baseline_function(m)

    def test_range_closed_boundary_inside_and_outside(self):
        for distance, shots in ((5.0 - 1e-10, 1), (5.0, 1), (5.0 + 1e-10, 0)):
            with self.subTest(distance=distance):
                world, uid = fixture([(10, distance, 0.0, 60.0)])
                after, gun = self.compare_tick(world, uid)
                self.assertEqual(gun.shots, shots)
                self.assertEqual(gun.ammo, 2 - shots)
                self.assertEqual(len(after.bullets), shots)
                self.assertEqual(gun.angle, 0.0)

    def test_nearest_then_low_id_independent_of_insertion_order(self):
        for entries in (
            [(20, 3, 0, 60), (10, 0, 3, 60)],
            [(10, 0, 3, 60), (20, 3, 0, 60)],
            [(10, 4, 0, 60), (20, 0, 3, 60)],
        ):
            with self.subTest(entries=entries):
                world, uid = fixture(entries)
                after, gun = self.compare_tick(world, uid)
                self.assertEqual(gun.angle, math.radians(world.content["duo"]["rotate_speed"]))
                self.assertEqual(gun.shots, 0)
                self.assertEqual(after.rng_state, world.rng_state)
                self.assertEqual(list(after.enemies), [entry[0] for entry in entries])

    def test_dead_and_empty_targets_leave_aim_and_rng(self):
        for entries in ([], [(10, 1, 0, 0)], [(10, 1, 0, -1)]):
            with self.subTest(entries=entries):
                world, uid = fixture(entries, angle=.3, reload=0.0)
                after, gun = self.compare_tick(world, uid)
                self.assertEqual(gun.angle, .3)
                self.assertEqual(gun.reload, 1.0)
                self.assertEqual(gun.shots, 0)
                self.assertEqual(after.rng_state, world.rng_state)
        world, uid = fixture([(5, 0, 1, 0), (10, 3, 0, 60)])
        self.assertEqual(self.compare_tick(world, uid)[1].shots, 1)

    def test_no_ammo_still_reloads_without_aim_or_rng(self):
        world, uid = fixture([(10, 3, 0, 60)], ammo=0, reload=19.5, angle=.4)
        after, gun = self.compare_tick(world, uid)
        self.assertEqual(gun.reload, 20.0)
        self.assertEqual(gun.angle, .4)
        self.assertEqual(gun.shots, 0)
        self.assertEqual(after.rng_state, world.rng_state)

    def test_aiming_threshold_and_reload_keep_original_order(self):
        for degrees, reload, shots in ((14.999999, 20.0, 1), (15.000001, 20.0, 0), (0, 18.0, 0)):
            with self.subTest(degrees=degrees, reload=reload):
                angle = math.radians(degrees)
                world, uid = fixture([(10, 3 * math.cos(angle), 3 * math.sin(angle), 60)], reload=reload)
                after, gun = self.compare_tick(world, uid)
                self.assertEqual(gun.shots, shots)
                self.assertEqual(gun.reload, 0 if shots else min(20, reload + 1))
                self.assertEqual(after.stats["shots"], shots)
                self.assertEqual(after.next_id, world.next_id + shots)
                expected_rng = (1664525 * world.rng_state + 1013904223) & 0xFFFFFFFF if shots else world.rng_state
                self.assertEqual(after.rng_state, expected_rng)

    def test_nonfinite_manual_targets_do_not_invert_old_inclusion(self):
        # Invalid saves reject these; preserve old direct-call exclusion as well.
        for entries in ([(10, math.nan, 0, 60)], [(10, 0, 0, math.nan)], [(10, math.inf, 0, 60)]):
            world, uid = fixture(entries)
            baseline, candidate = copy.deepcopy(world), copy.deepcopy(world)
            t.bind_pair(m, baseline, candidate)
            baseline._tick_turret(baseline.buildings[uid])
            candidate._tick_turret(candidate.buildings[uid])
            self.assertEqual(asdict(baseline.buildings[uid]), asdict(candidate.buildings[uid]))
            self.assertEqual(candidate.buildings[uid].shots, 0)
            self.assertEqual(candidate.rng_state, world.rng_state)

    def test_all_worlds_multiple_seeds_every_tick_and_actual_save_resume(self):
        for seed in (1, 90210, 0xFFFFFFFF):
            for scenario in t.SCENARIOS:
                with self.subTest(seed=seed, scenario=scenario):
                    report = t.run_scenario(m, scenario, "small", 8, 0, seed)
                    self.assertEqual(report["status"], "passed", report.get("error"))
                    self.assertEqual(len(report["samples"]), 9)
                    self.assertTrue(all(row["verified"] for row in report["samples"]))
                    self.assertEqual(report["samples"][0]["order"], ["baseline", "candidate"])
                    self.assertEqual(report["samples"][1]["order"], ["candidate", "baseline"])
                    checkpoint = report["checkpoint"]
                    self.assertTrue(checkpoint["same_bytes"])
                    self.assertTrue(checkpoint["unchanged"])
                    self.assertEqual(len(checkpoint["continuation"]), 3)
                    self.assertEqual([r["tick"] for r in checkpoint["continuation"]], [10, 11, 12])
                    self.assertEqual(checkpoint["continuation"][0]["events"][0]["op"], "place")
                    self.assertEqual(checkpoint["continuation"][1]["events"][0]["op"], "remove")

    def test_repeat_reverses_order_without_altering_state(self):
        a = t.run_scenario(m, "battle", "small", 8, 0, repeat=0)
        b = t.run_scenario(m, "battle", "small", 8, 0, repeat=1)
        self.assertEqual(a["status"], "passed")
        self.assertEqual(b["status"], "passed")
        self.assertEqual([r["digest"] for r in a["samples"]], [r["digest"] for r in b["samples"]])
        for x, y in zip(a["samples"], b["samples"]):
            self.assertEqual(x["order"], y["order"][::-1])
        self.assertEqual(a["summary"]["first"]["baseline"]["count"], 1)
        self.assertEqual(a["summary"]["warmup"]["baseline"]["status"], "not_run")
        self.assertEqual(a["summary"]["steady"]["baseline"]["count"], 8)

    def test_changed_state_and_step_failure_are_not_passing_samples(self):
        original = m.World._tick_turret
        def changed(world, gun):
            world.random()
            return original(world, gun)
        with mock.patch.object(m.World, "_tick_turret", changed):
            report = t.run_scenario(m, "battle", "small", 8, 0)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["samples"], [])
        self.assertIn("state differs", report["error"]["message"])
        self.assertEqual(report["checkpoint"]["status"], "not_run")
        with mock.patch.object(m.World, "step", side_effect=RuntimeError("step failed")):
            report = t.run_scenario(m, "battle", "small", 8, 0)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["samples"], [])
        self.assertEqual(report["error"]["message"], "step failed")

    def test_save_failure_and_temporary_files_cleanup(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as parent:
            with mock.patch.object(m.World, "save", side_effect=OSError("disk failed")):
                report = t.run_scenario(m, "normal", "small", 8, 0, temp_parent=parent)
            self.assertEqual(report["status"], "failed")
            self.assertEqual(report["phase"], "input_save_load")
            self.assertEqual(list(Path(parent).iterdir()), [])
        original = m.World.save
        calls = 0
        def fail_checkpoint(world, path):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("checkpoint failed")
            return original(world, path)
        with mock.patch.object(m.World, "save", fail_checkpoint):
            report = t.run_scenario(m, "normal", "small", 8, 0)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["checkpoint"]["status"], "failed")
        self.assertEqual(len(report["samples"]), 9)

    def test_validation_existing_output_and_standalone_cli(self):
        for kwargs in ({"scenario": "unknown"}, {"preset": "huge"}, {"ticks": 7},
                       {"warmups": -1}, {"repeats": 0}, {"seed": -1}, {"seed": 2**32}):
            args = dict(scenario="normal", preset="small", ticks=8, warmups=0, repeats=1, seed=1)
            args.update(kwargs)
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                t.validate(**args)
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            root = Path(folder)
            for path in (ROOT / "tools/check_target_selection.py", ROOT / "tools/profile_world.py", ROOT / "mindustry_pythonista.py"):
                shutil.copyfile(path, root / path.name)
                ast.parse(path.read_text(), feature_version=(3, 10))
            output = root / "results.json"
            command = [sys.executable, str(root / "check_target_selection.py"), "--scenario", "normal", "--ticks", "8", "--warmups", "0", "--repeats", "1", "--output", str(output)]
            result = subprocess.run(command, cwd=root, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            self.assertEqual(result.returncode, 0, result.stdout)
            saved = output.read_bytes()
            result = subprocess.run(command, cwd=root, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            self.assertEqual(result.returncode, 2, result.stdout)
            self.assertEqual(output.read_bytes(), saved)


if __name__ == "__main__":
    unittest.main()
