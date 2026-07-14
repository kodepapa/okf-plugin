#!/usr/bin/env python3
"""Keep the standalone helper byte-identical in both distributed skills."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUTHOR = ROOT / "skills/okf-author/scripts/okf.py"
READ = ROOT / "skills/okf-read/scripts/okf.py"


def main() -> int:
    source = AUTHOR.read_text(encoding="utf-8")
    READ.write_text(source, encoding="utf-8")
    print(f"synced {READ.relative_to(ROOT)} from {AUTHOR.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
