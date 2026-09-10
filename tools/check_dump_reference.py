#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Compare drill dump selection/order against extracted Java methods.

Development only: requires javac/java (JDK 17 in CI). Receiver acceptance
tables and proximity order are explicit test adapters, not the original game.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.check_conveyor_reference import diagnose_tool, identifier, load_game

FIXTURES = ROOT / "reference" / "drill_dump_scenarios.json"
JAVA_SOURCE = ROOT / "reference" / "DrillDumpReference.java"
PYTHON_SOURCE = ROOT / "mindustry_pythonista.py"
UPSTREAM_COMMIT = "c9686eb5d0ae5dd47ee02c40f99f7d5018ccbc8c"
ITEMS = ("copper", "lead")
CONDITIONS = {"has_items": True, "can_dump": True, "item_ids": list(ITEMS),
              "neighbor_order": "explicit_fixture_order", "receiver": "scripted_item_set_and_total_capacity",
              "calls": "explicit_dump_or_periodic_drill_boundary", "inventory_limit": 10}


def integer(value: Any, maximum: int = 2**53) -> int:
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError("invalid nonnegative fixture/trace integer")
    return value


def inventory(value: Any, sparse: bool = False) -> Counter[str]:
    if not isinstance(value, dict) or (not set(value).issubset(ITEMS) if sparse else set(value) != set(ITEMS)):
        raise ValueError("invalid inventory item names")
    return Counter({name: integer(count, 10) for name, count in value.items()})


def load_fixtures(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != 1 or data.get("upstream", {}).get("commit") != UPSTREAM_COMMIT:
        raise ValueError("unsupported fixture schema or upstream commit")
    if data.get("conditions") != CONDITIONS:
        raise ValueError("fixtures exceed the extracted dump scope")
    cases = data.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("fixtures must contain cases")
    names = set()
    for case in cases:
        name = identifier(case["name"])
        if name in names:
            raise ValueError("duplicate case name")
        names.add(name)
        integer(case["cursor"])
        if case["dominant"] not in (None,) + ITEMS:
            raise ValueError("unknown dominant item")
        cargo = inventory(case["inventory"], sparse=True)
        if sum(cargo.values()) > 10 or any(count == 0 for count in cargo.values()):
            raise ValueError("invalid initial drill inventory")
        if not isinstance(case["neighbors"], list):
            raise ValueError("neighbors must be an explicit list")
        # Java's cdump and scan index are int. Compare only non-overflowing
        # cases; the game's schema 1 cursor validator is unchanged.
        if case["cursor"] + max(len(case["neighbors"]), 1) > 2**31 - 1:
            raise ValueError("cursor scan exceeds the upstream int comparison scope")
        neighbor_names = set()
        for neighbor in case["neighbors"]:
            name = identifier(neighbor["name"])
            if name in neighbor_names:
                raise ValueError("duplicate neighbor name")
            neighbor_names.add(name)
            accepted = neighbor["accepts"]
            if not isinstance(accepted, list) or any(item not in ITEMS for item in accepted) or len(set(accepted)) != len(accepted):
                raise ValueError("invalid scripted acceptance set")
            integer(neighbor["capacity"], 10)
        if not isinstance(case["calls"], list) or not case["calls"] or len(case["calls"]) > 20:
            raise ValueError("explicit calls must contain 1..20 entries (no mining in adapter)")
        if any(kind not in ("drill", "any") + ITEMS for kind in case["calls"]):
            raise ValueError("unknown dump call kind")
    return data


def protocol_input(cases: list[dict[str, Any]]) -> str:
    lines = []
    for case in cases:
        lines.append("\t".join(("C", case["name"], str(case["cursor"]), case["dominant"] or "any",
                                *(str(case["inventory"].get(item, 0)) for item in ITEMS))))
        for neighbor in case["neighbors"]:
            mask = sum(1 << ITEMS.index(item) for item in neighbor["accepts"])
            lines.append("\t".join(("N", neighbor["name"], str(mask), str(neighbor["capacity"]))))
        lines.extend("D\t" + call for call in case["calls"])
        lines.append("E")
    return "\n".join(lines) + "\n"


def python_traces(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    game = load_game()
    traces = []
    for case in cases:
        world = game.World(32, 32)
        # The real periodic method computes dominant from ore. Seed it for
        # placement, then remove ore when the fixture requests no dominant.
        world.ore[world.index(10, 10)] = case["dominant"] or "copper"
        drill = world.place("mechanical-drill", 10, 10, free=True)
        if case["dominant"] is None:
            world.ore[world.index(10, 10)] = ""
        drill.inventory = dict(case["inventory"])
        drill.cursor = case["cursor"]
        neighbors = [game.Building(index + 100, "router", 0, 0) for index in range(len(case["neighbors"]))]
        seeds = {building.id: seed for building, seed in zip(neighbors, case["neighbors"])}
        receipts = {seed["name"]: dict.fromkeys(ITEMS, 0) for seed in case["neighbors"]}
        attempts: list[dict[str, Any]] = []
        world.neighbors = lambda source: neighbors

        def receive(target, source, item):
            seed = seeds[target.id]
            received = receipts[seed["name"]]
            accepted = item in seed["accepts"] and sum(received.values()) < seed["capacity"]
            attempts.append({"neighbor": seed["name"], "item": item, "accepted": accepted,
                             "cursor_before": source.cursor})
            if accepted:
                received[item] += 1
            return accepted

        world.receive = receive
        selected: list[Any] = [None]
        outcome: list[bool] = [False]
        original_dump = world.dump

        def traced_dump(source, item=None):
            selected[0] = item
            outcome[0] = original_dump(source, item)
            return outcome[0]

        world.dump = traced_dump
        frames = []
        for kind in case["calls"]:
            attempts.clear()
            if kind == "drill":
                drill.dump_ticks = 4
                world._tick_drill(drill)
            else:
                world.dump(drill, None if kind == "any" else kind)
            if world.stats["mined"] != 0:
                raise ValueError("fixture escaped the non-producing drill adapter")
            frames.append({"call": kind, "selected": selected[0], "result": outcome[0],
                           "cursor": drill.cursor, "inventory": {item: drill.inventory.get(item, 0) for item in ITEMS},
                           "receipts": {name: dict(values) for name, values in receipts.items()},
                           "attempts": list(attempts)})
        traces.append({"name": case["name"], "frames": frames})
    return traces


def validate_traces(cases: list[dict[str, Any]], traces: list[dict[str, Any]]) -> None:
    if not isinstance(traces, list) or len(traces) != len(cases):
        raise ValueError("trace case count differs")
    for case, trace in zip(cases, traces):
        if trace["name"] != case["name"] or len(trace["frames"]) != len(case["calls"]):
            raise ValueError("trace identity or call count differs")
        seeds = {seed["name"]: seed for seed in case["neighbors"]}
        received = {name: Counter() for name in seeds}
        initial = inventory(case["inventory"], sparse=True)
        remaining = initial.copy()
        for kind, frame in zip(case["calls"], trace["frames"]):
            if frame["call"] != kind or frame["selected"] not in (None,) + ITEMS or type(frame["result"]) is not bool:
                raise ValueError("invalid call result/selector")
            integer(frame["cursor"])
            if set(frame["receipts"]) != set(seeds):
                raise ValueError("trace neighbor set differs")
            successes = 0
            for attempt in frame["attempts"]:
                if attempt["neighbor"] not in seeds or attempt["item"] not in ITEMS or type(attempt["accepted"]) is not bool:
                    raise ValueError("invalid receipt attempt")
                integer(attempt["cursor_before"])
                if attempt["accepted"]:
                    seed = seeds[attempt["neighbor"]]
                    values = received[attempt["neighbor"]]
                    if attempt["item"] not in seed["accepts"] or sum(values.values()) >= seed["capacity"]:
                        raise ValueError("receipt violates scripted acceptance")
                    values[attempt["item"]] += 1
                    remaining[attempt["item"]] -= 1
                    successes += 1
            if successes != int(frame["result"]):
                raise ValueError("dump must transfer exactly one item iff successful")
            cargo = inventory(frame["inventory"])
            if cargo != remaining:
                raise ValueError("source inventory differs from receipt attempts")
            for name, values in frame["receipts"].items():
                actual = inventory(values)
                if actual != received[name]:
                    raise ValueError("receipt inventory differs from attempts")
                cargo.update(actual)
            if cargo != initial:
                raise ValueError("per-item cargo is not conserved")


def compare_traces(expected: list[dict[str, Any]], actual: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(expected) != len(actual):
        return [{"field": "case_count", "java": len(expected), "python": len(actual)}]
    mismatches = []
    for reference, port in zip(expected, actual):
        if reference["name"] != port["name"] or len(reference["frames"]) != len(port["frames"]):
            mismatches.append({"case": reference["name"], "field": "identity_or_frame_count"})
            continue
        for index, (left, right) in enumerate(zip(reference["frames"], port["frames"])):
            for field in ("call", "selected", "result", "cursor", "inventory", "receipts", "attempts"):
                if left[field] != right[field]:
                    mismatches.append({"case": reference["name"], "call_index": index, "field": field,
                                       "java": left[field], "python": right[field]})
    return mismatches


def java_traces(cases: list[dict[str, Any]], toolchain: dict[str, Any]) -> list[dict[str, Any]]:
    with tempfile.TemporaryDirectory(prefix=".dump-reference-", dir=ROOT) as directory:
        compiled = subprocess.run([toolchain["javac"]["path"], "-encoding", "UTF-8", "-d", directory, str(JAVA_SOURCE)],
                                  text=True, capture_output=True, timeout=30, check=False)
        if compiled.returncode:
            raise RuntimeError("javac failed: " + compiled.stderr.strip())
        result = subprocess.run([toolchain["java"]["path"], "-cp", directory, "DrillDumpReference"],
                                input=protocol_input(cases), text=True, capture_output=True, timeout=30, check=False)
        if result.returncode:
            raise RuntimeError("Java reference failed: " + result.stderr.strip())
        return [json.loads(line) for line in result.stdout.splitlines() if line.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", type=Path, default=FIXTURES)
    parser.add_argument("--output", type=Path, help="write a new report; refuses to overwrite")
    args = parser.parse_args(argv)
    if args.output is not None and args.output.exists():
        parser.error("output already exists; choose a new report path")
    report: dict[str, Any] = {"status": "error", "started_at": datetime.now(timezone.utc).isoformat(),
        "python": sys.version, "platform": platform.platform(), "upstream_commit": UPSTREAM_COMMIT,
        "reference_kind": "source-extracted Java dump and drill selector with scripted receivers; not the original engine",
        "exact_fields": ["selector", "result", "cursor", "inventory", "receipts", "attempt order and cursor"],
        "device_test": "not run", "java_comparison": "not run"}
    exit_code = 2
    try:
        fixtures = load_fixtures(args.fixtures)
        cases = fixtures["cases"]
        report.update({"conditions": fixtures["conditions"], "excluded": fixtures["excluded"],
            "case_count": len(cases), "call_count": sum(len(case["calls"]) for case in cases),
            "sha256": {"fixtures": hashlib.sha256(args.fixtures.read_bytes()).hexdigest(),
                       "java_source": hashlib.sha256(JAVA_SOURCE.read_bytes()).hexdigest(),
                       "python_runtime": hashlib.sha256(PYTHON_SOURCE.read_bytes()).hexdigest()}})
        actual = python_traces(cases)
        validate_traces(cases, actual)
        report["python_traces"] = actual
        report["python_trace_status"] = "generated; shape, scripted receipts and cargo checked"
        toolchain = {name: diagnose_tool(name) for name in ("javac", "java")}
        report["toolchain"] = toolchain
        if not all(tool["available"] for tool in toolchain.values()):
            report.update(status="unavailable_toolchain", error="A working javac and java are required; Java comparison was not executed.")
        else:
            report["java_comparison"] = "attempted; no completed comparison"
            expected = java_traces(cases, toolchain)
            validate_traces(cases, expected)
            mismatches = compare_traces(expected, actual)
            report.update(java_traces=expected, mismatches=mismatches, mismatch_count=len(mismatches),
                          java_comparison="executed", status="mismatch" if mismatches else "passed")
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
