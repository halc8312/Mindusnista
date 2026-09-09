# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Mindustry-derived portions: Copyright (c) Anuken and contributors.
# Python adaptation and original integration: 2026-09-09.
# Modified work: Pythonista development port, NOT an official Mindustry release.
# License: GNU GPL version 3. This program comes WITHOUT ANY WARRANTY.
# See LICENSE and NOTICE.md in the accompanying source package.
"""Pure conveyor kernels; extracted unchanged from the 0.1.2-dev baseline."""
from __future__ import annotations
from typing import List, Tuple


ITEM_SPACE = 0.4             # Conveyor.java, v159.7, line 24
BELT_CAPACITY = 3           # Conveyor.java, v159.7, line 25


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def approach(value: float, target: float, amount: float) -> float:
    return value + clamp(target - value, -amount, amount)


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
