from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

from ruamel.yaml import YAML

ROOT = Path(__file__).parents[2]


def test_release_please_tracks_every_public_version() -> None:
    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "version"
    ]
    manifest = json.loads((ROOT / ".release-please-manifest.json").read_text(encoding="utf-8"))
    codex = json.loads((ROOT / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))
    claude = json.loads((ROOT / ".claude-plugin/plugin.json").read_text(encoding="utf-8"))
    init = (ROOT / "src/okfleet/__init__.py").read_text(encoding="utf-8")
    init_version = re.search(r'__version__ = "([^"]+)"', init)

    assert init_version is not None
    assert {manifest["."], codex["version"], claude["version"], init_version.group(1)} == {version}


def test_release_please_config_and_workflow_are_wired() -> None:
    config = json.loads((ROOT / "release-please-config.json").read_text(encoding="utf-8"))
    package = config["packages"]["."]
    extra_paths = {item["path"] for item in package["extra-files"]}
    workflow = YAML(typ="safe").load(
        (ROOT / ".github/workflows/release-please.yml").read_text(encoding="utf-8")
    )

    assert package["release-type"] == "python"
    assert extra_paths == {
        "src/okfleet/__init__.py",
        ".codex-plugin/plugin.json",
        ".claude-plugin/plugin.json",
    }
    assert "release-please" in workflow["jobs"]
