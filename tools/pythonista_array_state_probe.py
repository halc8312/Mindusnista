#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""P-03 standalone persistent-state experiment, not a game or game-save codec.

Python 3.10; standard library plus an optional, already installed NumPy.
All backends update all positions and expose all results on every tick.
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
DEFAULT_SEED = 159703
STATE_FORMAT = "mindusnista-p03-synthetic-state"
COLUMNS = ["id", "x", "y", "vx", "vy", "target_x", "target_y", "threshold2"]
RESULT_COLUMNS = ("ids", "x", "y", "distances", "mask")
FRAME_COMPONENTS = ("state_update_seconds", "compute_sync_seconds",
                    "result_apply_seconds", "runner_overhead_seconds")


def partition_ranges(count, workers):
    if count < 0 or workers < 1:
        raise ValueError("invalid partition")
    return [(count * i // workers, count * (i + 1) // workers)
            for i in range(workers) if count * i // workers < count * (i + 1) // workers]


def make_rows(count, seed=DEFAULT_SEED):
    """Binary fractions, nonzero velocity in both axes, stable integer IDs."""
    rng = random.Random(seed)
    return [[i, rng.randint(-8192, 8192) / 16, rng.randint(-8192, 8192) / 16,
             rng.choice((-7, -3, 1, 5)) / 128, rng.choice((-5, -1, 3, 7)) / 128,
             rng.randint(-8192, 8192) / 16, rng.randint(-8192, 8192) / 16,
             rng.randint(0, 8388608) / 32] for i in range(count)]


def reference_tick(rows, tick):
    """Independent scalar oracle; the returned full lists own their values."""
    result = {key: [] for key in RESULT_COLUMNS}
    result["tick"] = tick
    for row in rows:
        row[1] = row[1] + row[3]
        row[2] = row[2] + row[4]
        dx, dy = row[1] - row[5], row[2] - row[6]
        distance = dx * dx + dy * dy
        for key, value in zip(RESULT_COLUMNS,
                              (row[0], row[1], row[2], distance, distance <= row[7])):
            result[key].append(value)
    return result


class PythonStateRunner:
    def __init__(self, rows, tick=0):
        started = time.perf_counter()
        self.rows = [list(row) for row in rows]
        self.initial_conversion_seconds = time.perf_counter() - started
        self.tick = tick

    def step(self):
        start = time.perf_counter()
        for row in self.rows:
            row[1] += row[3]
            row[2] += row[4]
        self.tick += 1
        updated = time.perf_counter()
        distances, mask = [], []
        for row in self.rows:
            dx, dy = row[1] - row[5], row[2] - row[6]
            squared = dx * dx + dy * dy
            distances.append(squared)
            mask.append(squared <= row[7])
        computed = time.perf_counter()
        output = {"tick": self.tick, "ids": [r[0] for r in self.rows],
                  "x": [r[1] for r in self.rows], "y": [r[2] for r in self.rows],
                  "distances": distances, "mask": mask}
        applied = time.perf_counter()
        return output, {"state_update_seconds": updated - start,
                        "compute_sync_seconds": computed - updated,
                        "result_apply_seconds": applied - computed}

    def export_state(self):
        return {"format": STATE_FORMAT, "schema": 1, "columns": list(COLUMNS),
                "tick": self.tick, "rows": [list(row) for row in self.rows]}

    def close(self):
        pass


class NumpyStateRunner:
    """Persistent arrays; update before dispatch; nonoverlapping worker outputs."""
    def __init__(self, np, rows, workers, tick=0):
        if workers < 1:
            raise ValueError("workers must be positive")
        self.np, self.tick = np, tick
        converted = time.perf_counter()
        self.ids = np.array([row[0] for row in rows], dtype=np.int64)
        self.state = np.array([row[1:] for row in rows], dtype=np.float64).reshape((-1, 7))
        self.initial_conversion_seconds = time.perf_counter() - converted
        self.dx, self.dy = np.empty(len(rows), dtype=np.float64), np.empty(len(rows), dtype=np.float64)
        self.mask = np.empty(len(rows), dtype=np.bool_)
        self.ranges = partition_ranges(len(rows), workers)
        self.chunks = [(self.state[a:b], self.dx[a:b], self.dy[a:b], self.mask[a:b])
                       for a, b in self.ranges]
        self.executor = ThreadPoolExecutor(max_workers=workers)

    def _chunk(self, state, dx, dy, mask):
        np = self.np
        np.subtract(state[:, 0], state[:, 4], out=dx)
        np.subtract(state[:, 1], state[:, 5], out=dy)
        np.multiply(dx, dx, out=dx)
        np.multiply(dy, dy, out=dy)
        np.add(dx, dy, out=dx)
        np.less_equal(dx, state[:, 6], out=mask)

    def step(self):
        start = time.perf_counter()
        self.np.add(self.state[:, 0], self.state[:, 2], out=self.state[:, 0])
        self.np.add(self.state[:, 1], self.state[:, 3], out=self.state[:, 1])
        self.tick += 1
        updated = time.perf_counter()
        futures, first_error = [], None
        try:
            for chunk in self.chunks:
                futures.append(self.executor.submit(self._chunk, *chunk))
        except Exception as exc:
            first_error = exc
        # Wait for every writer even when one raises, before a caller can retry
        # or export state. No input update overlaps a previous worker.
        for future in futures:
            try:
                future.result()
            except Exception as exc:
                if first_error is None:
                    first_error = exc
        if first_error is not None:
            raise first_error
        computed = time.perf_counter()
        output = {"tick": self.tick, "ids": self.ids.tolist(),
                  "x": self.state[:, 0].tolist(), "y": self.state[:, 1].tolist(),
                  "distances": self.dx.tolist(), "mask": self.mask.tolist()}
        applied = time.perf_counter()
        return output, {"state_update_seconds": updated - start,
                        "compute_sync_seconds": computed - updated,
                        "result_apply_seconds": applied - computed}

    def export_state(self):
        return {"format": STATE_FORMAT, "schema": 1, "columns": list(COLUMNS),
                "tick": self.tick,
                "rows": [[identity] + values for identity, values in
                         zip(self.ids.tolist(), self.state.tolist())]}

    def close(self):
        self.executor.shutdown(wait=True)


def compare_results(expected, actual):
    if not isinstance(actual, dict) or set(actual) != set(RESULT_COLUMNS) | {"tick"}:
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
                    or (wanted_type is float and not math.isfinite(got))):
                return {"ok": False, "reason": "value_mismatch", "column": key,
                        "index": index, "expected": repr(wanted), "actual": repr(got)}
    return {"ok": True, "checked_rows": count, "numeric_rule": "exact_float64",
            "identity_rule": "exact_integer", "mask_rule": "exact_boolean"}


def result_digest(result):
    digest = hashlib.sha256(struct.pack("!Q", result["tick"]))
    for values in zip(*(result[key] for key in RESULT_COLUMNS)):
        digest.update(struct.pack("!qddd?", *values))
    return digest.hexdigest()


def encode_state(state):
    return json.dumps(state, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("utf-8")


def decode_state(payload):
    state = json.loads(payload)
    if (not isinstance(state, dict) or set(state) != {"format", "schema", "columns", "tick", "rows"}
            or state["format"] != STATE_FORMAT or type(state["schema"]) is not int
            or state["schema"] != 1 or state["columns"] != COLUMNS
            or type(state["tick"]) is not int or state["tick"] < 0
            or type(state["rows"]) is not list or not state["rows"]):
        raise ValueError("invalid synthetic state header")
    identities = set()
    for row in state["rows"]:
        if (type(row) is not list or len(row) != 8 or type(row[0]) is not int
                or not -(2 ** 63) <= row[0] < 2 ** 63 or row[0] in identities):
            raise ValueError("invalid synthetic state row or identity")
        identities.add(row[0])
        if any(type(value) is not float or not math.isfinite(value) for value in row[1:]):
            raise ValueError("synthetic state values must be finite float64 numbers")
        if row[7] < 0:
            raise ValueError("negative squared threshold")
    return state


def timing_summary(samples):
    if not samples:
        return None
    ordered = sorted(samples)
    return {"samples_seconds": samples, "count": len(samples),
            "p50_seconds": statistics.median(samples),
            "p95_seconds": ordered[math.ceil(0.95 * len(samples)) - 1],
            "max_seconds": ordered[-1], "p95_method": "nearest_rank"}


def measured_step(runner):
    started = time.perf_counter()
    result, sample = runner.step()
    ended = time.perf_counter()
    total = ended - started
    sample["runner_overhead_seconds"] = total - sum(sample.values())
    sample["total_seconds"] = total
    return result, sample


def measure_frames(runner, rows, warmups, repeats):
    reference = [list(row) for row in rows]
    samples, actual_digests, expected_digests = [], [], []
    checked, first_failure, error = 0, None, None
    planned = 1 + warmups + repeats
    for tick in range(1, planned + 1):
        expected = reference_tick(reference, tick)
        try:
            actual, sample = measured_step(runner)
            sample.update({"tick": tick, "phase": "first" if tick == 1 else
                           "warmup" if tick <= warmups + 1 else "steady"})
            comparison = compare_results(expected, actual)
            expected_digest = result_digest(expected)
            # Digests are independent evidence, never a copy of the oracle.
            try:
                actual_digest = result_digest(actual)
            except (KeyError, TypeError, ValueError, struct.error, OverflowError):
                actual_digest = None
            # Commit one fully examined record. A comparison exception must
            # not leave sample counts ahead of either digest sequence.
            samples.append(sample)
            expected_digests.append(expected_digest)
            actual_digests.append(actual_digest)
            if comparison["ok"]:
                checked += 1
            elif first_failure is None:
                first_failure = dict(comparison, tick=tick)
        except Exception as exc:
            error = type(exc).__name__ + ": " + str(exc)
            if first_failure is None:
                first_failure = {"ok": False, "reason": "exception", "tick": tick}
            break
    steady = [sample for sample in samples if sample["phase"] == "steady"]
    return {"status": "error" if error else "mismatch" if first_failure else "correct",
            "reason": error, "frame_samples": samples,
            "steady": timing_summary([sample["total_seconds"] for sample in steady]),
            "steady_components": {name: timing_summary([sample[name] for sample in steady])
                                  for name in FRAME_COMPONENTS},
            "verification": {"planned_runs": planned, "completed_runs": len(samples),
                             "verified_runs": checked, "checked_rows": checked * len(rows),
                             "first_failure": first_failure,
                             "actual_frame_digests_sha256": actual_digests,
                             "expected_frame_digests_sha256": expected_digests}}


def measure_checkpoint(runner, factory, expected_rows, tick, resume_ticks=3):
    """Actual common JSON encoding, decoding, validation, restoration and resume."""
    started = time.perf_counter()
    state = runner.export_state()
    exported = time.perf_counter()
    payload = encode_state(state)
    encoded = time.perf_counter()
    decoded = decode_state(payload)
    parsed = time.perf_counter()
    restored = factory(decoded["rows"], decoded["tick"])
    loaded = time.perf_counter()
    record = {"state_export_seconds": exported - started,
              "json_encode_seconds": encoded - exported,
              "json_decode_validate_seconds": parsed - encoded,
              "state_restore_seconds": loaded - parsed,
              "total_seconds": loaded - started, "bytes": len(payload),
              "snapshot_sha256": hashlib.sha256(payload).hexdigest(),
              "resume_samples": [], "resume_ticks": resume_ticks,
              "verified_resume_ticks": 0, "first_failure": None}
    reference = [list(row) for row in expected_rows]
    expected_state = {"format": STATE_FORMAT, "schema": 1, "columns": COLUMNS,
                      "tick": tick, "rows": reference}
    try:
        record["snapshot_matches_reference"] = payload == encode_state(expected_state)
        # Catch a restore that mutates state even if the next calculation masks it.
        record["restored_snapshot_matches"] = restored.export_state() == state
        if not record["snapshot_matches_reference"] or not record["restored_snapshot_matches"]:
            record["first_failure"] = {"reason": "snapshot_or_restore_mismatch"}
        for offset in range(1, resume_ticks + 1):
            expected = reference_tick(reference, tick + offset)
            actual, sample = measured_step(restored)
            comparison = compare_results(expected, actual)
            sample.update({"tick": tick + offset, "comparison": comparison,
                           "expected_digest_sha256": result_digest(expected),
                           "actual_digest_sha256": result_digest(actual)})
            record["resume_samples"].append(sample)
            if comparison["ok"]:
                record["verified_resume_ticks"] += 1
            elif record["first_failure"] is None:
                record["first_failure"] = dict(comparison, tick=tick + offset)
    finally:
        restored.close()
    record["status"] = "mismatch" if record["first_failure"] else "correct"
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
    if any(type(value) is not int for value in (count, seed, warmups, repeats)) or count < 1 or warmups < 0 or repeats < 1:
        raise ValueError("integer count/repeats >= 1 and warmups >= 0 required")
    began = time.perf_counter()
    rows = make_rows(count, seed)
    dataset_seconds = time.perf_counter() - began
    imported = time.perf_counter()
    np, numpy_error, numpy_reason = None, False, "disabled_by_argument"
    if use_numpy:
        try:
            np = importlib.import_module("numpy")
        except ModuleNotFoundError as exc:
            numpy_reason = type(exc).__name__ + ": " + str(exc)
            numpy_error = exc.name != "numpy"
        except Exception as exc:
            numpy_reason = type(exc).__name__ + ": " + str(exc)
            numpy_error = True
    import_seconds = time.perf_counter() - imported if use_numpy else 0.0
    report = {"probe": "Mindusnista P-03 persistent synthetic state", "probe_schema": 1,
              "created_at_utc": datetime.now(timezone.utc).isoformat(), "source": source_info(),
              "environment": environment_info(),
              "workload": {"rows": count, "seed": seed, "warmups": warmups,
                           "steady_repeats": repeats, "columns": COLUMNS,
                           "dataset_seconds": dataset_seconds, "dtype": "float64 + int64 IDs",
                           "formula": "x+=vx; y+=vy; dx=x-target_x; dy=y-target_y; d2=dx*dx+dy*dy; hit=d2<=threshold2",
                           "output_every_tick": ["id", "x", "y", "distance2", "hit"],
                           "snapshot_cadence": "once after all measured ticks, then restore and verify 3 ticks"},
              "measurement": {"clock": "time.perf_counter",
                              "timed": "initial ingest/allocation; per-tick state update, compute/sync and all Python result lists; one JSON checkpoint/restore",
                              "untimed": "dataset generation (separate), oracle, full comparison/digests, report generation, shutdown",
                              "backend_order": ["python", "numpy 1", "numpy 2", "numpy 4"],
                              "numeric_buffer_estimate_bytes": count * 81,
                              "numeric_buffer_estimate_rule": "7 float64 state + int64 ID + 2 float64 work + bool per row",
                              "numeric_buffer_estimate_excludes": "Python inputs/results/reference/snapshots, NumPy internal temporaries, executors, allocator and runtime",
                              "peak_process_memory_bytes": None, "peak_process_memory_status": "not_measured"},
              "numpy": {"status": "available" if np is not None else "error" if numpy_error else "not_run",
                        "version": str(np.__version__) if np is not None else None,
                        "import_seconds": import_seconds, "reason": None if np is not None else numpy_reason},
              "limitations": ["different workload and state boundary from P-02; ratios between them are not same-work speedups",
                              "synthetic float64 model, not Java float32 parity or game integration",
                              "checkpoint is not schema 1 game save or original msav; no disk I/O is timed",
                              "requested workers are not proof of simultaneous CPU execution",
                              "fixed order, sparse repeats and oracle interleaving affect timing; no sustained thermal/FPS test",
                              "no game feature, scale or effect requirement is reduced"], "backends": []}
    final_rows = [list(row) for row in rows]
    tick_count = 1 + warmups + repeats
    for tick in range(1, tick_count + 1):
        reference_tick(final_rows, tick)
    for name, workers in (("python", 1), ("numpy", 1), ("numpy", 2), ("numpy", 4)):
        item = {"name": name, "workers": workers}
        if name == "numpy" and np is None:
            item.update({"status": "error" if numpy_error else "not_run", "reason": numpy_reason})
            report["backends"].append(item)
            continue
        factory = (lambda values, tick=0: PythonStateRunner(values, tick)) if name == "python" else (
            lambda values, tick=0, workers=workers: NumpyStateRunner(np, values, workers, tick))
        runner = None
        try:
            preparing = time.perf_counter()
            runner = factory(rows)
            item["prepare_seconds"] = time.perf_counter() - preparing
            item["initial_conversion_seconds"] = runner.initial_conversion_seconds
            item.update(measure_frames(runner, rows, warmups, repeats))
            samples = item["frame_samples"]
            if samples:
                frames_total = sum(s["total_seconds"] for s in samples)
                item["first_with_prepare_seconds"] = item["prepare_seconds"] + samples[0]["total_seconds"]
                item["amortized_seconds_per_tick"] = (item["prepare_seconds"] + frames_total) / len(samples)
                item["amortized_with_import_seconds_per_tick"] = (
                    item["prepare_seconds"] + frames_total + (import_seconds if name == "numpy" else 0)) / len(samples)
            if item["status"] == "correct":
                checkpoint = measure_checkpoint(runner, factory, final_rows, tick_count)
                item["checkpoint"] = checkpoint
                if checkpoint["status"] != "correct":
                    item["status"] = checkpoint["status"]
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
                    item.setdefault("reason", item["cleanup_error"])
        baseline = report["backends"][0] if report["backends"] else item
        if name == "numpy" and item["status"] == baseline["status"] == "correct":
            item["python_p50_ratio"] = baseline["steady"]["p50_seconds"] / item["steady"]["p50_seconds"]
        report["backends"].append(item)
    report["status"] = ("failed" if any(i["status"] in ("error", "mismatch") for i in report["backends"])
                        else "partial" if np is None else "correct")
    return report


def japanese_summary(report):
    lines = ["P-03 継続状態比較: {:,}件、結果={}（独立モデル・実機未判定）".format(
        report["workload"]["rows"], report["status"])]
    for item in report["backends"]:
        label = "{} / {}ワーカー".format(item["name"], item["workers"])
        if item["status"] in ("not_run", "error"):
            lines.append("{}: {} ({})".format(label, item["status"], item.get("reason") or item.get("cleanup_error")))
        else:
            checkpoint = item.get("checkpoint")
            checkpoint_text = "{:.3f} ms ({})".format(checkpoint["total_seconds"] * 1000,
                                                   checkpoint["status"]) if checkpoint else "未実行"
            lines.append("{}: {}、中央値 {:.3f} ms / p95 {:.3f} ms、保存復元 {}".format(
                label, item["status"], item["steady"]["p50_seconds"] * 1000,
                item["steady"]["p95_seconds"] * 1000, checkpoint_text))
    lines.append("P-02と別の仕事です。ゲーム導入・原作保存共有・実ピークメモリ・実機性能は未達／未測定。")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Pythonista向け独立した継続状態比較。ゲーム保存は扱いません。")
    parser.add_argument("--count", type=int, default=DEFAULT_COUNT)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--warmups", type=int, default=2)
    parser.add_argument("--repeats", type=int, default=7)
    parser.add_argument("--no-numpy", action="store_true")
    parser.add_argument("--output", help="新規JSON出力。既存ファイルは上書きしない")
    args = parser.parse_args(argv)
    if args.count < 1 or args.warmups < 0 or args.repeats < 1:
        parser.error("count/repeatsは1以上、warmupsは0以上が必要です")
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
