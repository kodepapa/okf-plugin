from __future__ import annotations

import argparse
import tarfile
import zipfile
from pathlib import Path

WHEEL_MEMBERS = {
    "okfleet/py.typed",
    "okfleet/provider_plugin/.claude-plugin/plugin.json",
    "okfleet/provider_plugin/skills/okf-author/SKILL.md",
    "okfleet/provider_plugin/skills/okf-read/SKILL.md",
}

SDIST_MEMBERS = {
    "AGENTS.md",
    "CHANGELOG.md",
    "LICENSE",
    "NOTICE",
    "README.md",
    "pyproject.toml",
}


def _one(directory: Path, pattern: str) -> Path:
    matches = sorted(directory.glob(pattern))
    if len(matches) != 1:
        raise SystemExit(f"Expected one {pattern!r} in {directory}, found {len(matches)}")
    return matches[0]


def verify_wheel(path: Path) -> None:
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        missing = WHEEL_MEMBERS - names
        if missing:
            raise SystemExit(f"Wheel is missing: {', '.join(sorted(missing))}")

        metadata_name = next(name for name in names if name.endswith(".dist-info/METADATA"))
        metadata = archive.read(metadata_name).decode("utf-8")
        if "License-Expression: Apache-2.0" not in metadata:
            raise SystemExit("Wheel metadata is missing the Apache-2.0 license expression")

        entry_points_name = next(
            name for name in names if name.endswith(".dist-info/entry_points.txt")
        )
        entry_points = archive.read(entry_points_name).decode("utf-8")
        if "okfleet = okfleet.cli:main" not in entry_points:
            raise SystemExit("Wheel metadata is missing the okfleet console script")


def verify_sdist(path: Path) -> None:
    with tarfile.open(path, "r:gz") as archive:
        names = archive.getnames()
        root = names[0].split("/", 1)[0]
        relative_names = {
            name.removeprefix(f"{root}/") for name in names if name.startswith(f"{root}/")
        }
        missing = SDIST_MEMBERS - relative_names
        if missing:
            raise SystemExit(f"Source distribution is missing: {', '.join(sorted(missing))}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify OKFleet distribution contents")
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    verify_wheel(_one(args.directory, "*.whl"))
    verify_sdist(_one(args.directory, "*.tar.gz"))


if __name__ == "__main__":
    main()
