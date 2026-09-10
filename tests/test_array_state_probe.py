# SPDX-License-Identifier: GPL-3.0-only
"""Persistent synthetic state, exact outputs, checkpoint and failure regressions."""

import ast
from contextlib import redirect_stderr
import copy
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import pythonista_array_state_probe as probe

NUMPY_AVAILABLE = importlib.util.find_spec("numpy") is not None


class ArrayStateProbeTests(unittest.TestCase):
    def test_dataset_is_reproducible_and_every_position_really_evolves(self):
        rows = probe.make_rows(17)
        self.assertEqual(rows, probe.make_rows(17))
        before = copy.deepcopy(rows)
        runner = probe.PythonStateRunner(rows)
        first, _ = runner.step()
        second, _ = runner.step()
        self.assertEqual(rows, before)
        self.assertEqual(first["ids"], list(range(17)))
        for index, row in enumerate(rows):
            self.assertEqual(first["x"][index], row[1] + row[3])
            self.assertEqual(second["x"][index], row[1] + row[3] + row[3])
            self.assertEqual(second["y"][index], row[2] + row[4] + row[4])
            self.assertNotEqual(first["x"][index], second["x"][index])
            self.assertNotEqual(first["y"][index], second["y"][index])

    def test_scalar_result_and_threshold_boundary_are_independently_defined(self):
        rows = [[12, 0.0, 0.0, 0.5, 0.25, 1.0, 1.0, 0.8125],
                [13, 0.0, 0.0, 0.5, 0.25, 1.0, 1.0, 0.8124999999999999]]
        runner = probe.PythonStateRunner(rows)
        actual, _ = runner.step()
        self.assertEqual(actual, {"tick": 1, "ids": [12, 13], "x": [0.5, 0.5],
                                  "y": [0.25, 0.25], "distances": [0.8125, 0.8125],
                                  "mask": [True, False]})

    def test_old_results_and_snapshot_do_not_alias_later_state(self):
        runner = probe.PythonStateRunner(probe.make_rows(9))
        first, _ = runner.step()
        snapshot = runner.export_state()
        saved_first, saved_snapshot = copy.deepcopy(first), copy.deepcopy(snapshot)
        for _ in range(3):
            runner.step()
        self.assertEqual(first, saved_first)
        self.assertEqual(snapshot, saved_snapshot)
        snapshot["rows"][0][1] = 999.0
        self.assertNotEqual(runner.export_state()["rows"][0][1], 999.0)

    def test_comparison_checks_all_columns_types_and_identity(self):
        expected = probe.reference_tick(probe.make_rows(3), 1)
        for column in probe.RESULT_COLUMNS:
            bad = copy.deepcopy(expected)
            bad[column][0] = not bad[column][0] if column == "mask" else bad[column][0] + 1
            self.assertFalse(probe.compare_results(expected, bad)["ok"])
        for column, wrong in (("ids", True), ("x", float("nan")), ("y", float("inf")),
                              ("distances", 0), ("mask", 1)):
            bad = copy.deepcopy(expected)
            bad[column][0] = wrong
            self.assertFalse(probe.compare_results(expected, bad)["ok"])
        for bad in ({}, dict(expected, tick=True), dict(expected, ids=expected["ids"][:-1]),
                    dict(expected, extra=[])):
            self.assertFalse(probe.compare_results(expected, bad)["ok"])

    def test_each_tick_has_exact_independent_digests_and_all_phases(self):
        rows = probe.make_rows(9)
        item = probe.measure_frames(probe.PythonStateRunner(rows), rows, 1, 3)
        self.assertEqual(item["status"], "correct")
        verification = item["verification"]
        self.assertEqual(verification["verified_runs"], 5)
        self.assertEqual(verification["checked_rows"], 45)
        self.assertEqual(verification["actual_frame_digests_sha256"],
                         verification["expected_frame_digests_sha256"])
        self.assertEqual(len(set(verification["actual_frame_digests_sha256"])), 5)
        self.assertEqual([s["phase"] for s in item["frame_samples"]],
                         ["first", "warmup", "steady", "steady", "steady"])
        for sample in item["frame_samples"]:
            self.assertTrue(all(sample[key] >= 0 for key in probe.FRAME_COMPONENTS))
            self.assertAlmostEqual(sum(sample[key] for key in probe.FRAME_COMPONENTS),
                                   sample["total_seconds"], places=12)

    def test_stale_or_bad_outputs_fail_and_actual_digest_is_not_fabricated(self):
        rows = probe.make_rows(9)

        class StaleRunner(probe.PythonStateRunner):
            def step(self):
                actual, sample = super().step()
                if not hasattr(self, "first"):
                    self.first = copy.deepcopy(actual)
                self.first["tick"] = actual["tick"]
                return self.first, sample

        item = probe.measure_frames(StaleRunner(rows), rows, 0, 3)
        self.assertEqual(item["status"], "mismatch")
        self.assertEqual(item["verification"]["verified_runs"], 1)
        self.assertEqual(item["verification"]["first_failure"]["tick"], 2)
        self.assertNotEqual(item["verification"]["actual_frame_digests_sha256"][1],
                            item["verification"]["expected_frame_digests_sha256"][1])

        class BadRunner(probe.PythonStateRunner):
            def step(self):
                actual, sample = super().step()
                actual["x"][0] = "bad"
                return actual, sample

        failed = probe.measure_frames(BadRunner(rows), rows, 0, 1)
        self.assertEqual(failed["status"], "mismatch")
        self.assertEqual(failed["verification"]["actual_frame_digests_sha256"], [None, None])

    def test_midrun_exception_retains_completed_samples(self):
        rows = probe.make_rows(9)

        class FailedRunner(probe.PythonStateRunner):
            def step(self):
                if self.tick == 2:
                    raise RuntimeError("worker exploded")
                return super().step()

        item = probe.measure_frames(FailedRunner(rows), rows, 0, 3)
        self.assertEqual(item["status"], "error")
        self.assertEqual(item["verification"]["completed_runs"], 2)
        self.assertEqual(item["verification"]["planned_runs"], 4)
        self.assertEqual(item["verification"]["first_failure"]["tick"], 3)
        self.assertIn("worker exploded", item["reason"])

    def test_comparison_exception_keeps_samples_and_both_digest_sequences_paired(self):
        rows = probe.make_rows(9)
        original = probe.compare_results
        for failing_tick in (1, 3):
            def broken_compare(expected, actual):
                if actual["tick"] == failing_tick:
                    raise RuntimeError("comparison failed")
                return original(expected, actual)

            with patch.object(probe, "compare_results", broken_compare):
                item = probe.measure_frames(probe.PythonStateRunner(rows), rows, 0, 3)
            self.assertEqual(item["status"], "error")
            verification = item["verification"]
            self.assertEqual(verification["first_failure"]["tick"], failing_tick)
            self.assertEqual(verification["completed_runs"], failing_tick - 1)
            self.assertEqual(verification["verified_runs"], failing_tick - 1)
            self.assertEqual(len(item["frame_samples"]), failing_tick - 1)
            self.assertEqual(len(verification["actual_frame_digests_sha256"]), failing_tick - 1)
            self.assertEqual(len(verification["expected_frame_digests_sha256"]), failing_tick - 1)

    def test_snapshot_bytes_preserve_full_state_and_resume_exactly(self):
        rows = probe.make_rows(9)
        runner = probe.PythonStateRunner(rows)
        reference = copy.deepcopy(rows)
        for tick in range(1, 4):
            runner.step()
            probe.reference_tick(reference, tick)
        record = probe.measure_checkpoint(runner, probe.PythonStateRunner, reference, 3)
        self.assertEqual(record["status"], "correct")
        self.assertEqual(record["verified_resume_ticks"], 3)
        self.assertTrue(record["snapshot_matches_reference"])
        self.assertTrue(record["restored_snapshot_matches"])
        self.assertEqual(record["bytes"], len(probe.encode_state(runner.export_state())))
        self.assertAlmostEqual(record["total_seconds"], sum(record[key] for key in
                               ("state_export_seconds", "json_encode_seconds",
                                "json_decode_validate_seconds", "state_restore_seconds")), places=12)
        for sample in record["resume_samples"]:
            self.assertEqual(sample["actual_digest_sha256"], sample["expected_digest_sha256"])

    def test_snapshot_validator_rejects_corruption_without_mutating_input(self):
        state = probe.PythonStateRunner(probe.make_rows(3)).export_state()
        invalid = []
        for key, value in (("format", "mindustry-pythonista-dev"), ("schema", True),
                           ("tick", -1), ("columns", []), ("rows", [])):
            item = copy.deepcopy(state)
            item[key] = value
            invalid.append(item)
        for index, value in ((0, True), (0, 2 ** 63), (1, float("inf")),
                             (2, True), (7, -1.0)):
            item = copy.deepcopy(state)
            item["rows"][0][index] = value
            invalid.append(item)
        duplicate = copy.deepcopy(state)
        duplicate["rows"][1][0] = duplicate["rows"][0][0]
        invalid.append(duplicate)
        for item in invalid:
            payload = json.dumps(item).encode()
            with self.assertRaises(ValueError):
                probe.decode_state(payload)
            self.assertEqual(payload, json.dumps(item).encode())
        self.assertEqual(probe.decode_state(probe.encode_state(state)), state)

    def test_restore_mutation_is_a_mismatch_before_resumed_computation(self):
        rows = probe.make_rows(9)
        runner = probe.PythonStateRunner(rows)

        def bad_factory(values, tick):
            restored = probe.PythonStateRunner(values, tick)
            restored.rows[0][5] += 1
            return restored

        record = probe.measure_checkpoint(runner, bad_factory, rows, 0)
        self.assertEqual(record["status"], "mismatch")
        self.assertFalse(record["restored_snapshot_matches"])

    def test_missing_numpy_is_unexecuted_but_broken_import_is_error(self):
        with patch.object(probe.importlib, "import_module",
                          side_effect=ModuleNotFoundError("no numpy", name="numpy")):
            partial = probe.run_probe(9, warmups=0, repeats=1)
        self.assertEqual(partial["status"], "partial")
        self.assertEqual([item["status"] for item in partial["backends"]],
                         ["correct", "not_run", "not_run", "not_run"])
        for error in (RuntimeError("broken native module"),
                      ModuleNotFoundError("broken numpy dependency", name="numpy_dependency")):
            with patch.object(probe.importlib, "import_module", side_effect=error):
                failed = probe.run_probe(9, warmups=0, repeats=1)
            self.assertEqual(failed["status"], "failed")
            self.assertEqual([item["status"] for item in failed["backends"]],
                             ["correct", "error", "error", "error"])

    def test_invalid_measurement_arguments_are_rejected(self):
        for kwargs in ({"count": 0}, {"count": True}, {"warmups": -1}, {"repeats": 0}, {"seed": 1.5}):
            with self.assertRaises(ValueError):
                probe.run_probe(use_numpy=False, **kwargs)

    @unittest.skipUnless(NUMPY_AVAILABLE, "NumPy absent; array state not executed")
    def test_numpy_every_row_for_small_uneven_partitions_and_large_ids(self):
        import numpy as np

        for count in (1, 3, 17):
            rows = probe.make_rows(count)
            rows[0][0] = 2 ** 53 + 7
            for workers in (1, 2, 4):
                reference = copy.deepcopy(rows)
                runner = probe.NumpyStateRunner(np, rows, workers)
                try:
                    for tick in range(1, 6):
                        expected = probe.reference_tick(reference, tick)
                        actual, _ = runner.step()
                        self.assertTrue(probe.compare_results(expected, actual)["ok"])
                    self.assertEqual(runner.export_state()["rows"], reference)
                    self.assertEqual(probe.decode_state(probe.encode_state(runner.export_state()))["rows"],
                                     reference)
                finally:
                    runner.close()

    @unittest.skipUnless(NUMPY_AVAILABLE, "NumPy absent; array ownership not executed")
    def test_numpy_buffers_are_reused_and_worker_writes_do_not_overlap(self):
        import numpy as np

        rows = probe.make_rows(17)
        runner = probe.NumpyStateRunner(np, rows, 4)
        arrays = (runner.ids, runner.state, runner.dx, runner.dy, runner.mask)
        pointers = [array.__array_interface__["data"][0] for array in arrays]
        try:
            first, _ = runner.step()
            snapshot = runner.export_state()
            retained = copy.deepcopy(first), copy.deepcopy(snapshot)
            for _ in range(3):
                runner.step()
            self.assertEqual(first, retained[0])
            self.assertEqual(snapshot, retained[1])
            self.assertEqual([array.__array_interface__["data"][0] for array in arrays], pointers)
            self.assertEqual([index for start, end in runner.ranges for index in range(start, end)],
                             list(range(17)))
            for index, left in enumerate(arrays):
                for right in arrays[index + 1:]:
                    self.assertFalse(np.shares_memory(left, right))
            for index, left in enumerate(runner.chunks):
                for right in runner.chunks[index + 1:]:
                    for left_array in left:
                        for right_array in right:
                            self.assertFalse(np.shares_memory(left_array, right_array))
        finally:
            runner.close()
        self.assertEqual(rows, probe.make_rows(17))

    @unittest.skipUnless(NUMPY_AVAILABLE, "NumPy absent; full report not executed")
    def test_report_has_same_snapshots_and_preparation_checkpoint_amortization(self):
        report = probe.run_probe(17, warmups=1, repeats=2)
        self.assertEqual(report["status"], "correct")
        self.assertIsNone(report["measurement"]["peak_process_memory_bytes"])
        self.assertEqual(report["measurement"]["numeric_buffer_estimate_bytes"], 17 * 81)
        baseline = report["backends"][0]
        for item in report["backends"]:
            self.assertEqual(item["verification"]["actual_frame_digests_sha256"],
                             baseline["verification"]["expected_frame_digests_sha256"])
            self.assertEqual(item["checkpoint"]["snapshot_sha256"], baseline["checkpoint"]["snapshot_sha256"])
            self.assertGreaterEqual(item["prepare_seconds"], item["initial_conversion_seconds"])
            total = item["prepare_seconds"] + sum(s["total_seconds"] for s in item["frame_samples"])
            self.assertAlmostEqual(item["amortized_seconds_per_tick"], total / 4)
            imported = report["numpy"]["import_seconds"] if item["name"] == "numpy" else 0
            self.assertAlmostEqual(item["amortized_with_import_seconds_per_tick"], (total + imported) / 4)
            self.assertAlmostEqual(item["amortized_with_checkpoint_seconds_per_tick"],
                                   (total + item["checkpoint"]["total_seconds"]) / 4)
        json.dumps(report, allow_nan=False)

    @unittest.skipUnless(NUMPY_AVAILABLE, "NumPy absent; mismatch and cleanup failure not executed")
    def test_failed_backends_never_get_speed_ratios(self):
        original_step = probe.NumpyStateRunner.step

        def bad_step(runner):
            actual, sample = original_step(runner)
            actual["mask"][0] = not actual["mask"][0]
            return actual, sample

        with patch.object(probe.NumpyStateRunner, "step", bad_step):
            report = probe.run_probe(9, warmups=0, repeats=1)
        self.assertEqual(report["status"], "failed")
        self.assertIn("保存復元 未実行", probe.japanese_summary(report))
        for item in report["backends"][1:]:
            self.assertEqual(item["status"], "mismatch")
            self.assertNotIn("python_p50_ratio", item)
        original_close = probe.NumpyStateRunner.close

        def bad_close(runner):
            original_close(runner)
            raise RuntimeError("shutdown failed")

        with patch.object(probe.NumpyStateRunner, "close", bad_close):
            report = probe.run_probe(9, warmups=0, repeats=1)
        self.assertEqual(report["status"], "failed")
        for item in report["backends"][1:]:
            self.assertEqual(item["status"], "error")
            self.assertNotIn("python_p50_ratio", item)

    @unittest.skipUnless(NUMPY_AVAILABLE, "NumPy absent; worker failure not executed")
    def test_worker_exception_is_propagated_after_every_writer_finishes(self):
        import numpy as np

        runner = probe.NumpyStateRunner(np, probe.make_rows(17), 4)
        completed = []

        def bad_chunk(*chunk):
            completed.append(len(chunk[0]))
            raise RuntimeError("chunk failed")

        try:
            with patch.object(runner, "_chunk", bad_chunk):
                with self.assertRaisesRegex(RuntimeError, "chunk failed"):
                    runner.step()
            self.assertEqual(len(completed), 4)
        finally:
            runner.close()

    def test_cli_runs_in_isolation_with_python310_syntax_and_protects_output(self):
        source = ROOT / "tools/pythonista_array_state_probe.py"
        ast.parse(source.read_text(), feature_version=(3, 10))
        with tempfile.TemporaryDirectory(dir=ROOT.parent) as directory:
            script = Path(directory) / "probe.py"
            script.write_bytes(source.read_bytes())
            output = Path(directory) / "result.json"
            args = [sys.executable, str(script), "--count", "9", "--warmups", "0",
                    "--repeats", "1", "--no-numpy", "--output", str(output)]
            result = subprocess.run(args, cwd=directory, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(output.read_text())
            self.assertEqual(report["status"], "partial")
            self.assertEqual(report["source"], probe.source_info())
            before = output.read_bytes()
            retry = subprocess.run(args, cwd=directory, capture_output=True, text=True, timeout=30)
            self.assertEqual(retry.returncode, 2)
            self.assertEqual(output.read_bytes(), before)

    def test_cli_reports_delayed_close_failure_without_success_message(self):
        class FailedOutput(io.StringIO):
            def close(self):
                super().close()
                raise OSError("delayed close failure")

        report = probe.run_probe(9, warmups=0, repeats=1, use_numpy=False)
        captured = io.StringIO()
        with patch("builtins.open", return_value=FailedOutput()), \
                patch.object(probe, "run_probe", return_value=report), redirect_stderr(captured):
            self.assertEqual(probe.main(["--output", "new.json"]), 2)
        self.assertIn("比較器エラー", captured.getvalue())
        self.assertNotIn("JSON保存先", captured.getvalue())


if __name__ == "__main__":
    unittest.main()
