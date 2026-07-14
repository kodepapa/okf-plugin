from __future__ import annotations

import difflib
import os
import shutil
import tempfile
import uuid
from pathlib import Path

from .core import atomic_write_bytes, content_hash, load_bundle, validate_bundle
from .models import ChangeSet, FileChange


def tree_hashes(root: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for directory, names, files in os.walk(root, followlinks=False):
        names[:] = sorted(name for name in names if name != ".git")
        current = Path(directory)
        for name in sorted(files):
            path = current / name
            if path.is_symlink() or not path.is_file():
                continue
            relative = path.relative_to(root).as_posix()
            hashes[relative] = content_hash(path.read_bytes())
    return hashes


def _text_or_none(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None


def _diff(relative: str, before: Path, after: Path) -> str:
    old = _text_or_none(before)
    new = _text_or_none(after)
    if (old is None and before.exists()) or (new is None and after.exists()):
        return f"Binary file changed: {relative}\n"
    return "".join(
        difflib.unified_diff(
            (old or "").splitlines(keepends=True),
            (new or "").splitlines(keepends=True),
            f"a/{relative}",
            f"b/{relative}",
        )
    )


class StagedWorkspace:
    def __init__(self, source_root: Path) -> None:
        self.source_root = source_root.expanduser().resolve()
        if not self.source_root.is_dir():
            raise ValueError(f"bundle does not exist: {self.source_root}")
        self._temporary = tempfile.TemporaryDirectory(prefix="okfleet-work-")
        self.root = Path(self._temporary.name) / "bundle"
        self._copy_safe()
        self.baseline_hashes = tree_hashes(self.source_root)
        self.staged_baseline_hashes = tree_hashes(self.root)

    def _copy_safe(self) -> None:
        source = self.source_root

        def ignore(directory: str, names: list[str]) -> set[str]:
            current = Path(directory)
            ignored = {".git"} & set(names)
            for name in names:
                path = current / name
                if not path.is_symlink():
                    continue
                try:
                    target = path.resolve()
                    target.relative_to(source)
                    if path.is_absolute():
                        ignored.add(name)
                except (OSError, ValueError):
                    ignored.add(name)
            return ignored

        shutil.copytree(source, self.root, symlinks=True, ignore=ignore)

    def changeset(self) -> ChangeSet:
        current = tree_hashes(self.root)
        paths = sorted(set(self.staged_baseline_hashes) | set(current))
        changes: list[FileChange] = []
        for relative in paths:
            before_hash = self.staged_baseline_hashes.get(relative)
            after_hash = current.get(relative)
            if before_hash == after_hash:
                continue
            kind = "modified"
            if before_hash is None:
                kind = "added"
            elif after_hash is None:
                kind = "deleted"
            changes.append(
                FileChange(
                    path=relative,
                    kind=kind,
                    before_hash=before_hash,
                    after_hash=after_hash,
                    diff=_diff(relative, self.source_root / relative, self.root / relative),
                )
            )
        diagnostics = validate_bundle(load_bundle(self.root), include_health=True)
        source_now = tree_hashes(self.source_root)
        conflicts = [
            relative
            for relative in sorted(set(self.baseline_hashes) | set(source_now))
            if self.baseline_hashes.get(relative) != source_now.get(relative)
        ]
        return ChangeSet(
            id=str(uuid.uuid4()),
            source_root=self.source_root,
            staged_root=self.root,
            changes=changes,
            baseline_hashes=dict(self.baseline_hashes),
            diagnostics=diagnostics,
            conflicts=sorted(set(conflicts)),
        )

    def apply(self, *, allow_invalid: bool = False) -> ChangeSet:
        changeset = self.changeset()
        if changeset.conflicts:
            raise RuntimeError(
                "source files changed since staging: " + ", ".join(changeset.conflicts)
            )
        if not allow_invalid and any(
            item.severity.value == "error" for item in changeset.diagnostics
        ):
            raise RuntimeError("staged bundle has validation errors")
        backup_root = Path(self._temporary.name) / "backup"
        backup_root.mkdir(parents=True, exist_ok=True)
        applied: list[FileChange] = []
        try:
            for change in changeset.changes:
                source = self.source_root / change.path
                staged = self.root / change.path
                backup = backup_root / change.path
                if source.exists():
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, backup)
                if change.kind == "deleted":
                    source.unlink(missing_ok=True)
                else:
                    atomic_write_bytes(source, staged.read_bytes())
                applied.append(change)
        except Exception:
            for change in reversed(applied):
                source = self.source_root / change.path
                backup = backup_root / change.path
                if backup.exists():
                    atomic_write_bytes(source, backup.read_bytes())
                else:
                    source.unlink(missing_ok=True)
            raise
        self.baseline_hashes = tree_hashes(self.source_root)
        self.staged_baseline_hashes = tree_hashes(self.root)
        return changeset

    def close(self) -> None:
        self._temporary.cleanup()

    def __enter__(self) -> StagedWorkspace:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
