# SPDX-License-Identifier: GPL-3.0-only
"""Probe correctness and standalone CLI tests; no Pythonista device is run."""

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


class ParallelProbeTests(unittest.TestCase):
    def test_partitions_cover_once_in_order_and_balance(self):
        for count in range(10):
            for workers in (1, 2, 4):
                ranges = probe.partition_ranges(count, workers)
                self.assertEqual([i for start, end in ranges for i in range(start, end)],
                                 list(range(count)))
                lengths = [end - start for start, end in ranges]
                self.assertLessEqual(max(lengths) - min(lengths), 1)
        for args in ((-1, 2), (5, 0)):
            with self.assertRaises(ValueError):
                probe.partition_ranges(*args)

    def test_fixed_seed_prefix_and_threshold_edges(self):
        data = probe.make_dataset(67, 42)
        self.assertEqual(data, probe.make_dataset(67, 42))
        self.assertEqual(data, probe.make_dataset(100, 42)[:67])
        self.assertNotEqual(data[8:], probe.make_dataset(67, 43)[8:])
        distances, mask = probe.python_kernel(data[:8])
        self.assertEqual(distances[:5], [0.0, 25.0, 25.0, 25.0, 25.0])
        self.assertEqual(mask, [True, True, False, True, True, True, True, False])

    def test_comparison_rejects_length_mask_distance_and_nonfinite(self):
        expected = ([25.0], [True])
        self.assertTrue(probe.compare_results(expected, ([25.0], [True]))["ok"])
        for actual in (([], []), ([25.0], [False]), ([25.000000000001], [True]),
                       ([float("nan")], [True]), ([float("inf")], [True])):
            self.assertFalse(probe.compare_results(expected, actual)["ok"])

    def test_each_phase_is_checked_and_mismatch_is_retained(self):
        data = probe.make_dataset(2)
        expected = probe.python_kernel(data)
        outputs = [expected, ([0.0, 0.0], [True, True]), expected, expected]
        result = probe.measure_runner(lambda rows: outputs.pop(0), data, expected, 1, 2)
        self.assertEqual(result["status"], "mismatch")
        self.assertEqual(result["verification"]["verified_runs"], 3)
        self.assertEqual(result["verification"]["first_failure"]["run_index"], 1)
        self.assertEqual(len(result["warmup_seconds"]), 1)
        self.assertEqual(result["steady"]["count"], 2)

    def test_missing_numpy_is_not_successful_numpy_execution(self):
        with patch.object(probe.importlib, "import_module", side_effect=ImportError("numpy absent")):
            result = probe.run_probe(count=13, warmups=0, repeats=2)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["backends"][0]["status"], "correct")
        self.assertEqual([item["status"] for item in result["backends"][1:]], ["not_run"] * 3)
        self.assertIn("未実行", probe.japanese_summary(result))
        json.dumps(result, allow_nan=False)

    def test_mismatch_gets_no_speedup_claim(self):
        class BadRunner:
            def __init__(self, np, workers):
                pass

            def __call__(self, data):
                return [0.0] * len(data), [False] * len(data)

            def close(self):
                pass

        class FakeNumpy:
            __version__ = "test-double"

        with patch.object(probe.importlib, "import_module", return_value=FakeNumpy()), \
                patch.object(probe, "NumpyRunner", BadRunner):
            result = probe.run_probe(count=9, warmups=0, repeats=1)
        self.assertEqual(result["status"], "failed")
        for item in result["backends"][1:]:
            self.assertEqual(item["status"], "mismatch")
            self.assertNotIn("python_p50_ratio", item)

    @unittest.skipUnless(importlib.util.find_spec("numpy"), "NumPy not installed; real numeric backend unexecuted")
    def test_real_numpy_all_worker_counts_and_small_uneven_inputs(self):
        import numpy as np

        for count in (1, 3, 67):
            data = probe.make_dataset(count)
            original = list(data)
            expected = probe.python_kernel(data)
            for workers in (1, 2, 4):
                runner = probe.NumpyRunner(np, workers)
                try:
                    for _ in range(2):
                        self.assertEqual(runner(data), expected)
                finally:
                    runner.close()
                self.assertEqual(data, original)

    def run_cli(self, *args, directory=None, script=None):
        return subprocess.run([sys.executable, str(script or ROOT / "tools/pythonista_parallel_probe.py"),
                               "--count", "17", "--warmups", "0", "--repeats", "1",
                               "--no-numpy", *args], cwd=directory or ROOT,
                              capture_output=True, text=True, timeout=30)

    def test_standalone_cli_json_and_no_implicit_files(self):
        with tempfile.TemporaryDirectory(dir=ROOT.parent) as directory:
            script = Path(directory) / "pythonista_parallel_probe.py"
            script.write_bytes((ROOT / "tools/pythonista_parallel_probe.py").read_bytes())
            result = self.run_cli(directory=directory, script=script)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["workload"]["rows"], 17)
            self.assertEqual(report["status"], "partial")
            self.assertIn("未実行", result.stderr)
            self.assertEqual(list(Path(directory).iterdir()), [script])

    def test_cli_exclusive_json_output_and_existing_file_untouched(self):
        with tempfile.TemporaryDirectory(dir=ROOT.parent) as directory:
            target = Path(directory) / "result.json"
            result = self.run_cli("--output", str(target), directory=directory)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(target.read_text())["status"], "partial")
            original = target.read_bytes()
            retry = self.run_cli("--output", str(target), directory=directory)
            self.assertEqual(retry.returncode, 2)
            self.assertEqual(target.read_bytes(), original)

    def test_cli_invalid_counts_fail_before_output(self):
        for option, value in (("--count", "0"), ("--repeats", "0"), ("--warmups", "-1")):
            result = self.run_cli(option, value)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(result.stdout, "")

    def test_cli_reports_delayed_output_failure_before_success(self):
        class DelayedFailureFile:
            def __init__(self, failure):
                self.failure = failure
                self.close_calls = 0

            def write(self, text):
                return len(text)

            def flush(self):
                if self.failure == "flush":
                    raise OSError("delayed flush failure")

            def close(self):
                self.close_calls += 1
                if self.failure == "close":
                    raise OSError("delayed close failure")
                self.flush()

        report = probe.run_probe(count=9, warmups=0, repeats=1, use_numpy=False)
        for failure in ("flush", "close"):
            with self.subTest(failure=failure):
                target = DelayedFailureFile(failure)
                captured = io.StringIO()
                with patch("builtins.open", return_value=target), \
                        patch.object(probe, "run_probe", return_value=report), \
                        redirect_stderr(captured):
                    result = probe.main(["--output", "new-report.json", "--no-numpy"])
                self.assertEqual(result, 2)
                self.assertIn("比較器エラー", captured.getvalue())
                self.assertNotIn("JSON保存先", captured.getvalue())
                self.assertEqual(target.close_calls, 1)


if __name__ == "__main__":
    unittest.main()
