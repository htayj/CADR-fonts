#!/usr/bin/env python3
"""Build twice in isolated directories and require byte-identical trees."""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "scripts" / "build.py"


def snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--omit-json", action="store_true")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="cadr-font-repro-") as directory:
        temporary = Path(directory)
        outputs = (temporary / "first", temporary / "second")
        for output in outputs:
            command = [sys.executable, str(BUILD), "--output", str(output)]
            if args.omit_json:
                command.append("--omit-json")
            subprocess.run(
                command,
                cwd=ROOT,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        first = snapshot(outputs[0])
        second = snapshot(outputs[1])
        if first.keys() != second.keys():
            missing = sorted(first.keys() - second.keys())
            added = sorted(second.keys() - first.keys())
            parser.error(f"build file sets differ; missing={missing}, added={added}")
        changed = [path for path in first if first[path] != second[path]]
        if changed:
            parser.error("non-reproducible files: " + ", ".join(changed))
    print(f"reproducible: {len(first)} files are byte-identical")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
