#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""P-04 standalone dynamic state experiment; not game logic or a save codec.

Python 3.10, standard library plus optional already installed NumPy.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import importlib
import json
import math
from pathlib import Path
import platform
import random
import statistics
import struct
import sys
import time

DEFAULT_COUNT = 20000
DEFAULT_SEED = 159704
STATE_FORMAT = "mindusnista-p04-synthetic-state"
COLUMNS = ["id", "x", "y", "vx", "vy", "target_x", "target_y", "threshold2"]
RESULT_COLUMNS = tuple(["ids"] + COLUMNS[1:] + ["distances", "mask"])
FRAME_COMPONENTS = ("command_validate_seconds", "command_apply_seconds", "state_update_seconds",
                    "compute_sync_seconds", "result_apply_seconds", "runner_overhead_seconds")


def valid_id(value):
    return type(value) is int and -(2 ** 63) <= value < 2 ** 63


def validate_row(row):
    if (type(row) is not list or len(row) != 8 or not valid_id(row[0])
            or any(type(v) is not float or not math.isfinite(v) for v in row[1:])
            or row[7] < 0):
        raise ValueError("row requires an int64 ID and seven finite floats, threshold2 >= 0")


def make_rows(count, seed=DEFAULT_SEED, first_id=0):
    rng = random.Random(seed)
    return [[first_id + i, rng.randint(-8192, 8192) / 16, rng.randint(-8192, 8192) / 16,
             rng.choice((-7, -3, 1, 5)) / 128, rng.choice((-5, -1, 3, 7)) / 128,
             rng.randint(-8192, 8192) / 16, rng.randint(-8192, 8192) / 16,
             rng.randint(0, 8388608) / 32] for i in range(count)]


def initial_snapshot(rows, capacity=None):
    identities = set()
    for row in rows:
        validate_row(row)
        if row[0] in identities:
            raise ValueError("duplicate initial ID")
        identities.add(row[0])
    capacity = len(rows) if capacity is None else capacity
    if type(capacity) is not int or capacity < len(rows):
        raise ValueError("capacity must hold every initial row")
    return {"format": STATE_FORMAT, "schema": 1, "columns": list(COLUMNS), "tick": 0,
            "capacity": capacity, "next_id": max(max(identities, default=-1), -1) + 1,
            "order": [row[0] for row in rows],
            "free_slots": list(range(capacity - 1, len(rows) - 1, -1)),
            "slots": [list(row) for row in rows] + [None] * (capacity - len(rows))}


def validate_commands(commands, mapping, next_id):
    """Validate the complete ordered batch before mutation; only touched IDs copied."""
    if type(commands) is not list:
        raise ValueError("commands must be a list")
    changed = {}
    for command in commands:
        if type(command) is not dict:
            raise ValueError("command must be an object")
        op = command.get("op")
        fields = {"spawn": {"op", "row"}, "delete": {"op", "id"},
                  "velocity": {"op", "id", "vx", "vy"},
                  "target": {"op", "id", "x", "y", "threshold2"}}
        if type(op) is not str or op not in fields or set(command) != fields[op]:
            raise ValueError("unknown command or fields")
        if op == "spawn":
            validate_row(command["row"])
            identity = command["row"][0]
            if identity < next_id or changed.get(identity, identity in mapping):
                raise ValueError("duplicate, reused or nonmonotonic spawn ID")
            next_id = identity + 1
            changed[identity] = True
        else:
            identity = command["id"]
            if not valid_id(identity) or not changed.get(identity, identity in mapping):
                raise ValueError("missing or stale command ID")
            if op == "delete":
                changed[identity] = False
            else:
                for key, value in command.items():
                    if key not in ("op", "id") and (type(value) is not float or not math.isfinite(value)):
                        raise ValueError("command values must be finite floats")
                if op == "target" and command["threshold2"] < 0:
                    raise ValueError("negative squared threshold")


def make_workload(rows, ticks, seed=DEFAULT_SEED):
    """Shared prebuilt commands; generation is reported separately from backend time."""
    active = [row[0] for row in rows]
    next_id = max(max(active, default=-1), -1) + 1
    batches = []
    for tick in range(1, ticks + 1):
        batch = []
        delete_count = 0 if tick == 1 else min(len(active), max(1, len(rows) // 64))
        removed, active = active[:delete_count], active[delete_count:]
        batch.extend({"op": "delete", "id": identity} for identity in removed)
        # Tick 1 necessarily grows a full initial buffer. Later ticks reuse slots,
        # including a nonempty free list at even-tick checkpoints for ordinary N.
        spawn_count = max(1, len(rows) // 32) if tick == 1 else (
            max(0, delete_count - 1) if tick % 2 == 0 else delete_count + 1)
        for row in make_rows(spawn_count, seed + tick, next_id):
            batch.append({"op": "spawn", "row": row})
            active.append(row[0])
        next_id += spawn_count
        for identity in active[::max(1, len(active) // max(1, len(rows) // 64))][:max(1, len(rows) // 64)]:
            batch.append({"op": "velocity", "id": identity,
                          "vx": ((tick % 7) + 1) / 128, "vy": -((tick % 5) + 1) / 128})
            batch.append({"op": "target", "id": identity, "x": (tick + identity % 31) / 8,
                          "y": (tick - identity % 17) / 8, "threshold2": (tick % 13) / 4})
        batches.append(batch)
    return batches


class ScalarOracle:
    """Independent dictionary model; no runner mutation/update implementation reused."""
    def __init__(self, rows, capacity=None):
        state = initial_snapshot(rows, capacity)
        self.rows = {row[0]: list(row) for row in rows}
        self.locations = {row[0]: slot for slot, row in enumerate(rows)}
        self.capacity, self.free = state["capacity"], state["free_slots"]
        self.next_id, self.tick = state["next_id"], 0

    def step(self, commands):
        for c in commands:
            if c["op"] == "spawn":
                identity = c["row"][0]
                if identity < self.next_id or identity in self.rows:
                    raise ValueError("oracle rejected reused ID")
                if not self.free:
                    old = self.capacity
                    self.capacity = max(1, old * 2)
                    self.free.extend(reversed(range(old, self.capacity)))
                self.locations[identity] = self.free.pop()
                self.rows[identity] = list(c["row"])
                self.next_id = identity + 1
            elif c["op"] == "delete":
                del self.rows[c["id"]]
                self.free.append(self.locations.pop(c["id"]))
            elif c["op"] == "velocity":
                self.rows[c["id"]][3:5] = [c["vx"], c["vy"]]
            elif c["op"] == "target":
                self.rows[c["id"]][5:8] = [c["x"], c["y"], c["threshold2"]]
            else:
                raise ValueError("oracle unknown command")
        self.tick += 1
        output = {key: [] for key in RESULT_COLUMNS}
        output["tick"] = self.tick
        for identity, row in self.rows.items():
            row[1], row[2] = row[1] + row[3], row[2] + row[4]
            dx, dy = row[1] - row[5], row[2] - row[6]
            distance = dx * dx + dy * dy
            for key, value in zip(RESULT_COLUMNS, row + [distance, distance <= row[7]]):
                output[key].append(value)
        return output

    def export_state(self):
        slots = [None] * self.capacity
        for identity, row in self.rows.items():
            slots[self.locations[identity]] = list(row)
        return {"format": STATE_FORMAT, "schema": 1, "columns": list(COLUMNS), "tick": self.tick,
                "capacity": self.capacity, "next_id": self.next_id, "order": list(self.rows),
                "free_slots": list(self.free), "slots": slots}


class PythonDynamicRunner:
    def __init__(self, rows=None, state=None):
        started = time.perf_counter()
        state = initial_snapshot(rows) if state is None else state
        self.tick, self.next_id = state["tick"], state["next_id"]
        self.capacity, self.free = state["capacity"], list(state["free_slots"])
        self.slots = [None if row is None else list(row) for row in state["slots"]]
        locations = {row[0]: i for i, row in enumerate(self.slots) if row is not None}
        self.mapping = {identity: locations[identity] for identity in state["order"]}
        self.distances, self.mask = [0.0] * self.capacity, [False] * self.capacity
        self.closed, self.failed = False, False
        self.initial_conversion_seconds = time.perf_counter() - started

    def _grow(self):
        old = self.capacity
        self.capacity = max(1, old * 2)
        self.slots.extend([None] * (self.capacity - old))
        self.distances.extend([0.0] * (self.capacity - old))
        self.mask.extend([False] * (self.capacity - old))
        self.free.extend(range(self.capacity - 1, old - 1, -1))

    def _write(self, slot, row):
        self.slots[slot] = list(row)

    def _delete(self, slot):
        self.slots[slot] = None

    def _change(self, slot, start, values):
        self.slots[slot][start:start + len(values)] = values

    def _apply(self, commands):
        growth_seconds, growth_events, reused = 0.0, 0, 0
        for c in commands:
            op = c["op"]
            if op == "spawn":
                if not self.free:
                    began = time.perf_counter()
                    self._grow()
                    growth_seconds += time.perf_counter() - began
                    growth_events += 1
                else:
                    reused += 1
                slot = self.free.pop()
                row = c["row"]
                self._write(slot, row)
                self.mapping[row[0]] = slot
                self.next_id = row[0] + 1
            else:
                slot = self.mapping[c["id"]]
                if op == "delete":
                    self._delete(slot)
                    del self.mapping[c["id"]]
                    self.free.append(slot)
                elif op == "velocity":
                    self._change(slot, 3, [c["vx"], c["vy"]])
                else:
                    self._change(slot, 5, [c["x"], c["y"], c["threshold2"]])
        return {"growth_seconds": growth_seconds, "growth_events": growth_events,
                "free_slot_allocations": reused, "capacity": self.capacity, "active_rows": len(self.mapping)}

    def _update(self):
        for row in self.slots:
            if row is not None:
                row[1] += row[3]
                row[2] += row[4]

    def _compute(self):
        for slot, row in enumerate(self.slots):
            if row is not None:
                dx, dy = row[1] - row[5], row[2] - row[6]
                squared = dx * dx + dy * dy
                self.distances[slot], self.mask[slot] = squared, squared <= row[7]

    def _result(self):
        output = {key: [] for key in RESULT_COLUMNS}
        output["tick"] = self.tick
        for slot in self.mapping.values():
            for key, value in zip(RESULT_COLUMNS, self.slots[slot] + [self.distances[slot], self.mask[slot]]):
                output[key].append(value)
        return output

    def step(self, commands):
        if self.closed or self.failed:
            raise RuntimeError("runner is closed or failed")
        start = time.perf_counter()
        validate_commands(commands, self.mapping, self.next_id)
        validated = time.perf_counter()
        try:
            stats = self._apply(commands)
            applied = time.perf_counter()
            self._update()
            self.tick += 1
            updated = time.perf_counter()
            self._compute()
            computed = time.perf_counter()
            output = self._result()
            reflected = time.perf_counter()
        except Exception:
            self.failed = True
            raise
        return output, {"command_validate_seconds": validated - start,
                        "command_apply_seconds": applied - validated,
                        "state_update_seconds": updated - applied,
                        "compute_sync_seconds": computed - updated,
                        "result_apply_seconds": reflected - computed}, stats

    def export_state(self):
        if self.failed:
            raise RuntimeError("failed runner cannot checkpoint partial state")
        return {"format": STATE_FORMAT, "schema": 1, "columns": list(COLUMNS), "tick": self.tick,
                "capacity": self.capacity, "next_id": self.next_id, "order": list(self.mapping),
                "free_slots": list(self.free),
                "slots": [None if row is None else list(row) for row in self.slots]}

    def close(self):
        self.closed = True


class NumpyDynamicRunner(PythonDynamicRunner):
    def __init__(self, np, rows=None, workers=1, state=None):
        if type(workers) is not int or workers < 1:
            raise ValueError("positive worker count required")
        started = time.perf_counter()
        state = initial_snapshot(rows) if state is None else state
        self.np, self.workers = np, workers
        self.tick, self.next_id = state["tick"], state["next_id"]
        self.capacity, self.free = state["capacity"], list(state["free_slots"])
        locations = {row[0]: i for i, row in enumerate(state["slots"]) if row is not None}
        self.mapping = {identity: locations[identity] for identity in state["order"]}
        self.ids = np.zeros(self.capacity, dtype=np.int64)
        self.state = np.zeros((self.capacity, 7), dtype=np.float64)
        for slot, row in enumerate(state["slots"]):
            if row is not None:
                self._write(slot, row)
        self._buffers()
        self.closed, self.failed = False, False
        self.initial_conversion_seconds = time.perf_counter() - started
        self.executor = ThreadPoolExecutor(max_workers=workers)

    def _buffers(self):
        np = self.np
        self.dx, self.dy = np.empty(self.capacity, dtype=np.float64), np.empty(self.capacity, dtype=np.float64)
        self.mask = np.empty(self.capacity, dtype=np.bool_)
        self.ranges = [(self.capacity * i // self.workers, self.capacity * (i + 1) // self.workers)
                       for i in range(self.workers) if self.capacity * i // self.workers < self.capacity * (i + 1) // self.workers]

    def _grow(self):
        # step has waited for every previous writer before any mutation/growth.
        old = self.capacity
        capacity = max(1, old * 2)
        ids = self.np.zeros(capacity, dtype=self.np.int64)
        state = self.np.zeros((capacity, 7), dtype=self.np.float64)
        ids[:old], state[:old] = self.ids, self.state
        self.ids, self.state, self.capacity = ids, state, capacity
        self._buffers()
        self.free.extend(range(capacity - 1, old - 1, -1))

    def _write(self, slot, row):
        self.ids[slot], self.state[slot] = row[0], row[1:]

    def _delete(self, slot):
        self.ids[slot], self.state[slot] = 0, 0.0

    def _change(self, slot, start, values):
        self.state[slot, start - 1:start - 1 + len(values)] = values

    def _update(self):
        # Capacity scan intentionally includes zeroed free slots. No active row
        # is dropped; extra work and capacity are included in measurements.
        self.np.add(self.state[:, 0], self.state[:, 2], out=self.state[:, 0])
        self.np.add(self.state[:, 1], self.state[:, 3], out=self.state[:, 1])

    def _chunk(self, start, end):
        state, dx, dy, mask = self.state[start:end], self.dx[start:end], self.dy[start:end], self.mask[start:end]
        self.np.subtract(state[:, 0], state[:, 4], out=dx)
        self.np.subtract(state[:, 1], state[:, 5], out=dy)
        self.np.multiply(dx, dx, out=dx)
        self.np.multiply(dy, dy, out=dy)
        self.np.add(dx, dy, out=dx)
        self.np.less_equal(dx, state[:, 6], out=mask)

    def _compute(self):
        futures, first_error = [], None
        try:
            for start, end in self.ranges:
                futures.append(self.executor.submit(self._chunk, start, end))
        except Exception as exc:
            first_error = exc
        for future in futures:
            try:
                future.result()
            except Exception as exc:
                if first_error is None:
                    first_error = exc
        if first_error is not None:
            raise first_error

    def _result(self):
        indices = self.np.fromiter(self.mapping.values(), dtype=self.np.intp, count=len(self.mapping))
        output = {"tick": self.tick, "ids": self.ids[indices].tolist(),
                  "distances": self.dx[indices].tolist(), "mask": self.mask[indices].tolist()}
        for index, key in enumerate(COLUMNS[1:]):
            output[key] = self.state[indices, index].tolist()
        return output

    def export_state(self):
        if self.failed:
            raise RuntimeError("failed runner cannot checkpoint partial state")
        slots = [None] * self.capacity
        for identity, slot in self.mapping.items():
            slots[slot] = [int(self.ids[slot])] + self.state[slot].tolist()
        return {"format": STATE_FORMAT, "schema": 1, "columns": list(COLUMNS), "tick": self.tick,
                "capacity": self.capacity, "next_id": self.next_id, "order": list(self.mapping),
                "free_slots": list(self.free), "slots": slots}

    def close(self):
        try:
            self.executor.shutdown(wait=True)
        finally:
            self.closed = True


def encode_state(state):
    return json.dumps(state, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("utf-8")


def decode_state(payload):
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result
    state = json.loads(payload, object_pairs_hook=unique_object)
    fields = {"format", "schema", "columns", "tick", "capacity", "next_id", "order", "free_slots", "slots"}
    if (type(state) is not dict or set(state) != fields or state["format"] != STATE_FORMAT
            or type(state["schema"]) is not int or state["schema"] != 1 or state["columns"] != COLUMNS
            or any(type(state[k]) is not int for k in ("tick", "capacity", "next_id"))
            or state["tick"] < 0 or state["capacity"] < 0 or not 0 <= state["next_id"] <= 2 ** 63
            or any(type(state[k]) is not list for k in ("slots", "order", "free_slots"))
            or len(state["slots"]) != state["capacity"]):
        raise ValueError("invalid synthetic snapshot header")
    identities, free = set(), set()
    for slot, row in enumerate(state["slots"]):
        if row is None:
            free.add(slot)
        else:
            validate_row(row)
            if row[0] in identities or row[0] >= state["next_id"]:
                raise ValueError("duplicate ID or invalid next_id")
            identities.add(row[0])
    if (any(not valid_id(i) for i in state["order"]) or len(set(state["order"])) != len(state["order"])
            or set(state["order"]) != identities
            or any(type(i) is not int for i in state["free_slots"])
            or len(set(state["free_slots"])) != len(state["free_slots"])
            or set(state["free_slots"]) != free):
        raise ValueError("invalid active order, mapping or free list")
    return state


def compare_results(expected, actual):
    if type(actual) is not dict or set(actual) != set(RESULT_COLUMNS) | {"tick"}:
        return {"ok": False, "reason": "result_shape"}
    if type(actual["tick"]) is not int or actual["tick"] != expected["tick"]:
        return {"ok": False, "reason": "tick_mismatch"}
    count = len(expected["ids"])
    for key in RESULT_COLUMNS:
        if type(actual[key]) is not list or len(actual[key]) != count:
            return {"ok": False, "reason": "column_shape", "column": key}
        wanted_type = int if key == "ids" else bool if key == "mask" else float
        for index, (wanted, got) in enumerate(zip(expected[key], actual[key])):
            if (type(got) is not wanted_type or got != wanted
                    or wanted_type is float and not math.isfinite(got)):
                return {"ok": False, "reason": "value_mismatch", "column": key,
                        "index": index, "expected": repr(wanted), "actual": repr(got)}
    return {"ok": True, "checked_rows": count, "numeric_rule": "exact_float64",
            "identity_rule": "exact_integer", "mask_rule": "exact_boolean"}


def result_digest(result):
    digest = hashlib.sha256(struct.pack("!Q", result["tick"]))
    for values in zip(*(result[key] for key in RESULT_COLUMNS)):
        digest.update(struct.pack("!qdddddddd?", *values))
    return digest.hexdigest()


def actual_digest(result):
    try:
        return result_digest(result)
    except (KeyError, TypeError, ValueError, struct.error, OverflowError):
        return None


def timing_summary(samples):
    if not samples:
        return None
    ordered = sorted(samples)
    return {"samples_seconds": samples, "count": len(samples), "p50_seconds": statistics.median(samples),
            "p95_seconds": ordered[math.ceil(0.95 * len(samples)) - 1], "max_seconds": ordered[-1],
            "p95_method": "nearest_rank"}


def measured_step(runner, commands):
    started = time.perf_counter()
    result, sample, stats = runner.step(commands)
    total = time.perf_counter() - started
    sample["runner_overhead_seconds"] = total - sum(sample.values())
    sample["total_seconds"] = total
    sample["mutation"] = stats
    sample["command_count"] = len(commands)
    return result, sample


def measure_frames(runner, rows, batches, warmups, repeats):
    reference = ScalarOracle(rows)
    samples, actual_digests, expected_digests = [], [], []
    checked, checked_rows, first_failure, error = 0, 0, None, None
    planned = 1 + warmups + repeats
    for tick in range(1, planned + 1):
        try:
            expected = reference.step(batches[tick - 1])
            actual, sample = measured_step(runner, batches[tick - 1])
            sample.update({"tick": tick, "phase": "first" if tick == 1 else
                           "warmup" if tick <= warmups + 1 else "steady"})
            comparison = compare_results(expected, actual)
            wanted_digest, got_digest = result_digest(expected), actual_digest(actual)
            samples.append(sample)
            expected_digests.append(wanted_digest)
            actual_digests.append(got_digest)
            if comparison["ok"]:
                checked += 1
                checked_rows += len(expected["ids"])
            elif first_failure is None:
                first_failure = dict(comparison, tick=tick)
        except Exception as exc:
            error = type(exc).__name__ + ": " + str(exc)
            first_failure = first_failure or {"ok": False, "reason": "exception", "tick": tick}
            break
    steady = [s for s in samples if s["phase"] == "steady"]
    return {"status": "error" if error else "mismatch" if first_failure else "correct", "reason": error,
            "frame_samples": samples, "steady": timing_summary([s["total_seconds"] for s in steady]),
            "steady_components": {key: timing_summary([s[key] for s in steady]) for key in FRAME_COMPONENTS},
            "verification": {"planned_runs": planned, "completed_runs": len(samples), "verified_runs": checked,
                             "checked_rows": checked_rows, "first_failure": first_failure,
                             "actual_frame_digests_sha256": actual_digests,
                             "expected_frame_digests_sha256": expected_digests}}


def measure_checkpoint(runner, factory, reference, resume_batches):
    restored = None
    record = {"status": "error", "resume_samples": [], "resume_ticks": len(resume_batches),
              "verified_resume_ticks": 0, "first_failure": None}
    try:
        started = time.perf_counter()
        state = runner.export_state()
        exported = time.perf_counter()
        payload = encode_state(state)
        encoded = time.perf_counter()
        decoded = decode_state(payload)
        parsed = time.perf_counter()
        restored = factory(state=decoded)
        loaded = time.perf_counter()
        record.update({"state_export_seconds": exported - started, "json_encode_seconds": encoded - exported,
                       "json_decode_validate_seconds": parsed - encoded, "state_restore_seconds": loaded - parsed,
                       "total_seconds": loaded - started, "bytes": len(payload),
                       "snapshot_sha256": hashlib.sha256(payload).hexdigest(),
                       "snapshot_matches_reference": payload == encode_state(reference.export_state()),
                       "restored_snapshot_matches": restored.export_state() == state})
        if not record["snapshot_matches_reference"] or not record["restored_snapshot_matches"]:
            record["first_failure"] = {"reason": "snapshot_or_restore_mismatch"}
        for batch in resume_batches:
            expected = reference.step(batch)
            actual, sample = measured_step(restored, batch)
            comparison = compare_results(expected, actual)
            sample.update({"tick": expected["tick"], "comparison": comparison,
                           "expected_digest_sha256": result_digest(expected), "actual_digest_sha256": actual_digest(actual)})
            record["resume_samples"].append(sample)
            if comparison["ok"]:
                record["verified_resume_ticks"] += 1
            elif record["first_failure"] is None:
                record["first_failure"] = dict(comparison, tick=expected["tick"])
        record["final_snapshot_matches_reference"] = restored.export_state() == reference.export_state()
        if not record["final_snapshot_matches_reference"]:
            record["first_failure"] = record["first_failure"] or {"reason": "resumed_internal_state_mismatch"}
        record["status"] = "mismatch" if record["first_failure"] else "correct"
    except Exception as exc:
        record.update({"status": "error", "reason": type(exc).__name__ + ": " + str(exc)})
    finally:
        if restored is not None:
            try:
                restored.close()
            except Exception as exc:
                record.update({"status": "error", "cleanup_error": type(exc).__name__ + ": " + str(exc)})
    return record


def environment_info():
    info = {"python_version": sys.version, "implementation": platform.python_implementation(),
            "platform": platform.platform(), "machine": platform.machine(),
            "pythonista": {"status": "not_detected"}}
    if sys.platform == "ios" or "Pythonista" in sys.executable:
        try:
            objc = importlib.import_module("objc_util")
            bundle = objc.ObjCClass("NSBundle").mainBundle()
            device = objc.ObjCClass("UIDevice").currentDevice()
            info["pythonista"] = {"status": "reported_by_app",
                                   "version": str(bundle.objectForInfoDictionaryKey_("CFBundleShortVersionString")),
                                   "build": str(bundle.objectForInfoDictionaryKey_("CFBundleVersion")),
                                   "ios_version": str(device.systemVersion())}
        except Exception as exc:
            info["pythonista"] = {"status": "metadata_unavailable", "reason": type(exc).__name__}
    return info


def source_info():
    try:
        return {"sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), "status": "read"}
    except (OSError, NameError) as exc:
        return {"sha256": None, "status": "unavailable", "reason": type(exc).__name__}


def run_probe(count=DEFAULT_COUNT, seed=DEFAULT_SEED, warmups=2, repeats=7, use_numpy=True):
    if (any(type(v) is not int for v in (count, seed, warmups, repeats))
            or count < 0 or warmups < 0 or repeats < 1):
        raise ValueError("integer count/warmups >= 0 and repeats >= 1 required")
    began = time.perf_counter()
    rows = make_rows(count, seed)
    dataset_seconds = time.perf_counter() - began
    tick_count = 1 + warmups + repeats
    began = time.perf_counter()
    batches = make_workload(rows, tick_count + 3, seed)
    command_generation_seconds = time.perf_counter() - began
    imported = time.perf_counter()
    np, numpy_error, numpy_reason = None, False, "disabled_by_argument"
    if use_numpy:
        try:
            np = importlib.import_module("numpy")
        except ModuleNotFoundError as exc:
            numpy_reason = type(exc).__name__ + ": " + str(exc)
            numpy_error = exc.name != "numpy"
        except Exception as exc:
            numpy_reason, numpy_error = type(exc).__name__ + ": " + str(exc), True
    import_seconds = time.perf_counter() - imported if use_numpy else 0.0
    report = {"probe": "Mindusnista P-04 dynamic synthetic state", "probe_schema": 1,
              "created_at_utc": datetime.now(timezone.utc).isoformat(), "source": source_info(),
              "environment": environment_info(),
              "workload": {"initial_rows": count, "seed": seed, "warmups": warmups,
                           "steady_repeats": repeats, "columns": COLUMNS, "dataset_seconds": dataset_seconds,
                           "command_generation_seconds": command_generation_seconds,
                           "command_batches_sha256": hashlib.sha256(encode_state(batches)).hexdigest(),
                           "command_counts": [{op: sum(c["op"] == op for c in batch)
                                               for op in ("spawn", "delete", "velocity", "target")} for batch in batches],
                           "dtype": "float64 + int64 IDs", "output_every_tick": list(RESULT_COLUMNS),
                           "order": "surviving insertion order; fresh ID appends, LIFO free slots, capacity doubles",
                           "id_rule": "int64, each new ID >= next_id, IDs never reused, exhausted range raises",
                           "snapshot_cadence": "once after measured ticks, restore then replay 3 command batches"},
              "measurement": {"clock": "time.perf_counter",
                              "timed": "prepare; full command validation/application including growth; update; compute/sync; all fields as Python lists; JSON checkpoint/restore",
                              "untimed": "dataset/command generation (separate), scalar oracle, comparisons/digests, report, shutdown",
                              "backend_order": ["python", "numpy 1", "numpy 2", "numpy 4"],
                              "growth_seconds_rule": "inside command_apply_seconds, never add twice",
                              "numeric_buffer_estimate_rule": "NumPy capacity * 81 bytes: 7 float64 state + int64 ID + 2 float64 work + bool",
                              "numeric_buffer_estimate_excludes": "mapping/free lists, Python input/output/oracle/JSON, index temporaries, growth overlap, executor/runtime",
                              "peak_process_memory_bytes": None, "peak_process_memory_status": "not_measured"},
              "numpy": {"status": "available" if np is not None else "error" if numpy_error else "not_run",
                        "version": str(np.__version__) if np is not None else None,
                        "import_seconds": import_seconds, "reason": None if np is not None else numpy_reason},
              "limitations": ["different workload/boundary from P-03; cross-probe ratios are not same-work speedups",
                              "synthetic float64 state and commands, not original float32 parity or game integration",
                              "NumPy scans allocated capacity including zero free slots; Python scans capacity and skips None slots",
                              "snapshot is not game schema 1 or msav; no disk I/O is timed",
                              "fixed order, few repeats, interleaved oracle; workers do not prove simultaneous CPU execution",
                              "no device FPS, thermal, sustained load, peak memory, or game/effects reduction"], "backends": []}
    for name, workers in (("python", 1), ("numpy", 1), ("numpy", 2), ("numpy", 4)):
        item = {"name": name, "workers": workers}
        if name == "numpy" and np is None:
            item.update({"status": "error" if numpy_error else "not_run", "reason": numpy_reason})
            report["backends"].append(item)
            continue
        factory = (lambda rows=None, state=None: PythonDynamicRunner(rows, state)) if name == "python" else (
            lambda rows=None, state=None, workers=workers: NumpyDynamicRunner(np, rows, workers, state))
        runner = None
        try:
            preparing = time.perf_counter()
            runner = factory(rows)
            item["prepare_seconds"] = time.perf_counter() - preparing
            item["initial_conversion_seconds"] = runner.initial_conversion_seconds
            item.update(measure_frames(runner, rows, batches, warmups, repeats))
            samples = item["frame_samples"]
            if samples:
                frames_total = sum(s["total_seconds"] for s in samples)
                item["first_with_prepare_seconds"] = item["prepare_seconds"] + samples[0]["total_seconds"]
                item["amortized_seconds_per_tick"] = (item["prepare_seconds"] + frames_total) / len(samples)
                item["amortized_with_import_seconds_per_tick"] = (
                    item["prepare_seconds"] + frames_total + (import_seconds if name == "numpy" else 0)) / len(samples)
                item["final_capacity"] = runner.capacity
                item["numeric_buffer_estimate_bytes"] = runner.capacity * 81 if name == "numpy" else None
            if item["status"] == "correct":
                reference = ScalarOracle(rows)
                for batch in batches[:tick_count]:
                    reference.step(batch)
                checkpoint = measure_checkpoint(runner, factory, reference, batches[tick_count:])
                item["checkpoint"] = checkpoint
                if checkpoint["status"] != "correct":
                    item["status"] = checkpoint["status"]
                    item["reason"] = checkpoint.get("reason") or checkpoint.get("cleanup_error") or "checkpoint mismatch"
                if "total_seconds" in checkpoint:
                    item["amortized_with_checkpoint_seconds_per_tick"] = (
                        item["prepare_seconds"] + frames_total + checkpoint["total_seconds"]) / len(samples)
        except Exception as exc:
            item.update({"status": "error", "reason": type(exc).__name__ + ": " + str(exc)})
        finally:
            if runner is not None:
                try:
                    runner.close()
                except Exception as exc:
                    item.update({"status": "error", "cleanup_error": type(exc).__name__ + ": " + str(exc)})
                    item["reason"] = item.get("reason") or item["cleanup_error"]
        baseline = report["backends"][0] if report["backends"] else item
        if name == "numpy" and item["status"] == baseline["status"] == "correct":
            item["python_p50_ratio"] = baseline["steady"]["p50_seconds"] / item["steady"]["p50_seconds"]
        report["backends"].append(item)
    report["status"] = ("failed" if any(i["status"] in ("error", "mismatch") for i in report["backends"])
                        else "partial" if np is None else "correct")
    return report


def japanese_summary(report):
    lines = ["P-04 動的状態比較: 初期 {:,}件、結果={}（独立モデル・実機未判定）".format(
        report["workload"]["initial_rows"], report["status"])]
    for item in report["backends"]:
        label = "{} / {}ワーカー".format(item["name"], item["workers"])
        if item["status"] in ("not_run", "error"):
            lines.append("{}: {} ({})".format(label, item["status"], item.get("reason") or item.get("cleanup_error")))
        else:
            steady = item.get("steady")
            timing = "{:.3f} ms / p95 {:.3f} ms".format(steady["p50_seconds"] * 1000,
                                                      steady["p95_seconds"] * 1000) if steady else "未完了"
            checkpoint = item.get("checkpoint")
            checkpoint_text = "{:.3f} ms ({})".format(checkpoint["total_seconds"] * 1000,
                                                   checkpoint["status"]) if checkpoint and "total_seconds" in checkpoint else "未実行"
            lines.append("{}: {}、中央値 {}、保存復元 {}".format(label, item["status"], timing, checkpoint_text))
    lines.append("P-03と別の仕事です。ゲーム導入・原作保存共有・実ピークメモリ・実機性能は未達／未測定。")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Pythonista向け独立した動的状態比較。ゲーム保存は扱いません。")
    parser.add_argument("--count", type=int, default=DEFAULT_COUNT)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--warmups", type=int, default=2)
    parser.add_argument("--repeats", type=int, default=7)
    parser.add_argument("--no-numpy", action="store_true")
    parser.add_argument("--output", help="新規JSON出力。既存ファイルは上書きしない")
    args = parser.parse_args(argv)
    if args.count < 0 or args.warmups < 0 or args.repeats < 1:
        parser.error("count/warmupsは0以上、repeatsは1以上が必要です")
    output = None
    try:
        if args.output:
            output = open(args.output, "x", encoding="utf-8")
        report = run_probe(args.count, args.seed, args.warmups, args.repeats, not args.no_numpy)
        serialized = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        if output is not None:
            output.write(serialized)
            output.flush()
            closing, output = output, None
            closing.close()
        else:
            sys.stdout.write(serialized)
        print(japanese_summary(report), file=sys.stderr)
        if args.output:
            print("JSON保存先: " + args.output, file=sys.stderr)
        return 1 if report["status"] == "failed" else 0
    except (OSError, ValueError) as exc:
        print("比較器エラー: " + str(exc), file=sys.stderr)
        return 2
    finally:
        if output is not None:
            try:
                output.close()
            except OSError:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
