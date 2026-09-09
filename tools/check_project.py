# SPDX-License-Identifier: GPL-3.0-only
"""Run PC-side checks. Does not run Pythonista or operate an iPhone."""
from __future__ import annotations
import ast
from pathlib import Path
import platform
import subprocess
import sys


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    print("Interpreter:", sys.version.replace("\n", " "), flush=True)
    print("OS:", platform.platform(), flush=True)
    try:
        files = ([root / "mindustry_pythonista.py"]
                 + list((root / "tests").glob("*.py"))
                 + list((root / "tools").glob("*.py")))
        for path in files:
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path), feature_version=(3, 10))
        print("Python 3.10 syntax: PASS (not a Python 3.10 runtime test)", flush=True)
        for args in (("-m", "unittest", "discover", "-s", "tests", "-v"),
                     ("mindustry_pythonista.py", "--self-test")):
            subprocess.run([sys.executable, *args], cwd=root, check=True, timeout=180)
    except (SyntaxError, OSError, subprocess.SubprocessError) as error:
        print("CHECK FAILED:", error, file=sys.stderr)
        return 1
    print("PC checks passed. iPhone/Pythonista testing is still a separate step.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
