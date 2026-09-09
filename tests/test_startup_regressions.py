# SPDX-License-Identifier: GPL-3.0-only
"""Synthetic lifecycle/file-error regression tests, NOT an iOS emulator.

0.1.0 failed with the reported missing _failed both before setup and after an
exception in the first few setup lines. These tests verify the hardened paths.
"""
import contextlib
import io
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import mindustry_pythonista as m
from pythonista_stub import scene, ui, touch


class StartupRegressionTests(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.tmp = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.data = self.tmp / 'data'
        self.private = self.tmp / 'private'
        self.stack.enter_context(patch.object(m, 'data_directory', return_value=self.data))
        self.stack.enter_context(patch.object(m, 'private_data_directory', return_value=self.private))
        self.output = io.StringIO()
        self.stack.enter_context(contextlib.redirect_stdout(self.output))
        self.cls = m.make_scene_class(scene, ui)

    def all_callbacks(self, s):
        s.update()
        s.pause()
        s.resume()
        s.stop()
        s.save_world(manual=True)
        s.did_change_size()
        s.touch_began(touch(1, (100, 300)))
        s.touch_moved(touch(1, (110, 310)))
        s.touch_ended(touch(1, (110, 310)))
        s.perform('new')

    def test_flags_exist_immediately_after_construction(self):
        s = self.cls()
        self.assertIs(s._failed, False)
        self.assertIs(s._ready, False)
        self.assertIs(s._setup_attempted, False)
        self.assertIsNone(s.storage)

    def test_early_update_initializes_once_instead_of_missing_failed(self):
        s = self.cls()
        s.update()
        self.assertTrue(s._ready)
        self.assertFalse(s._failed)
        world = s.world
        s.setup()
        self.assertIs(s.world, world)
        self.assertEqual(len(s.children), 3)
        s.close_overlay()
        s.update()
        self.assertEqual(s.world.tick_count, 2)

    def test_zero_size_waits_without_creating_saves_then_initializes(self):
        s = self.cls()
        s.size = SimpleNamespace(w=0, h=0)
        self.all_callbacks(s)
        self.assertFalse(s._ready)
        self.assertFalse(s._setup_attempted)
        self.assertFalse(self.data.exists())
        s.size = SimpleNamespace(w=390, h=844)
        s.update()
        self.assertTrue(s._ready)
        self.assertFalse(s._failed)

    def test_touches_and_lifecycle_before_setup_are_noops(self):
        s = self.cls()
        # Do not update here: update may bootstrap a valid-size scene.
        s.touch_began(touch(1, (100, 300)))
        s.touch_moved(touch(1, (110, 310)))
        s.touch_ended(touch(1, (110, 310)))
        s.pause(); s.resume(); s.stop(); s.save_world(True)
        s.did_change_size(); s.perform('new')
        self.assertFalse(self.data.exists())
        self.assertFalse(s._ready)

    def test_reentrant_callbacks_during_setup_cannot_use_partial_world(self):
        s = self.cls()
        rebuild = self.cls.rebuild_world
        def interrupted_rebuild(obj):
            self.assertTrue(obj._setup_in_progress)
            self.assertFalse(obj._ready)
            self.all_callbacks(obj)
            self.assertFalse((self.data / 'autosave.json').exists())
            return rebuild(obj)
        with patch.object(self.cls, 'rebuild_world', interrupted_rebuild):
            s.setup()
        self.assertTrue(s._ready)
        self.assertFalse(s._failed)

    def test_callbacks_from_base_constructor_have_flags(self):
        testcase = self
        class EarlyScene(scene.Scene):
            def __init__(self):
                super().__init__()
                self.size = SimpleNamespace(w=0, h=0)
                testcase.all_callbacks(self)
                self.size = SimpleNamespace(w=390, h=844)
                self.setup()
        injected = SimpleNamespace(**vars(scene))
        injected.Scene = EarlyScene
        s = m.make_scene_class(injected, ui)()
        self.assertTrue(s._ready)
        self.assertFalse(s._failed)
        # Subclass __init__ must not reset state after base-triggered setup.
        self.assertEqual(s.overlay_kind, 'help')

    def test_startup_exception_retains_original_error_and_blocks_callbacks(self):
        s = self.cls()
        with patch.object(m, 'prepare_data_directory', side_effect=PermissionError('ROOT-STARTUP')) as init:
            s.setup()
            for _ in range(3):
                self.all_callbacks(s)
                s.setup()
            self.assertEqual(init.call_count, 1)
        self.assertTrue(s._failed)
        self.assertFalse(s._ready)
        self.assertIn('PermissionError: ROOT-STARTUP', s._last_error)
        self.assertNotIn("no attribute '_failed'", self.output.getvalue())
        self.assertIn('startup / storage', s._failure_report)
        self.assertFalse((self.data / 'autosave.json').exists())
        self.assertEqual((self.data / 'crash.log').read_text(), s._failure_report)

    def test_error_during_update_is_reported_once_and_never_autosaved(self):
        s = self.cls(); s.setup(); s.close_overlay()
        s.save_world()
        before = (self.data / 'autosave.json').read_bytes()
        with patch.object(s, 'sync_nodes', side_effect=RuntimeError('ROOT-UPDATE')) as sync:
            s.update(); s.update(); s.stop()
        self.assertEqual(sync.call_count, 1)
        self.assertTrue(s._failed)
        self.assertIn('RuntimeError: ROOT-UPDATE', s._last_error)
        self.assertEqual((self.data / 'autosave.json').read_bytes(), before)

    def test_log_write_failure_never_masks_first_traceback(self):
        s = self.cls()
        with patch.object(m, 'prepare_data_directory', side_effect=RuntimeError('ROOT-FIRST')):
            with patch.object(Path, 'write_text', side_effect=PermissionError('SECOND-LOG')):
                s.setup()
                self.all_callbacks(s)
        self.assertIn('ROOT-FIRST', s._last_error)
        self.assertNotIn('SECOND-LOG', s._last_error)
        self.assertIsNone(s._crash_log_path)
        self.assertIn('Could not write crash.log', self.output.getvalue())
        self.assertIn('ROOT-FIRST', self.output.getvalue())

    def test_primary_log_failure_uses_private_log_without_masking(self):
        s = self.cls()
        original = Path.write_text
        def write(path, *args, **kwargs):
            if path.parent == self.data:
                raise PermissionError('blocked-primary-log')
            return original(path, *args, **kwargs)
        with patch.object(m, 'prepare_data_directory', side_effect=RuntimeError('ROOT-FALLBACK-LOG')):
            with patch.object(Path, 'write_text', write):
                s.setup()
        self.assertEqual(s._crash_log_path, self.private / 'crash.log')
        self.assertIn('ROOT-FALLBACK-LOG', s._crash_log_path.read_text())

    def test_error_screen_failure_never_masks_first_traceback(self):
        s = self.cls()
        with patch.object(m, 'prepare_data_directory', side_effect=RuntimeError('ROOT-FIRST')):
            with patch.object(scene, 'LabelNode', side_effect=RuntimeError('SECOND-LABEL')):
                s.setup()
                self.all_callbacks(s)
        self.assertIn('ROOT-FIRST', s._last_error)
        self.assertNotIn('SECOND-LABEL', s._last_error)
        self.assertIn('Could not draw error screen', self.output.getvalue())

    def test_late_setup_failure_preserves_valid_autosave_byte_for_byte(self):
        self.data.mkdir()
        m.World.demo().save(self.data / 'autosave.json')
        before = (self.data / 'autosave.json').read_bytes()
        s = self.cls()
        with patch.object(self.cls, 'layout', side_effect=RuntimeError('ROOT-LAYOUT')):
            s.setup()
            self.all_callbacks(s)
        self.assertTrue(s._failed)
        self.assertIn('startup / layout', s._failure_report)
        self.assertEqual((self.data / 'autosave.json').read_bytes(), before)
        self.assertFalse((self.data / 'manual.json').exists())

    def test_failure_during_resize_uses_same_safe_failure_path(self):
        s = self.cls(); s.setup()
        with patch.object(s, 'layout', side_effect=RuntimeError('ROOT-RESIZE')):
            s.did_change_size()
            self.all_callbacks(s)
        self.assertTrue(s._failed)
        self.assertIn('ROOT-RESIZE', s._last_error)
        self.assertIn('Phase: resize', s._failure_report)

    def test_writable_original_save_folder_is_preferred_and_files_untouched(self):
        self.data.mkdir()
        sentinel = self.data / 'manual.json'
        sentinel.write_bytes(b'KEEP-ORIGINAL')
        path, warning = m.prepare_data_directory()
        self.assertEqual(path, self.data)
        self.assertEqual(warning, '')
        self.assertEqual(sentinel.read_bytes(), b'KEEP-ORIGINAL')
        self.assertFalse(self.private.exists())
        self.assertFalse(list(self.data.glob('.startup-check-*')))

    def test_uncreatable_original_folder_uses_private_storage_with_warning(self):
        self.data.write_bytes(b'KEEP-FILE-NOT-DIRECTORY')
        path, warning = m.prepare_data_directory()
        self.assertEqual(path, self.private)
        self.assertTrue(warning)
        self.assertEqual(self.data.read_bytes(), b'KEEP-FILE-NOT-DIRECTORY')
        self.assertIn('Active save directory:', self.output.getvalue())

    def test_readonly_original_folder_uses_fallback_without_moving_old_save(self):
        self.data.mkdir()
        sentinel = self.data / 'autosave.json'
        sentinel.write_bytes(b'KEEP-READONLY-SAVE')
        original = tempfile.NamedTemporaryFile
        def probe(*args, **kwargs):
            if Path(kwargs['dir']) == self.data:
                raise PermissionError('synthetic-readonly-provider')
            return original(*args, **kwargs)
        with patch.object(m.tempfile, 'NamedTemporaryFile', probe):
            path, warning = m.prepare_data_directory()
        self.assertEqual(path, self.private)
        self.assertTrue(warning)
        self.assertEqual(sentinel.read_bytes(), b'KEEP-READONLY-SAVE')
        self.assertFalse((self.private / 'autosave.json').exists())

    def test_both_storage_locations_fail_without_uninitialized_state(self):
        s = self.cls()
        with patch.object(m.tempfile, 'NamedTemporaryFile', side_effect=PermissionError('ALL-READONLY')):
            s.setup()
            self.all_callbacks(s)
        self.assertTrue(s._failed)
        self.assertIn('ALL-READONLY', s._last_error)
        self.assertNotIn("no attribute '_failed'", self.output.getvalue())
        self.assertFalse((self.data / 'autosave.json').exists())

    def test_storage_fallback_scene_starts_and_saves_only_to_selected_folder(self):
        self.data.write_bytes(b'KEEP-BLOCKING-FILE')
        s = self.cls(); s.setup()
        self.assertTrue(s._ready)
        self.assertFalse(s._failed)
        self.assertEqual(s.storage, self.private)
        self.assertIn('保存先', s.message)
        s.pause()
        self.assertTrue((self.private / 'autosave.json').exists())
        self.assertEqual(self.data.read_bytes(), b'KEEP-BLOCKING-FILE')

    def test_missing_runtime_file_global_does_not_break_setup_or_new_demo(self):
        old_file = m.__dict__.pop('__file__')
        try:
            s = self.cls(); s.setup()
            self.assertTrue(s._ready)
            s.world.stock['copper'] = 333
            s.perform('new'); s.perform('new')
            self.assertEqual(s.world.stock['copper'], 500)
            self.assertFalse(s._failed)
        finally:
            m.__dict__['__file__'] = old_file

    def test_config_uses_captured_script_directory(self):
        (self.tmp / 'content_overrides.json').write_text('{"duo":{"damage":18}}')
        with patch.object(m, '_SCRIPT_DIRECTORY', self.tmp):
            s = self.cls(); s.setup()
            self.assertEqual(s.world.content['duo']['damage'], 18)
            (self.tmp / 'content_overrides.json').write_text('{"duo":{"damage":21}}')
            s.perform('new'); s.perform('new')
            self.assertEqual(s.world.content['duo']['damage'], 21)

    def test_original_save_format_and_simulation_are_unchanged(self):
        self.assertEqual(m.SAVE_VERSION, 1)
        w = m.World.demo(); w.step(601)
        self.data.mkdir()
        w.save(self.data / 'autosave.json')
        s = self.cls(); s.setup()
        self.assertTrue(s._ready)
        self.assertEqual(s.world.digest(), w.digest())


if __name__ == '__main__':
    unittest.main(verbosity=2)
