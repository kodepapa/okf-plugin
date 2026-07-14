from __future__ import annotations

from pathlib import Path

import pytest

from okfleet.workspace import StagedWorkspace, tree_hashes


def _symlink_or_skip(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target, target_is_directory=target.is_dir())
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlinks are unavailable on this platform: {exc}")


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


def test_staged_workspace_rejects_source_symlinks(bundle_path: Path, tmp_path: Path) -> None:
    external = tmp_path / "external.md"
    external.write_text("outside\n", encoding="utf-8")
    _symlink_or_skip(bundle_path / "external.md", external)

    with pytest.raises(ValueError, match="symlink"):
        StagedWorkspace(bundle_path)
    with pytest.raises(ValueError, match="symlink"):
        tree_hashes(bundle_path)


def test_apply_rejects_raced_source_parent_symlink(
    bundle_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()

    with StagedWorkspace(bundle_path) as workspace:
        staged = workspace.root / "docs/new.md"
        staged.parent.mkdir()
        staged.write_text(
            "---\ntype: Note\ntitle: New\ndescription: Staged note.\n---\n\nContent.\n",
            encoding="utf-8",
        )
        original_changeset = workspace.changeset

        def changeset_with_race():
            changeset = original_changeset()
            _symlink_or_skip(bundle_path / "docs", outside)
            return changeset

        monkeypatch.setattr(workspace, "changeset", changeset_with_race)

        with pytest.raises(ValueError, match="symlink"):
            workspace.apply()

    assert not (outside / "new.md").exists()
