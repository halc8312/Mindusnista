#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Bounded independent check of M1-04's rejected-suffix aggregation.

Usage: python review-aggregation.py /absolute/path/to/Mindusnista
Uses the actual World in both paths. The reference path disables only the
suffix optimization and still applies every real offload side effect.
This checks optimization equivalence, not original-engine compatibility.
"""
import copy
import hashlib
import json
from pathlib import Path
import random
import sys

root = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(root / "tests"))
from test_drill_offload import drill_world
import mindustry_pythonista as m

rng = random.Random(1404)
naive_calls = 0
for case in range(48):
    world, drill = drill_world("lead" if case % 2 else "copper")
    for pos in ((12, 10), (10, 12), (9, 10), (10, 9)):
        kind = rng.choice(("router", "duo", "conveyor", "copper-wall"))
        target = world.place(kind, *pos, rotation=rng.randrange(4), free=True)
        if kind == "router" and rng.randrange(2):
            target.inventory = {"copper": 1}
        if kind == "duo":
            target.ammo = rng.choice((0, 28, 30))
    existing = rng.randrange(11)
    drill.inventory = {"copper": existing} if existing else {}
    drill.cursor = rng.choice((0, 1, 3, 17, 2**53))
    drill.progress = rng.randrange(40) * 650 + rng.randrange(650)
    drill.dump_ticks = rng.choice((0, 4))
    reference = m.World.from_dict(copy.deepcopy(world.to_dict()))
    raw_offload = reference.offload

    def every_offer(source, item):
        global naive_calls
        naive_calls += 1
        raw_offload(source, item)
        # The real call already applied transfer/fallback. Returning True only
        # prevents the caller from taking the rejected-suffix shortcut.
        return True

    reference.offload = every_offer
    world._tick_drill(drill)
    reference._tick_drill(reference.buildings[drill.id])
    if world.digest() != reference.digest():
        raise AssertionError("case %d: optimized/every-offer state differs" % case)

print(json.dumps({
    "status": "passed", "seed": 1404, "case_count": 48,
    "unaggregated_offload_calls": naive_calls,
    "comparison": "Full World.digest, optimized suffix versus every real offload",
    "python": sys.version, "executable": sys.executable,
    "runtime_sha256": hashlib.sha256((root / "mindustry_pythonista.py").read_bytes()).hexdigest(),
    "original_engine_run": False, "device_run": False,
}, indent=2))
