#!/usr/bin/env python3
"""Verify checked-in generated/duplicated distribution artifacts."""

import json
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUTHOR = ROOT / "skills/okf-author/scripts/okf.py"
READ = ROOT / "skills/okf-read/scripts/okf.py"


def _versions() -> dict[str, str]:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    lock_packages = [package for package in lock["package"] if package["name"] == "okfleet"]
    if len(lock_packages) != 1:
        raise ValueError(f"expected one okfleet package in uv.lock, found {len(lock_packages)}")

    package_init = (ROOT / "src/okfleet/__init__.py").read_text(encoding="utf-8")
    init_match = re.search(r'^__version__ = "([^"]+)"', package_init, flags=re.MULTILINE)
    if init_match is None:
        raise ValueError("src/okfleet/__init__.py has no __version__ assignment")

    def json_version(path: str, key: str = "version") -> str:
        document = json.loads((ROOT / path).read_text(encoding="utf-8"))
        return str(document[key])

    return {
        "pyproject.toml": str(project["version"]),
        "uv.lock": str(lock_packages[0]["version"]),
        "src/okfleet/__init__.py": init_match.group(1),
        ".codex-plugin/plugin.json": json_version(".codex-plugin/plugin.json"),
        ".claude-plugin/plugin.json": json_version(".claude-plugin/plugin.json"),
        ".release-please-manifest.json": json_version(".release-please-manifest.json", key="."),
    }


def main() -> int:
    valid = True
    if AUTHOR.read_bytes() != READ.read_bytes():
        print("skill helper copies differ; run: python tools/sync_skill_helpers.py")
        valid = False

    versions = _versions()
    expected = versions["pyproject.toml"]
    mismatches = {path: version for path, version in versions.items() if version != expected}
    if mismatches:
        details = ", ".join(f"{path}={version}" for path, version in mismatches.items())
        print(f"public versions differ from pyproject.toml={expected}: {details}")
        valid = False

    if not valid:
        return 1
    print("generated artifacts OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
