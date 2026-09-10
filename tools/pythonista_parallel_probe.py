#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""P-01/P-02: standalone Python/NumPy distance comparison (Python 3.10).

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


FRAME_COMPONENTS = ("input_update_seconds", "input_conversion_seconds",
                    "compute_sync_seconds", "result_apply_seconds", "runner_overhead_seconds")


def update_frame(rows, base, frame_index):
    """Same changing Python-list input boundary for every P-02 backend.

    Offsets are binary fractions. Every row changes on every successive frame;
    targets and thresholds stay fixed. Always derive from base, not accumulated
    rounding or the previous backend's output. This is a synthetic movement.
    """
    offset_x, offset_y = frame_index / 16, frame_index / 32
    for index, (x, y, tx, ty, threshold) in enumerate(base):
        rows[index] = (x + offset_x, y - offset_y, tx, ty, threshold)


class PythonFrameRunner:
    def __init__(self, data):
        self.base = tuple(data)
        self.source_rows = list(data)
        self.initial_conversion_seconds = 0.0

    def run_frame(self, frame_index):
        t0 = time.perf_counter()
        update_frame(self.source_rows, self.base, frame_index)
        t1 = time.perf_counter()
        actual = python_kernel(self.source_rows)
        t2 = time.perf_counter()
        # Python already creates the final lists in the kernel. Its list
        # construction is included in compute_sync, not omitted from the total.
        return actual, {"input_update_seconds": t1 - t0,
                        "input_conversion_seconds": 0.0,
                        "compute_sync_seconds": t2 - t1,
                        "result_apply_seconds": 0.0, "total_seconds": t2 - t0}

    def close(self):
        pass


class NumpyFrameRunner(PythonFrameRunner):
    """Profile full list-to-list frames, with optional retained numeric arrays.

    The main thread changes input before dispatch. Workers own non-overlapping
    views and all futures finish before input changes again. Result lists are
    independent copies: later frames cannot overwrite earlier Python outputs.
    """

    def __init__(self, np, data, workers, resident):
        super().__init__(data)
        self.np, self.workers, self.resident = np, workers, resident
        self.ranges = [(start, end) for start, end in partition_ranges(len(data), workers)
                       if start != end]
        self.rows = self.dx = self.dy = self.mask = None
        self.chunks = []
        if resident:
            converted = time.perf_counter()
            self.rows = np.asarray(data, dtype=np.float64).reshape((-1, 5))
            self.initial_conversion_seconds = time.perf_counter() - converted
            self.dx = np.empty(len(data), dtype=np.float64)
            self.dy = np.empty(len(data), dtype=np.float64)
            self.mask = np.empty(len(data), dtype=np.bool_)
            self.chunks = [(self.rows[start:end], self.dx[start:end], self.dy[start:end],
                            self.mask[start:end]) for start, end in self.ranges]
        # Start only after allocation has succeeded, avoiding a leaked executor
        # if construction fails. Thread startup is lazy and inside first frame.
        self.executor = ThreadPoolExecutor(max_workers=workers)

    def _resident_chunk(self, chunk):
        rows, dx, dy, mask = chunk
        self.np.subtract(rows[:, 0], rows[:, 2], out=dx)
        self.np.subtract(rows[:, 1], rows[:, 3], out=dy)
        self.np.multiply(dx, dx, out=dx)
        self.np.multiply(dy, dy, out=dy)
        self.np.add(dx, dy, out=dx)
        self.np.less_equal(dx, rows[:, 4], out=mask)
        return dx, mask

    def run_frame(self, frame_index):
        t0 = time.perf_counter()
        update_frame(self.source_rows, self.base, frame_index)
        t1 = time.perf_counter()
        if self.resident:
            # Assignment still converts every changed Python row. Do not count
            # this as zero-copy or assume NumPy internals allocate no scratch.
            self.rows[:] = self.source_rows
        else:
            self.rows = self.np.asarray(self.source_rows, dtype=self.np.float64).reshape((-1, 5))
        t2 = time.perf_counter()
        if self.resident:
            futures = [self.executor.submit(self._resident_chunk, chunk) for chunk in self.chunks]
        else:
            futures = [self.executor.submit(NumpyRunner._chunk, self, self.rows[start:end])
                       for start, end in self.ranges]
        # No tolist until every requested computation has completed. This
        # interval measures dispatch, calculation AND synchronization together;
        # it is not a CPU-only or per-worker timing estimate.
        chunks = [future.result() for future in futures]
        t3 = time.perf_counter()
        distances, mask = [], []
        for chunk_distances, chunk_mask in chunks:
            distances.extend(chunk_distances.tolist())
            mask.extend(chunk_mask.tolist())
        t4 = time.perf_counter()
        return (distances, mask), {
            "input_update_seconds": t1 - t0, "input_conversion_seconds": t2 - t1,
            "compute_sync_seconds": t3 - t2, "result_apply_seconds": t4 - t3,
            "total_seconds": t4 - t0}

    def close(self):
        self.executor.shutdown(wait=True)


def measure_frames(runner, base, warmups, repeats):
    samples, digests = [], []
    verified = 0
    first_failure = None
    error = None
    reference_seconds = 0.0
    planned = 1 + warmups + repeats
    for index in range(planned):
        frame_index = index + 1
        started = time.perf_counter()
        reference_rows = list(base)
        update_frame(reference_rows, base, frame_index)
        expected = python_kernel(reference_rows)
        reference_seconds += time.perf_counter() - started
        expected_digest = result_digest(expected)
        try:
            called = time.perf_counter()
            actual, timings = runner.run_frame(frame_index)
            elapsed = time.perf_counter() - called
            # Include Python call/return, timing-record creation, and local
            # future/temporary cleanup outside the runner's interior markers.
            timings["runner_overhead_seconds"] = elapsed - timings["total_seconds"]
            timings["total_seconds"] = elapsed
            comparison = compare_results(expected, actual)
            sample = dict(timings, frame_index=frame_index,
                          phase="first" if index == 0 else "warmup" if index <= warmups else "steady")
            samples.append(sample)
            # One digest per recorded sample, including numeric mismatches.
            # Raised frames never acquire a digest without a sample.
            digests.append(expected_digest)
            if comparison["ok"]:
                verified += 1
            elif first_failure is None:
                first_failure = dict(comparison, frame_index=frame_index)
            del actual
        except Exception as exc:
            error = type(exc).__name__ + ": " + str(exc)
            if first_failure is None:
                first_failure = {"frame_index": frame_index, "reason": error}
            break
        finally:
            del expected, reference_rows
    item = {
        "status": "error" if error else "mismatch" if first_failure else "correct",
        "frame_samples": samples, "reference_seconds": reference_seconds,
        "verification": {"verified_runs": verified, "total_runs": len(samples),
                         "planned_runs": planned, "checked_rows": verified * len(base),
                         "first_failure": first_failure,
                         "expected_frame_digests_sha256": digests,
                         "distance_rule": "exact_float64", "mask_rule": "exact_boolean",
                         "relative_tolerance": 0.0, "absolute_tolerance": 0.0},
    }
    if error:
        item["reason"] = error
    if samples:
        item["first_run_seconds"] = samples[0]["total_seconds"]
        item["warmup_seconds"] = [s["total_seconds"] for s in samples if s["phase"] == "warmup"]
    steady = [s for s in samples if s["phase"] == "steady"]
    if steady:
        item["steady"] = timing_summary([s["total_seconds"] for s in steady])
        item["steady_components"] = {name: timing_summary([s[name] for s in steady])
                                     for name in FRAME_COMPONENTS}
    return item


def run_resident_probe(count=DEFAULT_COUNT, seed=DEFAULT_SEED, warmups=2, repeats=7,
                       use_numpy=True):
    """P-02 has its own report schema; P-01 default CLI/report stay unchanged."""
    if count < 1 or warmups < 0 or repeats < 1:
        raise ValueError("count/repeats must be positive and warmups nonnegative")
    started = time.perf_counter()
    data = make_dataset(count, seed)
    dataset_seconds = time.perf_counter() - started
    np = None
    imported = time.perf_counter()
    unavailable_reason = "disabled_by_argument"
    if use_numpy:
        try:
            np = importlib.import_module("numpy")
        except Exception as exc:
            unavailable_reason = type(exc).__name__ + ": " + str(exc)
    numpy_info = {"status": "available" if np is not None else "not_run",
                  "version": str(np.__version__) if np is not None else None,
                  "import_seconds": time.perf_counter() - imported,
                  "reason": None if np is not None else unavailable_reason}
    report = {
        "probe": "Mindusnista P-02 changing-input resident-array comparison", "probe_schema": 2,
        "created_at_utc": datetime.now(timezone.utc).isoformat(), "environment": environment_info(),
        "numpy": numpy_info,
        "workload": {"rows": count, "seed": seed, "columns": 5, "dtype": "float64",
                     "formula": "dx=x-target_x; dy=y-target_y; d2=dx*dx+dy*dy; hit=d2<=threshold2",
                     "frame_update": "x=base_x+frame/16; y=base_y-frame/32; frame starts at 1",
                     "changed_rows_per_frame": count, "warmups": warmups, "steady_repeats": repeats,
                     "dataset_seconds": dataset_seconds},
        "measurement": {
            "clock": "time.perf_counter", "input_boundary": "same changing Python list of five-value rows",
            "output_boundary": "all distance floats and all hit bools in ordered Python lists",
            "timed": "Python input update, numeric conversion, dispatch/compute/wait, tolist/ordered merge",
            "untimed": "reference generation, exact checks, metadata, report serialization and cleanup",
            "prepare_rule": "one-time source copies, retained array conversion/allocation, executor creation",
            "initial_conversion_rule": "subset of prepare_seconds, not an additional charge",
            "amortization_rule": "(prepare + all first/warm/steady frame totals) / completed frames",
            "import_rule": "NumPy import is separate; including_numpy_import amortization charges it once per candidate",
            "python_result_rule": "Python list creation is included in compute_sync; separate apply is zero",
            "interval_rule": "wall-clock intervals plus call/return overhead partition each frame; compute_sync includes scheduling and waits",
            "order": "Python; converting NumPy 1/2/4; retained NumPy 1/2/4",
            "numeric_buffer_estimate_bytes": count * 57,
            "numeric_buffer_estimate_rule": "5 input float64 + 2 work/output float64 + 1 output bool per row",
            "numeric_buffer_estimate_excludes": "Python rows/results/reference, NumPy internal scratch, futures, allocator and runtime",
            "peak_process_memory_bytes": None, "peak_process_memory_status": "not_measured",
        },
        "backends": [], "not_implemented": ["Accelerate", "Metal", "game integration"],
        "limitations": ["synthetic float64 kernel, not upstream Java float32 parity",
                        "unchanged list input/output boundaries; no zero-copy input or array-native world claim",
                        "retained arrays still convert all changed input and materialize all result lists",
                        "requested workers do not prove simultaneous CPU execution",
                        "fixed order and inter-frame correctness work can bias cache/frequency/thermal behavior",
                        "short synthetic measurement, no device FPS, thermal or peak memory evidence"],
    }
    configurations = [("python", 1, False)] + [(name, workers, resident)
                       for name, resident in (("numpy_convert", False), ("numpy_resident", True))
                       for workers in (1, 2, 4)]
    for name, workers, resident in configurations:
        item = {"name": name, "workers": workers,
                "partition_rows": [end - start for start, end in partition_ranges(count, workers)]}
        if name != "python" and np is None:
            item.update({"status": "not_run", "reason": unavailable_reason})
            report["backends"].append(item)
            continue
        runner = None
        try:
            prepared = time.perf_counter()
            runner = (PythonFrameRunner(data) if name == "python" else
                      NumpyFrameRunner(np, data, workers, resident))
            item["prepare_seconds"] = time.perf_counter() - prepared
            item["initial_conversion_seconds"] = runner.initial_conversion_seconds
            item.update(measure_frames(runner, data, warmups, repeats))
            samples = item["frame_samples"]
            if samples:
                item["first_with_prepare_seconds"] = item["prepare_seconds"] + item["first_run_seconds"]
                total = item["prepare_seconds"] + sum(s["total_seconds"] for s in samples)
                item["amortized_seconds_per_frame"] = total / len(samples)
                import_seconds = 0.0 if name == "python" else numpy_info["import_seconds"]
                item["amortized_including_numpy_import_seconds_per_frame"] = (total + import_seconds) / len(samples)
        except Exception as exc:
            item.update({"status": "error", "reason": type(exc).__name__ + ": " + str(exc)})
        finally:
            if runner is not None:
                try:
                    runner.close()
                except Exception as exc:
                    item["cleanup_error"] = type(exc).__name__ + ": " + str(exc)
                    item.setdefault("reason", item["cleanup_error"])
                    item["status"] = "error"
        baseline = report["backends"][0] if report["backends"] else item
        if name != "python" and item["status"] == baseline["status"] == "correct":
            item["python_p50_ratio"] = baseline["steady"]["p50_seconds"] / item["steady"]["p50_seconds"]
            item["faster_than_python_p50"] = item["python_p50_ratio"] > 1.0
        report["backends"].append(item)
        del runner
    report["status"] = ("failed" if any(item["status"] in ("mismatch", "error")
                                        for item in report["backends"]) else
                        "partial" if np is None else "correct")
    return report


def japanese_summary(report):
    task = "P-02 入力更新・配列保持比較" if report["probe_schema"] == 2 else "P-01 距離比較"
    lines = ["{}: {:,}件、結果={}（実機のFPS・原作互換の判定ではありません）".format(
        task, report["workload"]["rows"], report["status"])]
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
    parser.add_argument("--resident", action="store_true", help="P-02: 毎回変わる入力で都度変換と配列保持も比較")
    parser.add_argument("--output", help="新しいJSONファイルへ保存。既存ファイルは上書きしない")
    args = parser.parse_args(argv)
    if args.count < 1 or args.warmups < 0 or args.repeats < 1:
        parser.error("count/repeats は1以上、warmups は0以上が必要です")
    output = None
    try:
        # Reserve a new path BEFORE potentially costly work; never overwrite.
        if args.output:
            output = open(args.output, "x", encoding="utf-8")
        selected_probe = run_resident_probe if args.resident else run_probe
        report = selected_probe(args.count, args.seed, args.warmups, args.repeats, not args.no_numpy)
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
