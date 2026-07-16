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
    locked_packages = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))["package"]
    locked_version = next(
        package["version"] for package in locked_packages if package["name"] == "okfleet"
    )
    init = (ROOT / "src/okfleet/__init__.py").read_text(encoding="utf-8")
    init_version = re.search(r'__version__ = "([^"]+)"', init)

    assert init_version is not None
    assert {
        manifest["."],
        codex["version"],
        claude["version"],
        locked_version,
        init_version.group(1),
    } == {version}


def test_release_please_config_and_workflow_are_wired() -> None:
    config = json.loads((ROOT / "release-please-config.json").read_text(encoding="utf-8"))
    package = config["packages"]["."]
    extra_paths = {item["path"] for item in package["extra-files"]}
    workflow = YAML(typ="safe").load(
        (ROOT / ".github/workflows/release-please.yml").read_text(encoding="utf-8")
    )

    assert package["release-type"] == "python"
    assert config["bootstrap-sha"] == "40e4541ba95200ba2cd2651bdd33ec6a3ec010bc"
    assert package["include-v-in-tag"] is True
    assert package["include-component-in-tag"] is False
    assert extra_paths == {
        "src/okfleet/__init__.py",
        ".codex-plugin/plugin.json",
        ".claude-plugin/plugin.json",
        "uv.lock",
    }
    uv_lock = next(item for item in package["extra-files"] if item["path"] == "uv.lock")
    assert uv_lock == {
        "type": "toml",
        "path": "uv.lock",
        "jsonpath": '$.package[?(@.name=="okfleet")].version',
    }
    assert set(workflow["jobs"]) == {"release-please"}
    workflow_text = (ROOT / ".github/workflows/release-please.yml").read_text(encoding="utf-8")
    assert "secrets.RELEASE_PLEASE_TOKEN || github.token" in workflow_text
    assert "steps.release.outputs.release_created" in workflow_text
    assert "gh release upload" in workflow_text


def test_ci_has_one_quality_gate_and_a_minimal_compatibility_matrix() -> None:
    workflow = YAML(typ="safe").load(
        (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    )

    assert workflow["on"]["push"]["branches"] == ["main"]
    assert workflow["on"]["pull_request"]["branches"] == ["main"]
    assert set(workflow["jobs"]) == {"quality", "compatibility"}
    matrix = workflow["jobs"]["compatibility"]["strategy"]["matrix"]["include"]
    assert {(item["os"], item["python"]) for item in matrix} == {
        ("ubuntu-latest", "3.11"),
        ("ubuntu-latest", "3.12"),
        ("macos-latest", "3.13"),
    }


def test_workflows_pin_actions_and_ci_uses_the_lockfile() -> None:
    yaml = YAML(typ="safe")
    workflows = [
        yaml.load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")),
        yaml.load((ROOT / ".github/workflows/release-please.yml").read_text(encoding="utf-8")),
    ]

    for workflow in workflows:
        for job in workflow["jobs"].values():
            for step in job["steps"]:
                if action := step.get("uses"):
                    assert re.fullmatch(r"[^@]+@[0-9a-f]{40}", action)

    ci_text = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "uv sync --locked --extra dev" in ci_text
    assert "pytest --cov=okfleet" in ci_text
    assert "tools/verify_distribution.py" in ci_text


def test_distribution_metadata_is_open_source_and_typed() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]

    assert project["license"] == "Apache-2.0"
    assert set(project["license-files"]) == {"LICENSE", "NOTICE"}
    assert (ROOT / "LICENSE").is_file()
    assert (ROOT / "NOTICE").is_file()
    assert (ROOT / "src/okfleet/py.typed").is_file()


def test_dependabot_covers_locked_dependencies_and_actions() -> None:
    config = YAML(typ="safe").load((ROOT / ".github/dependabot.yml").read_text(encoding="utf-8"))

    assert {update["package-ecosystem"] for update in config["updates"]} == {
        "github-actions",
        "pre-commit",
        "uv",
    }
