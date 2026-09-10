#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Compare explicit belt updates against an extracted Java float reference.

Development only: requires working javac/java (JDK 17 in CI), no extra Python
libraries. A missing/broken JDK is an error, never a successful comparison.
This does not run the original Mindustry engine or Pythonista scene.
"""
from __future__ import annotations

import argparse
from collections import Counter
import copy
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "reference" / "conveyor_transfer_scenarios.json"
JAVA_SOURCE = ROOT / "reference" / "ConveyorTransferReference.java"
PYTHON_SOURCE = ROOT / "mindustry_pythonista.py"
UPSTREAM_COMMIT = "c9686eb5d0ae5dd47ee02c40f99f7d5018ccbc8c"
TOLERANCE = 2e-6
IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9_]*\Z")


def identifier(value: Any) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ValueError("invalid fixture identifier")
    return value


def number(value: Any, low: float, high: float) -> float:
    if type(value) not in (float, int) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError("fixture number outside the supported finite range")
    return float(value)


def load_fixtures(path: Path) -> dict[str, Any]:
    fixture = json.loads(path.read_text(encoding="utf-8"))
    if fixture.get("schema") != 1 or fixture.get("upstream", {}).get("commit") != UPSTREAM_COMMIT:
        raise ValueError("unsupported fixture schema or upstream commit")
    fixed_conditions = {"delta": 1, "efficiency": 1, "time_scale": 1, "team": "same",
                        "block_size": 1, "initial_mid": 0, "initial_last_inserted": 0}
    if any(fixture.get("conditions", {}).get(key) != value for key, value in fixed_conditions.items()):
        raise ValueError("fixture conditions are outside the extracted reference scope")
    cases = fixture.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("fixtures must contain cases")
    names = set()
    for case in cases:
        name = identifier(case["name"])
        if name in names:
            raise ValueError("duplicate case name")
        names.add(name)
        number(case["speed"], 1e-9, .25)
        if not isinstance(case["belts"], list) or not case["belts"]:
            raise ValueError("case must contain belts")
        belts, occupied = set(), set()
        for belt in case["belts"]:
            belt_name = identifier(belt["name"])
            if belt_name in belts:
                raise ValueError("duplicate belt name")
            belts.add(belt_name)
            for field, maximum in (("x", 31), ("y", 31), ("rotation", 3)):
                if type(belt[field]) is not int or not 0 <= belt[field] <= maximum:
                    raise ValueError("invalid fixture coordinate or rotation")
            position = (belt["x"], belt["y"])
            if position in occupied:
                raise ValueError("overlapping fixture belts")
            occupied.add(position)
            number(belt["minitem"], 0, 1)
            items = belt["items"]
            if not isinstance(items, list) or len(items) > 3:
                raise ValueError("invalid fixture capacity")
            for item in items:
                if item["item"] not in ("copper", "lead"):
                    raise ValueError("fixture item is unsupported by the current port")
                number(item["y"], 0, 1)
                number(item["x"], -1, 1)
            if items != sorted(items, key=lambda item: item["y"]):
                raise ValueError("seeded items must be ordered by y")
            minimum = min((item["y"] for item in items), default=1.0)
            if abs(minimum - belt["minitem"]) > TOLERANCE:
                raise ValueError("fixtures in this slice must start with a primed minitem")
        if not isinstance(case["updates"], list) or not case["updates"]:
            raise ValueError("case must contain explicit updates")
        if any(name not in belts for name in case["updates"]):
            raise ValueError("update names an unknown belt")
    return fixture


def protocol_input(cases: list[dict[str, Any]]) -> str:
    """TSV identifiers are validated; data is stdin, never shell source."""
    lines = []
    for case in cases:
        lines.append("\t".join(("C", case["name"], str(case["speed"]))))
        for belt in case["belts"]:
            fields = ["B", belt["name"], str(belt["x"]), str(belt["y"]),
                      str(belt["rotation"]), str(belt["minitem"]), str(len(belt["items"]))]
            for item in belt["items"]:
                fields.extend((item["item"], str(item["y"]), str(item["x"])))
            lines.append("\t".join(fields))
        lines.extend("U\t" + name for name in case["updates"])
        lines.append("E")
    return "\n".join(lines) + "\n"


def load_game() -> Any:
    spec = importlib.util.spec_from_file_location("_mindusnista_transfer_target", PYTHON_SOURCE)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot import the generated Python runtime")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def python_traces(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    game = load_game()
    traces = []
    for case in cases:
        content = copy.deepcopy(game.DEFAULT_CONTENT)
        content["conveyor"]["speed"] = case["speed"]
        world = game.World(32, 32, content)
        belts = {}
        for seed in case["belts"]:
            belt = world.place("conveyor", seed["x"], seed["y"], seed["rotation"], free=True)
            if belt is None:
                raise ValueError("fixture placement failed: " + world.last_message)
            belt.belt = [game.BeltItem(item["item"], item["y"], item["x"]) for item in seed["items"]]
            belts[seed["name"]] = belt
        frames = []
        for name in case["updates"]:
            # Deliberately no World.step(), scheduler, RNG, scene or save I/O.
            world._tick_conveyor(belts[name])
            frames.append({"update": name, "belts": {
                key: {"count": len(belt.belt), "items": [
                    {"item": item.item, "y": item.y, "x": item.x} for item in belt.belt]}
                for key, belt in belts.items()}})
        traces.append({"name": case["name"], "frames": frames})
    return traces


def validate_traces(cases: list[dict[str, Any]], traces: list[dict[str, Any]]) -> None:
    """Reject malformed/incomplete traces, including cargo loss on either side."""
    if not isinstance(traces, list) or len(traces) != len(cases):
        raise ValueError("trace case count differs from fixtures")
    for case, trace in zip(cases, traces):
        if trace["name"] != case["name"] or len(trace["frames"]) != len(case["updates"]):
            raise ValueError("trace case name or update count differs from fixtures")
        expected_belts = {belt["name"] for belt in case["belts"]}
        initial_cargo = Counter(item["item"] for belt in case["belts"] for item in belt["items"])
        for update, frame in zip(case["updates"], trace["frames"]):
            if frame["update"] != update or set(frame["belts"]) != expected_belts:
                raise ValueError("trace update or belt names differ from fixtures")
            cargo: Counter[str] = Counter()
            for belt in frame["belts"].values():
                if type(belt["count"]) is not int or belt["count"] != len(belt["items"]):
                    raise ValueError("trace count does not match live items")
                if not 0 <= belt["count"] <= 3:
                    raise ValueError("trace capacity violation")
                for item in belt["items"]:
                    identifier(item["item"])
                    number(item["y"], -TOLERANCE, 1 + TOLERANCE)
                    number(item["x"], -1 - TOLERANCE, 1 + TOLERANCE)
                    cargo[item["item"]] += 1
            if cargo != initial_cargo:
                raise ValueError("trace violates per-item cargo conservation")


def compare_traces(expected: list[dict[str, Any]], actual: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Caller validates trace shape first. Java cache is evidence, not compared."""
    mismatches = []
    for ref, port in zip(expected, actual):
        for index, (ref_frame, port_frame) in enumerate(zip(ref["frames"], port["frames"])):
            for name, ref_belt in ref_frame["belts"].items():
                port_belt = port_frame["belts"][name]
                location = {"case": ref["name"], "update_index": index, "update": ref_frame["update"], "belt": name}
                if ref_belt["count"] != port_belt["count"]:
                    mismatches.append(dict(location, field="count", java=ref_belt["count"], python=port_belt["count"]))
                for item_index, (ref_item, port_item) in enumerate(zip(ref_belt["items"], port_belt["items"])):
                    for field in ("item", "y", "x"):
                        expected_value, actual_value = ref_item[field], port_item[field]
                        differs = expected_value != actual_value if field == "item" else abs(expected_value - actual_value) > TOLERANCE
                        if differs:
                            mismatches.append(dict(location, item_index=item_index, field=field,
                                                   java=expected_value, python=actual_value))
    return mismatches


def diagnose_tool(name: str) -> dict[str, Any]:
    path = shutil.which(name)
    if path is None:
        return {"available": False, "error": "executable not found"}
    try:
        process = subprocess.run([path, "-version"], text=True, capture_output=True, timeout=10, check=False)
        return {"available": process.returncode == 0, "path": path, "exit_code": process.returncode,
                "stdout": process.stdout.strip(), "stderr": process.stderr.strip()}
    except (OSError, subprocess.TimeoutExpired) as error:
        return {"available": False, "path": path, "error": str(error)}


def java_traces(cases: list[dict[str, Any]], toolchain: dict[str, Any]) -> list[dict[str, Any]]:
    with tempfile.TemporaryDirectory(prefix=".conveyor-reference-", dir=ROOT) as directory:
        compile_result = subprocess.run(
            [toolchain["javac"]["path"], "-encoding", "UTF-8", "-d", directory, str(JAVA_SOURCE)],
            text=True, capture_output=True, timeout=30, check=False)
        if compile_result.returncode:
            raise RuntimeError("javac failed: " + compile_result.stderr.strip())
        result = subprocess.run(
            [toolchain["java"]["path"], "-cp", directory, "ConveyorTransferReference"],
            input=protocol_input(cases), text=True, capture_output=True, timeout=30, check=False)
        if result.returncode:
            raise RuntimeError("Java reference failed: " + result.stderr.strip())
        return [json.loads(line) for line in result.stdout.splitlines() if line.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", type=Path, default=FIXTURES)
    parser.add_argument("--output", type=Path, help="write a new JSON report; refuses to overwrite")
    args = parser.parse_args(argv)
    if args.output is not None and args.output.exists():
        parser.error("output already exists; choose a new report path")
    report: dict[str, Any] = {
        "status": "error", "started_at": datetime.now(timezone.utc).isoformat(),
        "python": sys.version, "platform": platform.platform(),
        "reference_kind": "source-extracted Java float conveyor transfers; not the original engine",
        "upstream_commit": UPSTREAM_COMMIT, "position_absolute_tolerance": TOLERANCE,
        "exact_fields": ["case", "update", "belt", "count", "item identity and order"],
        "cache_comparison": "Java minitem/mid/lastInserted are recorded, but Python does not yet retain these caches.",
        "device_test": "not run", "java_comparison": "not run",
    }
    exit_code = 2
    try:
        fixtures = load_fixtures(args.fixtures)
        cases = fixtures["cases"]
        report.update({"conditions": fixtures["conditions"], "excluded": fixtures["excluded"],
                       "case_count": len(cases), "update_count": sum(len(case["updates"]) for case in cases),
                       "sha256": {"fixtures": hashlib.sha256(args.fixtures.read_bytes()).hexdigest(),
                                  "java_source": hashlib.sha256(JAVA_SOURCE.read_bytes()).hexdigest(),
                                  "python_runtime": hashlib.sha256(PYTHON_SOURCE.read_bytes()).hexdigest()}})
        actual = python_traces(cases)
        validate_traces(cases, actual)
        report["python_traces"] = actual
        report["python_trace_status"] = "generated; shape and cargo conservation checked"
        toolchain = {name: diagnose_tool(name) for name in ("javac", "java")}
        report["toolchain"] = toolchain
        if not all(tool["available"] for tool in toolchain.values()):
            report["status"] = "unavailable_toolchain"
            report["error"] = "A working javac and java are required; Java comparison was not executed."
        else:
            report["java_comparison"] = "attempted; no completed comparison"
            expected = java_traces(cases, toolchain)
            validate_traces(cases, expected)
            mismatches = compare_traces(expected, actual)
            report.update({"java_traces": expected, "mismatches": mismatches,
                           "mismatch_count": len(mismatches), "java_comparison": "executed",
                           "status": "mismatch" if mismatches else "passed"})
            exit_code = 1 if mismatches else 0
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.TimeoutExpired) as error:
        report["error"] = str(error)
    text = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if args.output is not None:
        try:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("x", encoding="utf-8") as handle:
                handle.write(text)
        except OSError as error:
            print("Cannot write report: " + str(error), file=sys.stderr)
            return 2
    print(text, end="")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
