# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Mindustry-derived portions: Copyright (c) Anuken and contributors.
# Python adaptation and original integration: 2026-09-09.
# Modified work: Pythonista development port, NOT an official Mindustry release.
# License: GNU GPL version 3. This program comes WITHOUT ANY WARRANTY.
# See LICENSE and NOTICE.md in the accompanying source package.
"""Mindustry -> Pythonista: development port 0.1.2 (rotation controls).

Open this file in Pythonista 3 and press Run. No pip packages, JVM,
web view, original assets, or network connection are required at runtime.

Linux/macOS/Windows (simulation only):
    python mindustry_pythonista.py --self-test
    python mindustry_pythonista.py --benchmark

SOURCE-BASED PORTS: conveyor movement/acceptance rules, dry mechanical
mining formula, selected content constants. INTEGRATION SCAFFOLD:
world scheduling, round-robin adjacency, combat/AI/waves, construction,
JSON saves, procedural artwork, and the complete Pythonista interface.
No .msav/.msch, multiplayer, campaign, Java/JS mod compatibility yet.
See PORT_STATUS.md for exact deviations and the next porting targets.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import heapq
import json
import math
import os
import sys
import tempfile
import time
import traceback
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Capture this while the script is executing, not later in a scene callback.
# This also keeps save/config paths stable if the working directory changes.
_SCRIPT_DIRECTORY = Path(os.path.abspath(
    globals().get("__file__") or "mindustry_pythonista.py")).parent

VERSION = "0.1.2-dev"
UPSTREAM = "v159.7"
SAVE_FORMAT = "mindustry-pythonista-dev"
SAVE_VERSION = 1
TPS = 60
TILE = 32
TOUCH_SLOP = 7  # Screen points, independent of map zoom.
BUILD_HOLD_SECONDS = .35
DIRECTIONS = ((1, 0), (0, 1), (-1, 0), (0, -1))
ARROWS = ("→", "↑", "←", "↓")
ITEMS = ("copper", "lead")
ITEM_LABELS = {"copper": "銅", "lead": "鉛"}
ITEM_COLORS = {"copper": "#d99d73", "lead": "#8c7fa9"}
ITEM_HARDNESS = {"copper": 1, "lead": 1}
ITEM_SPACE = 0.4             # Conveyor.java, v159.7, line 24
BELT_CAPACITY = 3           # Conveyor.java, v159.7, line 25

# Content constants refer to Blocks.java at tag v159.7. Custom/scaffold
# choices are recorded in PORT_STATUS.md rather than called full parity.
DEFAULT_CONTENT = {
    "core-shard": {"label": "コア", "size": 3, "health": 1100,
                   "capacity": 4000, "cost": {"copper": 1000, "lead": 800}},
    "mechanical-drill": {"label": "ドリル", "size": 2, "health": 160,
                         "capacity": 10, "cost": {"copper": 12},
                         "drill_time": 600.0, "hardness_multiplier": 50.0,
                         "warmup_speed": 0.015, "tier": 2},
    "conveyor": {"label": "ベルト", "size": 1, "health": 45,
                 "capacity": 3, "cost": {"copper": 1}, "speed": 0.046},
    "router": {"label": "分配器", "size": 1, "health": 40,
               "capacity": 1, "cost": {"copper": 3}, "speed": 8.0},
    "duo": {"label": "デュオ", "size": 1, "health": 250,
            "capacity": 30, "cost": {"copper": 35},
            "reload": 20.0, "range": 20.0, "damage": 9.0,
            "bullet_speed": 2.5 / 8.0, "bullet_life": 66,
            "ammo_multiplier": 2, "rotate_speed": 10.0},
    "copper-wall": {"label": "銅の壁", "size": 1, "health": 320,
                    "capacity": 0, "cost": {"copper": 6}},
}
BUILD_TOOLS = ("mechanical-drill", "conveyor", "router", "duo", "copper-wall")
SOLID_KINDS = {"core-shard", "mechanical-drill", "duo", "copper-wall"}
MAX_SAVE_BYTES = 8 * 1024 * 1024


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def approach(value: float, target: float, amount: float) -> float:
    return value + clamp(target - value, -amount, amount)


def finite_number(value: Any, name: str, lo: float, hi: float) -> float:
    if type(value) not in (float, int) or not math.isfinite(value):
        raise ValueError("%s must be a finite number" % name)
    if not lo <= value <= hi:
        raise ValueError("%s must be between %s and %s" % (name, lo, hi))
    return value


def integer(value: Any, name: str, lo: int, hi: int) -> int:
    if type(value) is not int or not lo <= value <= hi:
        raise ValueError("%s must be an integer between %d and %d" % (name, lo, hi))
    return value


def validate_content(content: Dict[str, Any]) -> Dict[str, Any]:
    """Reject structural changes; numeric tuning is deliberately narrow."""
    if not isinstance(content, dict) or set(content) != set(DEFAULT_CONTENT):
        raise ValueError("Content must contain exactly the six supported block kinds")
    result = copy.deepcopy(content)
    for kind, default in DEFAULT_CONTENT.items():
        spec = result[kind]
        if not isinstance(spec, dict) or set(spec) != set(default):
            raise ValueError("Invalid content keys for " + kind)
        if spec["size"] != default["size"] or spec["capacity"] != default["capacity"]:
            raise ValueError("Changing size/capacity requires a Python code change")
        if not isinstance(spec["label"], str) or len(spec["label"]) > 16:
            raise ValueError("Block labels must be short strings")
        if not isinstance(spec["cost"], dict) or not set(spec["cost"]).issubset(ITEMS):
            raise ValueError("Unknown build-cost item")
        for item, value in spec["cost"].items():
            integer(value, kind + ".cost." + item, 0, 100000)
        for key, value in spec.items():
            if key in ("label", "cost"):
                continue
            finite_number(value, kind + "." + key, 0, 1000000)
        for key in ("health", "drill_time", "reload", "speed", "bullet_speed", "range"):
            if key in spec and spec[key] <= 0:
                raise ValueError(kind + "." + key + " must be positive")
        if "speed" in spec and kind == "conveyor" and spec["speed"] > 0.25:
            raise ValueError("This integration supports belt speed <= 0.25 per tick")
        if kind == "duo":
            integer(spec["ammo_multiplier"], "ammo_multiplier", 1, 30)
            integer(spec["bullet_life"], "bullet_life", 1, 3600)
            if spec["range"] > 128:
                raise ValueError("Duo range must be <= 128 tiles")
    return result


def load_content(path: Path) -> Dict[str, Any]:
    result = copy.deepcopy(DEFAULT_CONTENT)
    if path.exists():
        patch = read_json(path)
        if not isinstance(patch, dict):
            raise ValueError("Content overrides must be a JSON object")
        for kind, fields in patch.items():
            if kind not in result or not isinstance(fields, dict):
                raise ValueError("Unknown content block: " + str(kind))
            for key, value in fields.items():
                if key not in result[kind]:
                    raise ValueError("Unknown content field: " + str(key))
                result[kind][key] = value
    return validate_content(result)


def read_json(path: Path) -> Any:
    if path.stat().st_size > MAX_SAVE_BYTES:
        raise ValueError("JSON file is too large (limit: 8 MiB)")
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle, parse_constant=lambda x: (_ for _ in ()).throw(
            ValueError("Non-finite JSON constant: " + x)))


def atomic_json(path: Path, data: Any) -> None:
    """Write alongside the destination, then atomically replace it."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def conveyor_accepts(minimum: float, count: int, incoming_direction: int,
                     rotation: int, source_rotates: bool = False,
                     source_is_front: bool = False) -> bool:
    """Port of ConveyorBuild.acceptItem's direction/spacing condition.

    incoming_direction points FROM the source edge TO this conveyor;
    rotation 0=east, 1=north, 2=west, 3=south (as in Mindustry).
    Team/edge adjacency validation belongs to World.accepts().
    """
    if count >= BELT_CAPACITY:
        return False
    direction = abs(incoming_direction - rotation)
    return (((direction == 0 and minimum >= ITEM_SPACE) or
             (direction % 2 == 1 and minimum > 0.7)) and
            not (source_rotates and source_is_front))


def advance_conveyor_positions(ys: List[float], xs: List[float], speed: float,
                               next_minimum: float = 1.0,
                               aligned: bool = False) -> Tuple[List[float], List[float]]:
    """ConveyorBuild.updateTile movement kernel, for delta=efficiency=1.

    Source: Anuken/Mindustry v159.7 Conveyor.java lines 239-249.
    No transfers/draw/clog/sleep logic here. Uses Python double precision;
    the upstream Java uses float. Isolated Java comparison is in reference/.
    """
    if len(ys) != len(xs):
        raise ValueError("Conveyor position arrays must have equal lengths")
    yy, xx = list(ys), list(xs)
    next_max = 1.0 - max(ITEM_SPACE - next_minimum, 0.0) if aligned else 1.0
    for i in range(len(yy) - 1, -1, -1):
        next_pos = (100.0 if i == len(yy) - 1 else yy[i + 1]) - ITEM_SPACE
        max_move = clamp(next_pos - yy[i], 0.0, speed)
        yy[i] = min(yy[i] + max_move, next_max)
        xx[i] = approach(xx[i], 0.0, speed * 2.0)
    return yy, xx


@dataclass
class BeltItem:
    item: str
    y: float = 0.0
    x: float = 0.0


@dataclass
class Building:
    id: int
    kind: str
    x: int
    y: int
    rotation: int = 0
    hp: float = 1.0
    inventory: Dict[str, int] = field(default_factory=dict)
    belt: List[BeltItem] = field(default_factory=list)
    progress: float = 0.0
    warmup: float = 0.0
    dump_ticks: int = 0
    cursor: int = 0
    router_time: float = 0.0
    last_input: int = 0
    reload: float = 0.0
    ammo: int = 0
    angle: float = 0.0
    shots: int = 0
    # Conveyor.java caches: refreshed by updateTile, not by handleItem.
    conveyor_minitem: float = 1.0
    conveyor_mid: int = 0


@dataclass
class Enemy:
    id: int
    x: float
    y: float
    hp: float = 60.0
    max_hp: float = 60.0
    speed: float = 0.035
    damage: float = 5.0
    cooldown: int = 0
    goal_x: int = -1
    goal_y: int = -1
    angle: float = 0.0


@dataclass
class Bullet:
    id: int
    x: float
    y: float
    vx: float
    vy: float
    damage: float
    life: int


def segment_circle_hit(ax: float, ay: float, bx: float, by: float,
                       cx: float, cy: float, radius: float) -> Optional[float]:
    """First contact parameter in [0,1], including a segment starting inside."""
    dx, dy, ox, oy = bx - ax, by - ay, ax - cx, ay - cy
    c = ox * ox + oy * oy - radius * radius
    if c <= 0:
        return 0.0
    a = dx * dx + dy * dy
    if a < 1e-18:
        return None
    b = 2 * (ox * dx + oy * dy)
    disc = b * b - 4 * a * c
    if disc < 0:
        return None
    t = (-b - math.sqrt(disc)) / (2 * a)
    return t if 0 <= t <= 1 else None


class World:
    """Pure-Python simulation. No rendering, iOS, timing or file dependencies.

    Coordinates use tile units with a building's lower-left corner as x/y.
    Tick ordering is stable insertion order, NOT upstream entity scheduling.
    """
    def __init__(self, width: int = 48, height: int = 32,
                 content: Optional[Dict[str, Any]] = None):
        self.width = integer(width, "width", 8, 128)
        self.height = integer(height, "height", 8, 128)
        self.content = validate_content(content or DEFAULT_CONTENT)
        self.terrain = [0] * (width * height)   # 0=ground, 1=rock, 2=water
        self.ore = [""] * (width * height)
        self.grid = [0] * (width * height)
        self.buildings: Dict[int, Building] = {}
        self.enemies: Dict[int, Enemy] = {}
        self.bullets: Dict[int, Bullet] = {}
        self.stock = {"copper": 500, "lead": 150}
        self.next_id = 1
        self.tick_count = 0
        self.wave = 0
        self.wave_timer = 90 * TPS
        self.spawn_remaining = 0
        self.spawn_delay = 0
        self.sandbox = False
        self.game_over = False
        self.rng_state = 90210
        self.stats = {"mined": 0, "delivered": 0, "shots": 0, "kills": 0}
        self.revision = 0
        self._neighbors: Dict[int, List[int]] = {}
        self._path_dirty = True
        self._distance = [math.inf] * (width * height)
        self.last_message = ""

    def uid(self) -> int:
        result = self.next_id
        self.next_id += 1
        return result

    def random(self) -> float:
        # Independent scaffold RNG; state is portable, no pickle or eval.
        self.rng_state = (1664525 * self.rng_state + 1013904223) & 0xFFFFFFFF
        return self.rng_state / 4294967296.0

    def inside(self, x: int, y: int) -> bool:
        return 0 <= x < self.width and 0 <= y < self.height

    def index(self, x: int, y: int) -> int:
        return y * self.width + x

    def at(self, x: int, y: int) -> Optional[Building]:
        return self.buildings.get(self.grid[self.index(x, y)]) if self.inside(x, y) else None

    def size_of(self, b: Building) -> int:
        return self.content[b.kind]["size"]

    def center(self, b: Building) -> Tuple[float, float]:
        size = self.size_of(b)
        return b.x + size / 2.0, b.y + size / 2.0

    def tiles(self, b: Building):
        size = self.size_of(b)
        for y in range(b.y, b.y + size):
            for x in range(b.x, b.x + size):
                yield x, y

    def cores(self) -> List[Building]:
        return [b for b in self.buildings.values() if b.kind == "core-shard"]

    def invalidated(self) -> None:
        self.revision += 1
        self._neighbors.clear()
        self._path_dirty = True
        for e in self.enemies.values():
            e.goal_x = e.goal_y = -1

    def neighbors(self, b: Building) -> List[Building]:
        if b.id not in self._neighbors:
            size, found = self.size_of(b), []
            points = ([(b.x + size, b.y + i) for i in range(size)] +
                      [(b.x + i, b.y + size) for i in range(size)] +
                      [(b.x - 1, b.y + i) for i in range(size)] +
                      [(b.x + i, b.y - 1) for i in range(size)])
            for x, y in points:
                other = self.at(x, y)
                if other is not None and other.id != b.id and other.id not in found:
                    found.append(other.id)
            self._neighbors[b.id] = found
        return [self.buildings[i] for i in self._neighbors[b.id] if i in self.buildings]

    def mine_info(self, b: Building) -> Tuple[Optional[str], int]:
        counts = Counter(self.ore[self.index(x, y)] for x, y in self.tiles(b)
                         if self.ore[self.index(x, y)] in ITEMS)
        counts = {item: n for item, n in counts.items()
                  if ITEM_HARDNESS[item] <= self.content[b.kind].get("tier", 0)}
        if not counts:
            return None, 0
        # Both supported ores are normal priority; ties use Items.load ID order.
        item = max(counts, key=lambda k: (counts[k], ITEMS.index(k)))
        return item, counts[item]

    def can_place(self, kind: str, x: int, y: int, free: bool = False) -> Tuple[bool, str]:
        if kind not in self.content:
            return False, "未対応のブロック"
        if self.game_over and not free:
            return False, "コア破壊：メニューから新規開始"
        if kind == "core-shard" and self.cores():
            return False, "この開発版はコア1個まで"
        spec = self.content[kind]
        for yy in range(y, y + spec["size"]):
            for xx in range(x, x + spec["size"]):
                if not self.inside(xx, yy):
                    return False, "マップの外です"
                idx = self.index(xx, yy)
                if self.terrain[idx] != 0:
                    return False, "岩・水には建築できません"
                if self.grid[idx]:
                    return False, "別の建物があります"
        if kind == "mechanical-drill":
            probe = Building(0, kind, x, y)
            if self.mine_info(probe)[0] is None:
                return False, "ドリルは銅色・紫色の鉱床へ"
        if not (free or self.sandbox):
            for item, count in spec["cost"].items():
                if self.stock.get(item, 0) < count:
                    return False, ITEM_LABELS[item] + "が足りません"
        return True, ""

    def place(self, kind: str, x: int, y: int, rotation: int = 0,
              free: bool = False) -> Optional[Building]:
        ok, why = self.can_place(kind, x, y, free)
        if not ok:
            self.last_message = why
            return None
        spec = self.content[kind]
        if not (free or self.sandbox):
            for item, count in spec["cost"].items():
                self.stock[item] -= count
        b = Building(self.uid(), kind, x, y, rotation % 4, float(spec["health"]))
        self.buildings[b.id] = b
        for xx, yy in self.tiles(b):
            self.grid[self.index(xx, yy)] = b.id
        self.invalidated()
        self.last_message = ""
        return b

    def remove(self, b: Building, refund: bool = True) -> bool:
        if b.id not in self.buildings or (b.kind == "core-shard" and refund):
            return False
        if refund and not self.sandbox:
            # Scaffold construction is instantaneous; dismantling gives 50%.
            for item, count in self.content[b.kind]["cost"].items():
                self.stock[item] = min(4000, self.stock[item] + count // 2)
        for x, y in self.tiles(b):
            self.grid[self.index(x, y)] = 0
        del self.buildings[b.id]
        self.invalidated()
        if b.kind == "core-shard":
            self.game_over = True
        return True

    def incoming_direction(self, source: Building, target: Building) -> Optional[int]:
        ss, ts = self.size_of(source), self.size_of(target)
        overlap_y = max(source.y, target.y) < min(source.y + ss, target.y + ts)
        overlap_x = max(source.x, target.x) < min(source.x + ss, target.x + ts)
        if source.x + ss == target.x and overlap_y:
            return 0
        if source.y + ss == target.y and overlap_x:
            return 1
        if target.x + ts == source.x and overlap_y:
            return 2
        if target.y + ts == source.y and overlap_x:
            return 3
        return None

    def front(self, b: Building) -> Optional[Building]:
        dx, dy = DIRECTIONS[b.rotation]
        return self.at(b.x + dx, b.y + dy)

    def accepts(self, target: Building, source: Building, item: str) -> bool:
        if item not in ITEMS or target.id == source.id:
            return False
        incoming = self.incoming_direction(source, target)
        if incoming is None:
            return False
        if target.kind == "core-shard":
            return self.stock[item] < self.content[target.kind]["capacity"]
        if target.kind == "conveyor":
            return conveyor_accepts(target.conveyor_minitem, len(target.belt), incoming, target.rotation,
                                    source.kind == "conveyor", self.front(target) is source)
        if target.kind == "router":
            return not target.inventory
        if target.kind == "duo":
            spec = self.content["duo"]
            return item == "copper" and target.ammo + spec["ammo_multiplier"] <= spec["capacity"]
        return False

    def receive(self, target: Building, source: Building, item: str) -> bool:
        if not self.accepts(target, source, item):
            return False
        return self._handle_item(target, source, item)

    def _handle_item(self, target: Building, source: Building, item: str) -> bool:
        """Handle an already accepted single item (Building.handleItem boundary)."""
        if target.kind == "core-shard":
            self.stock[item] += 1
            self.stats["delivered"] += 1
        elif target.kind == "conveyor":
            incoming = self.incoming_direction(source, target)
            ang = incoming - target.rotation
            xx = 1.0 if ang in (-1, 3) else -1.0 if ang in (1, -3) else 0.0
            pos = 0.0 if incoming == target.rotation else 0.5
            index = 0 if incoming == target.rotation else target.conveyor_mid
            target.belt.insert(index, BeltItem(item, pos, xx))
        elif target.kind == "router":
            target.inventory[item] = 1
            target.router_time = 0.0
            target.last_input = source.id
        elif target.kind == "duo":
            target.ammo += self.content["duo"]["ammo_multiplier"]
        return True

    def offload(self, b: Building, item: str) -> bool:
        """Offer one produced item, keeping it locally if every neighbor rejects.

        BuildingComp.offload advances cdump before each acceptance check.
        The bool is a port-only observation of external delivery; both outcomes
        preserve the item. Campaign produced()/unlock accounting is not ported.
        """
        neighbors = self.neighbors(b)
        start = b.cursor
        for offset in range(len(neighbors)):
            b.cursor = (b.cursor + 1) % len(neighbors)
            target = neighbors[(start + offset) % len(neighbors)]
            if self.receive(target, b, item):
                return True
        b.inventory[item] = b.inventory.get(item, 0) + 1
        return False

    def dump(self, b: Building, item: Optional[str] = None) -> bool:
        """Dump one stored item, following BuildingComp.dump at v159.7.

        Current inventory-bearing blocks use inherited canDump=true. The
        proximity list and scheduler remain the port's existing scaffolding.
        """
        if not b.inventory or (item is not None and not b.inventory.get(item, 0)):
            return False
        neighbors = self.neighbors(b)
        if not neighbors:
            return False
        start = b.cursor
        candidates = ITEMS if item is None else (item,)
        for offset in range(len(neighbors)):
            target = neighbors[(start + offset) % len(neighbors)]
            for candidate in candidates:
                if b.inventory.get(candidate, 0) and self.receive(target, b, candidate):
                    b.inventory[candidate] -= 1
                    if b.inventory[candidate] == 0:
                        del b.inventory[candidate]
                    b.cursor = (b.cursor + 1) % len(neighbors)
                    return True
            b.cursor = (b.cursor + 1) % len(neighbors)
        return False

    def _tick_drill(self, b: Building) -> None:
        item, count = self.mine_info(b)
        b.dump_ticks += 1
        if b.dump_ticks >= 5:
            b.dump_ticks = 0
            self.dump(b, item if item is not None and b.inventory.get(item, 0) else None)
        if item is None:
            return
        spec = self.content[b.kind]
        if sum(b.inventory.values()) >= spec["capacity"]:
            b.warmup = approach(b.warmup, 0.0, spec["warmup_speed"])
            return
        # Port of the dry, fully powered branch of DrillBuild.updateTile.
        b.warmup = approach(b.warmup, 1.0, spec["warmup_speed"])
        b.progress += count * b.warmup
        delay = spec["drill_time"] + spec["hardness_multiplier"] * ITEM_HARDNESS[item]
        if b.progress >= delay:
            amount = int(b.progress / delay)
            for index in range(amount):
                self.stats["mined"] += 1
                if not self.offload(b, item):
                    # Existing receive() rejection is pure, topology is fixed
                    # during this synchronous batch, and no tick intervenes.
                    # All later offers of this item must also fail. Preserve
                    # their exact cargo/count without replaying a huge backlog
                    # of identical failed scans. Side-effectful MOD receivers
                    # would need a different rule before they are supported.
                    remaining = amount - index - 1
                    b.inventory[item] += remaining
                    self.stats["mined"] += remaining
                    break
            # Upstream checks capacity before the batch, not after each item;
            # blocked multi-completions can legitimately exceed itemCapacity.
            b.progress %= delay

    def _tick_conveyor(self, b: Building) -> None:
        b.conveyor_minitem = 1.0
        b.conveyor_mid = 0
        if not b.belt:
            return
        target = self.front(b)
        aligned = bool(target and target.kind == "conveyor" and target.rotation == b.rotation)
        next_min = target.conveyor_minitem if aligned else 1.0
        next_max = 1.0 - max(ITEM_SPACE - next_min, 0.0) if aligned else 1.0
        moved = self.content[b.kind]["speed"]
        # Conveyor.java v159.7: move, pass and remove each item before updating
        # its follower. A successful pass changes which item is now the head.
        # Insertion keeps upstream array order, which need not be sorted after
        # several handleItem calls. Entity scheduling remains separate work.
        for index in range(len(b.belt) - 1, -1, -1):
            p = b.belt[index]
            next_pos = (100.0 if index == len(b.belt) - 1 else b.belt[index + 1].y) - ITEM_SPACE
            p.y = min(p.y + clamp(next_pos - p.y, 0.0, moved), next_max)
            if p.y > 0.5 and index > 0:
                b.conveyor_mid = index - 1
            p.x = approach(p.x, 0.0, moved * 2.0)
            if p.y >= 1.0 and target and self.receive(target, b, p.item):
                if aligned:
                    # lastInserted remains zero in the pinned ordinary path.
                    target.belt[0].x = p.x
                # Ordinary traffic passes the active tail, matching len=i.
                # Keep other cargo in manually fabricated unordered saves;
                # upstream's truncation of such arrays is outside this port.
                del b.belt[index]
            elif p.y < b.conveyor_minitem:
                b.conveyor_minitem = p.y

    def _router_target(self, b: Building, item: str, advance: bool) -> Optional[Building]:
        """RouterBuild.getTileTarget's uncontrolled, supported-block path.

        Router rotation is the round-robin pointer; cursor belongs to the
        inherited dump/offload path and remains saved independently. The
        overflow-gate input exception awaits that block's implementation.
        """
        neighbors = self.neighbors(b)
        start = b.rotation
        for offset in range(len(neighbors)):
            target = neighbors[(start + offset) % len(neighbors)]
            if advance:
                b.rotation = (b.rotation + 1) % len(neighbors)
            if self.accepts(target, b, item):
                return target
        return None

    def _tick_router(self, b: Building) -> None:
        if not b.inventory:
            return
        item = next(iter(b.inventory))
        b.router_time += 1.0 / self.content[b.kind]["speed"]
        target = self._router_target(b, item, False)
        if target is not None and (b.router_time >= 1.0 or target.kind != "router"):
            # Repeat the scan and advance rotation before handling, as upstream
            # does. Supported accepts() calls are pure, so the target is stable.
            self._router_target(b, item, True)
            self._handle_item(target, b, item)
            b.inventory[item] -= 1
            if b.inventory[item] == 0:
                del b.inventory[item]

    def _tick_turret(self, b: Building) -> None:
        spec = self.content[b.kind]
        b.reload = min(spec["reload"], b.reload + 1.0)
        if b.ammo <= 0 or not self.enemies:
            return
        x, y = self.center(b)
        targets = [e for e in self.enemies.values()
                   if e.hp > 0 and (e.x-x)**2 + (e.y-y)**2 <= spec["range"]**2]
        if not targets:
            return
        e = min(targets, key=lambda enemy: ((enemy.x-x)**2 + (enemy.y-y)**2, enemy.id))
        # Scaffold aiming: no upstream intercept prediction, recoil, or coolant.
        desired = math.atan2(e.y-y, e.x-x)
        difference = (desired - b.angle + math.pi) % (2*math.pi) - math.pi
        b.angle += clamp(difference, -math.radians(spec["rotate_speed"]),
                        math.radians(spec["rotate_speed"]))
        if b.reload >= spec["reload"] and abs(difference) <= math.radians(15):
            b.reload = 0.0
            b.ammo -= 1
            b.shots += 1
            self.stats["shots"] += 1
            # Original duo inaccuracy is two degrees; independent RNG here.
            angle = b.angle + math.radians((self.random()*2-1)*2)
            dx, dy = math.cos(angle), math.sin(angle)
            uid = self.uid()
            self.bullets[uid] = Bullet(uid, x + dx*.25, y + dy*.25,
                                      dx*spec["bullet_speed"], dy*spec["bullet_speed"],
                                      spec["damage"], spec["bullet_life"])

    def rebuild_path(self) -> None:
        # ORIGINAL SCAFFOLD, not a port of Mindustry's Pathfinder.
        # Weighted reverse Dijkstra: enemy units may break occupied cells.
        n = self.width * self.height
        self._distance = [math.inf] * n
        heap = []
        for b in self.cores():
            for x, y in self.tiles(b):
                idx = self.index(x, y)
                self._distance[idx] = 0.0
                heapq.heappush(heap, (0.0, idx))
        while heap:
            distance, idx = heapq.heappop(heap)
            if distance != self._distance[idx]:
                continue
            x, y = idx % self.width, idx // self.width
            block = self.at(x, y)
            cost = 1.0 + (6.0 if block and block.kind == "copper-wall" else
                          2.0 if block and block.kind in SOLID_KINDS else 0.0)
            for dx, dy in DIRECTIONS:
                nx, ny = x+dx, y+dy
                if not self.inside(nx, ny):
                    continue
                ni = self.index(nx, ny)
                if self.terrain[ni] != 0:
                    continue
                nd = distance + cost
                if nd < self._distance[ni]:
                    self._distance[ni] = nd
                    heapq.heappush(heap, (nd, ni))
        self._path_dirty = False

    def _tick_enemy(self, e: Enemy) -> None:
        e.cooldown = max(0, e.cooldown - 1)
        if e.goal_x < 0:
            tx, ty = int(e.x), int(e.y)
            choices = []
            for order, (dx, dy) in enumerate(DIRECTIONS):
                nx, ny = tx+dx, ty+dy
                if self.inside(nx, ny) and self.terrain[self.index(nx, ny)] == 0:
                    choices.append((self._distance[self.index(nx, ny)], order, nx, ny))
            if not choices:
                return
            distance, _, e.goal_x, e.goal_y = min(choices)
            if not math.isfinite(distance):
                e.goal_x = e.goal_y = -1
                return
        gx, gy = e.goal_x+.5, e.goal_y+.5
        dx, dy = gx-e.x, gy-e.y
        dist = math.hypot(dx, dy)
        blocker = self.at(e.goal_x, e.goal_y)
        solid = blocker is not None and blocker.kind in SOLID_KINDS
        if solid and dist <= .85:
            if e.cooldown == 0:
                blocker.hp -= e.damage
                e.cooldown = 25
                if blocker.hp <= 0:
                    self.remove(blocker, refund=False)
            return
        if dist > 1e-8:
            e.angle = math.atan2(dy, dx)
            move = min(e.speed, dist, max(0.0, dist-.8) if solid else dist)
            e.x += dx / dist * move
            e.y += dy / dist * move
        if not solid and dist <= e.speed + 1e-8:
            e.x, e.y = gx, gy
            e.goal_x = e.goal_y = -1

    def _tick_bullets(self) -> None:
        for bullet in list(self.bullets.values()):
            nx, ny = bullet.x+bullet.vx, bullet.y+bullet.vy
            nearest, hit = math.inf, None
            for enemy in self.enemies.values():
                if enemy.hp <= 0:
                    continue
                contact = segment_circle_hit(bullet.x, bullet.y, nx, ny,
                                             enemy.x, enemy.y, .38)
                if contact is not None and contact < nearest:
                    nearest, hit = contact, enemy
            if hit:
                hit.hp -= bullet.damage
                del self.bullets[bullet.id]
            else:
                bullet.x, bullet.y = nx, ny
                bullet.life -= 1
                if bullet.life <= 0 or not (0 <= nx < self.width and 0 <= ny < self.height):
                    del self.bullets[bullet.id]
        for uid in [e.id for e in self.enemies.values() if e.hp <= 0]:
            del self.enemies[uid]
            self.stats["kills"] += 1

    def start_wave(self) -> bool:
        if self.game_over or self.spawn_remaining or len(self.enemies) >= 160:
            return False
        self.wave += 1
        self.spawn_remaining = min(6 + self.wave*2, 100)
        self.spawn_delay = 0
        self.wave_timer = 75 * TPS
        return True

    def spawn_enemy(self, x: Optional[float] = None, y: Optional[float] = None) -> Enemy:
        if x is None:
            x, y = self.width-3.5, self.height/2 + (self.random()-.5)*6
            x, y = int(x)+.5, int(clamp(y, 2, self.height-3))+.5
            self.terrain[self.index(int(x), int(y))] = 0
        hp = 50.0 + self.wave * 8.0
        enemy = Enemy(self.uid(), float(x), float(y), hp, hp,
                      .029 + min(self.wave, 20)*.001, 5.0 + self.wave*.25)
        self.enemies[enemy.id] = enemy
        return enemy

    def step(self, ticks: int = 1) -> None:
        for _ in range(ticks):
            if self.game_over:
                return
            self.tick_count += 1
            for b in list(self.buildings.values()):
                if b.kind == "mechanical-drill":
                    self._tick_drill(b)
                elif b.kind == "conveyor":
                    self._tick_conveyor(b)
                elif b.kind == "router":
                    self._tick_router(b)
                elif b.kind == "duo":
                    self._tick_turret(b)
            if self.enemies and self._path_dirty:
                self.rebuild_path()
            for e in list(self.enemies.values()):
                if self._path_dirty:
                    self.rebuild_path()
                self._tick_enemy(e)
            self._tick_bullets()
            if not self.sandbox:
                self.wave_timer -= 1
                if self.wave_timer <= 0 and not self.spawn_remaining:
                    self.start_wave()
            if self.spawn_remaining:
                self.spawn_delay -= 1
                if self.spawn_delay <= 0 and len(self.enemies) < 200:
                    self.spawn_enemy()
                    self.spawn_remaining -= 1
                    self.spawn_delay = 24

    @classmethod
    def demo(cls, content: Optional[Dict[str, Any]] = None) -> World:
        w = cls(content=content)
        # Handcrafted integration map, NOT a Mindustry campaign/map conversion.
        for y in range(w.height):
            for x in range(w.width):
                i = w.index(x, y)
                if x in (0, w.width-1) or y in (0, w.height-1):
                    w.terrain[i] = 1
                elif (x-29)**2 + (y-7)**2 < 11:
                    w.terrain[i] = 2
                elif ((x*37 + y*73) % 127 == 0 and x > 24 and y > 24):
                    w.terrain[i] = 1
        for x0, y0, item in ((5, 9, "copper"), (15, 15, "copper"),
                             (7, 21, "lead"), (31, 23, "copper")):
            for y in range(y0, y0+4):
                for x in range(x0, x0+5):
                    w.ore[w.index(x, y)] = item
                    w.terrain[w.index(x, y)] = 0
        w.place("core-shard", 12, 9, free=True)
        w.place("mechanical-drill", 6, 10, free=True)
        for x in range(8, 12):
            w.place("conveyor", x, 10, 0, free=True)
        w.place("mechanical-drill", 16, 16, free=True)
        for x in range(18, 22):
            w.place("conveyor", x, 16, 0, free=True)
        w.place("router", 22, 16, free=True)
        for y in (15, 17):
            gun = w.place("duo", 22, y, free=True)
            gun.ammo = 20  # Explicit starter ammunition for the integration demo.
        for y in range(13, 20):
            w.place("copper-wall", 25, y, free=True)
        return w

    def to_dict(self) -> Dict[str, Any]:
        return {
            "format": SAVE_FORMAT, "schema": SAVE_VERSION,
            "port_version": VERSION, "upstream": UPSTREAM,
            "width": self.width, "height": self.height, "content": self.content,
            "terrain": self.terrain, "ore": self.ore,
            "buildings": [asdict(b) for b in self.buildings.values()],
            "enemies": [asdict(e) for e in self.enemies.values()],
            "bullets": [asdict(b) for b in self.bullets.values()],
            "stock": self.stock, "next_id": self.next_id, "tick_count": self.tick_count,
            "wave": self.wave, "wave_timer": self.wave_timer,
            "spawn_remaining": self.spawn_remaining, "spawn_delay": self.spawn_delay,
            "sandbox": self.sandbox, "game_over": self.game_over,
            "rng_state": self.rng_state, "stats": self.stats,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> World:
        """Validate a save without modifying a running world or executing code."""
        if not isinstance(data, dict) or data.get("format") != SAVE_FORMAT:
            raise ValueError("Not a Pythonista port save (original .msav is unsupported)")
        if data.get("schema") != SAVE_VERSION or data.get("upstream") != UPSTREAM:
            raise ValueError("Unsupported save schema/upstream version")
        w = cls(data["width"], data["height"], data["content"])
        count = w.width * w.height
        if not isinstance(data["terrain"], list) or len(data["terrain"]) != count:
            raise ValueError("Invalid terrain dimensions")
        w.terrain = [integer(x, "terrain", 0, 2) for x in data["terrain"]]
        if not isinstance(data["ore"], list) or len(data["ore"]) != count:
            raise ValueError("Invalid ore dimensions")
        if any(x not in ("",) + ITEMS for x in data["ore"]):
            raise ValueError("Unknown ore")
        w.ore = list(data["ore"])
        used_ids = set()

        def check_id(uid):
            integer(uid, "entity id", 1, 2**53)
            if uid in used_ids:
                raise ValueError("Duplicate entity ID")
            used_ids.add(uid)

        if not isinstance(data["buildings"], list) or len(data["buildings"]) > count:
            raise ValueError("Too many buildings")
        for raw in data["buildings"]:
            r = dict(raw)
            cache_keys = ("conveyor_minitem" in r, "conveyor_mid" in r)
            if cache_keys[0] != cache_keys[1]:
                raise ValueError("Incomplete conveyor cache")
            r["belt"] = [BeltItem(**p) for p in r["belt"]]
            b = Building(**r)
            check_id(b.id)
            if b.kind not in w.content:
                raise ValueError("Unknown building kind")
            integer(b.x, "building x", 0, w.width-1)
            integer(b.y, "building y", 0, w.height-1)
            integer(b.rotation, "rotation", 0, 3)
            finite_number(b.hp, "building hp", 0.00001, w.content[b.kind]["health"])
            for name in ("progress", "warmup", "router_time", "reload", "angle"):
                finite_number(getattr(b, name), name, -1e12 if name == "angle" else 0, 1e12)
            if b.warmup > 1.000001:
                raise ValueError("Invalid drill warmup")
            for name in ("dump_ticks", "cursor", "last_input", "ammo", "shots"):
                integer(getattr(b, name), name, 0, 2**53)
            if not isinstance(b.inventory, dict) or not set(b.inventory).issubset(ITEMS):
                raise ValueError("Unknown inventory item")
            for value in b.inventory.values():
                if b.kind == "mechanical-drill":
                    # A full production batch may overflow drill capacity.
                    # JSON uses Python integers; original ItemModule int32
                    # overflow and the .msav codec are separate porting work.
                    if type(value) is not int or value <= 0:
                        raise ValueError("Drill inventory must be a positive integer")
                else:
                    integer(value, "inventory", 1, 10)
            if b.kind != "mechanical-drill" and sum(b.inventory.values()) > w.content[b.kind]["capacity"]:
                raise ValueError("Inventory overflow")
            if b.kind not in ("router", "mechanical-drill") and b.inventory:
                raise ValueError("Inventory on an unsupported building")
            if len(b.belt) > BELT_CAPACITY or (b.kind != "conveyor" and b.belt):
                raise ValueError("Invalid conveyor contents")
            for p in b.belt:
                if p.item not in ITEMS:
                    raise ValueError("Unknown conveyor item")
                finite_number(p.y, "belt y", 0, 1)
                finite_number(p.x, "belt x", -1, 1)
            if not cache_keys[0]:
                # Legacy schema 1 did not record caches and always sorted
                # cargo. Derive a deterministic starting cache without ticking
                # or changing coordinates, inventory, time or RNG state.
                if [p.y for p in b.belt] != sorted(p.y for p in b.belt):
                    raise ValueError("Unsorted legacy conveyor contents")
                b.conveyor_minitem = min((p.y for p in b.belt), default=1.0)
                for index in range(len(b.belt) - 1, 0, -1):
                    if b.belt[index].y > 0.5:
                        b.conveyor_mid = index - 1
            finite_number(b.conveyor_minitem, "conveyor minitem", 0, 1)
            integer(b.conveyor_mid, "conveyor mid", 0, min(len(b.belt), BELT_CAPACITY - 2))
            if b.kind != "conveyor" and (b.conveyor_minitem != 1 or b.conveyor_mid != 0):
                raise ValueError("Conveyor cache on an unsupported building")
            if b.ammo > w.content["duo"]["capacity"] or (b.kind != "duo" and b.ammo):
                raise ValueError("Invalid turret ammunition")
            for x, y in w.tiles(b):
                if not w.inside(x, y) or w.terrain[w.index(x, y)] != 0 or w.at(x, y):
                    raise ValueError("Building is outside/overlapping/inside terrain")
                w.grid[w.index(x, y)] = b.id
            w.buildings[b.id] = b
        for key, factory, limit in (("enemies", Enemy, 256), ("bullets", Bullet, 4096)):
            if not isinstance(data[key], list) or len(data[key]) > limit:
                raise ValueError("Invalid " + key + " count")
            for raw in data[key]:
                obj = factory(**raw)
                check_id(obj.id)
                finite_number(obj.x, key+".x", 0, w.width)
                finite_number(obj.y, key+".y", 0, w.height)
                for name, value in asdict(obj).items():
                    finite_number(value, key+"."+name, -1e12, 2**53)
                finite_number(obj.damage, "damage", 0, 1000000)
                if key == "enemies":
                    finite_number(obj.hp, "enemy hp", .00001, obj.max_hp)
                    finite_number(obj.speed, "enemy speed", .00001, .5)
                    integer(obj.cooldown, "cooldown", 0, 100000)
                    integer(obj.goal_x, "goal_x", -1, w.width-1)
                    integer(obj.goal_y, "goal_y", -1, w.height-1)
                    if (obj.goal_x < 0) != (obj.goal_y < 0):
                        raise ValueError("Incomplete enemy destination")
                else:
                    integer(obj.life, "bullet life", 1, 3600)
                    finite_number(obj.vx, "bullet vx", -100, 100)
                    finite_number(obj.vy, "bullet vy", -100, 100)
                getattr(w, key)[obj.id] = obj
        if set(data["stock"]) != set(ITEMS):
            raise ValueError("Invalid core stock")
        w.stock = {item: integer(data["stock"][item], "stock", 0, 4000) for item in ITEMS}
        for name in ("next_id", "tick_count", "wave", "wave_timer", "spawn_remaining",
                     "spawn_delay", "rng_state"):
            setattr(w, name, integer(data[name], name, -10**9 if name in ("wave_timer", "spawn_delay") else 0, 2**53))
        if w.next_id <= max(used_ids, default=0) or w.spawn_remaining > 100:
            raise ValueError("Invalid ID sequence/spawn count")
        if w.rng_state > 0xFFFFFFFF:
            raise ValueError("Invalid random state")
        for name in ("sandbox", "game_over"):
            if type(data[name]) is not bool:
                raise ValueError(name + " must be bool")
            setattr(w, name, data[name])
        if set(data["stats"]) != set(w.stats):
            raise ValueError("Invalid statistics")
        w.stats = {k: integer(v, k, 0, 2**53) for k, v in data["stats"].items()}
        if len(w.cores()) != (0 if w.game_over else 1):
            raise ValueError("A live save must contain exactly one core")
        w._neighbors.clear()
        w._path_dirty = True
        w.revision += 1
        return w

    def save(self, path: Path) -> None:
        atomic_json(Path(path), self.to_dict())

    @classmethod
    def load(cls, path: Path) -> World:
        return cls.from_dict(read_json(Path(path)))

    def digest(self) -> str:
        raw = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def data_directory() -> Path:
    return _SCRIPT_DIRECTORY / "_mindustry_pythonista"


def private_data_directory() -> Path:
    """Persistent fallback inside Pythonista's own Documents directory."""
    return Path.home() / "Documents" / "_mindustry_pythonista"


def prepare_data_directory() -> Tuple[Path, str]:
    """Prefer the existing save folder; never delete or move existing saves.

    Some external File Provider folders cannot create sibling files. Check
    write access before gameplay; if needed, explicitly announce the fallback.
    A temporary directory is NOT used for save data.
    """
    errors = []
    tried = set()
    for location in (data_directory, private_data_directory):
        candidate = None
        try:
            candidate = location()
            if candidate in tried:
                continue
            tried.add(candidate)
            candidate.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                    mode="w+b", prefix=".startup-check-", dir=str(candidate)) as probe:
                probe.write(b"ok")
                probe.flush()
            warning = ""
            if errors:
                warning = "保存先をPythonista内Documentsへ変更。元の保存は移動していません。"
                print(warning)
                print("Previous storage errors:\n" + "\n".join(errors))
                print("Active save directory:", candidate)
            return candidate, warning
        except (OSError, RuntimeError) as error:
            errors.append("%s: %s: %s" % (
                candidate or getattr(location, "__name__", "storage location"),
                type(error).__name__, error))
    raise OSError("保存フォルダーを作成・使用できません。\n" + "\n".join(errors))


def self_test() -> None:
    """Small embedded test; the source archive contains a much larger suite."""
    yy, xx = advance_conveyor_positions([0.0], [1.0], .046)
    assert abs(yy[0] - .046) < 1e-12 and abs(xx[0] - .908) < 1e-12
    assert conveyor_accepts(.4, 1, 0, 0)
    assert not conveyor_accepts(.7, 1, 1, 0)
    w = World.demo()
    w.sandbox = True
    before = w.stock["copper"]
    w.step(1800)
    assert w.stock["copper"] > before, "Starter mining line did not deliver copper"
    restored = World.from_dict(w.to_dict())
    assert w.digest() == restored.digest(), "Save round trip differs"
    w.step(300)
    restored.step(300)
    assert w.digest() == restored.digest(), "Resume is not deterministic"
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "test.json"
        w.save(path)
        assert World.load(path).digest() == w.digest()
    print("SELF TEST PASSED: transport, mining, save/load, deterministic resume")


def benchmark(ticks: int = 3600) -> Dict[str, Any]:
    w = World.demo()
    w.start_wave()
    start = time.perf_counter()
    w.step(ticks)
    elapsed = time.perf_counter() - start
    return {"python": sys.version.split()[0], "requested_ticks": ticks,
            "completed_ticks": w.tick_count, "wall_seconds": round(elapsed, 6),
            "simulation_ticks_per_second": round(w.tick_count/max(elapsed, 1e-9), 1),
            "buildings": len(w.buildings), "enemies": len(w.enemies),
            "stats": w.stats, "core_hp": [b.hp for b in w.cores()],
            "note": "Headless container result; NOT an iPhone FPS measurement."}

# ---------------------------------------------------------------------------
# Pythonista presentation adapter. Imported lazily: desktop tests need no iOS.
# ---------------------------------------------------------------------------
def make_scene_class(sc, ui):
    """Dependency injection is for smoke tests; runtime uses real scene/ui."""

    def clear(node):
        for child in list(node.children):
            child.remove_from_parent()

    def line(points, color, width=2):
        path = ui.Path()
        path.move_to(*points[0])
        for point in points[1:]:
            path.line_to(*point)
        path.line_width = width
        ui.set_color(color)
        path.stroke()

    def rect(x, y, w, h, color):
        ui.set_color(color)
        ui.Path.rect(x, y, w, h).fill()

    def oval(x, y, w, h, color):
        ui.set_color(color)
        ui.Path.oval(x, y, w, h).fill()

    def make_texture(kind):
        # Procedural ORIGINAL artwork. No original Mindustry graphics included.
        with ui.ImageContext(64, 64) as context:
            if kind == "range":
                path = ui.Path.oval(2, 2, 60, 60)
                path.line_width = .7
                ui.set_color((.4, .85, .9, .65))
                path.stroke()
            elif kind == "selection":
                path = ui.Path.rect(1, 1, 62, 62)
                path.line_width = 2
                ui.set_color("white")
                path.stroke()
            elif kind == "item":
                rect(8, 8, 48, 48, "white")
                rect(14, 12, 30, 7, (1, 1, 1, .6))
            elif kind == "enemy":
                path = ui.Path()
                for i, p in enumerate(((60, 32), (18, 10), (4, 32), (18, 54))):
                    (path.move_to if i == 0 else path.line_to)(*p)
                path.close()
                ui.set_color("#df626b")
                path.fill()
                line(((24, 22), (43, 32), (24, 42)), "#ffd4c1", 5)
                rect(8, 14, 7, 36, "#822e47")
            elif kind == "gun-head":
                oval(13, 13, 38, 38, "#748fa4")
                rect(26, 19, 34, 8, "#e4bf7a")
                rect(26, 37, 34, 8, "#e4bf7a")
                oval(24, 24, 16, 16, "#344958")
            elif kind == "drill-head":
                oval(6, 6, 52, 52, "#3c5460")
                line(((10, 32), (54, 32)), "#dbb976", 8)
                line(((32, 10), (32, 54)), "#dbb976", 8)
                oval(24, 24, 16, 16, "#26353e")
            else:
                rect(2, 3, 60, 59, "#10191f")
                rect(4, 4, 56, 54, "#34434e")
                line(((5, 57), (5, 5), (58, 5)), "#637886", 3)
                if kind == "conveyor":
                    rect(6, 12, 52, 40, "#1f2b32")
                    for x in (13, 29, 45):
                        line(((x-5, 18), (x+5, 32), (x-5, 46)), "#b3a073", 4)
                    rect(5, 7, 54, 5, "#7e8991")
                    rect(5, 52, 54, 5, "#7e8991")
                elif kind == "router":
                    line(((12, 32), (52, 32)), "#d1b975", 9)
                    line(((32, 12), (32, 52)), "#d1b975", 9)
                    oval(22, 22, 20, 20, "#748c91")
                elif kind == "core-shard":
                    rect(12, 12, 40, 40, "#b99b58")
                    rect(18, 18, 28, 28, "#324550")
                    path = ui.Path()
                    path.move_to(32, 21)
                    path.line_to(43, 32)
                    path.line_to(32, 43)
                    path.line_to(21, 32)
                    path.close()
                    ui.set_color("#f8d782")
                    path.fill()
                    for x, y in ((7, 7), (47, 7), (7, 47), (47, 47)):
                        rect(x, y, 10, 10, "#75979b")
                elif kind == "mechanical-drill":
                    rect(9, 9, 46, 46, "#687e83")
                    oval(12, 12, 40, 40, "#293d47")
                    for x in (7, 51):
                        for y in (7, 51):
                            rect(x, y, 6, 6, "#cead73")
                elif kind == "duo":
                    oval(9, 9, 46, 46, "#72818a")
                    oval(15, 15, 34, 34, "#273d49")
                elif kind == "copper-wall":
                    rect(7, 7, 50, 50, "#b47757")
                    rect(11, 11, 42, 40, "#cf956b")
                    line(((12, 12), (51, 51)), "#e4b48a", 3)
                    line(((12, 51), (51, 12)), "#9b644c", 3)
            image = context.get_image()
        texture = sc.Texture(image)
        texture.filtering_mode = sc.FILTERING_NEAREST
        return texture

    class MindustryScene(sc.Scene):
        # Defaults also protect callbacks invoked while the base constructor
        # is running. Per-instance flags are assigned before calling it.
        _failed = False
        _ready = False
        _setup_in_progress = False
        _setup_attempted = False

        def __init__(self, *args, **kwargs):
            self._failed = False
            self._ready = False
            self._setup_in_progress = False
            self._setup_attempted = False
            self._stage = "construction"
            self._last_error = ""
            self._failure_report = ""
            self._crash_log_path = None
            self.storage = None
            super().__init__(*args, **kwargs)

        def setup(self):
            # Pythonista normally calls setup once before presenting the scene.
            # Guard against re-entry and an unexpected early update callback.
            if self._ready or self._failed or self._setup_in_progress:
                return
            try:
                if self.size.w <= 0 or self.size.h <= 0:
                    return  # Wait for a real view size; do not lay out at 0x0.
                self._setup_attempted = True
                self._setup_in_progress = True
                self._stage = "setup"
                self._setup_game()
                self._ready = True
                self._stage = "running"
            except Exception:
                self._report_failure("startup / " + self._stage)
            finally:
                self._setup_in_progress = False

        def _report_failure(self, phase):
            """Keep the FIRST traceback even if disk access or the HUD fails."""
            if self._failed:
                return
            self._failed = True
            self._ready = False
            self.sim_paused = True
            self._last_error = traceback.format_exc()
            self._failure_report = (
                "Mindustry Pythonista %s\nPhase: %s\nPython: %s\n"
                "Script directory: %s\nSave directory: %s\n\n%s" % (
                    VERSION, phase, sys.version.replace("\n", " "),
                    _SCRIPT_DIRECTORY, self.storage, self._last_error))
            print(self._failure_report)
            # Logging must never replace the original error with a second one.
            locations = []
            if self.storage is not None:
                locations.append(self.storage)
            for location in (data_directory, private_data_directory):
                try:
                    candidate = location()
                    if candidate not in locations:
                        locations.append(candidate)
                except Exception:
                    pass
            for directory in locations:
                try:
                    directory.mkdir(parents=True, exist_ok=True)
                    path = directory / "crash.log"
                    path.write_text(self._failure_report, encoding="utf-8")
                    self._crash_log_path = path
                    print("Crash log:", path)
                    break
                except Exception as error:
                    print("Could not write crash.log:", type(error).__name__, str(error))
            self._show_failure()

        def _show_failure(self):
            # Deliberately independent of world, textures, storage and the HUD.
            # A failure here is secondary; the console still has the root error.
            try:
                clear(self)
                self.background_color = (.10, .035, .04)
                width, height = self.size.w, self.size.h
                chars = max(12, int((width-36)/13))
                detail = self._last_error.strip().splitlines()[-1]
                wrapped = [detail[i:i+chars] for i in range(0, min(len(detail), chars*4), chars)]
                lines = ["起動／実行エラー  DEV " + VERSION,
                         "ゲーム処理を停止しました。", ""] + wrapped + [
                         "", "×で閉じてコンソールを確認してください。",
                         "Tracebackの全文を送ってください。"]
                step = min(24, max(14, (height-60)/max(1, len(lines))))
                y = min(height-45, height/2 + len(lines)*step/2)
                for text in lines:
                    sc.LabelNode(text, font=("Helvetica", 13), color="white",
                                 position=(width/2, y), parent=self, z_position=10000)
                    y -= step
            except Exception as error:
                print("Could not draw error screen:", type(error).__name__, str(error))

        def _setup_game(self):
            self._stage = "background"
            self.background_color = "#10171e"
            self._stage = "storage"
            self.storage, storage_warning = prepare_data_directory()
            self._clock = 0.0
            self._autosave_at = 30.0
            self.accumulator = 0.0
            self.sim_paused = False
            self.sim_speed = 1
            self.tool = "pan"
            self.build_rotation = 0
            self.position_mode = False
            self.preview_tile = None
            self.selected_id = None
            self.message = ""
            self.message_until = 0.0
            self.confirm_action = None
            self.confirm_until = 0.0
            self.gestures = {}
            self.ignored_touches = set()
            self.overlay_kind = None
            self._stage = "textures"
            self.textures = {kind: make_texture(kind) for kind in
                             tuple(DEFAULT_CONTENT) + ("range", "selection", "item",
                                                       "enemy", "gun-head", "drill-head")}
            startup_error = storage_warning
            self._stage = "content"
            self.content = load_content(_SCRIPT_DIRECTORY / "content_overrides.json")
            self._stage = "world / autosave"
            resume = self.storage / "autosave.json"
            if resume.exists():
                try:
                    self.world = World.load(resume)
                except (ValueError, OSError, KeyError, TypeError) as error:
                    # Preserve the broken file instead of silently overwriting it.
                    backup = self.storage / ("unreadable-autosave-%d.json" % time.time_ns())
                    os.replace(resume, backup)
                    self.world = World.demo(self.content)
                    startup_error = (startup_error + " " if startup_error else "") + \
                        "自動保存を読めず退避。詳細はコンソールへ"
                    print("Autosave preserved at", backup, "error:", error)
            else:
                self.world = World.demo(self.content)
            self._stage = "scene graph"
            self.root = sc.Node(parent=self, z_position=0)
            self.hud = sc.Node(parent=self, z_position=100)
            self.overlay = sc.Node(parent=self, z_position=200)
            self.zoom = max(.45, min(1.0, (self.size.w-32)/(27*TILE)))
            self.camera_x, self.camera_y = 16.5, 13.5
            self._last_hud = -1.0
            self._stage = "map drawing"
            self.rebuild_world()
            self._stage = "layout"
            self.layout()
            self._stage = "help overlay"
            self.show_overlay("help")
            if startup_error:
                self.notify(startup_error, 30)

        def rebuild_world(self):
            clear(self.root)
            self.building_nodes = {}
            self.enemy_nodes = {}
            self.bullet_nodes = {}
            self.item_pool = []
            self.visible_revision = -1
            # Cache the static map in 8x8 chunks, not 1536 separate tile nodes.
            for cy in range(0, self.world.height, 8):
                for cx in range(0, self.world.width, 8):
                    cols = min(8, self.world.width-cx)
                    rows = min(8, self.world.height-cy)
                    with ui.ImageContext(cols*TILE, rows*TILE) as context:
                        for iy in range(rows):
                            for ix in range(cols):
                                tx, ty = cx+ix, cy+iy
                                px, py = ix*TILE, (rows-1-iy)*TILE
                                idx = self.world.index(tx, ty)
                                terrain = self.world.terrain[idx]
                                shade = ((tx*19 + ty*23) % 7) / 255.0
                                color = (.145+shade, .19+shade, .21+shade)
                                if terrain == 1:
                                    color = "#45505a"
                                elif terrain == 2:
                                    color = "#254b60"
                                rect(px, py, TILE, TILE, color)
                                line(((px, py+TILE-1), (px+TILE, py+TILE-1)),
                                     (0, 0, 0, .18), .8)
                                line(((px+TILE-1, py), (px+TILE-1, py+TILE)),
                                     (0, 0, 0, .18), .8)
                                ore = self.world.ore[idx]
                                if ore:
                                    for ox, oy, size in ((6, 8, 7), (19, 6, 6), (15, 21, 7)):
                                        rect(px+ox, py+oy, size, size-1, ITEM_COLORS[ore])
                                if terrain == 1:
                                    line(((px+4, py+25), (px+11, py+7), (px+27, py+10)),
                                         "#64717b", 3)
                                if terrain == 2:
                                    line(((px+5, py+17), (px+16, py+14), (px+27, py+17)),
                                         "#3d697c", 1)
                        image = context.get_image()
                    texture = sc.Texture(image)
                    texture.filtering_mode = sc.FILTERING_NEAREST
                    node = sc.SpriteNode(texture, parent=self.root, z_position=-10)
                    node.anchor_point = (0, 0)
                    node.position = (cx*TILE, cy*TILE)
                    node.size = (cols*TILE, rows*TILE)
            sc.LabelNode("敵の入口 ←", font=("Helvetica", 13), color="#f0a5a0",
                         position=((self.world.width-5)*TILE, (self.world.height/2+5)*TILE),
                         parent=self.root, z_position=1)
            self.selection = sc.SpriteNode(self.textures["selection"], parent=self.root,
                                           z_position=15, alpha=0)
            self.range_node = sc.SpriteNode(self.textures["range"], parent=self.root,
                                            z_position=0, alpha=0)
            self.ghost_node = sc.SpriteNode(self.textures["conveyor"], parent=self.root,
                                             z_position=13, alpha=0)
            self.direction_marker = sc.Node(parent=self.root, z_position=20, alpha=0)
            sc.SpriteNode(color=(.04, .09, .12, .94), size=(34, 28),
                          parent=self.direction_marker)
            self.direction_label = sc.LabelNode("→", font=("Helvetica-Bold", 24),
                                               color="#f5d385", parent=self.direction_marker)
            self.preview_tile = None
            self.sync_nodes()

        def view_center(self):
            return self.size.w/2, (self.bar_top + self.size.h-self.header_height)/2

        def update_camera(self):
            self.camera_x = clamp(self.camera_x, 0, self.world.width)
            self.camera_y = clamp(self.camera_y, 0, self.world.height)
            cx, cy = self.view_center()
            self.root.x_scale = self.root.y_scale = self.zoom
            self.root.position = (cx-self.camera_x*TILE*self.zoom,
                                  cy-self.camera_y*TILE*self.zoom)
            if self.preview_tile is not None:
                self.highlight(*self.preview_tile)

        def screen_to_world(self, point):
            cx, cy = self.view_center()
            return (self.camera_x+(point[0]-cx)/(TILE*self.zoom),
                    self.camera_y+(point[1]-cy)/(TILE*self.zoom))

        def set_zoom(self, value, point=None):
            point = point or self.view_center()
            before = self.screen_to_world(point)
            self.zoom = clamp(value, .25, 2.5)
            after = self.screen_to_world(point)
            self.camera_x += before[0]-after[0]
            self.camera_y += before[1]-after[1]
            self.update_camera()

        def add_button(self, parent, action, title, box, subtitle=None, group=None):
            x, y, w, h = box
            bg = sc.SpriteNode(color="#273741", size=(w, h), position=(x+w/2, y+h/2),
                               parent=parent)
            title_units = sum(1.0 if ord(c) > 255 else .6 for c in title)
            font_size = max(10, min(13 if w < 85 else 15,
                                    int((w-10)/max(1, title_units))))
            label = sc.LabelNode(title, font=("Helvetica", font_size),
                                 color="#eff0e5", position=(0, 5 if subtitle else 0), parent=bg)
            sublabel = None
            if subtitle:
                sublabel = sc.LabelNode(subtitle, font=("Helvetica", 10), color="#bfc2b7",
                                        position=(0, -13), parent=bg)
            record = {"action": action, "rect": box, "bg": bg, "label": label,
                      "subtitle": sublabel}
            (group if group is not None else self.buttons).append(record)
            return record

        def layout(self):
            clear(self.hud)
            self.buttons = []
            portrait = self.size.h >= self.size.w
            edge = 10 if portrait else 44
            bottom = 30 if portrait else 18
            top = 58 if portrait else 28
            self.bar_top = bottom + 155
            self.header_height = top + 62
            sc.SpriteNode(color="#111c24", size=(self.size.w, self.bar_top),
                          position=(self.size.w/2, self.bar_top/2), parent=self.hud)
            sc.SpriteNode(color="#111c24", size=(self.size.w, self.header_height),
                          position=(self.size.w/2, self.size.h-self.header_height/2), parent=self.hud)
            sc.LabelNode("MINDUSTRY / PYTHONISTA  ·  DEV 0.1.2", font=("Helvetica-Bold", 12),
                         color="#b6d4d5", position=(self.size.w/2, self.size.h-top), parent=self.hud)
            self.stock_label = sc.LabelNode("", font=("Helvetica-Bold", 16), color="#f2d59b",
                                           position=(self.size.w/2, self.size.h-top-23), parent=self.hud)
            self.state_label = sc.LabelNode("", font=("Helvetica", 12), color="#aab9bd",
                                           position=(self.size.w/2, self.size.h-top-44), parent=self.hud)
            self.message_label = sc.LabelNode("", font=("Helvetica", 12), color="#e5d9b7",
                                             position=(self.size.w/2, self.bar_top+13), parent=self.hud)
            width = (self.size.w-edge*2-4*5)/5
            for col, kind in enumerate(BUILD_TOOLS):
                spec = self.world.content[kind]
                cost = "/".join(ITEM_LABELS[i]+str(n) for i, n in spec["cost"].items())
                self.add_button(self.hud, kind, spec["label"],
                                (edge+col*(width+5), bottom+102, width, 46), cost)
            # Keep the same three-row footprint, including in landscape.
            # Reuse the wave slot during building instead of adding small buttons.
            contextual = (("position-mode", "マス操作") if self.tool in BUILD_TOOLS
                          else ("wave", "ウェーブ"))
            for col, (action, title) in enumerate((
                ("pan", "移動/調査"), ("erase", "撤去"), ("pause", "停止"),
                contextual, ("menu", "メニュー"),
            )):
                self.add_button(self.hud, action, title,
                                (edge+col*(width+5), bottom, width, 46),
                                ("ON" if self.position_mode else "OFF") if action == "position-mode" else None)
            gap = 4
            rotation_width = (self.size.w-edge*2-gap*5)/6
            rotations = (("rotate", "↶", "左90°"),
                         ("direction-2", "←", "左向き"),
                         ("direction-1", "↑", "上向き"),
                         ("direction-3", "↓", "下向き"),
                         ("direction-0", "→", "右向き"),
                         ("rotate-cw", "↷", "右90°"))
            if self.position_mode:
                rotations = (("rotate", "↶", "向き回転"),
                             ("move-2", "←", "左1マス"),
                             ("move-1", "↑", "上1マス"),
                             ("move-3", "↓", "下1マス"),
                             ("move-0", "→", "右1マス"),
                             ("place-preview", "置く", "確定"))
            for col, (action, title, subtitle) in enumerate(rotations):
                button = self.add_button(self.hud, action, title,
                    (edge+col*(rotation_width+gap), bottom+51, rotation_width, 46),
                    subtitle)
                button["label"].font = ("Helvetica-Bold", 18 if action == "place-preview" else 23)
            self.update_camera()
            self.refresh_hud()

        def did_change_size(self):
            if self._failed:
                self._show_failure()
                return
            if not self._ready:
                return
            try:
                self.gestures.clear()
                self.ignored_touches.clear()
                self.layout()
                if self.overlay_kind:
                    self.show_overlay(self.overlay_kind)
            except Exception:
                self._report_failure("resize")

        def notify(self, text, duration=3.0):
            self.message = text
            self.message_until = self._clock + duration
            self._last_hud = -1

        def refresh_hud(self):
            w = self.world
            hp = int(w.cores()[0].hp) if w.cores() else 0
            self.stock_label.text = "銅 %d    鉛 %d    コア %d" % (w.stock["copper"], w.stock["lead"], hp)
            mode = "研究用" if w.sandbox else "防衛"
            state = "コア破壊" if w.game_over else "停止中" if self.sim_paused else mode
            self.state_label.text = "WAVE %d   敵 %d   次 %ds   %s" % (
                w.wave, len(w.enemies), max(0, w.wave_timer//TPS), state)
            if any(g.get("armed") and not g["pinched"] and not g.get("cancelled")
                   for g in self.gestures.values()):
                text = "連続撤去OK：なぞって撤去" if self.tool == "erase" else "連続設置OK：なぞって設置"
            elif self._clock < self.message_until:
                text = self.message
            elif self.position_mode:
                text = "マス操作：矢印で調整 →「置く」で確定"
            elif self.tool == "conveyor":
                text = "ベルト %s：タップで1個／長押し後になぞる" % ARROWS[self.build_rotation]
            elif self.rotation_target() is not None:
                text = "選択ベルト %s：中央の矢印で向きを変更" % ARROWS[self.rotation_target().rotation]
            elif self.tool in w.content:
                text = "%s：タップで設置（方向指定なし）" % w.content[self.tool]["label"]
            elif self.tool == "erase":
                text = "撤去：タップで1個／長押し後になぞる"
            else:
                text = "移動：1本指ドラッグ／2本指ズーム／タップで調査"
            max_chars = max(18, int((self.size.w-24)/12))
            self.message_label.text = text[:max_chars]
            for button in self.buttons:
                action = button["action"]
                button["bg"].color = "#3e6870" if action == self.tool else "#273741"
                if action == "pause":
                    button["label"].text = "再開" if self.sim_paused else "停止"
                elif action == "speed":
                    button["label"].text = "×%d" % self.sim_speed
                elif action == "position-mode":
                    button["bg"].color = "#8b682f" if self.position_mode else "#273741"
                elif action.startswith("move-"):
                    button["bg"].color = "#3e6870"
                elif action == "place-preview":
                    button["bg"].color = "#397050"
                if action in ("rotate", "rotate-cw") or action.startswith("direction-"):
                    enabled = self.tool == "conveyor" or self.rotation_target() is not None
                    button["bg"].alpha = 1.0 if enabled else .38
                    current = self.current_rotation()
                    active = action == "direction-%d" % current
                    button["bg"].color = ("#8b682f" if enabled and active else
                                            "#334b5d" if enabled else "#273741")
            self._last_hud = self._clock

        def show_overlay(self, kind):
            self.overlay_kind = kind
            self.gestures.clear()
            clear(self.overlay)
            self.overlay_buttons = []
            sc.SpriteNode(color=(.015, .025, .04, .86), size=(self.size.w, self.size.h),
                          position=(self.size.w/2, self.size.h/2), parent=self.overlay)
            cw = min(self.size.w-28, 650)
            if kind == "help":
                lines = ["原作v159.7を基準にした、部分移植の開発版です。",
                         "採掘→コア、採掘→砲台の2系統を配置済み。",
                         "移動：1本指ドラッグ。2本指で拡大・縮小。",
                         "建物を選び、地面をタップすると建築します。",
                         "ベルト：中央の←↑↓→で向き、↶↷で90°回転。",
                         "連続設置・撤去：少し長押し→OK表示→なぞる。",
                         "マス操作ON：矢印で位置を動かし、置くで確定。",
                         "既設ベルト：移動/調査で選択→方向ボタン。",
                         "ウェーブは下段またはメニュー。銅が砲台の弾薬。",
                         "保存・速度・コア移動・ズームはメニュー内。",
                         "本家セーブ・MOD・通信・キャンペーンは未対応。"]
                font = 12
                maxchars = max(16, int((cw-30)/font))
                wrapped = [s[i:i+maxchars] for s in lines for i in range(0, len(s), maxchars)]
                step = min(19, max(12, (self.size.h-150)/max(1, len(wrapped))))
                ch = 100+len(wrapped)*step
                x, y = (self.size.w-cw)/2, (self.size.h-ch)/2
                sc.SpriteNode(color="#1b2b36", size=(cw, ch),
                              position=(self.size.w/2, self.size.h/2), parent=self.overlay)
                sc.LabelNode("PYTHONISTA PORT / 開発版 0.1.2", font=("Helvetica-Bold", 15),
                             color="#edcd8d", position=(self.size.w/2, y+ch-25), parent=self.overlay)
                for i, text in enumerate(wrapped):
                    node = sc.LabelNode(text, font=("Helvetica", font), color="#dce3de",
                                        position=(x+15, y+ch-56-i*step), parent=self.overlay)
                    node.anchor_point = (0, .5)
                self.add_button(self.overlay, "close", "ゲームへ", (x+15, y+12, cw-30, 38),
                                group=self.overlay_buttons)
            else:
                # A separate controls page preserves large targets on small screens.
                ch = min(325, self.size.h-48)
                x, y = (self.size.w-cw)/2, (self.size.h-ch)/2
                sc.SpriteNode(color="#1b2b36", size=(cw, ch),
                              position=(self.size.w/2, self.size.h/2), parent=self.overlay)
                title = "表示・速度" if kind == "controls" else "開発版メニュー"
                sc.LabelNode(title, font=("Helvetica-Bold", 18),
                             color="#edcd8d", position=(self.size.w/2, y+ch-25), parent=self.overlay)
                if kind == "controls":
                    actions = (("speed", "速度 ×%d" % self.sim_speed), ("home", "コアへ移動"),
                               ("zoom-out", "縮小 −"), ("zoom-in", "拡大 ＋"),
                               ("menu", "メニューへ"), ("close", "ゲームへ"))
                else:
                    actions = (("save", "手動保存"), ("load", "手動読込"),
                               ("sandbox", "研究用 " + ("ON" if self.world.sandbox else "OFF")),
                               ("new", "新規デモ"), ("help", "操作説明"),
                               ("controls", "表示・速度"), ("wave", "ウェーブ開始"),
                               ("close", "ゲームへ"))
                bw = (cw-42)/2
                for i, (action, title) in enumerate(actions):
                    if self.confirm_action == action and self._clock < self.confirm_until:
                        title = "もう一度：" + title
                    self.add_button(self.overlay, action, title,
                                    (x+14+(i%2)*(bw+14), y+ch-94-(i//2)*53, bw, 44),
                                    group=self.overlay_buttons)
                if kind == "controls":
                    sc.LabelNode("2本指ピンチでも拡大・縮小できます", font=("Helvetica", 11),
                                 color="#aebbc0", position=(self.size.w/2, y+18), parent=self.overlay)

        def close_overlay(self):
            clear(self.overlay)
            self.overlay_kind = None
            self.gestures.clear()
            self.accumulator = 0.0

        def confirm(self, action):
            if self.confirm_action == action and self._clock < self.confirm_until:
                self.confirm_action = None
                return True
            self.confirm_action = action
            self.confirm_until = self._clock + 4
            self.show_overlay("menu")
            return False

        def save_world(self, manual=False):
            if self._failed or not self._ready:
                return
            path = self.storage / ("manual.json" if manual else "autosave.json")
            try:
                self.world.save(path)
                if manual:
                    self.notify("手動保存しました", 4)
            except (OSError, ValueError) as error:
                self.notify("保存失敗：" + str(error), 8)
                print("Save failed:", error)

        def perform(self, action):
            if self._failed or not self._ready:
                return
            try:
                self._perform(action)
            except Exception as error:
                self.notify("操作エラー：" + str(error), 8)
                traceback.print_exc()

        def rotation_target(self):
            """Only an explicitly inspected belt can be changed in pan mode."""
            if self.tool != "pan":
                return None
            selected = self.world.buildings.get(self.selected_id)
            return selected if selected and selected.kind == "conveyor" else None

        def current_rotation(self):
            selected = self.rotation_target()
            return selected.rotation if selected is not None else self.build_rotation

        def change_direction(self, rotation):
            selected = self.rotation_target()
            if self.tool != "conveyor" and selected is None:
                self.notify("ベルトを選択すると向きを変更できます")
                return
            rotation = int(rotation) % 4
            if selected is not None:
                # Reorient in place. Never rebuild, refund, or discard cargo.
                if selected.rotation != rotation:
                    selected.rotation = rotation
                    self.world.invalidated()
                self.build_rotation = rotation
                self.highlight(selected.x, selected.y)
                self.notify("選択ベルトを %s 向きに変更" % ARROWS[rotation], 2)
            else:
                self.build_rotation = rotation
                if self.preview_tile is not None:
                    self.highlight(*self.preview_tile)
                self.notify("設置方向 %s（次に置くベルト）" % ARROWS[rotation], 2)

        def move_preview(self, direction):
            """Move only the build cursor; never move or rebuild an existing block."""
            if not self.position_mode or self.tool not in BUILD_TOOLS:
                return
            self.gestures.clear()
            size = self.world.content[self.tool]["size"]
            x, y = self.preview_tile or tuple(map(math.floor, self.screen_to_world(self.view_center())))
            dx, dy = DIRECTIONS[direction % 4]
            x = int(clamp(x+dx, 0, self.world.width-size))
            y = int(clamp(y+dy, 0, self.world.height-size))
            self.highlight(x, y)
            # Follow the cursor only when it would leave the usable viewport.
            cx, cy = self.view_center()
            px = cx+(x+size/2-self.camera_x)*TILE*self.zoom
            py = cy+(y+size/2-self.camera_y)*TILE*self.zoom
            half = size*TILE*self.zoom/2
            if px-half < 0 or px+half > self.size.w:
                self.camera_x = x+size/2
            if py-half < self.bar_top+24 or py+half > self.size.h-self.header_height:
                self.camera_y = y+size/2
            self.update_camera()

        def _perform(self, action):
            if action in BUILD_TOOLS or action in ("pan", "erase"):
                self.gestures.clear()
                self.tool = action
                self.position_mode = False
                self.selected_id = None
                self.preview_tile = None
                self.selection.alpha = self.range_node.alpha = 0
                self.ghost_node.alpha = self.direction_marker.alpha = 0
                self.message_until = 0
                if action in BUILD_TOOLS:
                    wx, wy = self.screen_to_world(self.view_center())
                    self.highlight(int(math.floor(wx)), int(math.floor(wy)))
                self.layout()
            elif action == "position-mode" and self.tool in BUILD_TOOLS:
                self.gestures.clear()
                self.position_mode = not self.position_mode
                self.message_until = 0
                self.layout()
            elif action.startswith("move-"):
                self.move_preview(int(action.split("-", 1)[1]))
            elif action == "place-preview":
                if self.position_mode and self.tool in BUILD_TOOLS and self.preview_tile is not None:
                    self.gestures.clear()
                    self.apply_tool(*self.preview_tile, reorient=True)
            elif action in ("rotate", "rotate-cw"):
                # World axes: +1 is counterclockwise, -1 is clockwise.
                self.change_direction(self.current_rotation() + (1 if action == "rotate" else -1))
            elif action.startswith("direction-"):
                self.change_direction(int(action.split("-", 1)[1]))
            elif action in ("zoom-in", "zoom-out"):
                self.set_zoom(self.zoom*(1.25 if action == "zoom-in" else .8))
            elif action == "pause":
                self.gestures.clear()
                self.sim_paused = not self.sim_paused
                self.accumulator = 0
            elif action == "speed":
                self.sim_speed = 2 if self.sim_speed == 1 else 1
            elif action == "wave":
                if self.overlay_kind:
                    self.close_overlay()
                if self.world.start_wave():
                    self.notify("ウェーブ %d 開始" % self.world.wave)
                else:
                    self.notify("出現待ちの敵がいます／コア破壊後は新規開始")
            elif action == "home":
                core = self.world.cores()
                if core:
                    self.camera_x, self.camera_y = self.world.center(core[0])
                    self.update_camera()
            elif action in ("menu", "help", "controls"):
                self.show_overlay(action)
            elif action == "close":
                self.close_overlay()
            elif action == "save":
                self.save_world(manual=True)
                self.close_overlay()
            elif action == "load":
                if not self.confirm("load"):
                    return
                path = self.storage / "manual.json"
                candidate = World.load(path)  # Replace live state only after validation.
                self.world = candidate
                self.selected_id = None
                self.rebuild_world()
                self.layout()
                self.close_overlay()
                self.notify("手動保存を読み込みました")
            elif action == "sandbox":
                self.world.sandbox = not self.world.sandbox
                self.show_overlay("menu")
            elif action == "new":
                if not self.confirm("new"):
                    return
                self.content = load_content(_SCRIPT_DIRECTORY / "content_overrides.json")
                # Preserve the current state in a separate slot before resetting.
                self.world.save(self.storage / "before-new.json")
                self.world = World.demo(self.content)
                self.camera_x, self.camera_y = 16.5, 13.5
                self.selected_id = None
                self.sim_paused = False
                self.rebuild_world()
                self.layout()
                self.close_overlay()
                self.notify("新規デモ。前の状態は before-new.json に保存")
            if self.overlay_kind == "controls" and action in ("speed", "home", "zoom-in", "zoom-out"):
                self.show_overlay("controls")
            self.refresh_hud()

        def highlight(self, x, y):
            self.preview_tile = (x, y)
            self.ghost_node.alpha = self.direction_marker.alpha = 0
            b = self.world.at(x, y)
            if self.tool in BUILD_TOOLS:
                size = self.world.content[self.tool]["size"]
                center = x+size/2, y+size/2
                same_belt = self.tool == "conveyor" and b is not None and b.kind == "conveyor"
                ok = same_belt or self.world.can_place(self.tool, x, y)[0]
                color = "#90e1c1" if ok else "#ed8c86"
                kind = self.tool
                self.ghost_node.texture = self.textures[kind]
                self.ghost_node.position = center[0]*TILE, center[1]*TILE
                self.ghost_node.size = size*TILE, size*TILE
                self.ghost_node.rotation = self.build_rotation*math.pi/2 if kind == "conveyor" else 0
                self.ghost_node.alpha = .55
            elif b:
                size, center, kind, color = self.world.size_of(b), self.world.center(b), b.kind, "#e9d084"
            else:
                self.selection.alpha = self.range_node.alpha = 0
                return
            self.selection.position = center[0]*TILE, center[1]*TILE
            self.selection.size = size*TILE, size*TILE
            self.selection.color = color
            self.selection.alpha = .9
            if kind == "conveyor" and self.tool != "erase":
                rotation = self.build_rotation if self.tool == "conveyor" else b.rotation
                self.direction_label.text = ARROWS[rotation]
                # Constant-size badge; keep it inside the game viewport rather
                # than hiding half of it behind the header in landscape.
                cx, cy = self.view_center()
                screen_x = cx+(center[0]-self.camera_x)*TILE*self.zoom
                screen_y = cy+(center[1]-self.camera_y)*TILE*self.zoom
                low, high = self.bar_top+24, self.size.h-self.header_height
                badge_x, badge_y = screen_x, screen_y+size*TILE*self.zoom/2+18
                if high-low < 120:
                    badge_x, badge_y = screen_x+size*TILE*self.zoom/2+24, screen_y
                badge_x = clamp(badge_x, 18, self.size.w-18)
                badge_y = clamp(badge_y, low+14, max(low+14, high-14))
                wx, wy = self.screen_to_world((badge_x, badge_y))
                self.direction_marker.position = wx*TILE, wy*TILE
                self.direction_marker.x_scale = self.direction_marker.y_scale = 1/self.zoom
                self.direction_marker.alpha = 1 if (0 <= screen_x <= self.size.w and
                                                    low <= screen_y <= high) else 0
            self.range_node.alpha = .45 if kind == "duo" else 0
            if kind == "duo":
                radius = self.world.content["duo"]["range"]*TILE
                self.range_node.position = self.selection.position
                self.range_node.size = radius*2, radius*2

        def inspect_tile(self, x, y):
            b = self.world.at(x, y)
            self.selected_id = b.id if b else None
            if b:
                spec = self.world.content[b.kind]
                detail = ""
                if b.kind == "duo":
                    detail = "  弾 %d" % b.ammo
                elif b.kind == "conveyor":
                    detail = "  荷物 %d  %s" % (len(b.belt), ARROWS[b.rotation])
                elif b.kind == "mechanical-drill":
                    item, count = self.world.mine_info(b)
                    detail = "  %s鉱床%d" % (ITEM_LABELS.get(item, "無"), count)
                self.notify("%s HP%d/%d%s" % (spec["label"], b.hp, spec["health"], detail), 6)
            elif self.world.inside(x, y):
                item = self.world.ore[self.world.index(x, y)]
                self.notify("(%d,%d) %s" % (x, y, ITEM_LABELS.get(item, "地面")))
            self.highlight(x, y)
            self.refresh_hud()

        def apply_tool(self, x, y, reorient=False):
            if self.tool == "erase":
                b = self.world.at(x, y)
                if b and not self.world.remove(b):
                    self.notify("コアは撤去できません")
            elif self.tool in BUILD_TOOLS:
                existing = self.world.at(x, y)
                if existing and existing.kind == self.tool:
                    # Explicit taps can redirect a belt for free. Dragging across
                    # an existing factory must not silently rotate its belts.
                    if reorient and self.tool == "conveyor":
                        if existing.rotation != self.build_rotation:
                            existing.rotation = self.build_rotation
                            self.world.invalidated()
                        self.notify("既設ベルトを %s 向きに変更（資源消費なし）" % ARROWS[self.build_rotation], 2)
                    self.highlight(x, y)
                    return
                if self.world.place(self.tool, x, y, self.build_rotation) is None:
                    self.notify(self.world.last_message)
            self.highlight(x, y)

        def paint_line(self, start, end):
            # Bresenham, with an orthogonal intermediate tile on diagonal moves.
            x, y = start
            ex, ey = end
            dx, dy = abs(ex-x), abs(ey-y)
            sx, sy = (1 if x < ex else -1), (1 if y < ey else -1)
            error = dx-dy
            for _ in range(self.world.width+self.world.height+4):
                self.apply_tool(x, y)
                if (x, y) == (ex, ey):
                    break
                twice = error*2
                if twice > -dy:
                    error -= dy
                    x += sx
                    if twice < dx:
                        self.apply_tool(x, y)
                if twice < dx:
                    error += dx
                    y += sy

        def is_world_point(self, point):
            return (0 <= point[0] <= self.size.w and
                    self.bar_top+24 < point[1] < self.size.h-self.header_height)

        def arm_build_gesture(self, g):
            if (not g["armed"] and not g["drag"] and not g["pinched"] and not g["cancelled"]
                    and not self.position_mode and not self.overlay_kind and len(self.gestures) == 1
                    and self.tool in ("conveyor", "copper-wall", "erase")
                    and self._clock-g["started_at"] >= BUILD_HOLD_SECONDS):
                g["armed"] = True
                self._last_hud = -1

        @staticmethod
        def hit(button, point):
            x, y, w, h = button["rect"]
            return x <= point[0] <= x+w and y <= point[1] <= y+h

        def touch_began(self, touch):
            if self._failed or not self._ready:
                return
            p, tid = tuple(touch.location), touch.touch_id
            if self.overlay_kind:
                self.ignored_touches.add(tid)
                for button in self.overlay_buttons:
                    if self.hit(button, p):
                        self.perform(button["action"])
                        return
                return
            for button in self.buttons:
                if self.hit(button, p):
                    self.ignored_touches.add(tid)
                    self.perform(button["action"])
                    return
            if not self.is_world_point(p):
                self.ignored_touches.add(tid)
                return
            wx, wy = self.screen_to_world(p)
            tile = int(math.floor(wx)), int(math.floor(wy))
            self.gestures[tid] = {"start": p, "last": p, "tile": tile, "origin_tile": tile,
                                  "started_at": self._clock, "armed": False, "cancelled": False,
                                  "drag": False, "pinched": False}
            if len(self.gestures) >= 2:
                for g in self.gestures.values():
                    g["pinched"] = True
                    g["armed"] = False
                self._last_hud = -1
            else:
                self.highlight(int(math.floor(wx)), int(math.floor(wy)))

        def touch_moved(self, touch):
            if self._failed or not self._ready:
                return
            tid, p = touch.touch_id, tuple(touch.location)
            if tid not in self.gestures or self.overlay_kind:
                return
            g = self.gestures[tid]
            old = g["last"]
            if len(self.gestures) >= 2:
                keys = list(self.gestures)[:2]
                oldp = [self.gestures[k]["last"] for k in keys]
                g["last"] = p
                newp = [self.gestures[k]["last"] for k in keys]
                oldmid = ((oldp[0][0]+oldp[1][0])/2, (oldp[0][1]+oldp[1][1])/2)
                newmid = ((newp[0][0]+newp[1][0])/2, (newp[0][1]+newp[1][1])/2)
                olddist = math.dist(oldp[0], oldp[1])
                newdist = math.dist(newp[0], newp[1])
                anchor = self.screen_to_world(oldmid)
                if olddist > 8:
                    self.zoom = clamp(self.zoom*newdist/olddist, .25, 2.5)
                cx, cy = self.view_center()
                self.camera_x = anchor[0]-(newmid[0]-cx)/(TILE*self.zoom)
                self.camera_y = anchor[1]-(newmid[1]-cy)/(TILE*self.zoom)
                self.update_camera()
                return
            g["last"] = p
            if g["pinched"] or g["cancelled"]:
                return
            if self.tool != "pan" and not self.is_world_point(p):
                g["cancelled"] = True
                self._last_hud = -1
                return
            self.arm_build_gesture(g)
            if math.dist(p, g["start"]) > TOUCH_SLOP:
                g["drag"] = True
            if self.tool == "pan":
                self.camera_x -= (p[0]-old[0])/(TILE*self.zoom)
                self.camera_y -= (p[1]-old[1])/(TILE*self.zoom)
                self.update_camera()
            elif self.is_world_point(p):
                wx, wy = self.screen_to_world(p)
                tile = (int(math.floor(wx)), int(math.floor(wy)))
                if self.position_mode:
                    self.highlight(*tile)
                elif g["drag"]:
                    if g["armed"]:
                        self.paint_line(g["tile"], tile)
                        g["tile"] = tile
                    else:
                        # Once a quick swipe is rejected, waiting mid-swipe
                        # cannot turn it into a brush stroke or an end-point tap.
                        g["cancelled"] = True
                        self.notify("スライドを取消：連続操作は長押し後になぞる", 2)
                        self.highlight(*g["origin_tile"])
                else:
                    # A few points of finger jitter must not switch tiles at
                    # low zoom. Keep an ordinary tap anchored to its start.
                    self.highlight(*g["origin_tile"])

        def touch_ended(self, touch):
            if self._failed or not self._ready:
                return
            tid, p = touch.touch_id, tuple(touch.location)
            self.ignored_touches.discard(tid)
            g = self.gestures.get(tid)
            if g and p != g["last"]:
                # Some input sequences end without a final moved callback.
                self.touch_moved(touch)
            g = self.gestures.pop(tid, None)
            self._last_hud = -1
            if not g or g["pinched"] or g["cancelled"] or self.overlay_kind or not self.is_world_point(p):
                return
            wx, wy = self.screen_to_world(p)
            tile = int(math.floor(wx)), int(math.floor(wy))
            if self.tool == "pan":
                if not g["drag"]:
                    self.inspect_tile(*tile)
            elif self.position_mode:
                self.highlight(*tile)
            elif not g["drag"]:
                self.apply_tool(*g["origin_tile"], reorient=True)
            elif g["armed"]:
                self.paint_line(g["tile"], tile)

        def sync_nodes(self):
            w = self.world
            if self.visible_revision != w.revision:
                for uid in list(self.building_nodes):
                    if uid not in w.buildings:
                        self.building_nodes.pop(uid)[0].remove_from_parent()
                for b in w.buildings.values():
                    if b.id in self.building_nodes:
                        continue
                    size = w.size_of(b)*TILE
                    x, y = w.center(b)
                    node = sc.SpriteNode(self.textures[b.kind], position=(x*TILE, y*TILE),
                                         size=(size, size), parent=self.root, z_position=2)
                    hp = sc.SpriteNode(color="#98d4ae", size=(size, 2),
                                       position=(-size/2, size/2+3), parent=node, z_position=5)
                    hp.anchor_point = (0, .5)
                    part, ammo = None, None
                    if b.kind in ("duo", "mechanical-drill"):
                        texture = self.textures["gun-head" if b.kind == "duo" else "drill-head"]
                        part = sc.SpriteNode(texture, size=(size*.85, size*.85), parent=node, z_position=3)
                    if b.kind == "duo":
                        ammo = sc.SpriteNode(color=ITEM_COLORS["copper"], size=(size, 2),
                                             position=(-size/2, -size/2), parent=node, z_position=4)
                        ammo.anchor_point = (0, .5)
                    self.building_nodes[b.id] = node, hp, part, ammo
                self.visible_revision = w.revision
            for b in w.buildings.values():
                node, hp, part, ammo = self.building_nodes[b.id]
                size = w.size_of(b)*TILE
                hp.alpha = .9 if b.hp < w.content[b.kind]["health"] else 0
                hp.size = (size*max(0, b.hp/w.content[b.kind]["health"]), 2)
                if b.kind == "conveyor":
                    node.rotation = b.rotation*math.pi/2
                if part is not None:
                    part.rotation = b.angle if b.kind == "duo" else w.tick_count*.035*b.warmup
                if ammo is not None:
                    ammo.size = (size*b.ammo/w.content["duo"]["capacity"], 2)
            # Dynamic items share a reusable node pool; no per-frame creation.
            drawn = 0
            for b in w.buildings.values():
                packets = [(p.item, p.y, p.x) for p in b.belt]
                if b.kind == "router" and b.inventory:
                    packets = [(next(iter(b.inventory)), .5, 0)]
                for item, along, lateral in packets:
                    if drawn >= len(self.item_pool):
                        self.item_pool.append(sc.SpriteNode(self.textures["item"], size=(9, 9),
                                                            parent=self.root, z_position=7))
                    node = self.item_pool[drawn]
                    drawn += 1
                    x, y = w.center(b)
                    dx, dy = DIRECTIONS[b.rotation]
                    node.position = ((x+dx*(along-.5)-dy*lateral/2)*TILE,
                                     (y+dy*(along-.5)+dx*lateral/2)*TILE)
                    node.color = ITEM_COLORS[item]
                    node.alpha = 1
            for node in self.item_pool[drawn:]:
                node.alpha = 0
            for uid in list(self.enemy_nodes):
                if uid not in w.enemies:
                    self.enemy_nodes.pop(uid)[0].remove_from_parent()
            for e in w.enemies.values():
                if e.id not in self.enemy_nodes:
                    container = sc.Node(parent=self.root, z_position=9)
                    picture = sc.SpriteNode(self.textures["enemy"], size=(25, 25), parent=container)
                    hp = sc.SpriteNode(color="#ed8d91", size=(24, 2), position=(-12, 17), parent=container)
                    hp.anchor_point = (0, .5)
                    self.enemy_nodes[e.id] = container, picture, hp
                container, picture, hp = self.enemy_nodes[e.id]
                container.position = (e.x*TILE, e.y*TILE)
                picture.rotation = e.angle
                hp.size = (24*max(0, e.hp/e.max_hp), 2)
                hp.alpha = .9 if e.hp < e.max_hp else 0
            for uid in list(self.bullet_nodes):
                if uid not in w.bullets:
                    self.bullet_nodes.pop(uid).remove_from_parent()
            for b in w.bullets.values():
                if b.id not in self.bullet_nodes:
                    self.bullet_nodes[b.id] = sc.SpriteNode(color="#ffe2a6", size=(10, 3),
                                                           parent=self.root, z_position=10)
                node = self.bullet_nodes[b.id]
                node.position = (b.x*TILE, b.y*TILE)
                node.rotation = math.atan2(b.vy, b.vx)

        def update(self):
            if self._failed:
                return
            if not self._ready:
                # Never use partly initialized state. A skipped setup callback
                # gets one attempt here, after the scene has a valid size.
                if not self._setup_attempted and not self._setup_in_progress:
                    self.setup()
                return
            try:
                dt = clamp(self.dt, 0.0, .1)
                self._clock += dt
                for g in self.gestures.values():
                    self.arm_build_gesture(g)
                if not self.overlay_kind and not self.sim_paused and not self.world.game_over:
                    self.accumulator += dt*TPS*self.sim_speed
                    steps = min(12, int(self.accumulator + 1e-9))
                    if steps:
                        self.world.step(steps)
                        self.accumulator -= steps
                else:
                    self.accumulator = 0
                self.sync_nodes()
                if self._clock-self._last_hud > .2:
                    self.refresh_hud()
                if self._clock >= self._autosave_at:
                    self.save_world()
                    self._autosave_at = self._clock+30
            except Exception:
                self._report_failure("update")

        def pause(self):
            # Called by Pythonista on backgrounding, not the in-game Pause button.
            if self._failed or not self._ready:
                return
            self.gestures.clear()
            self.ignored_touches.clear()
            self.accumulator = 0
            self.save_world()

        def resume(self):
            if self._failed or not self._ready:
                return
            self.gestures.clear()
            self.ignored_touches.clear()
            self.accumulator = 0

        def stop(self):
            self.save_world()

    return MindustryScene


def run_pythonista() -> None:
    try:
        import scene as sc
        import ui
    except ImportError as error:
        raise SystemExit("GUIにはiPhone/iPadのPythonista 3が必要です。\n"
                         "PCでは --self-test または --benchmark を利用してください。") from error
    MindustryScene = make_scene_class(sc, ui)
    sc.run(MindustryScene(), frame_interval=2, multi_touch=True, show_fps=False)


# Complete GPL text travels with the single-file distribution.
GPL3_LICENSE_TEXT = r"""
                    GNU GENERAL PUBLIC LICENSE
                       Version 3, 29 June 2007

 Copyright (C) 2007 Free Software Foundation, Inc. <https://fsf.org/>
 Everyone is permitted to copy and distribute verbatim copies
 of this license document, but changing it is not allowed.

                            Preamble

  The GNU General Public License is a free, copyleft license for
software and other kinds of works.

  The licenses for most software and other practical works are designed
to take away your freedom to share and change the works.  By contrast,
the GNU General Public License is intended to guarantee your freedom to
share and change all versions of a program--to make sure it remains free
software for all its users.  We, the Free Software Foundation, use the
GNU General Public License for most of our software; it applies also to
any other work released this way by its authors.  You can apply it to
your programs, too.

  When we speak of free software, we are referring to freedom, not
price.  Our General Public Licenses are designed to make sure that you
have the freedom to distribute copies of free software (and charge for
them if you wish), that you receive source code or can get it if you
want it, that you can change the software or use pieces of it in new
free programs, and that you know you can do these things.

  To protect your rights, we need to prevent others from denying you
these rights or asking you to surrender the rights.  Therefore, you have
certain responsibilities if you distribute copies of the software, or if
you modify it: responsibilities to respect the freedom of others.

  For example, if you distribute copies of such a program, whether
gratis or for a fee, you must pass on to the recipients the same
freedoms that you received.  You must make sure that they, too, receive
or can get the source code.  And you must show them these terms so they
know their rights.

  Developers that use the GNU GPL protect your rights with two steps:
(1) assert copyright on the software, and (2) offer you this License
giving you legal permission to copy, distribute and/or modify it.

  For the developers' and authors' protection, the GPL clearly explains
that there is no warranty for this free software.  For both users' and
authors' sake, the GPL requires that modified versions be marked as
changed, so that their problems will not be attributed erroneously to
authors of previous versions.

  Some devices are designed to deny users access to install or run
modified versions of the software inside them, although the manufacturer
can do so.  This is fundamentally incompatible with the aim of
protecting users' freedom to change the software.  The systematic
pattern of such abuse occurs in the area of products for individuals to
use, which is precisely where it is most unacceptable.  Therefore, we
have designed this version of the GPL to prohibit the practice for those
products.  If such problems arise substantially in other domains, we
stand ready to extend this provision to those domains in future versions
of the GPL, as needed to protect the freedom of users.

  Finally, every program is threatened constantly by software patents.
States should not allow patents to restrict development and use of
software on general-purpose computers, but in those that do, we wish to
avoid the special danger that patents applied to a free program could
make it effectively proprietary.  To prevent this, the GPL assures that
patents cannot be used to render the program non-free.

  The precise terms and conditions for copying, distribution and
modification follow.

                       TERMS AND CONDITIONS

  0. Definitions.

  "This License" refers to version 3 of the GNU General Public License.

  "Copyright" also means copyright-like laws that apply to other kinds of
works, such as semiconductor masks.

  "The Program" refers to any copyrightable work licensed under this
License.  Each licensee is addressed as "you".  "Licensees" and
"recipients" may be individuals or organizations.

  To "modify" a work means to copy from or adapt all or part of the work
in a fashion requiring copyright permission, other than the making of an
exact copy.  The resulting work is called a "modified version" of the
earlier work or a work "based on" the earlier work.

  A "covered work" means either the unmodified Program or a work based
on the Program.

  To "propagate" a work means to do anything with it that, without
permission, would make you directly or secondarily liable for
infringement under applicable copyright law, except executing it on a
computer or modifying a private copy.  Propagation includes copying,
distribution (with or without modification), making available to the
public, and in some countries other activities as well.

  To "convey" a work means any kind of propagation that enables other
parties to make or receive copies.  Mere interaction with a user through
a computer network, with no transfer of a copy, is not conveying.

  An interactive user interface displays "Appropriate Legal Notices"
to the extent that it includes a convenient and prominently visible
feature that (1) displays an appropriate copyright notice, and (2)
tells the user that there is no warranty for the work (except to the
extent that warranties are provided), that licensees may convey the
work under this License, and how to view a copy of this License.  If
the interface presents a list of user commands or options, such as a
menu, a prominent item in the list meets this criterion.

  1. Source Code.

  The "source code" for a work means the preferred form of the work
for making modifications to it.  "Object code" means any non-source
form of a work.

  A "Standard Interface" means an interface that either is an official
standard defined by a recognized standards body, or, in the case of
interfaces specified for a particular programming language, one that
is widely used among developers working in that language.

  The "System Libraries" of an executable work include anything, other
than the work as a whole, that (a) is included in the normal form of
packaging a Major Component, but which is not part of that Major
Component, and (b) serves only to enable use of the work with that
Major Component, or to implement a Standard Interface for which an
implementation is available to the public in source code form.  A
"Major Component", in this context, means a major essential component
(kernel, window system, and so on) of the specific operating system
(if any) on which the executable work runs, or a compiler used to
produce the work, or an object code interpreter used to run it.

  The "Corresponding Source" for a work in object code form means all
the source code needed to generate, install, and (for an executable
work) run the object code and to modify the work, including scripts to
control those activities.  However, it does not include the work's
System Libraries, or general-purpose tools or generally available free
programs which are used unmodified in performing those activities but
which are not part of the work.  For example, Corresponding Source
includes interface definition files associated with source files for
the work, and the source code for shared libraries and dynamically
linked subprograms that the work is specifically designed to require,
such as by intimate data communication or control flow between those
subprograms and other parts of the work.

  The Corresponding Source need not include anything that users
can regenerate automatically from other parts of the Corresponding
Source.

  The Corresponding Source for a work in source code form is that
same work.

  2. Basic Permissions.

  All rights granted under this License are granted for the term of
copyright on the Program, and are irrevocable provided the stated
conditions are met.  This License explicitly affirms your unlimited
permission to run the unmodified Program.  The output from running a
covered work is covered by this License only if the output, given its
content, constitutes a covered work.  This License acknowledges your
rights of fair use or other equivalent, as provided by copyright law.

  You may make, run and propagate covered works that you do not
convey, without conditions so long as your license otherwise remains
in force.  You may convey covered works to others for the sole purpose
of having them make modifications exclusively for you, or provide you
with facilities for running those works, provided that you comply with
the terms of this License in conveying all material for which you do
not control copyright.  Those thus making or running the covered works
for you must do so exclusively on your behalf, under your direction
and control, on terms that prohibit them from making any copies of
your copyrighted material outside their relationship with you.

  Conveying under any other circumstances is permitted solely under
the conditions stated below.  Sublicensing is not allowed; section 10
makes it unnecessary.

  3. Protecting Users' Legal Rights From Anti-Circumvention Law.

  No covered work shall be deemed part of an effective technological
measure under any applicable law fulfilling obligations under article
11 of the WIPO copyright treaty adopted on 20 December 1996, or
similar laws prohibiting or restricting circumvention of such
measures.

  When you convey a covered work, you waive any legal power to forbid
circumvention of technological measures to the extent such circumvention
is effected by exercising rights under this License with respect to
the covered work, and you disclaim any intention to limit operation or
modification of the work as a means of enforcing, against the work's
users, your or third parties' legal rights to forbid circumvention of
technological measures.

  4. Conveying Verbatim Copies.

  You may convey verbatim copies of the Program's source code as you
receive it, in any medium, provided that you conspicuously and
appropriately publish on each copy an appropriate copyright notice;
keep intact all notices stating that this License and any
non-permissive terms added in accord with section 7 apply to the code;
keep intact all notices of the absence of any warranty; and give all
recipients a copy of this License along with the Program.

  You may charge any price or no price for each copy that you convey,
and you may offer support or warranty protection for a fee.

  5. Conveying Modified Source Versions.

  You may convey a work based on the Program, or the modifications to
produce it from the Program, in the form of source code under the
terms of section 4, provided that you also meet all of these conditions:

    a) The work must carry prominent notices stating that you modified
    it, and giving a relevant date.

    b) The work must carry prominent notices stating that it is
    released under this License and any conditions added under section
    7.  This requirement modifies the requirement in section 4 to
    "keep intact all notices".

    c) You must license the entire work, as a whole, under this
    License to anyone who comes into possession of a copy.  This
    License will therefore apply, along with any applicable section 7
    additional terms, to the whole of the work, and all its parts,
    regardless of how they are packaged.  This License gives no
    permission to license the work in any other way, but it does not
    invalidate such permission if you have separately received it.

    d) If the work has interactive user interfaces, each must display
    Appropriate Legal Notices; however, if the Program has interactive
    interfaces that do not display Appropriate Legal Notices, your
    work need not make them do so.

  A compilation of a covered work with other separate and independent
works, which are not by their nature extensions of the covered work,
and which are not combined with it such as to form a larger program,
in or on a volume of a storage or distribution medium, is called an
"aggregate" if the compilation and its resulting copyright are not
used to limit the access or legal rights of the compilation's users
beyond what the individual works permit.  Inclusion of a covered work
in an aggregate does not cause this License to apply to the other
parts of the aggregate.

  6. Conveying Non-Source Forms.

  You may convey a covered work in object code form under the terms
of sections 4 and 5, provided that you also convey the
machine-readable Corresponding Source under the terms of this License,
in one of these ways:

    a) Convey the object code in, or embodied in, a physical product
    (including a physical distribution medium), accompanied by the
    Corresponding Source fixed on a durable physical medium
    customarily used for software interchange.

    b) Convey the object code in, or embodied in, a physical product
    (including a physical distribution medium), accompanied by a
    written offer, valid for at least three years and valid for as
    long as you offer spare parts or customer support for that product
    model, to give anyone who possesses the object code either (1) a
    copy of the Corresponding Source for all the software in the
    product that is covered by this License, on a durable physical
    medium customarily used for software interchange, for a price no
    more than your reasonable cost of physically performing this
    conveying of source, or (2) access to copy the
    Corresponding Source from a network server at no charge.

    c) Convey individual copies of the object code with a copy of the
    written offer to provide the Corresponding Source.  This
    alternative is allowed only occasionally and noncommercially, and
    only if you received the object code with such an offer, in accord
    with subsection 6b.

    d) Convey the object code by offering access from a designated
    place (gratis or for a charge), and offer equivalent access to the
    Corresponding Source in the same way through the same place at no
    further charge.  You need not require recipients to copy the
    Corresponding Source along with the object code.  If the place to
    copy the object code is a network server, the Corresponding Source
    may be on a different server (operated by you or a third party)
    that supports equivalent copying facilities, provided you maintain
    clear directions next to the object code saying where to find the
    Corresponding Source.  Regardless of what server hosts the
    Corresponding Source, you remain obligated to ensure that it is
    available for as long as needed to satisfy these requirements.

    e) Convey the object code using peer-to-peer transmission, provided
    you inform other peers where the object code and Corresponding
    Source of the work are being offered to the general public at no
    charge under subsection 6d.

  A separable portion of the object code, whose source code is excluded
from the Corresponding Source as a System Library, need not be
included in conveying the object code work.

  A "User Product" is either (1) a "consumer product", which means any
tangible personal property which is normally used for personal, family,
or household purposes, or (2) anything designed or sold for incorporation
into a dwelling.  In determining whether a product is a consumer product,
doubtful cases shall be resolved in favor of coverage.  For a particular
product received by a particular user, "normally used" refers to a
typical or common use of that class of product, regardless of the status
of the particular user or of the way in which the particular user
actually uses, or expects or is expected to use, the product.  A product
is a consumer product regardless of whether the product has substantial
commercial, industrial or non-consumer uses, unless such uses represent
the only significant mode of use of the product.

  "Installation Information" for a User Product means any methods,
procedures, authorization keys, or other information required to install
and execute modified versions of a covered work in that User Product from
a modified version of its Corresponding Source.  The information must
suffice to ensure that the continued functioning of the modified object
code is in no case prevented or interfered with solely because
modification has been made.

  If you convey an object code work under this section in, or with, or
specifically for use in, a User Product, and the conveying occurs as
part of a transaction in which the right of possession and use of the
User Product is transferred to the recipient in perpetuity or for a
fixed term (regardless of how the transaction is characterized), the
Corresponding Source conveyed under this section must be accompanied
by the Installation Information.  But this requirement does not apply
if neither you nor any third party retains the ability to install
modified object code on the User Product (for example, the work has
been installed in ROM).

  The requirement to provide Installation Information does not include a
requirement to continue to provide support service, warranty, or updates
for a work that has been modified or installed by the recipient, or for
the User Product in which it has been modified or installed.  Access to a
network may be denied when the modification itself materially and
adversely affects the operation of the network or violates the rules and
protocols for communication across the network.

  Corresponding Source conveyed, and Installation Information provided,
in accord with this section must be in a format that is publicly
documented (and with an implementation available to the public in
source code form), and must require no special password or key for
unpacking, reading or copying.

  7. Additional Terms.

  "Additional permissions" are terms that supplement the terms of this
License by making exceptions from one or more of its conditions.
Additional permissions that are applicable to the entire Program shall
be treated as though they were included in this License, to the extent
that they are valid under applicable law.  If additional permissions
apply only to part of the Program, that part may be used separately
under those permissions, but the entire Program remains governed by
this License without regard to the additional permissions.

  When you convey a copy of a covered work, you may at your option
remove any additional permissions from that copy, or from any part of
it.  (Additional permissions may be written to require their own
removal in certain cases when you modify the work.)  You may place
additional permissions on material, added by you to a covered work,
for which you have or can give appropriate copyright permission.

  Notwithstanding any other provision of this License, for material you
add to a covered work, you may (if authorized by the copyright holders of
that material) supplement the terms of this License with terms:

    a) Disclaiming warranty or limiting liability differently from the
    terms of sections 15 and 16 of this License; or

    b) Requiring preservation of specified reasonable legal notices or
    author attributions in that material or in the Appropriate Legal
    Notices displayed by works containing it; or

    c) Prohibiting misrepresentation of the origin of that material, or
    requiring that modified versions of such material be marked in
    reasonable ways as different from the original version; or

    d) Limiting the use for publicity purposes of names of licensors or
    authors of the material; or

    e) Declining to grant rights under trademark law for use of some
    trade names, trademarks, or service marks; or

    f) Requiring indemnification of licensors and authors of that
    material by anyone who conveys the material (or modified versions of
    it) with contractual assumptions of liability to the recipient, for
    any liability that these contractual assumptions directly impose on
    those licensors and authors.

  All other non-permissive additional terms are considered "further
restrictions" within the meaning of section 10.  If the Program as you
received it, or any part of it, contains a notice stating that it is
governed by this License along with a term that is a further
restriction, you may remove that term.  If a license document contains
a further restriction but permits relicensing or conveying under this
License, you may add to a covered work material governed by the terms
of that license document, provided that the further restriction does
not survive such relicensing or conveying.

  If you add terms to a covered work in accord with this section, you
must place, in the relevant source files, a statement of the
additional terms that apply to those files, or a notice indicating
where to find the applicable terms.

  Additional terms, permissive or non-permissive, may be stated in the
form of a separately written license, or stated as exceptions;
the above requirements apply either way.

  8. Termination.

  You may not propagate or modify a covered work except as expressly
provided under this License.  Any attempt otherwise to propagate or
modify it is void, and will automatically terminate your rights under
this License (including any patent licenses granted under the third
paragraph of section 11).

  However, if you cease all violation of this License, then your
license from a particular copyright holder is reinstated (a)
provisionally, unless and until the copyright holder explicitly and
finally terminates your license, and (b) permanently, if the copyright
holder fails to notify you of the violation by some reasonable means
prior to 60 days after the cessation.

  Moreover, your license from a particular copyright holder is
reinstated permanently if the copyright holder notifies you of the
violation by some reasonable means, this is the first time you have
received notice of violation of this License (for any work) from that
copyright holder, and you cure the violation prior to 30 days after
your receipt of the notice.

  Termination of your rights under this section does not terminate the
licenses of parties who have received copies or rights from you under
this License.  If your rights have been terminated and not permanently
reinstated, you do not qualify to receive new licenses for the same
material under section 10.

  9. Acceptance Not Required for Having Copies.

  You are not required to accept this License in order to receive or
run a copy of the Program.  Ancillary propagation of a covered work
occurring solely as a consequence of using peer-to-peer transmission
to receive a copy likewise does not require acceptance.  However,
nothing other than this License grants you permission to propagate or
modify any covered work.  These actions infringe copyright if you do
not accept this License.  Therefore, by modifying or propagating a
covered work, you indicate your acceptance of this License to do so.

  10. Automatic Licensing of Downstream Recipients.

  Each time you convey a covered work, the recipient automatically
receives a license from the original licensors, to run, modify and
propagate that work, subject to this License.  You are not responsible
for enforcing compliance by third parties with this License.

  An "entity transaction" is a transaction transferring control of an
organization, or substantially all assets of one, or subdividing an
organization, or merging organizations.  If propagation of a covered
work results from an entity transaction, each party to that
transaction who receives a copy of the work also receives whatever
licenses to the work the party's predecessor in interest had or could
give under the previous paragraph, plus a right to possession of the
Corresponding Source of the work from the predecessor in interest, if
the predecessor has it or can get it with reasonable efforts.

  You may not impose any further restrictions on the exercise of the
rights granted or affirmed under this License.  For example, you may
not impose a license fee, royalty, or other charge for exercise of
rights granted under this License, and you may not initiate litigation
(including a cross-claim or counterclaim in a lawsuit) alleging that
any patent claim is infringed by making, using, selling, offering for
sale, or importing the Program or any portion of it.

  11. Patents.

  A "contributor" is a copyright holder who authorizes use under this
License of the Program or a work on which the Program is based.  The
work thus licensed is called the contributor's "contributor version".

  A contributor's "essential patent claims" are all patent claims
owned or controlled by the contributor, whether already acquired or
hereafter acquired, that would be infringed by some manner, permitted
by this License, of making, using, or selling its contributor version,
but do not include claims that would be infringed only as a
consequence of further modification of the contributor version.  For
purposes of this definition, "control" includes the right to grant
patent sublicenses in a manner consistent with the requirements of
this License.

  Each contributor grants you a non-exclusive, worldwide, royalty-free
patent license under the contributor's essential patent claims, to
make, use, sell, offer for sale, import and otherwise run, modify and
propagate the contents of its contributor version.

  In the following three paragraphs, a "patent license" is any express
agreement or commitment, however denominated, not to enforce a patent
(such as an express permission to practice a patent or covenant not to
sue for patent infringement).  To "grant" such a patent license to a
party means to make such an agreement or commitment not to enforce a
patent against the party.

  If you convey a covered work, knowingly relying on a patent license,
and the Corresponding Source of the work is not available for anyone
to copy, free of charge and under the terms of this License, through a
publicly available network server or other readily accessible means,
then you must either (1) cause the Corresponding Source to be so
available, or (2) arrange to deprive yourself of the benefit of the
patent license for this particular work, or (3) arrange, in a manner
consistent with the requirements of this License, to extend the patent
license to downstream recipients.  "Knowingly relying" means you have
actual knowledge that, but for the patent license, your conveying the
covered work in a country, or your recipient's use of the covered work
in a country, would infringe one or more identifiable patents in that
country that you have reason to believe are valid.

  If, pursuant to or in connection with a single transaction or
arrangement, you convey, or propagate by procuring conveyance of, a
covered work, and grant a patent license to some of the parties
receiving the covered work authorizing them to use, propagate, modify
or convey a specific copy of the covered work, then the patent license
you grant is automatically extended to all recipients of the covered
work and works based on it.

  A patent license is "discriminatory" if it does not include within
the scope of its coverage, prohibits the exercise of, or is
conditioned on the non-exercise of one or more of the rights that are
specifically granted under this License.  You may not convey a covered
work if you are a party to an arrangement with a third party that is
in the business of distributing software, under which you make payment
to the third party based on the extent of your activity of conveying
the work, and under which the third party grants, to any of the
parties who would receive the covered work from you, a discriminatory
patent license (a) in connection with copies of the covered work
conveyed by you (or copies made from those copies), or (b) primarily
for and in connection with specific products or compilations that
contain the covered work, unless you entered into that arrangement,
or that patent license was granted, prior to 28 March 2007.

  Nothing in this License shall be construed as excluding or limiting
any implied license or other defenses to infringement that may
otherwise be available to you under applicable patent law.

  12. No Surrender of Others' Freedom.

  If conditions are imposed on you (whether by court order, agreement or
otherwise) that contradict the conditions of this License, they do not
excuse you from the conditions of this License.  If you cannot convey a
covered work so as to satisfy simultaneously your obligations under this
License and any other pertinent obligations, then as a consequence you may
not convey it at all.  For example, if you agree to terms that obligate you
to collect a royalty for further conveying from those to whom you convey
the Program, the only way you could satisfy both those terms and this
License would be to refrain entirely from conveying the Program.

  13. Use with the GNU Affero General Public License.

  Notwithstanding any other provision of this License, you have
permission to link or combine any covered work with a work licensed
under version 3 of the GNU Affero General Public License into a single
combined work, and to convey the resulting work.  The terms of this
License will continue to apply to the part which is the covered work,
but the special requirements of the GNU Affero General Public License,
section 13, concerning interaction through a network will apply to the
combination as such.

  14. Revised Versions of this License.

  The Free Software Foundation may publish revised and/or new versions of
the GNU General Public License from time to time.  Such new versions will
be similar in spirit to the present version, but may differ in detail to
address new problems or concerns.

  Each version is given a distinguishing version number.  If the
Program specifies that a certain numbered version of the GNU General
Public License "or any later version" applies to it, you have the
option of following the terms and conditions either of that numbered
version or of any later version published by the Free Software
Foundation.  If the Program does not specify a version number of the
GNU General Public License, you may choose any version ever published
by the Free Software Foundation.

  If the Program specifies that a proxy can decide which future
versions of the GNU General Public License can be used, that proxy's
public statement of acceptance of a version permanently authorizes you
to choose that version for the Program.

  Later license versions may give you additional or different
permissions.  However, no additional obligations are imposed on any
author or copyright holder as a result of your choosing to follow a
later version.

  15. Disclaimer of Warranty.

  THERE IS NO WARRANTY FOR THE PROGRAM, TO THE EXTENT PERMITTED BY
APPLICABLE LAW.  EXCEPT WHEN OTHERWISE STATED IN WRITING THE COPYRIGHT
HOLDERS AND/OR OTHER PARTIES PROVIDE THE PROGRAM "AS IS" WITHOUT WARRANTY
OF ANY KIND, EITHER EXPRESSED OR IMPLIED, INCLUDING, BUT NOT LIMITED TO,
THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
PURPOSE.  THE ENTIRE RISK AS TO THE QUALITY AND PERFORMANCE OF THE PROGRAM
IS WITH YOU.  SHOULD THE PROGRAM PROVE DEFECTIVE, YOU ASSUME THE COST OF
ALL NECESSARY SERVICING, REPAIR OR CORRECTION.

  16. Limitation of Liability.

  IN NO EVENT UNLESS REQUIRED BY APPLICABLE LAW OR AGREED TO IN WRITING
WILL ANY COPYRIGHT HOLDER, OR ANY OTHER PARTY WHO MODIFIES AND/OR CONVEYS
THE PROGRAM AS PERMITTED ABOVE, BE LIABLE TO YOU FOR DAMAGES, INCLUDING ANY
GENERAL, SPECIAL, INCIDENTAL OR CONSEQUENTIAL DAMAGES ARISING OUT OF THE
USE OR INABILITY TO USE THE PROGRAM (INCLUDING BUT NOT LIMITED TO LOSS OF
DATA OR DATA BEING RENDERED INACCURATE OR LOSSES SUSTAINED BY YOU OR THIRD
PARTIES OR A FAILURE OF THE PROGRAM TO OPERATE WITH ANY OTHER PROGRAMS),
EVEN IF SUCH HOLDER OR OTHER PARTY HAS BEEN ADVISED OF THE POSSIBILITY OF
SUCH DAMAGES.

  17. Interpretation of Sections 15 and 16.

  If the disclaimer of warranty and limitation of liability provided
above cannot be given local legal effect according to their terms,
reviewing courts shall apply local law that most closely approximates
an absolute waiver of all civil liability in connection with the
Program, unless a warranty or assumption of liability accompanies a
copy of the Program in return for a fee.

                     END OF TERMS AND CONDITIONS

            How to Apply These Terms to Your New Programs

  If you develop a new program, and you want it to be of the greatest
possible use to the public, the best way to achieve this is to make it
free software which everyone can redistribute and change under these terms.

  To do so, attach the following notices to the program.  It is safest
to attach them to the start of each source file to most effectively
state the exclusion of warranty; and each file should have at least
the "copyright" line and a pointer to where the full notice is found.

    <one line to give the program's name and a brief idea of what it does.>
    Copyright (C) <year>  <name of author>

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <https://www.gnu.org/licenses/>.

Also add information on how to contact you by electronic and paper mail.

  If the program does terminal interaction, make it output a short
notice like this when it starts in an interactive mode:

    <program>  Copyright (C) <year>  <name of author>
    This program comes with ABSOLUTELY NO WARRANTY; for details type `show w'.
    This is free software, and you are welcome to redistribute it
    under certain conditions; type `show c' for details.

The hypothetical commands `show w' and `show c' should show the appropriate
parts of the General Public License.  Of course, your program's commands
might be different; for a GUI interface, you would use an "about box".

  You should also get your employer (if you work as a programmer) or school,
if any, to sign a "copyright disclaimer" for the program, if necessary.
For more information on this, and how to apply and follow the GNU GPL, see
<https://www.gnu.org/licenses/>.

  The GNU General Public License does not permit incorporating your program
into proprietary programs.  If your program is a subroutine library, you
may consider it more useful to permit linking proprietary applications with
the library.  If this is what you want to do, use the GNU Lesser General
Public License instead of this License.  But first, please read
<https://www.gnu.org/licenses/why-not-lgpl.html>.

"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true", help="Run embedded headless checks")
    parser.add_argument("--benchmark", action="store_true", help="Measure simulation only, not iPhone FPS")
    args = parser.parse_args()
    if args.self_test:
        self_test()
    elif args.benchmark:
        print(json.dumps(benchmark(), ensure_ascii=False, indent=2))
    else:
        run_pythonista()


if __name__ == "__main__":
    main()
