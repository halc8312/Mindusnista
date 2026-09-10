# SPDX-License-Identifier: GPL-3.0-only
"""P-05: old versus single-pass turret selection in the same real World.

Development-only comparison, not original combat parity or iPhone performance.
Requires sibling profile_world.py and the standalone game; no extra packages.
"""
from __future__ import annotations

import argparse
import importlib.util
import inspect
import json
from pathlib import Path
import platform
import sys
import tempfile
import textwrap
import time
from types import MethodType

_PROFILE_SPEC = importlib.util.spec_from_file_location(
    "_mindusnista_target_profile", Path(__file__).with_name("profile_world.py"))
p = importlib.util.module_from_spec(_PROFILE_SPEC)
_PROFILE_SPEC.loader.exec_module(p)

BASELINE_COMMIT = '9f466b9f43fd80c172f6e6a7de9db60fac7c004d'
BASELINE_PATH = "src/mindusnista/app.py"
BASELINE_SHA256 = 'f06cb4e4bdfafc0d418068dd17b63628cc6b8a761a2bbb6ccd132a6bcd2e8248'
BASELINE_SOURCE = '    def _tick_turret(self, b: Building) -> None:\n        spec = self.content[b.kind]\n        b.reload = min(spec["reload"], b.reload + 1.0)\n        if b.ammo <= 0 or not self.enemies:\n            return\n        x, y = self.center(b)\n        targets = [e for e in self.enemies.values()\n                   if e.hp > 0 and (e.x-x)**2 + (e.y-y)**2 <= spec["range"]**2]\n        if not targets:\n            return\n        e = min(targets, key=lambda enemy: ((enemy.x-x)**2 + (enemy.y-y)**2, enemy.id))\n        # Scaffold aiming: no upstream intercept prediction, recoil, or coolant.\n        desired = math.atan2(e.y-y, e.x-x)\n        difference = (desired - b.angle + math.pi) % (2*math.pi) - math.pi\n        b.angle += clamp(difference, -math.radians(spec["rotate_speed"]),\n                        math.radians(spec["rotate_speed"]))\n        if b.reload >= spec["reload"] and abs(difference) <= math.radians(15):\n            b.reload = 0.0\n            b.ammo -= 1\n            b.shots += 1\n            self.stats["shots"] += 1\n            # Original duo inaccuracy is two degrees; independent RNG here.\n            angle = b.angle + math.radians((self.random()*2-1)*2)\n            dx, dy = math.cos(angle), math.sin(angle)\n            uid = self.uid()\n            self.bullets[uid] = Bullet(uid, x + dx*.25, y + dy*.25,\n                                      dx*spec["bullet_speed"], dy*spec["bullet_speed"],\n                                      spec["damage"], spec["bullet_life"])\n'

SCENARIOS = ("normal",) + p.SCENARIOS


def baseline_function(runtime):
    if p.sha256(BASELINE_SOURCE.encode()) != BASELINE_SHA256:
        raise AssertionError("Frozen baseline source hash differs")
    namespace = dict(vars(runtime))
    exec(compile(textwrap.dedent(BASELINE_SOURCE), "<p05-frozen-turret>", "exec"), namespace)
    return namespace["_tick_turret"]


def bind_pair(runtime, baseline, candidate):
    # Equal per-instance method lookup cost; no class mutation or timing wrapper.
    baseline._tick_turret = MethodType(baseline_function(runtime), baseline)
    candidate._tick_turret = MethodType(runtime.World._tick_turret, candidate)


def build_fixture(runtime, scenario, preset, seed):
    if scenario == "normal":
        world = runtime.World.demo()
        info = {"scenario": "normal", "preset": "existing_demo_48x32",
                "config": {"width": world.width, "height": world.height},
                "sandbox": world.sandbox, "content": world.content,
                "commands": [{"tick": 2, "op": "place", "kind": "copper-wall", "x": 1, "y": 1},
                             {"tick": 4, "op": "remove", "x": 1, "y": 1}]}
    else:
        world, info = p.build_fixture(runtime, scenario, preset)
    world.rng_state = seed
    info.update({"seed": seed, "initial_counts": p.counts(world), "initial_digest": world.digest()})
    p.compare_worlds(world, runtime.World.from_dict(world.to_dict()), include_cache=False)
    return world, info


def validate(scenario, preset, ticks, warmups, repeats, seed):
    if scenario not in SCENARIOS:
        raise ValueError("Unknown scenario")
    p.validate_run("mixed" if scenario == "normal" else scenario, preset, ticks, warmups)
    if type(repeats) is not int or repeats < 1:
        raise ValueError("repeats must be a positive integer")
    if type(seed) is not int or not 0 <= seed <= 0xFFFFFFFF:
        raise ValueError("seed must be an integer in [0, 2**32-1]")


def summaries(rows):
    result = {}
    for phase in ("first", "warmup", "steady"):
        selected = [r for r in rows if r["phase"] == phase]
        baseline = p.summarize([r["baseline_step_ns"] for r in selected])
        candidate = p.summarize([r["candidate_step_ns"] for r in selected])
        result[phase] = {"baseline": baseline, "candidate": candidate,
            "candidate_over_baseline_p50": candidate["p50_ns"] / baseline["p50_ns"]
            if selected and baseline["p50_ns"] else None}
    return result


def run_scenario(runtime, scenario="mixed", preset="small", ticks=60, warmups=5,
                 seed=p.SEED, repeat=0, temp_parent=None):
    validate(scenario, preset, ticks, warmups, 1, seed)
    report = {"scenario": scenario, "preset": preset, "repeat": repeat, "seed": seed,
              "status": "running", "phase": "fixture", "samples": [],
              "requested": {"first": 1, "warmups": warmups, "steady": ticks, "resume": 3},
              "checkpoint": {"status": "not_run"}}
    try:
        with tempfile.TemporaryDirectory(prefix="mindusnista-target-", dir=temp_parent) as directory:
            root = Path(directory)
            original, fixture = build_fixture(runtime, scenario, preset, seed)
            report["fixture"] = fixture
            report["phase"] = "input_save_load"
            input_path = root / "input.json"
            original.save(input_path)
            input_bytes = input_path.read_bytes()
            report["input"] = {"sha256": p.sha256(input_bytes), "bytes": len(input_bytes), "unchanged": None}
            baseline, candidate = runtime.World.load(input_path), runtime.World.load(input_path)
            bind_pair(runtime, baseline, candidate)
            p.compare_worlds(baseline, candidate)
            if baseline.digest() != fixture["initial_digest"]:
                raise AssertionError("Input save changes fixture state")
            report["phase"] = "steps"
            total = 1 + warmups + ticks
            for index in range(total):
                tick = index + 1
                row = {"tick": tick, "phase": "first" if index == 0 else "warmup" if index <= warmups else "steady"}
                report["failed_attempt"] = row
                events = p.apply_commands(baseline, fixture["commands"], tick)
                if events != p.apply_commands(candidate, fixture["commands"], tick):
                    raise AssertionError("Command results differ")
                row.update({"events": events, "counts_before": p.counts(baseline),
                            "path_dirty_before": baseline._path_dirty})
                ordered = (("baseline", baseline), ("candidate", candidate))
                if (index + repeat) % 2:
                    ordered = ordered[::-1]
                row["order"] = [name for name, world in ordered]
                for name, world in ordered:
                    _, row[name + "_step_ns"] = p.timed(world.step)
                if baseline.tick_count != tick or candidate.tick_count != tick:
                    raise AssertionError("Requested World tick did not execute")
                row["digest"], row["verification_ns"] = p.timed(lambda: p.compare_worlds(baseline, candidate))
                row.update({"verified": True, "counts_after": p.counts(baseline)})
                report["samples"].append(row)
                report.pop("failed_attempt")
            report["phase"] = "checkpoint"
            checkpoint = report["checkpoint"] = {"status": "running", "continuation": []}
            restored = []
            saved_files = []
            for name, world in (("baseline", baseline), ("candidate", candidate)):
                path = root / (name + ".json")
                _, save_ns = p.timed(lambda: world.save(path))
                saved = path.read_bytes()
                resumed, load_ns = p.timed(lambda: runtime.World.load(path))
                p.compare_worlds(world, resumed, include_cache=False)
                checkpoint[name] = {"save_ns": save_ns, "load_ns": load_ns,
                                    "bytes": len(saved), "sha256": p.sha256(saved)}
                restored.append(resumed)
                saved_files.append((path, saved))
            if saved_files[0][1] != saved_files[1][1]:
                raise AssertionError("Saved file bytes differ")
            bind_pair(runtime, *restored)
            p.compare_worlds(*restored)
            # Continue all four states with the same new place/remove commands.
            commands = [{"tick": 1, "op": "place", "kind": "copper-wall", "x": 1, "y": 1},
                        {"tick": 2, "op": "remove", "x": 1, "y": 1}]
            checkpoint["commands"] = commands
            for index in range(3):
                event_lists = [p.apply_commands(w, commands, index + 1) for w in (baseline, candidate, *restored)]
                if any(events != event_lists[0] for events in event_lists):
                    raise AssertionError("Continuation commands differ")
                for world in (baseline, candidate, *restored):
                    world.step()
                    if world.tick_count != total + index + 1:
                        raise AssertionError("Continuation tick did not execute")
                digest = p.compare_worlds(baseline, candidate)
                p.compare_worlds(*restored)
                p.compare_worlds(baseline, restored[0], include_cache=False)
                p.compare_worlds(candidate, restored[1], include_cache=False)
                checkpoint["continuation"].append({"tick": baseline.tick_count, "digest": digest,
                                                   "events": event_lists[0], "verified": True})
            if input_path.read_bytes() != input_bytes or any(path.read_bytes() != data for path, data in saved_files):
                raise AssertionError("Read-only input/checkpoint changed")
            report["input"]["unchanged"] = True
            checkpoint.update({"status": "passed", "unchanged": True, "same_bytes": True})
            report["final_counts"], report["final_stats"] = p.counts(baseline), dict(baseline.stats)
            report["status"], report["phase"] = "passed", "complete"
    except Exception as error:
        report["status"] = "failed"
        report["error"] = {"type": type(error).__name__, "message": str(error)}
        if report["checkpoint"]["status"] == "running":
            report["checkpoint"]["status"] = "failed"
    report["summary"] = summaries(report["samples"])
    return report


def run_suite(runtime_path, scenario="all", preset="small", ticks=60, warmups=5, repeats=3, seed=p.SEED):
    chosen = SCENARIOS if scenario == "all" else (scenario,)
    for name in chosen:
        validate(name, preset, ticks, warmups, repeats, seed)
    report = {"format": "mindusnista-target-selection", "schema": 1, "status": "running", "runs": [],
        "environment": {"python": sys.version, "platform": platform.platform(),
                        "clock": vars(time.get_clock_info("perf_counter"))},
        "tool_sha256": p.sha256(Path(__file__).read_bytes()),
        "profile_tool_sha256": p.sha256(Path(p.__file__).read_bytes()),
        "baseline": {"commit": BASELINE_COMMIT, "path": BASELINE_PATH, "method_sha256": BASELINE_SHA256},
        "boundaries": {"both_steps_uninstrumented": True, "alternating_order_per_tick_and_repeat": True,
                       "commands_and_verification_outside_step": True, "same_current_World_except_turret": True,
                       "timing_adoption_gate": "manual review of total World.step, not a microbenchmark",
                       "original_combat_parity": "not_tested", "iphone_performance": "not_measured",
                       "rendering_effects_and_peak_memory": "not_measured"}}
    try:
        runtime_path = Path(runtime_path).resolve()
        runtime = p.load_runtime(runtime_path)
        baseline_function(runtime)
        report["runtime"] = {"filename": runtime_path.name, "sha256": p.sha256(runtime_path.read_bytes()),
            "candidate_method_sha256": p.sha256(inspect.getsource(runtime.World._tick_turret).encode()),
            "version": runtime.VERSION, "upstream": runtime.UPSTREAM, "save_schema": runtime.SAVE_VERSION}
        for name in chosen:
            for repeat in range(repeats):
                report["runs"].append(run_scenario(runtime, name, preset, ticks, warmups, seed, repeat))
        report["status"] = "passed" if all(r["status"] == "passed" for r in report["runs"]) else "failed"
    except Exception as error:
        report["status"] = "failed"
        report["error"] = {"type": type(error).__name__, "message": str(error)}
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, default=p.default_runtime())
    parser.add_argument("--scenario", choices=("all",) + SCENARIOS, default="all")
    parser.add_argument("--preset", choices=tuple(p.PRESETS), default="small")
    parser.add_argument("--ticks", type=int, default=60)
    parser.add_argument("--warmups", type=int, default=5)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--seed", type=int, default=p.SEED)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        for name in SCENARIOS if args.scenario == "all" else (args.scenario,):
            validate(name, args.preset, args.ticks, args.warmups, args.repeats, args.seed)
        with args.output.open("x", encoding="utf-8") as handle:
            report = run_suite(args.runtime, args.scenario, args.preset, args.ticks, args.warmups, args.repeats, args.seed)
            json.dump(report, handle, ensure_ascii=False, allow_nan=False, indent=2)
            handle.write("\n")
        print("Target selection comparison: %s; %s" % (report["status"], args.output))
        return 0 if report["status"] == "passed" else 1
    except (OSError, ValueError) as error:
        print("Target selection comparison not completed: " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
