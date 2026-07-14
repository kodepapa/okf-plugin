from __future__ import annotations

import difflib
import os
import shutil
import stat
import tempfile
import uuid
from contextlib import suppress
from pathlib import Path, PurePosixPath

from .core import (
    atomic_write_bytes,
    content_hash,
    load_bundle,
    read_bytes_nofollow,
    validate_bundle,
)
from .models import ChangeSet, FileChange


def _relative_parts(relative: str) -> tuple[str, ...]:
    pure = PurePosixPath(relative)
    if not pure.parts or pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise ValueError(f"unsafe workspace path: {relative}")
    return pure.parts


def _checked_path(root: Path, relative: str) -> Path:
    """Return a root-contained path after rejecting symlinks in every existing component."""
    parts = _relative_parts(relative)
    current = root
    for index, part in enumerate(parts):
        current /= part
        try:
            info = current.lstat()
        except FileNotFoundError:
            break
        except NotADirectoryError as exc:
            raise ValueError(f"non-directory workspace path component: {current}") from exc
        if stat.S_ISLNK(info.st_mode):
            raise ValueError(f"symlink is not allowed in a staged workspace: {current}")
        if index < len(parts) - 1 and not stat.S_ISDIR(info.st_mode):
            raise ValueError(f"non-directory workspace path component: {current}")
    return root.joinpath(*parts)


def _ensure_plain_parent(root: Path, relative: str) -> Path:
    """Create missing parents one at a time while refusing symlink components."""
    parts = _relative_parts(relative)
    current = root
    for part in parts[:-1]:
        current /= part
        try:
            info = current.lstat()
        except FileNotFoundError:
            with suppress(FileExistsError):
                current.mkdir()
            info = current.lstat()
        if stat.S_ISLNK(info.st_mode):
            raise ValueError(f"symlink is not allowed in a staged workspace: {current}")
        if not stat.S_ISDIR(info.st_mode):
            raise ValueError(f"non-directory workspace path component: {current}")
    return _checked_path(root, relative)


def tree_hashes(root: Path) -> dict[str, str]:
    expanded = root.expanduser()
    if expanded.is_symlink():
        raise ValueError(f"symlink is not allowed as a staged workspace root: {expanded}")
    root = expanded.resolve()
    hashes: dict[str, str] = {}
    for directory, names, files in os.walk(root, followlinks=False):
        current = Path(directory)
        names[:] = sorted(name for name in names if name != ".git")
        for name in names:
            path = current / name
            if path.is_symlink():
                raise ValueError(f"symlink is not allowed in a staged workspace: {path}")
        for name in sorted(files):
            if name == ".git":
                continue
            path = current / name
            relative = path.relative_to(root).as_posix()
            path = _checked_path(root, relative)
            try:
                info = path.lstat()
            except FileNotFoundError:
                raise RuntimeError(f"workspace file changed while hashing: {path}") from None
            if not stat.S_ISREG(info.st_mode):
                continue
            hashes[relative] = content_hash(read_bytes_nofollow(path))
    return hashes


def _text_or_none(root: Path, relative: str) -> tuple[str | None, bool]:
    path = _checked_path(root, relative)
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None, False
    if not stat.S_ISREG(info.st_mode):
        return None, True
    try:
        return read_bytes_nofollow(path).decode("utf-8"), True
    except UnicodeDecodeError:
        return None, True


def _diff(relative: str, before_root: Path, after_root: Path) -> str:
    old, before_exists = _text_or_none(before_root, relative)
    new, after_exists = _text_or_none(after_root, relative)
    if (old is None and before_exists) or (new is None and after_exists):
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
        expanded = source_root.expanduser()
        if expanded.is_symlink():
            raise ValueError(f"bundle root must not be a symlink: {expanded}")
        self.source_root = expanded.resolve()
        if not self.source_root.is_dir():
            raise ValueError(f"bundle does not exist: {self.source_root}")
        baseline_hashes = tree_hashes(self.source_root)
        self._temporary = tempfile.TemporaryDirectory(prefix="okfleet-work-")
        self.root = Path(self._temporary.name) / "bundle"
        try:
            self._copy_safe()
            self.staged_baseline_hashes = tree_hashes(self.root)
            if tree_hashes(self.source_root) != baseline_hashes:
                raise RuntimeError("source files changed while the staged workspace was created")
        except Exception:
            self._temporary.cleanup()
            raise
        self.baseline_hashes = baseline_hashes

    def _copy_safe(self) -> None:
        source = self.source_root

        def ignore(directory: str, names: list[str]) -> set[str]:
            current = Path(directory)
            ignored = {".git"} & set(names)
            for name in names:
                path = current / name
                if path.is_symlink():
                    ignored.add(name)
            return ignored

        shutil.copytree(source, self.root, symlinks=True, ignore=ignore)

    def changeset(self) -> ChangeSet:
        source_now = tree_hashes(self.source_root)
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
                    diff=_diff(relative, self.source_root, self.root),
                )
            )
        diagnostics = validate_bundle(load_bundle(self.root), include_health=True)
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
        source_now = tree_hashes(self.source_root)
        if source_now != self.baseline_hashes:
            raise RuntimeError("source files changed after the staged changeset was prepared")
        staged_now = tree_hashes(self.root)
        if any(staged_now.get(change.path) != change.after_hash for change in changeset.changes):
            raise RuntimeError("staged files changed after the changeset was prepared")
        for change in changeset.changes:
            _checked_path(self.source_root, change.path)
            _checked_path(self.root, change.path)
        applied: list[FileChange] = []
        try:
            for change in changeset.changes:
                source = _checked_path(self.source_root, change.path)
                staged = _checked_path(self.root, change.path)
                backup = _ensure_plain_parent(backup_root, change.path)
                try:
                    source_info = source.lstat()
                except FileNotFoundError:
                    source_info = None
                if source_info is not None:
                    if not stat.S_ISREG(source_info.st_mode):
                        raise ValueError(f"source workspace file is not regular: {source}")
                    source = _checked_path(self.source_root, change.path)
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    atomic_write_bytes(backup, read_bytes_nofollow(source))
                if change.kind == "deleted":
                    source = _checked_path(self.source_root, change.path)
                    source.unlink(missing_ok=True)
                else:
                    staged = _checked_path(self.root, change.path)
                    staged_content = read_bytes_nofollow(staged)
                    if content_hash(staged_content) != change.after_hash:
                        raise RuntimeError(f"staged file changed while applying: {change.path}")
                    source = _ensure_plain_parent(self.source_root, change.path)
                    source = _checked_path(self.source_root, change.path)
                    atomic_write_bytes(source, staged_content)
                applied.append(change)
        except Exception:
            for change in reversed(applied):
                source = _ensure_plain_parent(self.source_root, change.path)
                backup = _checked_path(backup_root, change.path)
                try:
                    backup_info = backup.lstat()
                except FileNotFoundError:
                    backup_info = None
                if backup_info is not None:
                    source = _checked_path(self.source_root, change.path)
                    atomic_write_bytes(source, read_bytes_nofollow(backup))
                else:
                    source = _checked_path(self.source_root, change.path)
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
