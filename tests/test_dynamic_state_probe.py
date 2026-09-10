# SPDX-License-Identifier: GPL-3.0-only
import ast
import copy
import importlib.util
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('dynamic_probe', ROOT / 'tools/pythonista_dynamic_state_probe.py')
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)
NUMPY_AVAILABLE = importlib.util.find_spec('numpy') is not None


class DynamicStateProbeTests(unittest.TestCase):
    def test_hand_checked_order_commands_and_threshold(self):
        row = [10, 0.0, 0.0, 1.0, 0.0, 1.0, 1.0, 1.0]
        runner = probe.PythonDynamicRunner([row])
        new = [11, 3.0, 0.0, 0.0, 0.0, 0.0, 0.0, 4.0]
        commands = [{'op': 'spawn', 'row': new}, {'op': 'velocity', 'id': 11, 'vx': -1.0, 'vy': 0.0},
                    {'op': 'target', 'id': 10, 'x': 1.0, 'y': 1.0, 'threshold2': 1.0}]
        output, _, stats = runner.step(commands)
        self.assertEqual(output, {'tick': 1, 'ids': [10, 11], 'x': [1.0, 2.0], 'y': [0.0, 0.0],
                                 'vx': [1.0, -1.0], 'vy': [0.0, 0.0], 'target_x': [1.0, 0.0],
                                 'target_y': [1.0, 0.0], 'threshold2': [1.0, 4.0],
                                 'distances': [1.0, 4.0], 'mask': [True, True]})
        self.assertEqual(stats['growth_events'], 1)
        self.assertEqual(new[1], 3.0)
        runner.step([{'op': 'delete', 'id': 10}, {'op': 'spawn', 'row': [12] + row[1:]}])
        self.assertEqual(list(runner.mapping), [11, 12])
        self.assertEqual(runner.mapping, {11: 1, 12: 0})

    def test_invalid_batch_is_atomic_including_middle_and_duplicate_delete(self):
        runner = probe.PythonDynamicRunner(probe.make_rows(3))
        state = runner.export_state()
        invalid = [
            [{'op': 'velocity', 'id': 0, 'vx': 5.0, 'vy': 5.0}, {'op': 'delete', 'id': 99}],
            [{'op': 'delete', 'id': 0}, {'op': 'delete', 'id': 0}],
            [{'op': 'delete', 'id': 0}, {'op': 'velocity', 'id': 0, 'vx': 1.0, 'vy': 1.0}],
            [{'op': 'spawn', 'row': [3] + probe.make_rows(1)[0][1:]}, {'op': 'spawn', 'row': [3] + probe.make_rows(1)[0][1:]}],
        ]
        for batch in invalid:
            with self.assertRaises(ValueError):
                runner.step(batch)
            self.assertEqual(runner.export_state(), state)
            self.assertFalse(runner.failed)
        runner.step([])

    def test_stale_and_reused_id_cannot_target_recycled_slot(self):
        runner = probe.PythonDynamicRunner(probe.make_rows(1))
        runner.step([{'op': 'delete', 'id': 0}, {'op': 'spawn', 'row': [1] + probe.make_rows(1)[0][1:]}])
        snapshot = runner.export_state()
        for batch in ([{'op': 'delete', 'id': 0}], [{'op': 'spawn', 'row': probe.make_rows(1)[0]}],
                      [{'op': 'delete', 'id': 1}, {'op': 'spawn', 'row': [1] + probe.make_rows(1)[0][1:]}]):
            with self.assertRaises(ValueError):
                runner.step(batch)
            self.assertEqual(snapshot, runner.export_state())
        self.assertEqual(runner.mapping, {1: 0})

    def test_invalid_commands_and_initial_rows_have_explicit_errors(self):
        runner = probe.PythonDynamicRunner(probe.make_rows(1))
        for commands in (None, {}, [None], [{'op': []}], [{'op': 'bad'}],
                         [{'op': 'delete', 'id': True}], [{'op': 'delete', 'id': 0, 'extra': 1}],
                         [{'op': 'velocity', 'id': 0, 'vx': float('nan'), 'vy': 0.0}],
                         [{'op': 'target', 'id': 0, 'x': 0.0, 'y': 0.0, 'threshold2': -1.0}]):
            with self.assertRaises((ValueError, TypeError)):
                runner.step(commands)
            self.assertEqual(runner.tick, 0)
        for rows in ([probe.make_rows(1)[0]] * 2, [[True] + [0.0] * 7], [[2 ** 63] + [0.0] * 7],
                     [[0] + [0.0] * 6 + [float('inf')]], [[0] + [0] * 7]):
            with self.assertRaises(ValueError):
                probe.PythonDynamicRunner(rows)

    def test_empty_state_and_int64_boundary_preserve_identity(self):
        runner = probe.PythonDynamicRunner([])
        output, _, _ = runner.step([])
        self.assertEqual(output, dict({k: [] for k in probe.RESULT_COLUMNS}, tick=1))
        self.assertEqual(probe.decode_state(probe.encode_state(runner.export_state())), runner.export_state())
        last = 2 ** 63 - 1
        runner.step([{'op': 'spawn', 'row': [last] + [0.0] * 7}])
        self.assertEqual(runner.next_id, 2 ** 63)
        self.assertEqual(probe.decode_state(probe.encode_state(runner.export_state()))['order'], [last])
        with self.assertRaises(ValueError):
            runner.step([{'op': 'spawn', 'row': [2 ** 63] + [0.0] * 7}])
        negative = probe.PythonDynamicRunner([[-20] + [0.0] * 7])
        self.assertEqual(probe.decode_state(probe.encode_state(negative.export_state()))['next_id'], 0)

    def test_snapshot_preserves_free_order_capacity_and_dynamic_continuation(self):
        rows = probe.make_rows(5)
        runner, oracle = probe.PythonDynamicRunner(rows), probe.ScalarOracle(rows)
        batches = probe.make_workload(rows, 9)
        for batch in batches[:6]:
            runner.step(batch)
            oracle.step(batch)
        state = runner.export_state()
        self.assertGreater(state['capacity'], len(state['order']))
        self.assertTrue(state['free_slots'])
        record = probe.measure_checkpoint(runner, probe.PythonDynamicRunner, oracle, batches[6:])
        self.assertEqual(record['status'], 'correct')
        self.assertEqual(record['verified_resume_ticks'], 3)
        self.assertTrue(record['snapshot_matches_reference'])
        self.assertTrue(record['restored_snapshot_matches'])
        self.assertTrue(record['final_snapshot_matches_reference'])
        self.assertEqual([s['actual_digest_sha256'] for s in record['resume_samples']],
                         [s['expected_digest_sha256'] for s in record['resume_samples']])

    def test_snapshot_rejects_duplicate_mapping_freelist_and_corrupt_values(self):
        runner = probe.PythonDynamicRunner(probe.make_rows(3))
        runner.step([{'op': 'delete', 'id': 1}])
        state = runner.export_state()
        invalid = []
        for key, value in (('schema', True), ('tick', -1), ('capacity', 4), ('next_id', 2),
                           ('order', [0, 0]), ('free_slots', [1, 1]), ('free_slots', []), ('free_slots', [True]),
                           ('format', 'mindustry-pythonista-dev'), ('columns', [])):
            bad = copy.deepcopy(state)
            bad[key] = value
            invalid.append(bad)
        bad = copy.deepcopy(state)
        bad['slots'][2][0] = 0
        invalid.append(bad)
        for item in invalid:
            with self.assertRaises(ValueError):
                probe.decode_state(probe.encode_state(item))
        with self.assertRaises(ValueError):
            probe.decode_state(b'{"format":0,"format":1}')

    def test_output_and_export_do_not_alias_next_tick_or_commands(self):
        rows = probe.make_rows(3)
        runner = probe.PythonDynamicRunner(rows)
        batches = probe.make_workload(rows, 3)
        original_commands = copy.deepcopy(batches)
        result, _, _ = runner.step(batches[0])
        state = runner.export_state()
        kept_result, kept_state = copy.deepcopy(result), copy.deepcopy(state)
        runner.step(batches[1])
        self.assertEqual(result, kept_result)
        self.assertEqual(state, kept_state)
        self.assertEqual(batches, original_commands)
        result['x'][1] = 999.0
        self.assertNotEqual(runner.export_state()['slots'][runner.mapping[result['ids'][1]]][1], 999.0)

    def test_workload_is_deterministic_and_exercises_every_mutation(self):
        rows = probe.make_rows(128)
        batches = probe.make_workload(rows, 6)
        self.assertEqual(batches, probe.make_workload(rows, 6))
        runner = probe.PythonDynamicRunner(rows)
        growth, free_allocations = 0, 0
        for batch in batches:
            _, _, stats = runner.step(batch)
            growth += stats['growth_events']
            free_allocations += stats['free_slot_allocations']
        self.assertGreater(growth, 0)
        self.assertGreater(free_allocations, 0)
        self.assertTrue(all(any(c['op'] == op for batch in batches for c in batch)
                            for op in ('spawn', 'delete', 'velocity', 'target')))

    def test_all_result_columns_types_and_order_are_checked(self):
        expected = probe.ScalarOracle(probe.make_rows(3)).step([])
        for key in probe.RESULT_COLUMNS:
            bad = copy.deepcopy(expected)
            bad[key][0] = not bad[key][0] if key == 'mask' else bad[key][0] + 1
            self.assertFalse(probe.compare_results(expected, bad)['ok'])
        for key, value in (('ids', True), ('vx', float('nan')), ('threshold2', 0), ('mask', 1)):
            bad = copy.deepcopy(expected)
            bad[key][0] = value
            self.assertFalse(probe.compare_results(expected, bad)['ok'])
        self.assertFalse(probe.compare_results(expected, dict(expected, tick=True))['ok'])
        self.assertFalse(probe.compare_results(expected, {})['ok'])

    def test_all_samples_digests_counts_and_timings_are_consistent(self):
        rows = probe.make_rows(9)
        batches = probe.make_workload(rows, 5)
        item = probe.measure_frames(probe.PythonDynamicRunner(rows), rows, batches, 1, 3)
        verification = item['verification']
        self.assertEqual(item['status'], 'correct')
        self.assertEqual(verification['verified_runs'], 5)
        self.assertEqual(verification['actual_frame_digests_sha256'], verification['expected_frame_digests_sha256'])
        self.assertEqual(verification['checked_rows'], sum(s['mutation']['active_rows'] for s in item['frame_samples']))
        self.assertEqual([s['phase'] for s in item['frame_samples']], ['first', 'warmup', 'steady', 'steady', 'steady'])
        for sample in item['frame_samples']:
            self.assertTrue(all(sample[key] >= 0 for key in probe.FRAME_COMPONENTS))
            self.assertAlmostEqual(sample['total_seconds'], sum(sample[key] for key in probe.FRAME_COMPONENTS), places=12)
            self.assertLessEqual(sample['mutation']['growth_seconds'], sample['command_apply_seconds'])

    def test_comparison_and_runner_exceptions_keep_paired_records(self):
        rows = probe.make_rows(3)
        batches = probe.make_workload(rows, 4)
        original = probe.compare_results
        for failed_tick in (1, 3):
            def broken_compare(expected, actual):
                if actual['tick'] == failed_tick:
                    raise RuntimeError('comparison failed')
                return original(expected, actual)
            with patch.object(probe, 'compare_results', broken_compare):
                result = probe.measure_frames(probe.PythonDynamicRunner(rows), rows, batches, 0, 3)
            self.assertEqual(result['status'], 'error')
            verification = result['verification']
            self.assertEqual(len(result['frame_samples']), failed_tick - 1)
            self.assertEqual(len(verification['actual_frame_digests_sha256']), failed_tick - 1)
            self.assertEqual(len(verification['expected_frame_digests_sha256']), failed_tick - 1)
        runner = probe.PythonDynamicRunner(rows)
        with patch.object(runner, '_update', side_effect=RuntimeError('update failed')):
            result = probe.measure_frames(runner, rows, batches, 0, 3)
        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['frame_samples'], [])
        self.assertTrue(runner.failed)
        with self.assertRaises(RuntimeError):
            runner.export_state()

    def test_mismatch_records_real_digest_or_null(self):
        rows = probe.make_rows(3)
        runner = probe.PythonDynamicRunner(rows)
        original = runner._result
        def broken():
            output = original()
            output['vx'][0] = 'bad'
            return output
        with patch.object(runner, '_result', broken):
            result = probe.measure_frames(runner, rows, probe.make_workload(rows, 2), 0, 1)
        self.assertEqual(result['status'], 'mismatch')
        self.assertEqual(result['verification']['actual_frame_digests_sha256'], [None, None])
        self.assertEqual(len(result['frame_samples']), 2)

    def test_restore_corruption_and_close_errors_fail_checkpoint(self):
        rows = probe.make_rows(3)
        runner, oracle = probe.PythonDynamicRunner(rows), probe.ScalarOracle(rows)
        def bad_restore(rows=None, state=None):
            restored = probe.PythonDynamicRunner(rows, state)
            restored.slots[0][3] += 1.0
            return restored
        record = probe.measure_checkpoint(runner, bad_restore, oracle, [])
        self.assertEqual(record['status'], 'mismatch')
        def bad_close(rows=None, state=None):
            restored = probe.PythonDynamicRunner(rows, state)
            restored.close = lambda: (_ for _ in ()).throw(RuntimeError('close failed'))
            return restored
        record = probe.measure_checkpoint(runner, bad_close, probe.ScalarOracle(rows), [])
        self.assertEqual(record['status'], 'error')
        self.assertIn('close failed', record['cleanup_error'])

    def test_numpy_absence_broken_import_and_cleanup_are_not_success(self):
        with patch.object(probe.importlib, 'import_module', side_effect=ModuleNotFoundError('absent', name='numpy')):
            report = probe.run_probe(3, warmups=0, repeats=1)
        self.assertEqual(report['status'], 'partial')
        self.assertEqual([b['status'] for b in report['backends']], ['correct', 'not_run', 'not_run', 'not_run'])
        with patch.object(probe.importlib, 'import_module', side_effect=ModuleNotFoundError('broken', name='dependency')):
            report = probe.run_probe(3, warmups=0, repeats=1)
        self.assertEqual(report['status'], 'failed')
        self.assertEqual([b['status'] for b in report['backends']], ['correct', 'error', 'error', 'error'])
        with patch.object(probe.PythonDynamicRunner, 'close', side_effect=RuntimeError('cleanup failed')):
            report = probe.run_probe(3, warmups=0, repeats=1, use_numpy=False)
        self.assertEqual(report['status'], 'failed')
        self.assertIn('cleanup failed', report['backends'][0]['cleanup_error'])

    def test_invalid_measurement_options_rejected_and_zero_supported(self):
        for kwargs in ({'count': -1}, {'count': True}, {'warmups': -1}, {'repeats': 0}, {'seed': 1.5}):
            with self.assertRaises(ValueError):
                probe.run_probe(use_numpy=False, **kwargs)
        report = probe.run_probe(0, warmups=0, repeats=1, use_numpy=False)
        self.assertEqual(report['backends'][0]['status'], 'correct')

    @unittest.skipUnless(NUMPY_AVAILABLE, 'NumPy absent; dynamic arrays not executed')
    def test_numpy_uneven_empty_large_ids_every_field_and_snapshot(self):
        import numpy as np
        for count in (0, 1, 3, 17):
            rows = probe.make_rows(count, first_id=2 ** 53 + 7)
            for workers in (1, 2, 4):
                runner = probe.NumpyDynamicRunner(np, rows, workers)
                oracle = probe.ScalarOracle(rows)
                try:
                    for batch in probe.make_workload(rows, 7):
                        expected = oracle.step(batch)
                        actual, _, _ = runner.step(batch)
                        self.assertTrue(probe.compare_results(expected, actual)['ok'])
                        self.assertEqual(runner.export_state(), oracle.export_state())
                finally:
                    runner.close()

    @unittest.skipUnless(NUMPY_AVAILABLE, 'NumPy absent; buffer ownership not executed')
    def test_numpy_grows_reuses_slots_and_preserves_nonalias_outputs(self):
        import numpy as np
        rows = probe.make_rows(3)
        runner = probe.NumpyDynamicRunner(np, rows, 4)
        try:
            before = runner.state
            first, _, _ = runner.step([{'op': 'spawn', 'row': [3] + rows[0][1:]}])
            self.assertIsNot(before, runner.state)
            kept = copy.deepcopy(first)
            pointers = [a.__array_interface__['data'][0] for a in (runner.ids, runner.state, runner.dx, runner.dy, runner.mask)]
            runner.step([{'op': 'delete', 'id': 0}, {'op': 'spawn', 'row': [4] + rows[0][1:]}])
            self.assertEqual(first, kept)
            self.assertEqual(runner.mapping[4], 0)
            self.assertEqual(pointers, [a.__array_interface__['data'][0] for a in (runner.ids, runner.state, runner.dx, runner.dy, runner.mask)])
            self.assertEqual([i for a, b in runner.ranges for i in range(a, b)], list(range(runner.capacity)))
            for index, (a, b) in enumerate(runner.ranges):
                for c, d in runner.ranges[index + 1:]:
                    self.assertFalse(np.shares_memory(runner.state[a:b], runner.state[c:d]))
        finally:
            runner.close()

    @unittest.skipUnless(NUMPY_AVAILABLE, 'NumPy absent; worker error path not executed')
    def test_worker_and_partial_submit_errors_drain_writers_then_poison_runner(self):
        import numpy as np
        for fail_submit in (False, True):
            runner = probe.NumpyDynamicRunner(np, probe.make_rows(8), 2)
            entered, finished, release = threading.Event(), threading.Event(), threading.Event()
            original_chunk, original_submit = runner._chunk, runner.executor.submit
            def chunk(start, end):
                if start == 0:
                    entered.set()
                    if not release.wait(2):
                        raise RuntimeError("test release timed out")
                    original_chunk(start, end)
                    finished.set()
                else:
                    self.assertTrue(entered.wait(2))
                    threading.Timer(0.02, release.set).start()
                    raise RuntimeError('worker failed')
            submissions = []
            def submit(*args):
                submissions.append(1)
                if fail_submit and len(submissions) == 2:
                    self.assertTrue(entered.wait(2))
                    threading.Timer(0.02, release.set).start()
                    raise RuntimeError('submit failed')
                return original_submit(*args)
            try:
                with patch.object(runner, '_chunk', chunk), patch.object(runner.executor, 'submit', submit):
                    with self.assertRaisesRegex(RuntimeError, 'submit failed' if fail_submit else 'worker failed'):
                        runner.step([])
                self.assertTrue(finished.is_set())
                self.assertTrue(runner.failed)
                with self.assertRaises(RuntimeError):
                    runner.step([])
                with self.assertRaises(RuntimeError):
                    runner.export_state()
            finally:
                runner.close()

    @unittest.skipUnless(NUMPY_AVAILABLE, 'NumPy absent; report comparison not executed')
    def test_all_backends_checkpoint_resume_and_ratio_require_success(self):
        report = probe.run_probe(17, warmups=0, repeats=2)
        self.assertEqual(report['status'], 'correct')
        snapshots = [b['checkpoint']['snapshot_sha256'] for b in report['backends']]
        self.assertEqual(len(set(snapshots)), 1)
        for item in report['backends']:
            self.assertEqual(item['checkpoint']['verified_resume_ticks'], 3)
            self.assertAlmostEqual(item['amortized_with_checkpoint_seconds_per_tick'],
                                   (item['prepare_seconds'] + sum(s['total_seconds'] for s in item['frame_samples'])
                                    + item['checkpoint']['total_seconds']) / 3)
        with patch.object(probe.NumpyDynamicRunner, '_compute', side_effect=RuntimeError('worker failed')):
            failed = probe.run_probe(3, warmups=0, repeats=1)
        self.assertEqual(failed['status'], 'failed')
        for item in failed['backends'][1:]:
            self.assertNotIn('python_p50_ratio', item)

    def test_cli_standalone_python310_and_existing_output_protected(self):
        script = ROOT / 'tools/pythonista_dynamic_state_probe.py'
        ast.parse(script.read_text(), feature_version=(3, 10))
        with tempfile.TemporaryDirectory() as directory:
            copied = Path(directory) / 'probe.py'
            shutil.copyfile(script, copied)
            output = Path(directory) / 'result.json'
            command = [sys.executable, '-I', str(copied), '--count', '3', '--warmups', '0', '--repeats', '1', '--no-numpy', '--output', str(output)]
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(output.read_text())['status'], 'partial')
            before = output.read_bytes()
            again = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(again.returncode, 2)
            self.assertEqual(before, output.read_bytes())

    def test_cli_delayed_close_error_does_not_report_saved(self):
        class FailingFile(io.StringIO):
            def close(self):
                raise OSError('delayed close failure')
        output, stderr = FailingFile(), io.StringIO()
        with patch('builtins.open', return_value=output), patch.object(sys, 'stderr', stderr):
            code = probe.main(['--count', '3', '--warmups', '0', '--repeats', '1', '--no-numpy', '--output', 'new.json'])
        self.assertEqual(code, 2)
        self.assertIn('delayed close failure', stderr.getvalue())
        self.assertNotIn('JSON保存先', stderr.getvalue())


if __name__ == '__main__':
    unittest.main()
