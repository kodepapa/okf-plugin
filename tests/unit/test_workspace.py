from __future__ import annotations

from pathlib import Path

import pytest

from okfleet.workspace import StagedWorkspace


def test_staged_workspace_diff_and_apply(bundle_path: Path) -> None:
    with StagedWorkspace(bundle_path) as workspace:
        staged = workspace.root / "metrics/revenue.md"
        staged.write_text(staged.read_text(encoding="utf-8") + "\nMore detail.\n", encoding="utf-8")
        changeset = workspace.changeset()
        assert [change.path for change in changeset.changes] == ["metrics/revenue.md"]
        assert "+More detail." in changeset.changes[0].diff
        workspace.apply()
    assert "More detail." in (bundle_path / "metrics/revenue.md").read_text(encoding="utf-8")


def test_staged_workspace_detects_concurrent_source_change(bundle_path: Path) -> None:
    with StagedWorkspace(bundle_path) as workspace:
        target = bundle_path / "metrics/revenue.md"
        target.write_text(target.read_text(encoding="utf-8") + "outside\n", encoding="utf-8")
        staged = workspace.root / "metrics/revenue.md"
        staged.write_text(staged.read_text(encoding="utf-8") + "inside\n", encoding="utf-8")
        with pytest.raises(RuntimeError, match="source files changed"):
            workspace.apply()


def test_staged_workspace_preserves_binary_assets(bundle_path: Path) -> None:
    asset = bundle_path / "diagram.png"
    asset.write_bytes(b"\x89PNG\r\n\x1a\noriginal")
    with StagedWorkspace(bundle_path) as workspace:
        updated = b"\x89PNG\r\n\x1a\nupdated\x00\xff"
        (workspace.root / "diagram.png").write_bytes(updated)
        changeset = workspace.changeset()
        assert changeset.changes[0].diff == "Binary file changed: diagram.png\n"
        workspace.apply()
    assert asset.read_bytes() == updated
