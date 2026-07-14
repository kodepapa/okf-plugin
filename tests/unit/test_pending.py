from __future__ import annotations

from pathlib import Path

import pytest

from okfleet.pending import PendingChangeStore
from okfleet.workspace import StagedWorkspace


def test_pending_changeset_roundtrip(bundle_path: Path, tmp_path: Path) -> None:
    store = PendingChangeStore(tmp_path / "changesets")
    with StagedWorkspace(bundle_path) as workspace:
        staged = workspace.root / "metrics/revenue.md"
        staged.write_text(staged.read_text(encoding="utf-8") + "pending\n", encoding="utf-8")
        changeset = workspace.changeset()
        changeset_id = store.save(workspace, changeset)

    manifest = store.manifest(changeset_id)
    assert manifest["files"] == ["metrics/revenue.md"]
    store.apply(changeset_id)
    assert "pending" in (bundle_path / "metrics/revenue.md").read_text(encoding="utf-8")
    assert store.list() == []


def test_pending_changeset_blocks_deleted_source_conflict(
    bundle_path: Path, tmp_path: Path
) -> None:
    store = PendingChangeStore(tmp_path / "changesets")
    with StagedWorkspace(bundle_path) as workspace:
        staged = workspace.root / "metrics/revenue.md"
        staged.write_text(staged.read_text(encoding="utf-8") + "pending\n", encoding="utf-8")
        changeset_id = store.save(workspace, workspace.changeset())
    (bundle_path / "tables/orders.md").unlink()

    with pytest.raises(RuntimeError, match="source files changed"):
        store.apply(changeset_id)
