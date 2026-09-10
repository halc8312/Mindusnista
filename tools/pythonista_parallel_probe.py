#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""P-01: standalone, read-only Python/NumPy distance comparison (Python 3.10).

This is a synthetic float64 kernel probe, not the game's simulation, an
upstream float32 oracle, or an iPhone performance claim. No game imports,
saves, network, or additional installed packages are required.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import importlib
import math
import platform
import random
import statistics
import struct
import sys
import time


PROBE_VERSION = 1
DEFAULT_COUNT = 20_000
DEFAULT_SEED = 1597


def partition_ranges(count, workers):
    """Non-overlapping, ordered ranges; every row is processed exactly once."""
    if count < 0 or workers < 1:
        raise ValueError("count must be nonnegative and workers must be positive")
    quotient, remainder = divmod(count, workers)
    start = 0
    ranges = []
    for index in range(workers):
        end = start + quotient + (index < remainder)
        ranges.append((start, end))
        start = end
    return ranges


def make_dataset(count, seed=DEFAULT_SEED):
    """Rows are x, y, target_x, target_y, squared threshold, all finite."""
    if count < 1:
        raise ValueError("count must be positive")
    # Equality, adjacent thresholds, repeated equal distances, zero and scale.
    edges = [
        (0.0, 0.0, 0.0, 0.0, 0.0),
        (3.0, 4.0, 0.0, 0.0, 25.0),
        (3.0, 4.0, 0.0, 0.0, math.nextafter(25.0, 0.0)),
        (3.0, 4.0, 0.0, 0.0, math.nextafter(25.0, math.inf)),
        (-3.0, -4.0, 0.0, 0.0, 25.0),
        (1e-6, 0.0, 0.0, 0.0, 1e-12),
        (1e6, 1e6, -1e6, -1e6, 8e12),
        (0.0, 0.0, 1.0, 0.0, 0.0),
    ]
    data = edges[:count]
    rng = random.Random(seed)
    while len(data) < count:
        scale = (1e-6, 1.0, 1e6)[rng.randrange(3)]
        x, y, tx, ty = (rng.uniform(-scale, scale) for _ in range(4))
        dx, dy = x - tx, y - ty
        squared = dx * dx + dy * dy
        mode = len(data) % 4
        if mode == 0:
            threshold = squared
        elif mode == 1:
            threshold = math.nextafter(squared, 0.0)
        elif mode == 2:
            threshold = math.nextafter(squared, math.inf)
        else:
            threshold = rng.uniform(0.0, 8.0) * scale * scale
        data.append((x, y, tx, ty, threshold))
    return data


def python_kernel(data):
    distances, mask = [], []
    for x, y, tx, ty, threshold in data:
        dx, dy = x - tx, y - ty
        squared = dx * dx + dy * dy
        distances.append(squared)
        mask.append(squared <= threshold)
    return distances, mask


class NumpyRunner:
    """Read-only inputs, worker-owned arrays, then ordered main-thread merge."""

    def __init__(self, np, workers):
        if workers < 1:
            raise ValueError("workers must be positive")
        self.np = np
        self.workers = workers
        self.executor = ThreadPoolExecutor(max_workers=workers)

    def _chunk(self, rows):
        dx = rows[:, 0] - rows[:, 2]
        dy = rows[:, 1] - rows[:, 3]
        # Separate multiply/add operations mirror Python's float64 expression.
        # In-place work avoids extra full-size temporaries; each worker owns it.
        self.np.multiply(dx, dx, out=dx)
        self.np.multiply(dy, dy, out=dy)
        self.np.add(dx, dy, out=dx)
        mask = dx <= rows[:, 4]
        return dx, mask

    def __call__(self, data):
        # Conversion, allocation, dispatch, waits and Python result application
        # are deliberately inside the caller's timed interval on EVERY run.
        rows = self.np.asarray(data, dtype=self.np.float64).reshape((-1, 5))
        rows.setflags(write=False)
        futures = [
            self.executor.submit(self._chunk, rows[start:end])
            for start, end in partition_ranges(len(data), self.workers)
            if start != end
        ]
        distances, mask = [], []
        for future in futures:
            chunk_distances, chunk_mask = future.result()
            distances.extend(chunk_distances.tolist())
            mask.extend(chunk_mask.tolist())
        return distances, mask

    def close(self):
        self.executor.shutdown(wait=True)


def compare_results(expected, actual):
    """Exact finite float64 values AND masks; no performance-only success."""
    lengths = [len(part) for part in expected + actual]
    if len(set(lengths)) != 1:
        return {"ok": False, "reason": "length_mismatch", "lengths": lengths}
    for index, (wanted, got, wanted_mask, got_mask) in enumerate(
            zip(expected[0], actual[0], expected[1], actual[1])):
        if not math.isfinite(got) or wanted != got or wanted_mask != got_mask:
            return {"ok": False, "reason": "value_or_mask_mismatch", "index": index,
                    "expected_distance": wanted, "actual_distance": repr(got),
                    "expected_mask": wanted_mask, "actual_mask": bool(got_mask)}
    return {"ok": True, "checked_rows": lengths[0], "distance_rule": "exact_float64",
            "mask_rule": "exact_boolean", "relative_tolerance": 0.0,
            "absolute_tolerance": 0.0}


def result_digest(result):
    digest = hashlib.sha256()
    for distance, hit in zip(*result):
        digest.update(struct.pack("!d?", distance, hit))
    return digest.hexdigest()


def timing_summary(samples):
    ordered = sorted(samples)
    return {"samples_seconds": samples, "count": len(samples),
            "p50_seconds": statistics.median(samples),
            "p95_seconds": ordered[math.ceil(0.95 * len(samples)) - 1],
            "max_seconds": ordered[-1], "p95_method": "nearest_rank"}


def measure_runner(runner, data, expected, warmups, repeats):
    timings = []
    verified = 0
    first_failure = None
    for index in range(1 + warmups + repeats):
        started = time.perf_counter()
        actual = runner(data)
        timings.append(time.perf_counter() - started)
        comparison = compare_results(expected, actual)
        if comparison["ok"]:
            verified += 1
        elif first_failure is None:
            first_failure = dict(comparison, run_index=index)
        del actual
    return {
        "status": "correct" if first_failure is None else "mismatch",
        "first_run_seconds": timings[0],
        "warmup_seconds": timings[1:1 + warmups],
        "steady": timing_summary(timings[1 + warmups:]),
        "verification": {"verified_runs": verified, "total_runs": len(timings),
                         "first_failure": first_failure},
    }


def environment_info():
    info = {"python_version": sys.version, "implementation": platform.python_implementation(),
            "os": platform.system(), "os_release": platform.release(),
            "platform": platform.platform(), "machine": platform.machine(),
            "pythonista": {"status": "not_detected", "version": None,
                           "build": None, "ios_version": None}}
    if sys.platform == "ios" or "Pythonista" in sys.executable:
        try:
            objc = importlib.import_module("objc_util")
            bundle = objc.ObjCClass("NSBundle").mainBundle()
            device = objc.ObjCClass("UIDevice").currentDevice()
            info["pythonista"] = {
                "status": "reported_by_app",
                "version": str(bundle.objectForInfoDictionaryKey_("CFBundleShortVersionString")),
                "build": str(bundle.objectForInfoDictionaryKey_("CFBundleVersion")),
                "ios_version": str(device.systemVersion()),
            }
        except Exception as exc:
            info["pythonista"]["status"] = "metadata_unavailable"
            info["pythonista"]["reason"] = type(exc).__name__
    return info


def run_probe(count=DEFAULT_COUNT, seed=DEFAULT_SEED, warmups=2, repeats=7,
              use_numpy=True):
    if count < 1 or warmups < 0 or repeats < 1:
        raise ValueError("count/repeats must be positive and warmups nonnegative")
    started = time.perf_counter()
    data = make_dataset(count, seed)
    dataset_seconds = time.perf_counter() - started
    started = time.perf_counter()
    expected = python_kernel(data)
    reference_seconds = time.perf_counter() - started
    report = {
        "probe": "Mindusnista P-01 NumPy distance comparison", "probe_schema": PROBE_VERSION,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "environment": environment_info(),
        "workload": {"rows": count, "seed": seed, "columns": 5,
                     "formula": "dx=x-target_x; dy=y-target_y; d2=dx*dx+dy*dy; hit=d2<=threshold2",
                     "dtype": "float64", "warmups": warmups, "steady_repeats": repeats,
                     "dataset_seconds": dataset_seconds,
                     "reference_seconds": reference_seconds,
                     "expected_digest_sha256": result_digest(expected),
                     "expected_hits": sum(expected[1])},
        "measurement": {
            "clock": "time.perf_counter", "timed": "input conversion through ordered Python result lists",
            "untimed": "dataset/reference generation, correctness checks, metadata and report serialization",
            "order": "Python, NumPy 1 worker, NumPy 2 workers, NumPy 4 workers",
            "numeric_buffer_estimate_bytes": count * 57,
            "numeric_buffer_estimate_rule": "5 input float64 + 2 worker float64 + 1 worker bool per row",
            "numeric_buffer_estimate_excludes": "Python input/results/reference objects, executor, allocator and runtime",
            "peak_process_memory_bytes": None,
            "peak_process_memory_status": "not_measured",
        },
        "backends": [],
        "not_implemented": ["Accelerate", "Metal", "game integration"],
        "limitations": ["synthetic float64 kernel, not upstream Java float32 parity",
                        "no FPS, thermal, long-run or full-game performance measurement",
                        "worker count is requested concurrency, not proof of simultaneous CPU execution",
                        "fixed backend order may include frequency/thermal/order bias",
                        "few repeats give a coarse p95; repeat and increase workload explicitly"],
    }
    baseline = measure_runner(python_kernel, data, expected, warmups, repeats)
    baseline.update({"name": "python", "workers": 1, "prepare_seconds": 0.0,
                     "first_with_prepare_seconds": baseline["first_run_seconds"]})
    report["backends"].append(baseline)
    np = None
    imported = time.perf_counter()
    unavailable_reason = "disabled_by_argument"
    if use_numpy:
        try:
            np = importlib.import_module("numpy")
        except Exception as exc:
            unavailable_reason = type(exc).__name__ + ": " + str(exc)
    report["numpy"] = {"status": "available" if np is not None else "not_run",
                       "version": str(np.__version__) if np is not None else None,
                       "import_seconds": time.perf_counter() - imported,
                       "reason": None if np is not None else unavailable_reason}
    for workers in (1, 2, 4):
        item = {"name": "numpy", "workers": workers,
                "partition_rows": [end - start for start, end in partition_ranges(count, workers)]}
        if np is None:
            item.update({"status": "not_run", "reason": unavailable_reason})
        else:
            runner = None
            try:
                prepared = time.perf_counter()
                runner = NumpyRunner(np, workers)
                prepare_seconds = time.perf_counter() - prepared
                item.update(measure_runner(runner, data, expected, warmups, repeats))
                item["prepare_seconds"] = prepare_seconds
                item["first_with_prepare_seconds"] = prepare_seconds + item["first_run_seconds"]
                if item["status"] == "correct" and baseline["status"] == "correct":
                    item["python_p50_ratio"] = (baseline["steady"]["p50_seconds"] /
                                                item["steady"]["p50_seconds"])
                    item["faster_than_python_p50"] = item["python_p50_ratio"] > 1.0
            except Exception as exc:
                item.update({"status": "error", "reason": type(exc).__name__ + ": " + str(exc)})
            finally:
                if runner is not None:
                    runner.close()
        report["backends"].append(item)
    report["status"] = ("failed" if any(item["status"] in ("mismatch", "error")
                                        for item in report["backends"]) else
                        "partial" if np is None else "correct")
    return report


def japanese_summary(report):
    lines = ["P-01 距離比較: {:,}件、結果={}（実機のFPS・原作互換の判定ではありません）".format(
        report["workload"]["rows"], report["status"])]
    for item in report["backends"]:
        label = "{} / {}ワーカー".format(item["name"], item["workers"])
        if item["status"] in ("not_run", "error"):
            lines.append("{}: {} ({})".format(label, "未実行" if item["status"] == "not_run" else "エラー",
                                             item["reason"]))
        else:
            lines.append("{}: {}、中央値 {:.3f} ms / p95 {:.3f} ms".format(
                label, "一致" if item["status"] == "correct" else "不一致",
                1000 * item["steady"]["p50_seconds"], 1000 * item["steady"]["p95_seconds"]))
    lines.append("Accelerate・Metal・ゲームへの導入・実使用ピークメモリは未実装／未測定。")
    return "\n".join(lines)


def main(argv=None):
    import json

    parser = argparse.ArgumentParser(description="Pythonista向け単体の距離比較器。ゲーム保存は読み書きしません。")
    parser.add_argument("--count", type=int, default=DEFAULT_COUNT, help="各回の同一総件数 (default: 20000)")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--warmups", type=int, default=2)
    parser.add_argument("--repeats", type=int, default=7)
    parser.add_argument("--no-numpy", action="store_true", help="標準ライブラリ経路だけを実行")
    parser.add_argument("--output", help="新しいJSONファイルへ保存。既存ファイルは上書きしない")
    args = parser.parse_args(argv)
    if args.count < 1 or args.warmups < 0 or args.repeats < 1:
        parser.error("count/repeats は1以上、warmups は0以上が必要です")
    output = None
    try:
        # Reserve a new path BEFORE potentially costly work; never overwrite.
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
                # A prior write/flush failure has already been reported. Do
                # not replace it with a second buffered-output cleanup error.
                pass


if __name__ == "__main__":
    raise SystemExit(main())
