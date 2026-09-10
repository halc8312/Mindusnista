#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Compare integrated, actual transport receivers with extracted Java methods.

Explicit proximity and update order are adapters. This is not a Mindustry
headless-engine run or an iPhone test. A missing JDK remains not_run/exit 2.
"""
from __future__ import annotations

import argparse
from collections import Counter
import copy
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
from tools.check_conveyor_reference import diagnose_tool, identifier, load_game, number
from tools.check_offload_reference import integer

FIXTURES = ROOT / "reference/integrated_transport_scenarios.json"
JAVA_SOURCE = ROOT / "reference/IntegratedTransportReference.java"
PYTHON_SOURCE = ROOT / "mindustry_pythonista.py"
UPSTREAM_COMMIT = "c9686eb5d0ae5dd47ee02c40f99f7d5018ccbc8c"
ITEMS = ("copper", "lead")
KINDS = ("mechanical-drill", "conveyor", "router", "copper-wall")
TOLERANCE = 2e-5
CONDITIONS = {
    "receiver": "actual_extracted_drill_conveyor_router_methods",
    "neighbor_order": "complete_explicit_fixture_proximity",
    "update_order": "explicit_per_building_not_entity_scheduler",
    "timer": "drill_five_update_counter_not_upstream_time_phase",
    "delta": 1, "efficiency": 1, "time_scale": 1, "optional_efficiency": 0,
    "team": "same", "router_speed": 8, "drill_delay": 650,
    "drill_warmup_speed": 0.015, "drill_capacity": 10,
    "item_ids": list(ITEMS), "conveyor_last_inserted": 0,
    "controlled_routers": False, "overflow_gates": False,
    "topology_changes": False, "float_absolute_tolerance": TOLERANCE,
    "discrete_comparison": "exact_including_item_order_transfer_update_and_rotation",
}
STATE_FIELDS = {"inventory", "belt", "minitem", "mid", "lastInserted", "cursor", "rotation",
                "routerTime", "lastInput", "progress", "warmup", "dumpTicks"}
FLOAT_FIELDS = {"x", "y", "minitem", "routerTime", "progress", "warmup"}


def inventory(value: Any) -> Counter[str]:
    if not isinstance(value, dict) or not set(value).issubset(ITEMS):
        raise ValueError("unsupported inventory items")
    return Counter({name: integer(count, 1000) for name, count in value.items()})


def adjacent(left: dict[str, Any], right: dict[str, Any]) -> bool:
    ls = 2 if left["kind"] == "mechanical-drill" else 1
    rs = 2 if right["kind"] == "mechanical-drill" else 1
    lx, ly, rx, ry = left["x"], left["y"], right["x"], right["y"]
    return ((lx + ls == rx or rx + rs == lx) and max(ly, ry) < min(ly + ls, ry + rs)
            or (ly + ls == ry or ry + rs == ly) and max(lx, rx) < min(lx + ls, rx + rs))


def load_fixtures(path: Path = FIXTURES) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != 1 or data.get("upstream", {}).get("commit") != UPSTREAM_COMMIT:
        raise ValueError("unsupported fixture schema or upstream commit")
    if data.get("conditions") != CONDITIONS:
        raise ValueError("fixtures exceed the extracted integration scope")
    cases = data.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("fixtures must contain cases")
    names = set()
    for case in cases:
        name = identifier(case["name"])
        if name in names:
            raise ValueError("duplicate case name")
        names.add(name)
        number(case["speed"], 0.001, 0.25)
        if not isinstance(case["buildings"], list) or not 1 <= len(case["buildings"]) <= 12:
            raise ValueError("unsupported fixture building count")
        builds, occupied = {}, set()
        for seed in case["buildings"]:
            name = identifier(seed["name"])
            if name == "none" or name in builds or seed["kind"] not in KINDS:
                raise ValueError("invalid or duplicate fixture building")
            builds[name] = seed
            size = 2 if seed["kind"] == "mechanical-drill" else 1
            integer(seed["x"], 32 - size)
            integer(seed["y"], 32 - size)
            tiles = {(x, y) for x in range(seed["x"], seed["x"] + size)
                     for y in range(seed["y"], seed["y"] + size)}
            if occupied & tiles:
                raise ValueError("overlapping fixture buildings")
            occupied.update(tiles)
            integer(seed["rotation"], 3)
            integer(seed["cursor"], 2**31 - 9)
            number(seed["router_time"], 0, 8)
            number(seed["progress"], 0, 2600)
            number(seed["warmup"], 0, 1)
            integer(seed["dump_ticks"], 4)
            held = inventory(seed["inventory"])
            limit = 10 if seed["kind"] == "mechanical-drill" else 1 if seed["kind"] == "router" else 0
            if sum(held.values()) > limit or any(count == 0 for count in held.values()):
                raise ValueError("invalid seed inventory")
            number(seed["minitem"], 0, 1)
            cargo = seed["belt"]
            if not isinstance(cargo, list) or len(cargo) > (3 if seed["kind"] == "conveyor" else 0):
                raise ValueError("invalid seed cargo")
            integer(seed["mid"], min(len(cargo), 1))
            if seed["kind"] != "conveyor" and (seed["minitem"] != 1 or seed["mid"] != 0):
                raise ValueError("conveyor cache on another block")
            for item in cargo:
                if item["item"] not in ITEMS:
                    raise ValueError("unsupported cargo item")
                number(item["y"], 0, 1)
                number(item["x"], -1, 1)
            if cargo != sorted(cargo, key=lambda item: item["y"]):
                raise ValueError("seed cargo must be ordered")
            count = integer(seed["ore_count"], 4)
            if seed["ore"] not in (None,) + ITEMS or (seed["ore"] is None) != (count == 0):
                raise ValueError("ore item/count disagree")
            if seed["kind"] != "mechanical-drill" and count:
                raise ValueError("ore on a non-drill fixture")
        proximity = case["neighbors"]
        if not isinstance(proximity, dict) or set(proximity) != set(builds):
            raise ValueError("every building needs an explicit proximity list")
        for name, neighbors in proximity.items():
            if not isinstance(neighbors, list) or len(set(neighbors)) != len(neighbors):
                raise ValueError("duplicate or malformed proximity")
            expected = {other for other in builds if other != name and adjacent(builds[name], builds[other])}
            if set(neighbors) != expected:
                raise ValueError("proximity must contain all and only edge neighbors")
            source = builds[name]["last_input"]
            if source is not None and source not in builds:
                raise ValueError("unknown last input")
        updates = case["updates"]
        if not isinstance(updates, list) or not 1 <= len(updates) <= 1000:
            raise ValueError("invalid explicit update count")
        if any(name not in builds or builds[name]["kind"] == "copper-wall" for name in updates):
            raise ValueError("unknown or static update target")
    return data


def protocol_input(cases: list[dict[str, Any]]) -> str:
    lines = []
    for case in cases:
        lines.append("\t".join(("C", case["name"], str(case["speed"]))))
        for seed in case["buildings"]:
            fields = ["B", seed["name"], seed["kind"], seed["x"], seed["y"], seed["rotation"],
                      seed["cursor"], seed["router_time"], seed["last_input"] or "none", seed["progress"],
                      seed["warmup"], seed["dump_ticks"], seed["inventory"].get("copper", 0),
                      seed["inventory"].get("lead", 0), seed["minitem"], seed["mid"], seed["ore"] or "none",
                      seed["ore_count"], len(seed["belt"])]
            for item in seed["belt"]:
                fields.extend((item["item"], item["y"], item["x"]))
            lines.append("\t".join(map(str, fields)))
        lines.extend("\t".join(["N", name] + neighbors) for name, neighbors in case["neighbors"].items())
        lines.extend("U\t" + name for name in case["updates"])
        lines.append("E")
    return "\n".join(lines) + "\n"


def make_world(case: dict[str, Any], game: Any) -> tuple[Any, dict[str, Any]]:
    content = copy.deepcopy(game.DEFAULT_CONTENT)
    content["conveyor"]["speed"] = case["speed"]
    world = game.World(32, 32, content)
    buildings = {}
    for seed in case["buildings"]:
        build = game.Building(world.uid(), seed["kind"], seed["x"], seed["y"], seed["rotation"],
                              content[seed["kind"]]["health"])
        world.buildings[build.id] = build
        for index, (x, y) in enumerate(world.tiles(build)):
            world.grid[world.index(x, y)] = build.id
            if index < seed["ore_count"]:
                world.ore[world.index(x, y)] = seed["ore"]
        for field in ("cursor", "router_time", "progress", "warmup", "dump_ticks"):
            setattr(build, field, seed[field])
        build.inventory = dict(seed["inventory"])
        build.belt = [game.BeltItem(item["item"], item["y"], item["x"]) for item in seed["belt"]]
        build.conveyor_minitem, build.conveyor_mid = seed["minitem"], seed["mid"]
        buildings[seed["name"]] = build
    for seed in case["buildings"]:
        build = buildings[seed["name"]]
        build.last_input = buildings[seed["last_input"]].id if seed["last_input"] else 0
        world._neighbors[build.id] = [buildings[name].id for name in case["neighbors"][seed["name"]]]
    return world, buildings


def state(buildings: dict[str, Any]) -> dict[str, Any]:
    names = {build.id: name for name, build in buildings.items()}
    result = {}
    for name, build in buildings.items():
        held = Counter(p.item for p in build.belt) if build.kind == "conveyor" else Counter(build.inventory)
        result[name] = {
            "inventory": {item: held[item] for item in ITEMS},
            "belt": [{"item": p.item, "y": p.y, "x": p.x} for p in build.belt],
            "minitem": build.conveyor_minitem, "mid": build.conveyor_mid, "lastInserted": 0,
            "cursor": build.cursor, "rotation": build.rotation, "routerTime": build.router_time,
            "lastInput": names.get(build.last_input), "progress": build.progress,
            "warmup": build.warmup, "dumpTicks": build.dump_ticks,
        }
    return result


def python_traces(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    game, traces = load_game(), []
    for case in cases:
        world, buildings = make_world(case, game)
        names = {build.id: name for name, build in buildings.items()}
        frames, events = [], []
        handle = world._handle_item
        def record(target: Any, source: Any, item: str) -> bool:
            events.append({"source": names[source.id], "target": names[target.id], "item": item,
                           "source_rotation": source.rotation, "source_cursor": source.cursor})
            return handle(target, source, item)
        world._handle_item = record
        for name in case["updates"]:
            events.clear()
            build = buildings[name]
            {"mechanical-drill": world._tick_drill, "conveyor": world._tick_conveyor,
             "router": world._tick_router}[build.kind](build)
            frames.append({"update": name, "mined": world.stats["mined"],
                           "deliveries": list(events), "buildings": state(buildings)})
        traces.append({"name": case["name"], "frames": frames})
    return traces


def validate_traces(cases: list[dict[str, Any]], traces: Any) -> None:
    if not isinstance(traces, list) or len(traces) != len(cases):
        raise ValueError("trace case count differs")
    for case, trace in zip(cases, traces):
        if set(trace) != {"name", "frames"} or trace["name"] != case["name"]:
            raise ValueError("trace case identity differs")
        if not isinstance(trace["frames"], list) or len(trace["frames"]) != len(case["updates"]):
            raise ValueError("trace update count differs")
        seeds = {seed["name"]: seed for seed in case["buildings"]}
        initial = Counter()
        for seed in seeds.values():
            initial.update(seed["inventory"])
            initial.update(item["item"] for item in seed["belt"])
        previous_mined = 0
        expected_cargo = initial.copy()
        for update, frame in zip(case["updates"], trace["frames"]):
            if set(frame) != {"update", "mined", "deliveries", "buildings"} or frame["update"] != update:
                raise ValueError("trace frame fields differ")
            mined = integer(frame["mined"], 1000)
            if mined < previous_mined:
                raise ValueError("production counter decreased")
            produced = mined - previous_mined
            if produced:
                source = seeds[update]
                if source["kind"] != "mechanical-drill" or source["ore"] is None:
                    raise ValueError("production reported by a non-mining update")
                expected_cargo[source["ore"]] += produced
            previous_mined = mined
            if set(frame["buildings"]) != set(seeds):
                raise ValueError("trace building names differ")
            held = Counter()
            for name, current in frame["buildings"].items():
                if set(current) != STATE_FIELDS or set(current["inventory"]) != set(ITEMS):
                    raise ValueError("trace state fields differ")
                cargo = inventory(current["inventory"])
                held.update(cargo)
                kind = seeds[name]["kind"]
                if kind == "router" and sum(cargo.values()) > 1 or kind == "copper-wall" and sum(cargo.values()):
                    raise ValueError("receiver inventory capacity exceeded")
                if not isinstance(current["belt"], list) or len(current["belt"]) > (3 if kind == "conveyor" else 0):
                    raise ValueError("trace cargo capacity exceeded")
                belt_count = Counter()
                for item in current["belt"]:
                    if set(item) != {"item", "y", "x"} or item["item"] not in ITEMS:
                        raise ValueError("trace cargo fields differ")
                    number(item["y"], -TOLERANCE, 1 + TOLERANCE)
                    number(item["x"], -1 - TOLERANCE, 1 + TOLERANCE)
                    belt_count[item["item"]] += 1
                if kind == "conveyor" and cargo != belt_count:
                    raise ValueError("conveyor inventory and cargo disagree")
                number(current["minitem"], -TOLERANCE, 1 + TOLERANCE)
                integer(current["mid"], min(len(current["belt"]), 1))
                if type(current["lastInserted"]) is not int or current["lastInserted"] != 0:
                    raise ValueError("lastInserted outside extracted scope")
                integer(current["cursor"], 2**31 - 1)
                integer(current["rotation"], 3)
                integer(current["dumpTicks"], 4)
                number(current["routerTime"], 0, 200)
                number(current["progress"], 0, 7000)
                number(current["warmup"], -TOLERANCE, 1 + TOLERANCE)
                if current["lastInput"] is not None and current["lastInput"] not in seeds:
                    raise ValueError("trace source missing")
            if held != expected_cargo:
                raise ValueError("trace violates per-item cargo conservation")
            if not isinstance(frame["deliveries"], list):
                raise ValueError("invalid delivery list")
            for event in frame["deliveries"]:
                if set(event) != {"source", "target", "item", "source_rotation", "source_cursor"}:
                    raise ValueError("invalid delivery fields")
                if event["source"] not in seeds or event["target"] not in case["neighbors"][event["source"]]:
                    raise ValueError("delivery is not edge-adjacent")
                if event["item"] not in ITEMS:
                    raise ValueError("invalid delivery item")
                integer(event["source_rotation"], 3)
                integer(event["source_cursor"], 2**31 - 1)


def compare_traces(expected: list[Any], actual: list[Any]) -> list[dict[str, Any]]:
    """Call after validation; continuous fields alone permit bounded roundoff."""
    mismatches = []
    def visit(left: Any, right: Any, path: str, field: str = "") -> None:
        if isinstance(left, dict) and isinstance(right, dict) and set(left) == set(right):
            for key in left:
                visit(left[key], right[key], path + "." + key, key)
        elif isinstance(left, list) and isinstance(right, list) and len(left) == len(right):
            for i, (lv, rv) in enumerate(zip(left, right)):
                visit(lv, rv, path + "[" + str(i) + "]", field)
        else:
            differs = (abs(left - right) > TOLERANCE if field in FLOAT_FIELDS
                       and type(left) in (int, float) and type(right) in (int, float) else left != right)
            if differs:
                mismatches.append({"path": path, "java": left, "python": right})
    visit(expected, actual, "traces")
    return mismatches


def java_traces(cases: list[dict[str, Any]], toolchain: dict[str, Any]) -> list[dict[str, Any]]:
    with tempfile.TemporaryDirectory(prefix=".integrated-reference-", dir=ROOT) as directory:
        result = subprocess.run([toolchain["javac"]["path"], "-encoding", "UTF-8", "-d", directory,
                                 str(JAVA_SOURCE)], text=True, capture_output=True, timeout=30, check=False)
        if result.returncode:
            raise RuntimeError("Java compilation failed: " + result.stderr)
        result = subprocess.run([toolchain["java"]["path"], "-cp", directory, "IntegratedTransportReference"],
                                input=protocol_input(cases), text=True, capture_output=True, timeout=30, check=False)
        if result.returncode:
            raise RuntimeError("Java execution failed: " + result.stderr)
        return [json.loads(line) for line in result.stdout.splitlines() if line.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="write a new report; refuses to overwrite")
    args = parser.parse_args(argv)
    if args.output is not None and args.output.exists():
        parser.error("output already exists; choose a new report path")
    report: dict[str, Any] = {
        "status": "error", "comparison": "not_run", "scope": "source_extracted_integrated_methods_not_original_engine",
        "created_at": datetime.now(timezone.utc).isoformat(), "python": sys.version,
        "platform": platform.platform(), "upstream_commit": UPSTREAM_COMMIT,
        "toolchain": {name: diagnose_tool(name) for name in ("javac", "java")},
        "case_count": 0, "update_count": 0, "conditions": CONDITIONS,
    }
    exit_code = 2
    try:
        data = load_fixtures()
        cases = data["cases"]
        report.update({"case_count": len(cases), "update_count": sum(len(case["updates"]) for case in cases),
                       "sha256": {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                                  for path in (FIXTURES, JAVA_SOURCE, PYTHON_SOURCE, Path(__file__))}})
        actual = python_traces(cases)
        validate_traces(cases, actual)
        report["python_trace_sha256"] = hashlib.sha256(json.dumps(actual, sort_keys=True).encode()).hexdigest()
        if not all(tool["available"] for tool in report["toolchain"].values()):
            report["error"] = "A working JDK is required; comparison was not run."
        else:
            expected = java_traces(cases, report["toolchain"])
            validate_traces(cases, expected)
            mismatches = compare_traces(expected, actual)
            report.update({"comparison": "executed", "status": "mismatch" if mismatches else "passed",
                           "mismatch_count": len(mismatches), "mismatches": mismatches,
                           "delivery_count": sum(len(frame["deliveries"]) for trace in actual for frame in trace["frames"]),
                           "cases": [{"name": case["name"], "updates": len(case["updates"])} for case in cases]})
            exit_code = 1 if mismatches else 0
    except (OSError, ValueError, TypeError, KeyError, RuntimeError, subprocess.TimeoutExpired) as error:
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
