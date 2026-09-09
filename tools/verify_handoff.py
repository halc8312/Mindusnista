# SPDX-License-Identifier: GPL-3.0-only
"""Verify the original handoff snapshot before editing. No network or writes."""
from __future__ import annotations
import hashlib
from pathlib import Path, PurePosixPath
import re
import sys


def verify(root: Path) -> int:
    root = root.resolve()
    manifest = root / "HANDOFF_SHA256SUMS.txt"
    try:
        entries = manifest.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        print("Cannot read handoff manifest:", exc, file=sys.stderr)
        return 1
    count = 0
    failures = []
    seen = set()
    for number, line in enumerate(entries, 1):
        if not line.strip() or line.startswith("#"):
            continue
        try:
            expected, name = line.split("  ", 1)
            rel = PurePosixPath(name)
            if (not re.fullmatch(r"[0-9a-f]{64}", expected)
                    or not name or name in seen or "\\" in name
                    or rel.is_absolute() or ".." in rel.parts
                    or ":" in name):
                raise ValueError("invalid or duplicate manifest entry")
            seen.add(name)
            path = root.joinpath(*rel.parts)
            resolved = path.resolve()
            if root not in resolved.parents:
                raise ValueError("path is outside project root")
            if path.is_symlink() or not path.is_file():
                raise ValueError("missing, non-regular or symbolic file")
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual != expected:
                raise ValueError("SHA256 mismatch")
            count += 1
        except (OSError, ValueError) as exc:
            failures.append(f"line {number}: {exc}")
    if not count and not failures:
        failures.append("empty manifest")
    if failures:
        for failure in failures:
            print(failure, file=sys.stderr)
        print("Snapshot verification FAILED; intentional later edits also change hashes.", file=sys.stderr)
        return 1
    print(f"Handoff snapshot verified: {count} files. Additional files are not checked.")
    print("This is an integrity check, not an authenticity or device-execution guarantee.")
    return 0


def main() -> int:
    return verify(Path(__file__).resolve().parents[1])


if __name__ == "__main__":
    raise SystemExit(main())
