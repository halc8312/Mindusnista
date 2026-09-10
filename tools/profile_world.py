# SPDX-License-Identifier: GPL-3.0-only
"""P-05: measure the real headless World without modifying game rules.

Development tool. No NumPy, Pythonista scene, game saves, or network required.
All timings are observations of this runtime and fixture, not original-engine
parity, iPhone FPS, or a proof of any proposed optimization.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import AbstractContextManager
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import platform
import statistics
import sys
import tempfile
import time
from typing import Any, Callable

METHODS = ("step", "_tick_drill", "_tick_conveyor", "_tick_router",
           "_tick_turret", "rebuild_path", "_tick_enemy", "_tick_bullets",
           "neighbors", "mine_info", "accepts", "receive", "offload", "dump")
PRESETS = {
    "small": {"width": 48, "height": 32, "lanes": 4, "belt_length": 10,
              "enemies": 24, "battle_turrets": 6},
    "standard": {"width": 96, "height": 64, "lanes": 12, "belt_length": 28,
                 "enemies": 192, "battle_turrets": 32},
}
SCENARIOS = ("transport", "battle", "mixed")
SEED = 90210


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_runtime(path: Path):
    path = Path(path).resolve()
    name = "_mindusnista_profile_runtime_" + sha256(str(path).encode())[:16]
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError("Cannot import runtime: " + str(path))
    module = importlib.util.module_from_spec(spec)
    previous = sys.modules.get(name)
    sys.modules[name] = module  # dataclass needs its defining module registered.
    try:
        spec.loader.exec_module(module)
    except BaseException:
        if previous is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = previous
        raise
    return module


def validate_run(scenario: str, preset: str, ticks: int, warmups: int) -> None:
    if scenario not in SCENARIOS or preset not in PRESETS:
        raise ValueError("Unknown scenario or preset")
    if type(ticks) is not int or ticks < 8:
        raise ValueError("ticks must be an integer >= 8; all fixture commands must run")
    if type(warmups) is not int or warmups < 0:
        raise ValueError("warmups must be a nonnegative integer")


def counts(world) -> dict:
    return {"tiles": world.width * world.height,
            "buildings": len(world.buildings),
            "building_kinds": dict(sorted(Counter(b.kind for b in world.buildings.values()).items())),
            "enemies": len(world.enemies), "bullets": len(world.bullets),
            "belt_items": sum(len(b.belt) for b in world.buildings.values()),
            "stored_items": sum(sum(b.inventory.values()) for b in world.buildings.values()),
            "ammo": sum(b.ammo for b in world.buildings.values())}


def cache_state(world) -> dict:
    # Include state omitted from saves for the instrumentation-vs-normal check.
    # Bound wrappers are deliberately excluded; their call data lives separately.
    cache_fields = {"grid", "revision", "_neighbors", "_path_dirty", "_distance", "last_message"}
    unknown = set(vars(world)) - set(world.to_dict()) - cache_fields - set(METHODS)
    if unknown:
        raise AssertionError("Unclassified runtime state: " + ", ".join(sorted(unknown)))
    return {"grid": world.grid, "revision": world.revision,
            "neighbors": [[k, v] for k, v in world._neighbors.items()],
            "path_dirty": world._path_dirty,
            "distance": world._distance,
            "last_message": world.last_message}


def checked_place(world, kind: str, x: int, y: int, rotation: int = 0):
    result = world.place(kind, x, y, rotation, free=True)
    if result is None:
        raise ValueError("Fixture placement failed: %s (%s,%s): %s" %
                         (kind, x, y, world.last_message))
    return result


def build_fixture(runtime, scenario: str, preset: str):
    if scenario not in SCENARIOS or preset not in PRESETS:
        raise ValueError("Unknown fixture")
    cfg = dict(PRESETS[preset])
    world = runtime.World(cfg["width"], cfg["height"])
    world.rng_state = SEED
    world.sandbox = True  # Explicitly suppress automatic waves, not entity work.
    checked_place(world, "core-shard", cfg["width"] - 6, cfg["height"] // 2)
    first_belt = None
    if scenario in ("transport", "mixed"):
        for lane in range(cfg["lanes"]):
            x, y = 3, 3 + 3 * lane
            for yy in (y, y + 1):
                for xx in (x, x + 1):
                    world.ore[world.index(xx, yy)] = "copper"
            drill = checked_place(world, "mechanical-drill", x, y)
            drill.inventory = {"copper": 5}
            drill.progress, drill.warmup = 600.0, 1.0
            last = None
            for xx in range(5, 5 + cfg["belt_length"]):
                last = checked_place(world, "conveyor", xx, y)
                last.belt = [runtime.BeltItem("copper", yy, 0.0) for yy in (.1, .5, .9)]
                last.conveyor_minitem, last.conveyor_mid = .1, 1
                first_belt = first_belt or last.id
            router = checked_place(world, "router", 5 + cfg["belt_length"], y)
            router.inventory, router.router_time = {"copper": 1}, 8.0
            router.last_input = last.id
            gun = checked_place(world, "duo", 6 + cfg["belt_length"], y)
            gun.ammo = 30 if scenario == "mixed" else 0
    if scenario == "battle":
        columns = 2 if preset == "small" else 4
        for i in range(cfg["battle_turrets"]):
            gun = checked_place(world, "duo", cfg["width"] // 2 - 8 + (i % columns) * 2,
                                5 + (i // columns) * 4)
            gun.ammo, gun.reload = 30, 20.0
    if scenario in ("battle", "mixed"):
        x0 = cfg["width"] // 2 - 2 if scenario == "battle" else 12 + cfg["belt_length"]
        for i in range(cfg["enemies"]):
            # Spawn explicitly so requested count is neither wave-capped nor clipped.
            # Counts remain below the existing schema-1 load limit (256).
            world.spawn_enemy(x0 + (i % 8) * .7, 4.5 + (i // 8) * 1.8)
    commands = [
        {"tick": 2, "op": "place", "kind": "copper-wall", "x": 1, "y": 1},
        {"tick": 4, "op": "remove", "x": 1, "y": 1},
    ]
    if first_belt is not None:
        commands.extend([{"tick": 6, "op": "rotate", "id": first_belt, "rotation": 1},
                         {"tick": 8, "op": "rotate", "id": first_belt, "rotation": 0}])
    # Use the actual game's validation, without changing any inherited limit.
    validated = runtime.World.from_dict(world.to_dict())
    if validated.digest() != world.digest():
        raise AssertionError("Fixture changes during schema validation")
    return world, {"scenario": scenario, "preset": preset, "config": cfg,
                   "seed": SEED, "sandbox": True, "content": world.content,
                   "starter_drill_inventory": 5, "starter_drill_progress": 600.0,
                   "starter_drill_warmup": 1.0, "starter_belt_y": [.1, .5, .9],
                   "commands": commands, "initial_counts": counts(world),
                   "initial_digest": world.digest()}


def apply_commands(world, commands: list[dict], tick: int) -> list[dict]:
    events = []
    for command in commands:
        if command["tick"] != tick:
            continue
        op = command["op"]
        if op == "place":
            b = checked_place(world, command["kind"], command["x"], command["y"])
        elif op == "remove":
            b = world.at(command["x"], command["y"])
            if b is None or b.kind != "copper-wall" or not world.remove(b, refund=True):
                raise ValueError("Fixture remove command failed")
        elif op == "rotate":
            b = world.buildings.get(command["id"])
            if b is None or b.kind != "conveyor" or command["rotation"] not in range(4):
                raise ValueError("Fixture rotation command failed")
            # Same state transition as the current scene rotation adapter.
            b.rotation = command["rotation"]
            world.invalidated()
        else:
            raise ValueError("Unknown fixture command: " + str(op))
        events.append({**command, "entity_id": b.id})
    return events


class MethodProfiler(AbstractContextManager):
    """Per-instance wrappers; exclusive = inclusive minus nested wrapped calls.

    Unwrapped helper work is attributed to its nearest wrapped caller. Wrapper
    overhead is not subtracted by a guessed calibration. External step wall time
    is also measured and compared with the genuinely uninstrumented instance.
    """
    def __init__(self, world, methods=METHODS, clock: Callable[[], int] = time.perf_counter_ns):
        self.world, self.methods, self.clock = world, tuple(methods), clock
        self.saved = {}
        self.stack = []
        self.data = {}
        self.reset()

    def reset(self):
        if self.stack:
            raise RuntimeError("Cannot reset an active profile")
        self.data = {name: {"calls": 0, "inclusive_ns": 0, "exclusive_ns": 0,
                            "failed_calls": 0} for name in self.methods}

    def wrap(self, name, method):
        def measured(*args, **kwargs):
            start = self.clock()
            frame = {"children": 0}
            self.stack.append(frame)
            failed = False
            try:
                return method(*args, **kwargs)
            except BaseException:
                failed = True
                raise
            finally:
                elapsed = self.clock() - start
                self.stack.pop()
                row = self.data[name]
                row["calls"] += 1
                row["failed_calls"] += int(failed)
                row["inclusive_ns"] += elapsed
                row["exclusive_ns"] += elapsed - frame["children"]
                if self.stack:
                    self.stack[-1]["children"] += elapsed
        return measured

    def __enter__(self):
        try:
            for name in self.methods:
                own = name in self.world.__dict__
                old = self.world.__dict__.get(name)
                method = getattr(self.world, name)
                self.saved[name] = (own, old)
                setattr(self.world, name, self.wrap(name, method))
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, *unused):
        for name, (own, old) in self.saved.items():
            if own:
                setattr(self.world, name, old)
            else:
                self.world.__dict__.pop(name, None)
        self.saved.clear()
        return False


def timed(call):
    start = time.perf_counter_ns()
    result = call()
    return result, time.perf_counter_ns() - start


def summarize(values: list[int]) -> dict:
    if not values:
        return {"status": "not_run", "count": 0}
    ordered = sorted(values)
    return {"status": "measured", "count": len(values), "total_ns": sum(values),
            "p50_ns": statistics.median(values),
            "p95_ns": ordered[max(0, math.ceil(.95 * len(ordered)) - 1)],
            "max_ns": ordered[-1]}


def frame_summary(rows: list[dict]) -> dict:
    result = {}
    for label, selected in (
        ("first", [r for r in rows if r["phase"] == "first"]),
        ("warmup", [r for r in rows if r["phase"] == "warmup"]),
        ("steady", [r for r in rows if r["phase"] == "steady"]),
        ("path_dirty_before", [r for r in rows if r["path_dirty_before"]]),
        ("path_clean_before", [r for r in rows if not r["path_dirty_before"]]),
    ):
        baseline = summarize([r["normal_step_ns"] for r in selected])
        profiled = summarize([r["profiled_step_ns"] for r in selected])
        result[label] = {"normal": baseline, "profiled": profiled,
                         "profiled_over_normal_p50": profiled["p50_ns"] / baseline["p50_ns"]
                         if selected and baseline["p50_ns"] > 0 else None,
                         "methods": {name: {
                             "calls": sum(r["methods"][name]["calls"] for r in selected),
                             "inclusive_ns": sum(r["methods"][name]["inclusive_ns"] for r in selected),
                             "exclusive_ns": sum(r["methods"][name]["exclusive_ns"] for r in selected),
                             "status": "measured" if any(r["methods"][name]["calls"] for r in selected)
                             else "not_run"} for name in METHODS}}
    return result


def compare_worlds(normal, profiled, include_cache: bool = True) -> str:
    expected, actual = normal.digest(), profiled.digest()
    if expected != actual or normal.to_dict() != profiled.to_dict():
        raise AssertionError("Full saved World state differs")
    if include_cache and cache_state(normal) != cache_state(profiled):
        raise AssertionError("Non-save runtime cache state differs")
    return expected


def run_scenario(runtime, scenario="mixed", preset="small", ticks=60, warmups=5,
                 resume_ticks=3, temp_parent: Path | None = None) -> dict:
    validate_run(scenario, preset, ticks, warmups)
    if type(resume_ticks) is not int or resume_ticks < 1:
        raise ValueError("resume_ticks must be a positive integer")
    report = {"scenario": scenario, "preset": preset, "status": "running", "phase": "build",
              "samples": [], "checkpoint": {"status": "not_run"},
              "requested": {"first": 1, "warmups": warmups, "steady": ticks, "resume": resume_ticks}}
    try:
        with tempfile.TemporaryDirectory(prefix="mindusnista-p05-", dir=temp_parent) as directory:
            root = Path(directory)
            original, fixture = build_fixture(runtime, scenario, preset)
            report["fixture"] = fixture
            report["phase"] = "input_save"
            input_path = root / "input.json"
            _, save_ns = timed(lambda: original.save(input_path))
            source = input_path.read_bytes()
            report["input"] = {"sha256": sha256(source), "bytes": len(source),
                               "save_ns": save_ns, "unchanged": None}
            report["phase"] = "input_load"
            normal, normal_load_ns = timed(lambda: runtime.World.load(input_path))
            profiled, profiled_load_ns = timed(lambda: runtime.World.load(input_path))
            report["input"].update({"normal_load_ns": normal_load_ns,
                                     "profiled_load_ns": profiled_load_ns})
            compare_worlds(normal, profiled)
            if normal.digest() != fixture["initial_digest"]:
                raise AssertionError("Input save changes fixture state")
            report["phase"] = "steps"
            total = 1 + warmups + ticks
            with MethodProfiler(profiled) as profiler:
                for index in range(total):
                    tick = index + 1
                    phase = "first" if index == 0 else "warmup" if index <= warmups else "steady"
                    row = {"tick": tick, "phase": phase}
                    report["failed_attempt"] = row
                    events, command_ns = timed(lambda: apply_commands(normal, fixture["commands"], tick))
                    actual_events = apply_commands(profiled, fixture["commands"], tick)
                    if events != actual_events:
                        raise AssertionError("Command results differ")
                    row.update({"events": events, "normal_commands_ns": command_ns,
                                "path_dirty_before": normal._path_dirty,
                                "counts_before": counts(normal)})
                    # Normal is intentionally measured first every time; order bias is documented.
                    _, row["normal_step_ns"] = timed(normal.step)
                    profiler.reset()
                    try:
                        _, row["profiled_step_ns"] = timed(profiled.step)
                    finally:
                        row["methods"] = {k: dict(v) for k, v in profiler.data.items()}
                    if normal.tick_count != tick or profiled.tick_count != tick:
                        raise AssertionError("World did not execute requested tick (game over?)")
                    digest, verification_ns = timed(lambda: compare_worlds(normal, profiled))
                    row.update({"digest": digest, "verified": True, "verification_ns": verification_ns,
                                "counts_after": counts(normal), "path_dirty_after": normal._path_dirty})
                    report["samples"].append(row)
                    report.pop("failed_attempt")
            report["phase"] = "checkpoint"
            checkpoint = report["checkpoint"] = {"status": "running", "continuation": []}
            path = root / "checkpoint.json"
            _, checkpoint["save_ns"] = timed(lambda: normal.save(path))
            saved = path.read_bytes()
            checkpoint.update({"bytes": len(saved), "sha256": sha256(saved)})
            restored, checkpoint["load_ns"] = timed(lambda: runtime.World.load(path))
            checkpoint["initial_digest"] = compare_worlds(normal, restored, include_cache=False)
            checkpoint["source_path_dirty"] = normal._path_dirty
            checkpoint["restored_path_dirty"] = restored._path_dirty
            with MethodProfiler(restored) as resume_profiler:
                for index in range(resume_ticks):
                    _, normal_ns = timed(normal.step)
                    resume_profiler.reset()
                    _, restored_ns = timed(restored.step)
                    digest = compare_worlds(normal, restored, include_cache=False)
                    if normal.tick_count != total + index + 1:
                        raise AssertionError("Continuation tick was not executed")
                    checkpoint["continuation"].append({"tick": normal.tick_count, "digest": digest,
                        "verified": True, "source_normal_step_ns": normal_ns,
                        "restored_profiled_step_ns": restored_ns,
                        "methods": {k: dict(v) for k, v in resume_profiler.data.items()}})
            if path.read_bytes() != saved or input_path.read_bytes() != source:
                raise AssertionError("Read-only input/checkpoint changed")
            report["input"]["unchanged"] = True
            checkpoint.update({"status": "passed", "unchanged": True,
                               "save_load_ns": checkpoint["save_ns"] + checkpoint["load_ns"]})
            report["summary"] = frame_summary(report["samples"])
            report["final_counts"] = counts(normal)
            report["final_stats"] = dict(normal.stats)
            report["status"], report["phase"] = "passed", "complete"
    except Exception as error:
        report["status"] = "failed"
        report["error"] = {"type": type(error).__name__, "message": str(error)}
        if report["checkpoint"]["status"] == "running":
            report["checkpoint"]["status"] = "failed"
        report["summary"] = frame_summary(report["samples"])
    return report


def run_suite(runtime_path: Path, scenario="all", preset="small", ticks=60, warmups=5) -> dict:
    chosen = SCENARIOS if scenario == "all" else (scenario,)
    for name in chosen:
        validate_run(name, preset, ticks, warmups)
    report = {"format": "mindusnista-world-profile", "schema": 1, "status": "running",
              "environment": {"python": sys.version, "implementation": platform.python_implementation(),
                              "platform": platform.platform(), "machine": platform.machine(),
                              "clock": vars(time.get_clock_info("perf_counter"))},
              "tool_sha256": sha256(Path(__file__).read_bytes()), "scenarios": [],
              "boundaries": {"runtime_changes": False, "scene_or_rendering": "not_run",
                  "iphone_execution": "not_established", "original_engine_parity": "not_tested",
                  "peak_memory": "not_measured", "warmup_excluded_from_steady": True,
                  "command_and_digest_time_excluded_from_step": True,
                  "normal_always_measured_before_profiled": True,
                  "exclusive_definition": "inclusive minus nested wrapped calls; wrapper overhead remains",
                  "save": "actual World.save fsync/replace and World.load; temporary synthetic fixture only",
                  "limits": "existing runtime limits retained; fixed presets validated by World.from_dict"}}
    try:
        runtime_path = Path(runtime_path).resolve()
        runtime, import_ns = timed(lambda: load_runtime(runtime_path))
        report["runtime"] = {"filename": runtime_path.name, "sha256": sha256(runtime_path.read_bytes()),
                             "import_ns": import_ns, "version": runtime.VERSION,
                             "upstream": runtime.UPSTREAM, "save_format": runtime.SAVE_FORMAT,
                             "save_schema": runtime.SAVE_VERSION, "max_save_bytes": runtime.MAX_SAVE_BYTES}
        for name in chosen:
            report["scenarios"].append(run_scenario(runtime, name, preset, ticks, warmups))
        report["status"] = "passed" if all(r["status"] == "passed" for r in report["scenarios"]) else "failed"
    except Exception as error:
        report["status"] = "failed"
        report["error"] = {"type": type(error).__name__, "message": str(error)}
    return report


def default_runtime() -> Path:
    here = Path(__file__).resolve().parent
    adjacent = here / "mindustry_pythonista.py"
    return adjacent if adjacent.exists() else here.parent / "mindustry_pythonista.py"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, default=default_runtime())
    parser.add_argument("--scenario", choices=("all",) + SCENARIOS, default="all")
    parser.add_argument("--preset", choices=tuple(PRESETS), default="small")
    parser.add_argument("--ticks", type=int, default=60, help="steady ticks, minimum 8")
    parser.add_argument("--warmups", type=int, default=5)
    parser.add_argument("--output", type=Path, required=True, help="new JSON file; never overwrite")
    args = parser.parse_args(argv)
    try:
        for scenario in SCENARIOS if args.scenario == "all" else (args.scenario,):
            validate_run(scenario, args.preset, args.ticks, args.warmups)
        # Reserve before any expensive work. Existing files (including links) are refused.
        with args.output.open("x", encoding="utf-8") as handle:
            report = run_suite(args.runtime, args.scenario, args.preset, args.ticks, args.warmups)
            json.dump(report, handle, ensure_ascii=False, allow_nan=False, indent=2)
            handle.write("\n")
        print("World profile: %s; %s" % (report["status"], args.output))
        return 0 if report["status"] == "passed" else 1
    except (OSError, ValueError) as error:
        print("World profile not completed: " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
