# SPDX-License-Identifier: GPL-3.0-only
"""Generate the standalone Pythonista script from the editable src modules.

No source is imported or executed. Only the explicit conveyor-kernel imports
are expanded, using original source text so runtime bytes remain stable.
"""
from __future__ import annotations

import argparse
import ast
import os
from pathlib import Path
import stat
import sys
import tempfile
from typing import Mapping


SOURCE_FILES = ("src/mindusnista/__init__.py", "src/mindusnista/kernels.py",
                "src/mindusnista/app.py")
SCRIPT = "mindustry_pythonista.py"
EXPORTS = ("ITEM_SPACE", "BELT_CAPACITY", "clamp", "approach",
           "conveyor_accepts", "advance_conveyor_positions")


class BundleError(ValueError):
    """Invalid editable source or an out-of-date generated script."""


def _parse(data: bytes, name: str) -> tuple[str, ast.Module]:
    text = data.decode("utf-8")
    if not text.endswith("\n") or "\r" in text:
        raise BundleError(f"Source must use LF with a final newline: {name}")
    return text, ast.parse(text, filename=name, feature_version=(3, 10))


def _docstring(node: ast.AST) -> bool:
    return (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str))


def _name(node: ast.AST) -> str | None:
    if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
        return node.name
    if (isinstance(node, ast.Assign) and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)):
        return node.targets[0].id
    return None


def render_script(snapshot: Mapping[str, bytes]) -> bytes:
    """Expand the six exports from one already-read snapshot into app.py."""
    try:
        _, package = _parse(snapshot[SOURCE_FILES[0]], SOURCE_FILES[0])
        if any(not _docstring(node) for node in package.body):
            raise BundleError("Package initializer must contain only a docstring/comments")
        kernel_text, kernel_tree = _parse(snapshot[SOURCE_FILES[1]], SOURCE_FILES[1])
        app_text, app_tree = _parse(snapshot[SOURCE_FILES[2]], SOURCE_FILES[2])
        definitions = {}
        order = []
        for node in kernel_tree.body:
            if _docstring(node):
                continue
            if isinstance(node, ast.ImportFrom):
                aliases = tuple((alias.name, alias.asname) for alias in node.names)
                allowed = {("__future__", (("annotations", None),)),
                           ("typing", (("List", None), ("Tuple", None)))}
                if node.level or (node.module, aliases) not in allowed:
                    raise BundleError("Unsupported kernel dependency; update the bundler explicitly")
                continue
            name = _name(node)
            if (name not in EXPORTS or name in definitions
                    or isinstance(node, ast.ClassDef)
                    or (isinstance(node, ast.FunctionDef) and node.decorator_list)):
                raise BundleError("Unexpected or duplicate kernel definition")
            definitions[name] = node
            order.append(name)
        if set(definitions) != set(EXPORTS):
            raise BundleError("Kernel exports are incomplete")

        kernel_lines = kernel_text.splitlines(keepends=True)
        app_lines = app_text.splitlines(keepends=True)
        imports = [node for node in ast.walk(app_tree)
                   if isinstance(node, ast.ImportFrom) and node.level]
        seen = set()
        replacements = []
        for node in imports:
            if node not in app_tree.body or node.level != 1 or node.module != "kernels":
                raise BundleError("Only top-level imports from .kernels can be bundled")
            names = [alias.name for alias in node.names]
            if (any(alias.asname for alias in node.names) or not names
                    or any(name not in definitions or name in seen for name in names)
                    or len(names) != len(set(names))):
                raise BundleError("Unknown, aliased or duplicate kernel import")
            positions = [order.index(name) for name in names]
            if positions != list(range(positions[0], positions[0] + len(positions))):
                raise BundleError("Kernel import must follow contiguous source definitions")
            # Refuse another statement after an import on the same line.
            tail = app_lines[node.end_lineno - 1][node.end_col_offset:].strip()
            if node.col_offset or (tail and not tail.startswith("#")):
                raise BundleError("Kernel import must occupy its own statement lines")
            start = definitions[names[0]].lineno - 1
            stop = definitions[names[-1]].end_lineno
            replacements.append((node.lineno - 1, node.end_lineno,
                                 "".join(kernel_lines[start:stop])))
            seen.update(names)
        if seen != set(EXPORTS):
            raise BundleError("App must import each kernel export exactly once")
        if any(_name(node) in seen for node in app_tree.body):
            raise BundleError("App still defines an imported kernel name")
        for start, stop, content in sorted(replacements, reverse=True):
            app_lines[start:stop] = [content]
        rendered = "".join(app_lines).encode("utf-8")
        _parse(rendered, SCRIPT)
        return rendered
    except BundleError:
        raise
    except (KeyError, UnicodeError, SyntaxError) as error:
        raise BundleError(str(error)) from error


def _regular_file(path: Path) -> bytes:
    for item in (path, *path.parents):
        if item.is_symlink():
            raise BundleError(f"Symbolic links are not allowed: {item}")
    if not stat.S_ISREG(path.stat().st_mode):
        raise BundleError(f"Not a regular file: {path}")
    return path.read_bytes()


def read_sources(root: Path) -> dict[str, bytes]:
    try:
        return {name: _regular_file(Path(root).absolute() / name) for name in SOURCE_FILES}
    except (OSError, UnicodeError) as error:
        raise BundleError(str(error)) from error


def check_generated(root: Path) -> None:
    """Check without repairing: stale artifacts must fail tests and releases."""
    try:
        expected = render_script(read_sources(root))
        if _regular_file(Path(root).absolute() / SCRIPT) != expected:
            raise BundleError("Generated script is stale; run python tools/build_single_file.py")
    except OSError as error:
        raise BundleError(str(error)) from error


def write_generated(root: Path) -> Path:
    """Atomically regenerate only the fixed root artifact, preserving mode."""
    temporary = None
    try:
        root = Path(root).absolute()
        expected = render_script(read_sources(root))
        destination = root / SCRIPT
        if destination.is_symlink():
            raise BundleError("Generated output must not be a symbolic link")
        mode = 0o644
        if destination.exists():
            old = _regular_file(destination)
            if old == expected:
                return destination
            mode = stat.S_IMODE(destination.stat().st_mode)
        fd, name = tempfile.mkstemp(prefix=".mindusnista-generated-", suffix=".tmp", dir=root)
        temporary = Path(name)
        with os.fdopen(fd, "wb") as stream:
            stream.write(expected)
        temporary.chmod(mode)
        os.replace(temporary, destination)
        return destination
    except (OSError, UnicodeError) as error:
        raise BundleError(str(error)) from error
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Check the artifact without writing")
    args = parser.parse_args(argv)
    root = Path(__file__).absolute().parents[1]
    try:
        if args.check:
            check_generated(root)
            print("Generated standalone script: up to date")
        else:
            print(write_generated(root))
    except BundleError as error:
        print(f"Single-file build failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
