# SPDX-License-Identifier: GPL-3.0-only
"""Release artifacts and data-preservation regressions; no Pythonista required."""
from __future__ import annotations

import ast
import hashlib
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.build_release import ReleaseError, build_release


REQUIRED_FILES = (
    "mindustry_pythonista.py", "LICENSE", "NOTICE.md", "SOURCES.md", "README.md",
    "README_ja.md", "tools/build_release.py", "tools/release_files.txt",
    "tools/check_project.py", "tests/test_release_packaging.py",
    "reference/ConveyorKernelReference.java", "reference/java_fixtures.json",
)


def tree_snapshot(path: Path) -> dict:
    """Include bytes, link targets and mtimes to detect destructive retries."""
    paths = [path]
    if path.is_dir() and not path.is_symlink():
        paths.extend(sorted(path.rglob("*")))
    result = {}
    for item in paths:
        info = item.lstat()
        if item.is_symlink():
            content = ("link", os.readlink(item))
        elif item.is_file():
            content = ("file", item.read_bytes())
        else:
            content = ("directory",)
        result[str(item.relative_to(path))] = (
            info.st_mode, info.st_mtime_ns, content,
        )
    return result


class ReleasePackagingTests(unittest.TestCase):
    def setUp(self):
        # Sandboxes may select the repository itself as tempfile's fallback.
        # The real-project check deliberately needs an output outside its tree.
        self.temporary = tempfile.TemporaryDirectory(
            prefix="mindusnista-release-", dir=ROOT.parent,
        )
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / "source"
        self.root.mkdir()
        self.files = list(REQUIRED_FILES) + ["docs/配布メモ.md", ".github/workflows/ci.yml", ".gitignore"]
        for name in self.files:
            destination = self.root / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text("fixture: " + name + "\n", encoding="utf-8")
        # Packaging must read this literal without importing or running the file.
        self.script = self.root / "mindustry_pythonista.py"
        self.script.write_text(
            'VERSION = "0.1.2-dev"\nraise RuntimeError("do not execute during packaging")\n',
            encoding="utf-8",
        )
        shutil.copyfile(ROOT / "tools/build_release.py", self.root / "tools/build_release.py")
        self.manifest = self.root / "tools/release_files.txt"
        self.write_manifest()

    def write_manifest(self, names=None):
        names = self.files if names is None else names
        self.manifest.write_text(
            "# Explicit release sources\n\n" + "\n".join(names) + "\n",
            encoding="utf-8",
        )

    def assert_release_rejected(self, output=None):
        output = self.root / "dist" if output is None else output
        with self.assertRaises(ReleaseError):
            build_release(self.root, output)
        self.assertFalse(output.exists(), "Invalid sources must not create an output")

    def test_artifacts_preserve_sources_licenses_and_fixed_zip_metadata(self):
        result = build_release(self.root)
        self.assertEqual(set(result), {"script", "source_zip", "checksums"})
        self.assertEqual(result["script"], self.root / "dist/mindustry_pythonista.py")
        self.assertEqual(result["source_zip"].name, "Mindusnista-0.1.2-dev-source.zip")
        self.assertEqual(result["checksums"].name, "SHA256SUMS.txt")
        self.assertEqual(result["script"].read_bytes(), self.script.read_bytes())
        self.assertEqual(set((self.root / "dist").iterdir()), set(result.values()))
        with zipfile.ZipFile(result["source_zip"]) as archive:
            self.assertEqual(archive.namelist(), ["Mindusnista/" + p for p in sorted(self.files)])
            for member in archive.infolist():
                with self.subTest(member=member.filename):
                    relative = member.filename.removeprefix("Mindusnista/")
                    self.assertEqual(archive.read(member), (self.root / relative).read_bytes())
                    self.assertEqual(member.date_time, (1980, 1, 1, 0, 0, 0))
                    self.assertEqual(member.compress_type, zipfile.ZIP_STORED)
                    self.assertEqual(stat.S_IMODE(member.external_attr >> 16), 0o644)
        checksum_lines = result["checksums"].read_text(encoding="ascii").splitlines()
        self.assertEqual(len(checksum_lines), 2)
        checksums = dict(line.split("  ", 1)[::-1] for line in checksum_lines)
        expected = {
            result[key].name: hashlib.sha256(result[key].read_bytes()).hexdigest()
            for key in ("script", "source_zip")
        }
        self.assertEqual(checksums, expected)

    def test_reproducible_across_source_mtime_mode_and_output_directory(self):
        first = build_release(self.root, self.base / "first")
        for name in self.files:
            path = self.root / name
            os.utime(path, (946684800, 946684800))
            path.chmod(0o600)
        second = build_release(self.root, self.root / "dist/nested/release")
        self.assertEqual(
            {key: path.read_bytes() for key, path in first.items()},
            {key: path.read_bytes() for key, path in second.items()},
        )

    def test_identical_existing_release_is_returned_without_rewriting(self):
        expected = build_release(self.root)
        before = tree_snapshot(self.root / "dist")
        self.assertEqual(build_release(self.root), expected)
        self.assertEqual(tree_snapshot(self.root / "dist"), before)

    def test_unlisted_files_never_enter_source_zip(self):
        for name in ("notes.txt", ".env", ".git/config", "saves/player.json",
                     "__pycache__/module.pyc", "startup.log", "user_config.json"):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("private data must remain local", encoding="utf-8")
        result = build_release(self.root)
        with zipfile.ZipFile(result["source_zip"]) as archive:
            self.assertEqual(set(archive.namelist()), {"Mindusnista/" + p for p in self.files})

    def test_manifest_must_include_each_required_source(self):
        for required in REQUIRED_FILES:
            with self.subTest(required=required):
                self.write_manifest([name for name in self.files if name != required])
                self.assert_release_rejected()

    def test_manifest_rejects_ambiguous_duplicate_and_escaping_paths(self):
        outside = self.base / "outside.txt"
        outside.write_text("outside the source tree", encoding="utf-8")
        for name in ("docs/note.md", "docs\\note.md", "C:/private.txt"):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("must not bypass manifest validation", encoding="utf-8")
        for entry in ("README.md", "../outside.txt", str(outside), "./README.md",
                      "docs/../README.md", "docs//note.md", "docs\\note.md",
                      "C:/private.txt", "docs/", "name\x00.txt"):
            with self.subTest(entry=entry):
                self.write_manifest(self.files + [entry])
                self.assert_release_rejected()

    def test_casefold_colliding_manifest_files_are_rejected(self):
        (self.root / "readme.md").write_text("different source file\n", encoding="utf-8")
        self.write_manifest(self.files + ["readme.md"])
        self.assert_release_rejected()

    def test_missing_or_nonregular_manifest_source_does_not_create_output(self):
        for kind in ("missing", "directory"):
            with self.subTest(kind=kind):
                path = self.root / "docs/missing.md"
                if kind == "directory":
                    path.mkdir()
                self.write_manifest(self.files + ["docs/missing.md"])
                self.assert_release_rejected()

    def test_explicitly_listed_private_or_generated_paths_are_rejected(self):
        excluded = (
            ".git/config", "dist/old-release.py", "__pycache__/cached.pyc",
            "saves/player.json", ".env", "credentials.json", "user_config.json", "startup.log",
        )
        for name in excluded:
            with self.subTest(name=name):
                path = self.root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("private data", encoding="utf-8")
                self.write_manifest(self.files + [name])
                # A listed dist file already created the default directory.
                self.assert_release_rejected(self.base / "rejected-output")

    def test_source_symlinks_and_symlinked_parents_are_rejected(self):
        external = self.base / "external"
        external.mkdir()
        (external / "data.md").write_text("external data", encoding="utf-8")
        link = self.root / "linked.md"
        link.symlink_to(external / "data.md")
        self.write_manifest(self.files + ["linked.md"])
        self.assert_release_rejected()
        link.unlink()
        (self.root / "linked").symlink_to(external, target_is_directory=True)
        self.write_manifest(self.files + ["linked/data.md"])
        self.assert_release_rejected()

    def test_symlinked_manifest_is_rejected(self):
        actual = self.base / "actual-manifest.txt"
        self.manifest.replace(actual)
        self.manifest.symlink_to(actual)
        self.assert_release_rejected()

    def test_source_root_ancestors_and_other_source_directories_are_not_outputs(self):
        for output in (self.root, self.base, self.root / "tests", self.root / "new-output"):
            with self.subTest(output=output):
                before = tree_snapshot(self.root)
                with self.assertRaises(ReleaseError):
                    build_release(self.root, output)
                self.assertEqual(tree_snapshot(self.root), before)

    def test_empty_nonempty_or_file_output_is_never_overwritten(self):
        for kind in ("empty", "user-files", "file"):
            with self.subTest(kind=kind):
                output = self.base / kind
                if kind == "file":
                    output.write_bytes(b"user file")
                else:
                    output.mkdir()
                    if kind == "user-files":
                        (output / "save.json").write_bytes(b'{"schema": 1}')
                before = tree_snapshot(output)
                with self.assertRaises(ReleaseError):
                    build_release(self.root, output)
                self.assertEqual(tree_snapshot(output), before)

    def test_output_created_during_build_keeps_user_save_and_gets_no_artifacts(self):
        output = self.base / "concurrent-release"
        original_mkdir = Path.mkdir
        created = {}

        def competing_mkdir(path, *args, **kwargs):
            if path == output and not created:
                original_mkdir(output)
                (output / "user-save.json").write_bytes(b'{"schema": 1, "keep": true}')
                created["snapshot"] = tree_snapshot(output)
            return original_mkdir(path, *args, **kwargs)

        with patch.object(Path, "mkdir", new=competing_mkdir):
            with self.assertRaises(ReleaseError):
                build_release(self.root, output)
        self.assertIn("snapshot", created, "The competing directory creation must run")
        self.assertEqual(tree_snapshot(output), created["snapshot"])
        self.assertEqual({path.name for path in output.iterdir()}, {"user-save.json"})

    def test_changed_or_additional_release_files_are_never_overwritten(self):
        for kind in ("changed", "extra"):
            with self.subTest(kind=kind):
                output = self.base / kind
                result = build_release(self.root, output)
                if kind == "changed":
                    result["script"].write_bytes(b"edited by user\n")
                else:
                    (output / "save.json").write_bytes(b'{"schema": 1}')
                before = tree_snapshot(output)
                with self.assertRaises(ReleaseError):
                    build_release(self.root, output)
                self.assertEqual(tree_snapshot(output), before)

    def test_changed_source_does_not_reuse_or_replace_an_older_release(self):
        build_release(self.root)
        before = tree_snapshot(self.root / "dist")
        (self.root / "README.md").write_text("new source revision\n", encoding="utf-8")
        with self.assertRaises(ReleaseError):
            build_release(self.root)
        self.assertEqual(tree_snapshot(self.root / "dist"), before)

    def test_output_symlink_and_symlinked_parent_leave_destination_untouched(self):
        external = self.base / "external"
        external.mkdir()
        (external / "save.json").write_bytes(b"keep this")
        link = self.base / "output-link"
        link.symlink_to(external, target_is_directory=True)
        for output in (link, link / "new-release"):
            with self.subTest(output=output):
                before = tree_snapshot(external)
                with self.assertRaises(ReleaseError):
                    build_release(self.root, output)
                self.assertEqual(tree_snapshot(external), before)
                self.assertTrue(link.is_symlink())

    def test_even_matching_output_symlink_is_rejected_without_changing_target(self):
        result = build_release(self.root)
        target = self.base / "matching-script.py"
        result["script"].replace(target)
        result["script"].symlink_to(target)
        before = tree_snapshot(self.root / "dist")
        target_before = tree_snapshot(target)
        with self.assertRaises(ReleaseError):
            build_release(self.root)
        self.assertEqual(tree_snapshot(self.root / "dist"), before)
        self.assertEqual(tree_snapshot(target), target_before)

    def test_version_must_be_a_safe_unambiguous_literal(self):
        for index, script in enumerate((
            'VERSION = "0.1." + "2-dev"\n',
            'VERSION = "../outside"\n',
            'VERSION = 12\n',
            'VERSION = "0.1.2-dev"\nVERSION = "0.1.3-dev"\n',
            'VERSION = "0.1.2-dev"\nVERSION += "-changed"\n',
            'OTHER = "0.1.2-dev"\n',
            'VERSION = (\n',
        )):
            with self.subTest(script=script):
                self.script.write_text(script, encoding="utf-8")
                self.assert_release_rejected(self.base / f"invalid-version-{index}")

    def test_cli_runs_from_other_working_directory_and_reports_validation_error(self):
        builder = self.root / "tools/build_release.py"
        completed = subprocess.run(
            [sys.executable, str(builder)], cwd=self.base, capture_output=True,
            text=True, timeout=30,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertTrue((self.root / "dist/mindustry_pythonista.py").is_file())
        outside = self.base / "cli-output"
        completed = subprocess.run(
            [sys.executable, str(builder), "--output", str(outside)], cwd=self.base,
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        (outside / "private.txt").write_bytes(b"keep")
        before = tree_snapshot(outside)
        completed = subprocess.run(
            [sys.executable, str(builder), "--output", str(outside)], cwd=self.base,
            capture_output=True, text=True, timeout=30,
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(tree_snapshot(outside), before)

    def test_real_release_self_test_and_unpacked_rebuild(self):
        output = self.base / "real-release"
        result = build_release(ROOT, output)
        self.assertEqual(result["script"].read_bytes(), (ROOT / "mindustry_pythonista.py").read_bytes())
        ast.parse(result["script"].read_text(encoding="utf-8"), feature_version=(3, 10))
        completed = subprocess.run(
            [sys.executable, str(result["script"]), "--self-test"], cwd=self.base,
            capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        with zipfile.ZipFile(result["source_zip"]) as archive:
            archive.extractall(self.base / "unpacked")
        unpacked = self.base / "unpacked/Mindusnista"
        rebuilt_output = self.base / "rebuilt"
        completed = subprocess.run(
            [sys.executable, str(unpacked / "tools/build_release.py"),
             "--output", str(rebuilt_output)], cwd=self.base, capture_output=True,
            text=True, timeout=30,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        for original in result.values():
            self.assertEqual((rebuilt_output / original.name).read_bytes(), original.read_bytes())


if __name__ == "__main__":
    unittest.main()
