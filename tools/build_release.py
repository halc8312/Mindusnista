# SPDX-License-Identifier: GPL-3.0-only
"""Build a deterministic Pythonista file and source archive without executing it.

Only the reviewed paths in tools/release_files.txt are read. Existing output is
never overwritten: an identical build is a no-op; otherwise choose a new path.
This tool needs only Python 3.10's standard library and works outside Git too.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import io
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import zipfile


MANIFEST = "tools/release_files.txt"
SCRIPT = "mindustry_pythonista.py"
REQUIRED_FILES = frozenset({
    SCRIPT, "LICENSE", "NOTICE.md", "SOURCES.md", "README.md", "README_ja.md",
    "tools/build_release.py", MANIFEST, "tools/check_project.py",
    "tests/test_release_packaging.py", "reference/ConveyorKernelReference.java",
    "reference/java_fixtures.json",
})
EXCLUDED_PARTS = frozenset({
    ".git", "dist", "__pycache__", ".pytest_cache", ".dist-cache", ".venv",
    "venv", "node_modules", "htmlcov", "_mindustry_pythonista", "saves",
    "save", "logs", "credentials", "secrets",
})
EXCLUDED_NAMES = frozenset({
    "content_overrides.json", "autosave.json", "manual.json", "user_config.json",
    "credentials.json", "secrets.json", "token.json", "token.txt",
    "id_rsa", "id_ed25519",
})
EXCLUDED_SUFFIXES = frozenset({
    ".pyc", ".pyo", ".class", ".log", ".tmp", ".pem", ".key", ".p12",
    ".pfx", ".zip", ".sqlite", ".db",
})
ALLOWED_DOT_PARTS = frozenset({".github", ".gitattributes", ".gitignore"})


class ReleaseError(ValueError):
    """Invalid source selection or an output that cannot be used safely."""


def _no_symlinks(path: Path) -> None:
    # Check lexical ancestors before resolve() can hide a symlink.
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ReleaseError(f"Symbolic links are not allowed: {part}")


def _regular_bytes(path: Path) -> bytes:
    _no_symlinks(path)
    if not stat.S_ISREG(path.stat().st_mode):
        raise ReleaseError(f"Not a regular source file: {path}")
    return path.read_bytes()


def _source_snapshot(root: Path) -> dict[str, bytes]:
    manifest_bytes = _regular_bytes(root / MANIFEST)
    names = set()
    portable_names = set()
    for number, name in enumerate(manifest_bytes.decode("utf-8").splitlines(), 1):
        if not name.strip() or name.startswith("#"):
            continue
        relative = PurePosixPath(name)
        if (name != name.strip() or "\\" in name or ":" in name
                or relative.is_absolute() or relative.as_posix() != name
                or ".." in relative.parts or not relative.parts
                or any(ord(char) < 32 or ord(char) == 127 for char in name)):
            raise ReleaseError(f"Invalid manifest path at line {number}: {name!r}")
        if name.casefold() in portable_names:
            raise ReleaseError(f"Duplicate or case-colliding manifest path: {name}")
        lowered = tuple(part.casefold() for part in relative.parts)
        if (any(part in EXCLUDED_PARTS for part in lowered)
                or any(part.startswith(".") and part not in ALLOWED_DOT_PARTS
                       for part in lowered)
                or relative.name.casefold() in EXCLUDED_NAMES
                or relative.suffix.casefold() in EXCLUDED_SUFFIXES):
            raise ReleaseError(f"Private/generated path is not distributable: {name}")
        names.add(name)
        portable_names.add(name.casefold())
    missing = REQUIRED_FILES - names
    if missing:
        raise ReleaseError("Manifest omits required files: " + ", ".join(sorted(missing)))
    # Include exactly the manifest that selected these files, even if its on-disk
    # copy is edited while another process is building.
    return {name: manifest_bytes if name == MANIFEST else _regular_bytes(root / name)
            for name in sorted(names)}


def _version(script: bytes) -> str:
    tree = ast.parse(script.decode("utf-8"), filename=SCRIPT, feature_version=(3, 10))
    assignments = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if any(isinstance(target, ast.Name) and target.id == "VERSION"
                   for target in node.targets):
                assignments.append(node.value)
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == "VERSION":
                assignments.append(node.value)
    version_writes = sum(isinstance(node, ast.Name) and node.id == "VERSION"
                         and isinstance(node.ctx, ast.Store) for node in ast.walk(tree))
    if (len(assignments) != 1 or version_writes != 1
            or not isinstance(assignments[0], ast.Constant)):
        raise ReleaseError("Source must define VERSION once as a string literal")
    value = assignments[0].value
    if not isinstance(value, str) or not re.fullmatch(
            r"[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9]+(?:[.-][A-Za-z0-9]+)*)?", value):
        raise ReleaseError("VERSION is not a safe release version")
    return value


def _payloads(snapshot: dict[str, bytes]) -> tuple[str, dict[str, bytes]]:
    version = _version(snapshot[SCRIPT])
    archive_name = f"Mindusnista-{version}-source.zip"
    buffer = io.BytesIO()
    # Stored bytes avoid a dependency on the host's zlib version. The source
    # archive is small; stable metadata is more useful here than compression.
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, content in sorted(snapshot.items()):
            info = zipfile.ZipInfo("Mindusnista/" + name, (1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            info.compress_type = zipfile.ZIP_STORED
            archive.writestr(info, content)
    payloads = {SCRIPT: snapshot[SCRIPT], archive_name: buffer.getvalue()}
    payloads["SHA256SUMS.txt"] = "".join(
        f"{hashlib.sha256(content).hexdigest()}  {name}\n"
        for name, content in sorted(payloads.items())
    ).encode("ascii")
    return archive_name, payloads


def _output_path(root: Path, output: Path | None) -> Path:
    path = root / "dist" if output is None else Path(output).absolute()
    _no_symlinks(path)
    path = path.resolve()
    if path == root or path in root.parents:
        raise ReleaseError("Output must not be the source root or its ancestor")
    if root in path.parents and path.relative_to(root).parts[0] != "dist":
        raise ReleaseError("Output inside the source tree must be under dist/")
    return path


def build_release(root: Path, output: Path | None = None) -> dict[str, Path]:
    """Read a source snapshot and publish three files in an unused directory.

    No source file is imported or executed. Source files are not changed.
    Existing output must match this build exactly; differing or unrelated files
    are refused before writing. To rebuild changed input, use a fresh output.
    """
    try:
        root = Path(root).absolute()
        _no_symlinks(root)
        root = root.resolve(strict=True)
        if not root.is_dir():
            raise ReleaseError("Source root must be a directory")
        destination = _output_path(root, output)
        archive_name, payloads = _payloads(_source_snapshot(root))
        result = {"script": destination / SCRIPT,
                  "source_zip": destination / archive_name,
                  "checksums": destination / "SHA256SUMS.txt"}
        if destination.exists():
            if (not destination.is_dir()
                    or {entry.name for entry in destination.iterdir()} != set(payloads)):
                raise ReleaseError("Output already exists; select a new unused directory")
            for name, data in payloads.items():
                if _regular_bytes(destination / name) != data:
                    raise ReleaseError("Output differs; select a new unused directory")
            return result

        destination.parent.mkdir(parents=True, exist_ok=True)
        _no_symlinks(destination)
        # Reserve an unused directory atomically. In particular, do not rename
        # onto a directory another build may have created after our check.
        destination.mkdir()
        for name, data in payloads.items():
            # Exclusive creation also protects any file that appears meanwhile.
            # Leave partial output on I/O failure; never delete someone else's
            # concurrent data. Checksums are written last, after both artifacts.
            with (destination / name).open("xb") as stream:
                stream.write(data)
        return result
    except ReleaseError:
        raise
    except (OSError, UnicodeError, SyntaxError, zipfile.BadZipFile) as error:
        raise ReleaseError(str(error)) from error


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path,
                        help="Unused output directory (default: project dist/)")
    args = parser.parse_args(argv)
    try:
        result = build_release(Path(__file__).absolute().parents[1], args.output)
    except ReleaseError as error:
        print(f"Release build failed: {error}", file=sys.stderr)
        return 1
    for name in ("script", "source_zip", "checksums"):
        print(result[name])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
