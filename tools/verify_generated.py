#!/usr/bin/env python3
"""Verify checked-in generated/duplicated distribution artifacts."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUTHOR = ROOT / "skills/okf-author/scripts/okf.py"
READ = ROOT / "skills/okf-read/scripts/okf.py"


def main() -> int:
    if AUTHOR.read_bytes() != READ.read_bytes():
        print("skill helper copies differ; run: python tools/sync_skill_helpers.py")
        return 1
    print("generated artifacts OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
