#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Compare offload and explicit drill production boundaries with extracted Java.

Development-only JDK comparison. Proximity/receivers/timer boundaries are test
adapters, not the original engine. Direct offload compares every attempt; tick
traces compare dump and first offload attempts plus the entire final state.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.check_conveyor_reference import diagnose_tool, identifier, load_game

FIXTURES = ROOT / "reference" / "drill_offload_scenarios.json"
JAVA_SOURCE = ROOT / "reference" / "DrillOffloadReference.java"
PYTHON_SOURCE = ROOT / "mindustry_pythonista.py"
UPSTREAM_COMMIT = "c9686eb5d0ae5dd47ee02c40f99f7d5018ccbc8c"
ITEMS = ("copper", "lead")
CONDITIONS = {
    "has_items": True, "can_dump": True, "item_ids": list(ITEMS),
    "neighbor_order": "explicit_fixture_order",
    "receiver": "scripted_item_set_and_total_capacity_without_rejection_side_effects",
    "calls": "direct_offload_or_explicit_drill_tick_with_timer_boundary",
    "delta": 1, "efficiency": 1, "optional_efficiency": 0, "initial_warmup": 1,
    "drill_delay": 650, "capacity": 10, "progress_scope": "integer_exact_at_active_boundaries",
    "tick_attempt_scope": "all_periodic_dump_attempts_and_first_offload_only",
    "event_scope": "consecutive_offload_calls_collapsed_to_one_category",
    "mined_scope": "adapter_tick_production_count_not_original_campaign_accounting",
}
FIELDS = ("call", "result", "cursor", "progress", "mined", "inventory", "receipts",
          "events", "offload_progress", "dump_attempts", "offload_attempts")


def integer(value: Any, maximum: int = 2**31 - 1) -> int:
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError("invalid nonnegative fixture/trace integer")
    return value


def exact_progress(value: Any) -> float:
    if type(value) not in (float, int) or not math.isfinite(value) or not 0 <= value <= 2700 or value != int(value):
        raise ValueError("progress escaped the exact integer comparison scope")
    return float(value)


def inventory(value: Any, sparse: bool = False) -> Counter[str]:
    if not isinstance(value, dict) or (not set(value).issubset(ITEMS) if sparse else set(value) != set(ITEMS)):
        raise ValueError("invalid inventory item names")
    return Counter({name: integer(count, 100) for name, count in value.items()})


def load_fixtures(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != 1 or data.get("upstream", {}).get("commit") != UPSTREAM_COMMIT:
        raise ValueError("unsupported fixture schema or upstream commit")
    if data.get("conditions") != CONDITIONS:
        raise ValueError("fixtures exceed the extracted offload scope")
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
        count = integer(case["ore_count"], 4)
        if (case["dominant"] is None) != (count == 0):
            raise ValueError("dominant item and ore count disagree")
        integer(case["progress"], 2600)
        cargo = inventory(case["inventory"], sparse=True)
        if sum(cargo.values()) > 10 or any(count == 0 for count in cargo.values()):
            raise ValueError("invalid initial drill inventory")
        if not isinstance(case["neighbors"], list):
            raise ValueError("neighbors must be an explicit list")
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
            integer(neighbor["capacity"], 100)
        if not isinstance(case["calls"], list) or not 1 <= len(case["calls"]) <= 12:
            raise ValueError("explicit calls must contain 1..12 entries")
        if any(kind not in ("tick", "dump_tick") + ITEMS for kind in case["calls"]):
            raise ValueError("unknown offload call kind")
    return data


def protocol_input(cases: list[dict[str, Any]]) -> str:
    lines = []
    for case in cases:
        lines.append("\t".join(("C", case["name"], str(case["cursor"]), case["dominant"] or "none",
                                str(case["ore_count"]), str(case["progress"]),
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
        world.ore[world.index(10, 10)] = "copper"
        drill = world.place("mechanical-drill", 10, 10, free=True)
        for index, (x, y) in enumerate(world.tiles(drill)):
            world.ore[world.index(x, y)] = case["dominant"] if index < case["ore_count"] else ""
        drill.inventory = dict(case["inventory"])
        drill.cursor, drill.progress, drill.warmup = case["cursor"], float(case["progress"]), 1.0
        neighbors = [game.Building(index + 100, "router", 0, 0) for index in range(len(case["neighbors"]))]
        seeds = {building.id: seed for building, seed in zip(neighbors, case["neighbors"])}
        receipts = {seed["name"]: dict.fromkeys(ITEMS, 0) for seed in case["neighbors"]}
        world.neighbors = lambda source: neighbors
        frame: dict[str, Any] = {}
        recording: list[Any] = [None]

        def receive(target, source, item):
            seed = seeds[target.id]
            received = receipts[seed["name"]]
            accepted = item in seed["accepts"] and sum(received.values()) < seed["capacity"]
            if recording[0] is not None:
                recording[0].append({"neighbor": seed["name"], "item": item, "accepted": accepted,
                                     "cursor_before": source.cursor})
            if accepted:
                received[item] += 1
            return accepted

        world.receive = receive
        original_dump, original_offload = world.dump, world.offload

        def event(kind):
            if not frame["events"] or frame["events"][-1] != kind:
                frame["events"].append(kind)

        def traced_dump(source, item=None):
            event("dump")
            recording[0] = frame["dump_attempts"]
            return original_dump(source, item)

        def traced_offload(source, item):
            event("offload")
            first = frame["offload_progress"] is None
            recording[0] = frame["offload_attempts"] if first else None
            if first:
                frame["offload_progress"] = source.progress
            return original_offload(source, item)

        world.dump, world.offload = traced_dump, traced_offload
        frames = []
        for kind in case["calls"]:
            frame = {"call": kind, "result": None, "events": [], "offload_progress": None,
                     "dump_attempts": [], "offload_attempts": []}
            if kind in ITEMS:
                frame["result"] = world.offload(drill, kind)
            else:
                drill.dump_ticks = 4 if kind == "dump_tick" else 0
                world._tick_drill(drill)
            frame.update(cursor=drill.cursor, progress=drill.progress, mined=world.stats["mined"],
                         inventory={item: drill.inventory.get(item, 0) for item in ITEMS},
                         receipts={name: dict(values) for name, values in receipts.items()})
            frames.append(frame)
        traces.append({"name": case["name"], "frames": frames})
    return traces


def validate_traces(cases: list[dict[str, Any]], traces: list[dict[str, Any]]) -> None:
    """Check conservation, full direct scans and each tick's observable prefix.

    Later production attempts may be algebraically batched after a rejection.
    Their final receipts/state are still compared exactly with the Java loop.
    """
    if not isinstance(traces, list) or len(traces) != len(cases):
        raise ValueError("trace case count differs")
    for case, trace in zip(cases, traces):
        if trace["name"] != case["name"] or len(trace["frames"]) != len(case["calls"]):
            raise ValueError("trace identity or call count differs")
        neighbors = case["neighbors"]
        seeds = {seed["name"]: seed for seed in neighbors}
        received = {name: Counter() for name in seeds}
        initial = inventory(case["inventory"], sparse=True)
        cargo = initial.copy()
        produced = Counter()
        cursor, mined = case["cursor"], 0
        for kind, frame in zip(case["calls"], trace["frames"]):
            if set(frame) != set(FIELDS) or frame["call"] != kind:
                raise ValueError("invalid frame fields/call")
            integer(frame["cursor"])
            exact_progress(frame["progress"])
            integer(frame["mined"], 100)
            delta_mined = frame["mined"] - mined
            if delta_mined < 0 or (kind in ITEMS and delta_mined):
                raise ValueError("invalid adapter production count")
            expected_events = (["dump"] if kind == "dump_tick" else [])
            has_offload = kind in ITEMS or delta_mined > 0
            if has_offload:
                expected_events.append("offload")
                exact_progress(frame["offload_progress"])
            elif frame["offload_progress"] is not None:
                raise ValueError("nonproducing tick recorded offload progress")
            if frame["events"] != expected_events:
                raise ValueError("dump/offload event order differs")
            if (kind in ITEMS and type(frame["result"]) is not bool) or (kind not in ITEMS and frame["result"] is not None):
                raise ValueError("invalid direct offload result")
            if set(frame["receipts"]) != set(seeds):
                raise ValueError("trace neighbor set differs")

            def consume_attempt(attempt, seed, item, expected_cursor):
                if set(attempt) != {"neighbor", "item", "accepted", "cursor_before"}:
                    raise ValueError("invalid attempt fields")
                values = received[seed["name"]]
                accepted = item in seed["accepts"] and sum(values.values()) < seed["capacity"]
                if (attempt["neighbor"] != seed["name"] or attempt["item"] != item
                        or type(attempt["accepted"]) is not bool or attempt["accepted"] != accepted
                        or type(attempt["cursor_before"]) is not int or attempt["cursor_before"] != expected_cursor):
                    raise ValueError("receipt attempt violates item/order/cursor/acceptance")
                if accepted:
                    values[item] += 1
                return accepted

            # Reconstruct the complete optional dump scan from its visible
            # starting inventory. No produced item exists at this point.
            expected_dump = []
            if kind == "dump_tick" and sum(cargo.values()) > 0 and neighbors:
                selected = case["dominant"] if cargo.get(case["dominant"], 0) else None
                candidates = (selected,) if selected else ITEMS
                start, done = cursor, False
                for offset in range(len(neighbors)):
                    seed = neighbors[(start + offset) % len(neighbors)]
                    for item in candidates:
                        if not cargo.get(item, 0):
                            continue
                        index = len(expected_dump)
                        if index >= len(frame["dump_attempts"]):
                            raise ValueError("missing dump attempt")
                        attempt = frame["dump_attempts"][index]
                        expected_dump.append(attempt)
                        if consume_attempt(attempt, seed, item, cursor):
                            cargo[item] -= 1
                            done = True
                            break
                    cursor = (cursor + 1) % len(neighbors)
                    if done:
                        break
            if len(expected_dump) != len(frame["dump_attempts"]):
                raise ValueError("unexpected dump attempts")
            first_external = False
            attempts = frame["offload_attempts"]
            used = 0
            if has_offload:
                item = kind if kind in ITEMS else case["dominant"]
                if item not in ITEMS:
                    raise ValueError("offload has no dominant item")
                start = cursor
                for offset in range(len(neighbors)):
                    cursor = (cursor + 1) % len(neighbors)
                    seed = neighbors[(start + offset) % len(neighbors)]
                    if used >= len(attempts):
                        raise ValueError("missing first offload attempt")
                    first_external = consume_attempt(attempts[used], seed, item, cursor)
                    used += 1
                    if first_external:
                        break
                if kind in ITEMS:
                    produced[item] += 1
                    if frame["result"] != first_external or frame["cursor"] != cursor:
                        raise ValueError("direct offload result or final cursor differs")
                else:
                    produced[item] += delta_mined
            if used != len(attempts):
                raise ValueError("unexpected first offload attempts")
            # Later offloads in the same tick are represented by their full
            # final receipts, without requiring repeated rejected scans.
            actual_cargo = inventory(frame["inventory"])
            total = actual_cargo.copy()
            later_transfers = 0
            for name, raw in frame["receipts"].items():
                actual = inventory(raw)
                if any(actual[item] < received[name][item] for item in ITEMS):
                    raise ValueError("receipts lost an observed item")
                extra = actual - received[name]
                if kind in ITEMS and extra:
                    raise ValueError("direct offload made unobserved transfers")
                if any(item != case["dominant"] for item, count in extra.items() if count):
                    raise ValueError("later production transferred a different item")
                later_transfers += sum(extra.values())
                if any(item not in seeds[name]["accepts"] for item, count in actual.items() if count):
                    raise ValueError("receipts violate the acceptance set")
                if sum(actual.values()) > seeds[name]["capacity"]:
                    raise ValueError("receipts exceed scripted capacity")
                received[name] = actual
                total.update(actual)
            if later_transfers > max(delta_mined - 1, 0):
                raise ValueError("later receipts exceed remaining production")
            expected = initial + produced
            if total != expected:
                raise ValueError("per-item cargo plus production is not conserved")
            cargo, cursor, mined = actual_cargo, frame["cursor"], frame["mined"]


def compare_traces(expected: list[dict[str, Any]], actual: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(expected) != len(actual):
        return [{"field": "case_count", "java": len(expected), "python": len(actual)}]
    mismatches = []
    for reference, port in zip(expected, actual):
        if reference["name"] != port["name"] or len(reference["frames"]) != len(port["frames"]):
            mismatches.append({"case": reference["name"], "field": "identity_or_frame_count"})
            continue
        for index, (left, right) in enumerate(zip(reference["frames"], port["frames"])):
            for field in FIELDS:
                if left[field] != right[field]:
                    mismatches.append({"case": reference["name"], "call_index": index, "field": field,
                                       "java": left[field], "python": right[field]})
    return mismatches


def java_traces(cases: list[dict[str, Any]], toolchain: dict[str, Any]) -> list[dict[str, Any]]:
    with tempfile.TemporaryDirectory(prefix=".offload-reference-", dir=ROOT) as directory:
        compiled = subprocess.run([toolchain["javac"]["path"], "-encoding", "UTF-8", "-d", directory, str(JAVA_SOURCE)],
                                  text=True, capture_output=True, timeout=30, check=False)
        if compiled.returncode:
            raise RuntimeError("javac failed: " + compiled.stderr.strip())
        result = subprocess.run([toolchain["java"]["path"], "-cp", directory, "DrillOffloadReference"],
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
        "reference_kind": "source-extracted Java offload/dump/dry drill branch with scripted receivers; not original engine",
        "exact_fields": list(FIELDS), "device_test": "not run", "java_comparison": "not run"}
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
        report["python_trace_status"] = "generated; prefixes, scripted receipts and production conservation checked"
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
    output = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if args.output is not None:
        try:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("x", encoding="utf-8") as handle:
                handle.write(output)
        except OSError as error:
            print("Cannot write report: " + str(error), file=sys.stderr)
            return 2
    print(output, end="")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
