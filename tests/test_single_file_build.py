# SPDX-License-Identifier: GPL-3.0-only
"""Single-file generation regressions; these do not exercise Pythonista."""
from __future__ import annotations

import ast
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.build_single_file import (
    BundleError, SOURCE_FILES, check_generated, read_sources, render_script,
    write_generated,
)

APP = "src/mindusnista/app.py"
KERNELS = "src/mindusnista/kernels.py"
GROUPS = (
    b"from .kernels import ITEM_SPACE, BELT_CAPACITY",
    b"from .kernels import clamp, approach",
    b"from .kernels import conveyor_accepts, advance_conveyor_positions",
)


def file_state(root: Path) -> dict:
    """Track content and mtimes, including link identity, for non-writing checks."""
    result = {}
    for path in sorted(root.rglob("*")):
        info = path.lstat()
        if path.is_symlink():
            value = ("link", os.readlink(path))
        elif path.is_file():
            value = ("file", path.read_bytes())
        else:
            value = ("directory",)
        result[path.relative_to(root).as_posix()] = (info.st_mode, info.st_mtime_ns, value)
    return result


class SingleFileBuildTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(
            prefix="mindusnista-bundle-", dir=ROOT.parent,
        )
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / "source"
        self.root.mkdir()
        self.snapshot = read_sources(ROOT)
        for name, data in self.snapshot.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        self.script = self.root / "mindustry_pythonista.py"
        self.generated = render_script(self.snapshot)
        self.script.write_bytes(self.generated)

    def run_python(self, *args, timeout=60):
        return subprocess.run(
            [sys.executable, *map(str, args)], cwd=self.base,
            capture_output=True, text=True, timeout=timeout,
        )

    def assert_succeeded(self, completed):
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def copy_tool(self, name):
        target = self.root / "tools" / name
        target.parent.mkdir(exist_ok=True)
        shutil.copyfile(ROOT / "tools" / name, target)
        return target

    def test_real_sources_generate_current_script_deterministically(self):
        before = dict(self.snapshot)
        reversed_snapshot = dict(reversed(list(self.snapshot.items())))
        self.assertEqual(set(self.snapshot), set(SOURCE_FILES))
        self.assertEqual(render_script(reversed_snapshot), self.generated)
        self.assertEqual(render_script(self.snapshot), self.generated)
        self.assertEqual(self.snapshot, before)
        self.assertEqual(self.generated, (ROOT / "mindustry_pythonista.py").read_bytes())
        ast.parse(self.generated.decode("utf-8"), feature_version=(3, 10))

    def test_render_reads_source_without_executing_application(self):
        snapshot = dict(self.snapshot)
        sentinel = b'\nraise RuntimeError("must not execute while building")\n'
        snapshot[APP] += sentinel
        self.assertTrue(render_script(snapshot).endswith(sentinel))

    def test_missing_source_and_invalid_python_are_rejected(self):
        for name in SOURCE_FILES:
            with self.subTest(missing=name):
                snapshot = dict(self.snapshot)
                del snapshot[name]
                with self.assertRaises(BundleError):
                    render_script(snapshot)
        for name in (APP, KERNELS):
            with self.subTest(syntax=name):
                snapshot = dict(self.snapshot)
                snapshot[name] += b"\ndef invalid(:\n"
                with self.assertRaises(BundleError):
                    render_script(snapshot)
        (self.root / KERNELS).unlink()
        with self.assertRaises(BundleError):
            read_sources(self.root)

    def test_unsupported_relative_imports_are_rejected(self):
        alternatives = (
            b"from .unknown import clamp, approach",
            b"from ..kernels import clamp, approach",
            b"from .kernels import clamp as renamed, approach",
            b"from .kernels import *",
            b"from .kernels import unknown, approach",
        )
        for replacement in alternatives:
            with self.subTest(replacement=replacement):
                snapshot = dict(self.snapshot)
                self.assertEqual(snapshot[APP].count(GROUPS[1]), 1)
                snapshot[APP] = snapshot[APP].replace(GROUPS[1], replacement)
                with self.assertRaises(BundleError):
                    render_script(snapshot)

    def test_missing_or_repeated_import_groups_are_rejected(self):
        for group in GROUPS:
            for replacement in (b"", group + b"\n" + group):
                with self.subTest(group=group, replacement=replacement):
                    snapshot = dict(self.snapshot)
                    snapshot[APP] = snapshot[APP].replace(group, replacement)
                    with self.assertRaises(BundleError):
                        render_script(snapshot)

    def test_missing_or_duplicate_kernel_definitions_are_rejected(self):
        for replacement in (
            self.snapshot[KERNELS].replace(b"def clamp(", b"def renamed_clamp("),
            self.snapshot[KERNELS] + b"\ndef clamp(value, lo, hi):\n    return value\n",
        ):
            with self.subTest(replacement=replacement[-100:]):
                snapshot = dict(self.snapshot)
                snapshot[KERNELS] = replacement
                with self.assertRaises(BundleError):
                    render_script(snapshot)

    def test_check_is_read_only_for_matching_stale_and_missing_output(self):
        before = file_state(self.root)
        self.assertIsNone(check_generated(self.root))
        self.assertEqual(file_state(self.root), before)
        for state in ("stale", "missing"):
            with self.subTest(state=state):
                if state == "stale":
                    self.script.write_bytes(b"# old generated file\n")
                else:
                    self.script.unlink()
                before = file_state(self.root)
                with self.assertRaises(BundleError):
                    check_generated(self.root)
                self.assertEqual(file_state(self.root), before)

    def test_regeneration_reflects_source_edit_and_identical_retry_does_not_write(self):
        kernel = self.root / KERNELS
        original = kernel.read_bytes()
        self.assertEqual(original.count(b"ITEM_SPACE = 0.4"), 1)
        kernel.write_bytes(original.replace(b"ITEM_SPACE = 0.4", b"ITEM_SPACE = 0.35"))
        with self.assertRaises(BundleError):
            check_generated(self.root)
        self.assertEqual(write_generated(self.root), self.script)
        updated = self.script.read_bytes()
        self.assertNotEqual(updated, self.generated)
        self.assertIn(b"ITEM_SPACE = 0.35", updated)
        self.assertEqual(updated, render_script(read_sources(self.root)))
        check_generated(self.root)
        before = file_state(self.root)
        self.assertEqual(write_generated(self.root), self.script)
        self.assertEqual(file_state(self.root), before)

    def test_symlink_and_nonregular_outputs_are_preserved(self):
        outside = self.base / "user-file.py"
        outside.write_bytes(self.generated)
        self.script.unlink()
        self.script.symlink_to(outside)
        for operation in (check_generated, write_generated):
            with self.subTest(operation=operation.__name__):
                before = file_state(self.base)
                with self.assertRaises(BundleError):
                    operation(self.root)
                self.assertEqual(file_state(self.base), before)
        self.script.unlink()
        self.script.mkdir()
        (self.script / "save.json").write_bytes(b'{"schema": 1}')
        before = file_state(self.base)
        with self.assertRaises(BundleError):
            write_generated(self.root)
        self.assertEqual(file_state(self.base), before)

    def test_failed_atomic_replace_preserves_old_output_and_removes_temporary_file(self):
        self.script.write_bytes(b"# previous complete output\n")
        before = {name: value for name, value in file_state(self.root).items()
                  if value[2][0] != "directory"}
        with patch("tools.build_single_file.os.replace", side_effect=OSError("write failure")):
            with self.assertRaises((BundleError, OSError)):
                write_generated(self.root)
        after = {name: value for name, value in file_state(self.root).items()
                 if value[2][0] != "directory"}
        self.assertEqual(after, before)

    def test_generated_file_imports_and_self_tests_without_source_package(self):
        standalone = self.base / "standalone"
        standalone.mkdir()
        script = standalone / self.script.name
        script.write_bytes(self.generated)
        code = (
            "import importlib.util, pathlib, sys; "
            "path = pathlib.Path(sys.argv[1]); "
            "spec = importlib.util.spec_from_file_location('standalone_game', path); "
            "game = importlib.util.module_from_spec(spec); "
            "sys.modules[spec.name] = game; spec.loader.exec_module(game); "
            "assert game.SAVE_VERSION == 1; "
            "assert game._SCRIPT_DIRECTORY == path.parent; "
            "assert not any(n == 'mindusnista' or n.startswith('mindusnista.') "
            "for n in sys.modules); "
            "assert 'scene' not in sys.modules and 'ui' not in sys.modules"
        )
        self.assert_succeeded(self.run_python("-I", "-c", code, script))
        self.assert_succeeded(self.run_python("-I", script, "--self-test"))

    def test_development_kernels_and_standalone_match_existing_conveyor_fixtures(self):
        spec = importlib.util.spec_from_file_location("bundle_test_kernels", ROOT / KERNELS)
        kernels = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(kernels)
        import mindustry_pythonista as standalone
        fixtures = json.loads((ROOT / "reference/java_fixtures.json").read_text(encoding="utf-8"))
        for case in fixtures["acceptance"]:
            args = (case["minimum"], case["count"], case["incoming"],
                    case["rotation"], case["rotates"], case["front"])
            self.assertEqual(kernels.conveyor_accepts(*args), standalone.conveyor_accepts(*args))
        for case in fixtures["movement"]:
            dev_y, dev_x = case["ys"], case["xs"]
            out_y, out_x = case["ys"], case["xs"]
            for _ in range(case["steps"]):
                tail = (case["speed"], case["next_minimum"], case["aligned"])
                dev_y, dev_x = kernels.advance_conveyor_positions(dev_y, dev_x, *tail)
                out_y, out_x = standalone.advance_conveyor_positions(out_y, out_x, *tail)
            self.assertEqual((dev_y, dev_x), (out_y, out_x))

    def test_cli_checks_without_repair_and_regenerates_from_another_directory(self):
        builder = self.copy_tool("build_single_file.py")
        self.assert_succeeded(self.run_python(builder, "--check"))
        self.script.write_bytes(b"# stale output\n")
        before = file_state(self.root)
        checked = self.run_python(builder, "--check")
        self.assertNotEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertEqual(file_state(self.root), before)
        self.assert_succeeded(self.run_python(builder))
        self.assertEqual(self.script.read_bytes(), self.generated)
        self.assert_succeeded(self.run_python(builder, "--check"))

    def test_project_check_rejects_an_unregenerated_source_edit(self):
        self.copy_tool("build_single_file.py")
        checker = self.copy_tool("check_project.py")
        # A passing control prevents test discovery failures from masking the gate.
        tests = self.root / "tests"
        tests.mkdir()
        (tests / "test_control.py").write_text(
            "import unittest\n"
            "import mindustry_pythonista as game\n"
            "class Control(unittest.TestCase):\n"
            "    def test_standalone_import(self):\n"
            "        self.assertEqual(game.SAVE_VERSION, 1)\n",
            encoding="utf-8",
        )
        self.assert_succeeded(self.run_python(checker))
        app = self.root / APP
        app.write_bytes(app.read_bytes() + b"\n# source edit not yet regenerated\n")
        before = self.script.read_bytes()
        checked = self.run_python(checker)
        self.assertNotEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertEqual(self.script.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
