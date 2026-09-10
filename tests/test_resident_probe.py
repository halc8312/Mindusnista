# SPDX-License-Identifier: GPL-3.0-only
"""Changing-input, retained-buffer probe regressions; no device benchmark."""

import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import pythonista_parallel_probe as probe


class ResidentProbeTests(unittest.TestCase):
    def test_frame_inputs_change_without_mutating_seed_rows(self):
        base = probe.make_dataset(13)
        original = list(base)
        rows = list(base)
        probe.update_frame(rows, base, 1)
        first = list(rows)
        probe.update_frame(rows, base, 2)
        self.assertEqual(base, original)
        self.assertTrue(all(a != b for a, b in zip(first, rows)))
        for row, source in zip(rows, original):
            self.assertEqual(row, (source[0] + 2 / 16, source[1] - 2 / 32,
                                   source[2], source[3], source[4]))
        self.assertNotEqual(probe.python_kernel(first), probe.python_kernel(rows))

    def test_python_frame_result_uses_current_input_and_full_lists(self):
        data = probe.make_dataset(17)
        runner = probe.PythonFrameRunner(data)
        for frame in (1, 3, 2):
            actual, timings = runner.run_frame(frame)
            expected_rows = [(x + frame / 16, y - frame / 32, tx, ty, threshold)
                             for x, y, tx, ty, threshold in data]
            self.assertEqual(actual, probe.python_kernel(expected_rows))
            self.assertTrue(all(type(part) is list for part in actual))
            self.assertEqual(timings["input_conversion_seconds"], 0)
            self.assertEqual(timings["result_apply_seconds"], 0)

    def test_timing_intervals_add_up_and_all_phases_checked(self):
        data = probe.make_dataset(11)
        runner = probe.PythonFrameRunner(data)
        item = probe.measure_frames(runner, data, 2, 3)
        self.assertEqual(item["status"], "correct")
        self.assertEqual(item["verification"]["verified_runs"], 6)
        self.assertEqual(item["verification"]["checked_rows"], 66)
        self.assertEqual(len(set(item["verification"]["expected_frame_digests_sha256"])), 6)
        self.assertEqual([f["phase"] for f in item["frame_samples"]],
                         ["first", "warmup", "warmup", "steady", "steady", "steady"])
        for frame in item["frame_samples"]:
            values = [frame[name] for name in probe.FRAME_COMPONENTS]
            self.assertTrue(all(value >= 0 for value in values))
            self.assertAlmostEqual(sum(values), frame["total_seconds"], places=12)
        self.assertEqual(item["steady"]["count"], 3)
        self.assertEqual(item["steady_components"]["input_update_seconds"]["count"], 3)

    def test_stale_result_is_detected_on_each_changed_frame(self):
        data = probe.make_dataset(9)

        class StaleRunner(probe.PythonFrameRunner):
            def run_frame(self, frame):
                return super().run_frame(1)

        item = probe.measure_frames(StaleRunner(data), data, 1, 2)
        self.assertEqual(item["status"], "mismatch")
        self.assertEqual(item["verification"]["verified_runs"], 1)
        self.assertEqual(item["verification"]["first_failure"]["frame_index"], 2)

    def test_error_retains_completed_measurements(self):
        data = probe.make_dataset(9)

        class FailedRunner(probe.PythonFrameRunner):
            def run_frame(self, frame):
                if frame == 3:
                    raise RuntimeError("worker failed")
                return super().run_frame(frame)

        item = probe.measure_frames(FailedRunner(data), data, 0, 3)
        self.assertEqual(item["status"], "error")
        self.assertEqual(len(item["frame_samples"]), 2)
        self.assertIn("worker failed", item["reason"])
        self.assertEqual(item["verification"]["first_failure"]["frame_index"], 3)
        self.assertEqual(item["verification"]["planned_runs"], 4)

    def test_worker_exception_keeps_digest_and_sample_frames_aligned(self):
        data = probe.make_dataset(9)
        for failed_frame in (1, 3):
            with self.subTest(failed_frame=failed_frame):
                class FailedRunner(probe.PythonFrameRunner):
                    def run_frame(self, frame):
                        if frame == failed_frame:
                            raise RuntimeError("worker failed")
                        return super().run_frame(frame)

                item = probe.measure_frames(FailedRunner(data), data, 0, 3)
                samples = item["frame_samples"]
                digests = item["verification"]["expected_frame_digests_sha256"]
                self.assertEqual(len(digests), len(samples))
                self.assertEqual(len(samples), failed_frame - 1)
                for sample, digest in zip(samples, digests):
                    rows = list(data)
                    probe.update_frame(rows, data, sample["frame_index"])
                    self.assertEqual(digest, probe.result_digest(probe.python_kernel(rows)))
                self.assertEqual(item["verification"]["first_failure"]["frame_index"], failed_frame)
                self.assertEqual(item["status"], "error")

    def test_comparison_exception_does_not_add_unrecorded_frame_digest(self):
        data = probe.make_dataset(9)
        comparisons = 0
        original = probe.compare_results

        def compare(expected, actual):
            nonlocal comparisons
            comparisons += 1
            if comparisons == 3:
                raise ValueError("invalid worker result")
            return original(expected, actual)

        with patch.object(probe, "compare_results", side_effect=compare):
            item = probe.measure_frames(probe.PythonFrameRunner(data), data, 0, 3)
        self.assertEqual(item["status"], "error")
        self.assertEqual(len(item["frame_samples"]), 2)
        self.assertEqual(len(item["verification"]["expected_frame_digests_sha256"]), 2)
        self.assertEqual(item["verification"]["verified_runs"], 2)
        self.assertEqual(item["verification"]["first_failure"]["frame_index"], 3)

    def test_missing_numpy_marks_both_families_unexecuted(self):
        with patch.object(probe.importlib, "import_module", side_effect=ImportError("absent")):
            report = probe.run_resident_probe(9, warmups=0, repeats=1)
        self.assertEqual(report["status"], "partial")
        self.assertEqual(report["backends"][0]["status"], "correct")
        self.assertEqual([item["status"] for item in report["backends"][1:]], ["not_run"] * 6)
        self.assertEqual(report["probe_schema"], 2)
        self.assertIn("P-02", probe.japanese_summary(report))
        json.dumps(report, allow_nan=False)

    def test_invalid_measurement_arguments_fail(self):
        for kwargs in ({"count": 0}, {"warmups": -1}, {"repeats": 0}):
            with self.assertRaises(ValueError):
                probe.run_resident_probe(use_numpy=False, **kwargs)

    def test_mismatching_backend_never_gets_a_speed_ratio(self):
        class FakeNumpy:
            __version__ = "test-double"

        class BadRunner(probe.PythonFrameRunner):
            def __init__(self, np, data, workers, resident):
                super().__init__(data)

            def run_frame(self, frame):
                actual, timings = super().run_frame(frame)
                actual[1][0] = not actual[1][0]
                return actual, timings

        with patch.object(probe.importlib, "import_module", return_value=FakeNumpy()), \
                patch.object(probe, "NumpyFrameRunner", BadRunner):
            report = probe.run_resident_probe(9, warmups=1, repeats=2)
        self.assertEqual(report["status"], "failed")
        for item in report["backends"][1:]:
            self.assertEqual(item["status"], "mismatch")
            self.assertEqual(item["verification"]["verified_runs"], 0)
            self.assertEqual(item["verification"]["total_runs"], 4)
            self.assertNotIn("python_p50_ratio", item)

    @unittest.skipUnless(importlib.util.find_spec("numpy"), "NumPy absent; retained arrays unexecuted")
    def test_real_numpy_all_rows_workers_and_changing_inputs(self):
        import numpy as np

        for count in (1, 3, 17):
            data = probe.make_dataset(count)
            for resident in (False, True):
                for workers in (1, 2, 4):
                    runner = probe.NumpyFrameRunner(np, data, workers, resident)
                    try:
                        for frame in (1, 2, 4):
                            expected_rows = [(x + frame / 16, y - frame / 32, tx, ty, threshold)
                                             for x, y, tx, ty, threshold in data]
                            actual, _ = runner.run_frame(frame)
                            self.assertEqual(actual, probe.python_kernel(expected_rows))
                            self.assertTrue(all(type(part) is list for part in actual))
                            self.assertEqual([len(part) for part in actual], [count, count])
                    finally:
                        runner.close()

    @unittest.skipUnless(importlib.util.find_spec("numpy"), "NumPy absent; buffer ownership unexecuted")
    def test_retained_buffers_keep_identity_and_worker_regions_do_not_overlap(self):
        import numpy as np

        data = probe.make_dataset(17)
        runner = probe.NumpyFrameRunner(np, data, 4, True)
        try:
            arrays = (runner.rows, runner.dx, runner.dy, runner.mask)
            pointers = [a.__array_interface__["data"][0] for a in arrays]
            first, _ = runner.run_frame(1)
            saved = (list(first[0]), list(first[1]))
            first_rows = runner.rows.copy()
            for frame in (2, 3):
                runner.run_frame(frame)
                self.assertEqual([a.__array_interface__["data"][0] for a in
                                  (runner.rows, runner.dx, runner.dy, runner.mask)], pointers)
            self.assertFalse(np.array_equal(first_rows, runner.rows))
            self.assertEqual(first, saved)
            for i, left in enumerate(arrays):
                for right in arrays[i + 1:]:
                    self.assertFalse(np.shares_memory(left, right))
            for i, left in enumerate(runner.chunks):
                for right in runner.chunks[i + 1:]:
                    for a in left:
                        for b in right:
                            self.assertFalse(np.shares_memory(a, b))
        finally:
            runner.close()
        self.assertEqual(data, probe.make_dataset(17))

    @unittest.skipUnless(importlib.util.find_spec("numpy"), "NumPy absent; full report unexecuted")
    def test_prepare_amortization_and_equivalent_reference_digests(self):
        report = probe.run_resident_probe(17, warmups=1, repeats=2)
        self.assertEqual(report["status"], "correct")
        digests = report["backends"][0]["verification"]["expected_frame_digests_sha256"]
        for item in report["backends"]:
            self.assertEqual(item["verification"]["expected_frame_digests_sha256"], digests)
            self.assertGreaterEqual(item["prepare_seconds"], item["initial_conversion_seconds"])
            self.assertAlmostEqual(item["first_with_prepare_seconds"],
                                   item["prepare_seconds"] + item["first_run_seconds"])
            total = sum(frame["total_seconds"] for frame in item["frame_samples"])
            self.assertAlmostEqual(item["amortized_seconds_per_frame"],
                                   (item["prepare_seconds"] + total) / len(item["frame_samples"]))
        self.assertEqual(report["measurement"]["peak_process_memory_bytes"], None)
        json.dumps(report, allow_nan=False)

    @unittest.skipUnless(importlib.util.find_spec("numpy"), "NumPy absent; cleanup failure path unexecuted")
    def test_cleanup_failure_is_recorded_and_removes_speed_claim(self):
        original = probe.NumpyFrameRunner.close

        def failed_close(runner):
            original(runner)
            raise RuntimeError("shutdown failed")

        with patch.object(probe.NumpyFrameRunner, "close", failed_close):
            report = probe.run_resident_probe(9, warmups=0, repeats=1)
        self.assertEqual(report["status"], "failed")
        for item in report["backends"][1:]:
            self.assertEqual(item["status"], "error")
            self.assertIn("shutdown failed", item["cleanup_error"])
            self.assertNotIn("python_p50_ratio", item)

    def test_resident_cli_is_standalone_and_exclusive(self):
        with tempfile.TemporaryDirectory(dir=ROOT.parent) as directory:
            script = Path(directory) / "probe.py"
            script.write_bytes((ROOT / "tools/pythonista_parallel_probe.py").read_bytes())
            target = Path(directory) / "result.json"
            args = [sys.executable, str(script), "--resident", "--no-numpy", "--count", "9",
                    "--warmups", "0", "--repeats", "1", "--output", str(target)]
            result = subprocess.run(args, cwd=directory, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(target.read_text())["probe_schema"], 2)
            before = target.read_bytes()
            retry = subprocess.run(args, cwd=directory, capture_output=True, text=True, timeout=30)
            self.assertEqual(retry.returncode, 2)
            self.assertEqual(target.read_bytes(), before)

    def test_resident_cli_retains_delayed_output_failure_handling(self):
        class FailedOutput(io.StringIO):
            def close(self):
                super().close()
                raise OSError("delayed close failure")

        report = probe.run_resident_probe(9, warmups=0, repeats=1, use_numpy=False)
        captured = io.StringIO()
        with patch("builtins.open", return_value=FailedOutput()), \
                patch.object(probe, "run_resident_probe", return_value=report), redirect_stderr(captured):
            self.assertEqual(probe.main(["--resident", "--output", "new.json"]), 2)
        self.assertIn("比較器エラー", captured.getvalue())
        self.assertNotIn("JSON保存先", captured.getvalue())


if __name__ == "__main__":
    unittest.main()
