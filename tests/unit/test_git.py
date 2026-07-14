from __future__ import annotations

import subprocess
from pathlib import Path

from okfleet.git import bundle_git_status


def test_git_status_is_scoped_to_bundle(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    bundle = repository / "knowledge"
    bundle.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repository)], check=True)
    (bundle / "concept.md").write_text("# Concept\n", encoding="utf-8")
    (repository / "outside.txt").write_text("outside\n", encoding="utf-8")

    status = bundle_git_status(bundle, include_diff=True)

    assert status["available"] is True
    assert [item["path"] for item in status["changes"]] == ["knowledge/concept.md"]
    assert "outside.txt" not in str(status)
