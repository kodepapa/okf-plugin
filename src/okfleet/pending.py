from __future__ import annotations

import json
import os
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .core import atomic_write
from .models import ChangeSet
from .search import default_database_path
from .workspace import StagedWorkspace


def default_changeset_root() -> Path:
    configured = os.environ.get("OKFLEET_CHANGESETS")
    return (
        Path(configured).expanduser()
        if configured
        else default_database_path().parent / "changesets"
    )


class PendingChangeStore:
    """Persist staged snapshots without granting them authority to mutate source."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or default_changeset_root()).expanduser()

    @staticmethod
    def _validated_id(changeset_id: str) -> str:
        try:
            return str(uuid.UUID(changeset_id))
        except ValueError as exc:
            raise KeyError(changeset_id) from exc

    def save(self, workspace: StagedWorkspace, changeset: ChangeSet) -> str:
        changeset_id = self._validated_id(changeset.id)
        destination = self.root / changeset_id
        if destination.exists():
            raise ValueError(f"changeset already exists: {changeset_id}")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        destination.mkdir(mode=0o700)
        if os.name != "nt":
            self.root.chmod(0o700)
            destination.chmod(0o700)
        shutil.copytree(workspace.root, destination / "bundle", symlinks=False)
        manifest = {
            "schema_version": 1,
            "id": changeset_id,
            "created_at": datetime.now(UTC).isoformat(),
            "source_root": str(workspace.source_root),
            "baseline_hashes": workspace.baseline_hashes,
            "staged_baseline_hashes": workspace.staged_baseline_hashes,
            "files": [change.path for change in changeset.changes],
            "diagnostics": [item.to_dict() for item in changeset.diagnostics],
        }
        atomic_write(destination / "manifest.json", json.dumps(manifest, indent=2) + "\n")
        return changeset_id

    def manifest(self, changeset_id: str) -> dict[str, Any]:
        normalized = self._validated_id(changeset_id)
        path = self.root / normalized / "manifest.json"
        if not path.is_file():
            raise KeyError(changeset_id)
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("id") != normalized:
            raise ValueError(f"invalid changeset manifest: {normalized}")
        return data

    def list(self) -> list[dict[str, Any]]:
        if not self.root.is_dir():
            return []
        manifests: list[dict[str, Any]] = []
        for path in sorted(self.root.glob("*/manifest.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(data, dict):
                manifests.append(data)
        return sorted(manifests, key=lambda item: str(item.get("created_at", "")), reverse=True)

    def open(self, changeset_id: str) -> StagedWorkspace:
        manifest = self.manifest(changeset_id)
        stored = self.root / str(manifest["id"]) / "bundle"
        if not stored.is_dir():
            raise ValueError(f"changeset snapshot is missing: {manifest['id']}")
        workspace = StagedWorkspace(Path(str(manifest["source_root"])))
        shutil.rmtree(workspace.root)
        shutil.copytree(stored, workspace.root, symlinks=False)
        workspace.baseline_hashes = {
            str(key): str(value) for key, value in manifest["baseline_hashes"].items()
        }
        workspace.staged_baseline_hashes = {
            str(key): str(value) for key, value in manifest["staged_baseline_hashes"].items()
        }
        return workspace

    def delete(self, changeset_id: str) -> None:
        normalized = self._validated_id(changeset_id)
        destination = self.root / normalized
        if not destination.is_dir():
            raise KeyError(changeset_id)
        shutil.rmtree(destination)

    def apply(self, changeset_id: str, *, allow_invalid: bool = False) -> ChangeSet:
        workspace = self.open(changeset_id)
        try:
            result = workspace.apply(allow_invalid=allow_invalid)
        finally:
            workspace.close()
        self.delete(changeset_id)
        return result
