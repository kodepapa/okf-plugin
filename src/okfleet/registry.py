from __future__ import annotations

import builtins
import os
import re
import stat
import tomllib
import uuid
from collections.abc import Iterable
from dataclasses import replace
from pathlib import Path
from typing import Any

from platformdirs import user_config_path

from .core import (
    EXCLUDED_DIRS,
    atomic_write,
    iter_markdown,
    parse_frontmatter,
    read_text_nofollow,
)
from .models import BundleRef


def default_config_path() -> Path:
    configured = os.environ.get("OKFLEET_CONFIG")
    return (
        Path(configured).expanduser() if configured else user_config_path("okfleet") / "config.toml"
    )


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip()).strip("-").lower()
    return slug or "bundle"


def _quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


class BundleRegistry:
    def __init__(self, path: Path | None = None) -> None:
        self._private_parent = path is None and "OKFLEET_CONFIG" not in os.environ
        self.path = (path or default_config_path()).expanduser()
        self.version = 1
        self.ui: dict[str, Any] = {"provider": "codex", "theme": "system"}
        self.discovery: dict[str, Any] = {
            "max_depth": 5,
            "follow_symlinks": False,
            "exclude": sorted(EXCLUDED_DIRS),
        }
        self.chat: dict[str, Any] = {
            "default_bundle_mode": "read",
            "default_work_strategy": "staged",
        }
        self._bundles: list[BundleRef] = []
        self.collections: dict[str, list[str]] = {}
        self.saved_searches: dict[str, dict[str, Any]] = {}
        self.remotes: dict[str, dict[str, str]] = {}
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            return
        data = tomllib.loads(read_text_nofollow(self.path))
        self.version = int(data.get("version", 1))
        self.ui.update(data.get("ui", {}))
        self.discovery.update(data.get("discovery", {}))
        self.chat.update(data.get("chat", {}))
        self.collections = {
            str(name): [str(item) for item in values]
            for name, values in data.get("collections", {}).items()
        }
        self.saved_searches = {
            str(name): dict(values)
            for name, values in data.get("saved_searches", {}).items()
            if isinstance(values, dict)
        }
        self.remotes = {
            str(name): {str(key): str(value) for key, value in values.items()}
            for name, values in data.get("remotes", {}).items()
            if isinstance(values, dict)
        }
        self._bundles = []
        for item in data.get("bundles", []):
            path = Path(str(item["path"])).expanduser().resolve()
            self._bundles.append(
                BundleRef(
                    id=str(item.get("id") or uuid.uuid4()),
                    alias=str(item["alias"]),
                    path=path,
                    source="global",
                    available=path.is_dir(),
                )
            )

    def save(self) -> None:
        lines = [f"version = {self.version}", "", "[ui]"]
        for key in sorted(self.ui):
            lines.append(f"{key} = {_quote(str(self.ui[key]))}")
        lines.extend(["", "[discovery]"])
        lines.append(f"max_depth = {int(self.discovery.get('max_depth', 5))}")
        lines.append(
            f"follow_symlinks = {'true' if self.discovery.get('follow_symlinks', False) else 'false'}"
        )
        excludes = ", ".join(_quote(str(item)) for item in self.discovery.get("exclude", []))
        lines.append(f"exclude = [{excludes}]")
        lines.extend(["", "[chat]"])
        for key in sorted(self.chat):
            lines.append(f"{key} = {_quote(str(self.chat[key]))}")
        if self.collections:
            lines.extend(["", "[collections]"])
            for name in sorted(self.collections):
                members = ", ".join(_quote(item) for item in self.collections[name])
                lines.append(f"{_quote(name)} = [{members}]")
        for name in sorted(self.saved_searches):
            saved = self.saved_searches[name]
            lines.extend(["", f"[saved_searches.{_quote(name)}]"])
            lines.append(f"query = {_quote(str(saved.get('query', '')))}")
            bundles = ", ".join(_quote(str(item)) for item in saved.get("bundles", []))
            lines.append(f"bundles = [{bundles}]")
            collection = saved.get("collection")
            if collection:
                lines.append(f"collection = {_quote(str(collection))}")
        for bundle_id in sorted(self.remotes):
            remote = self.remotes[bundle_id]
            lines.extend(["", f"[remotes.{_quote(bundle_id)}]"])
            lines.append(f"url = {_quote(remote['url'])}")
            if remote.get("ref"):
                lines.append(f"ref = {_quote(remote['ref'])}")
        for bundle in sorted(self._bundles, key=lambda item: item.alias):
            lines.extend(
                [
                    "",
                    "[[bundles]]",
                    f"id = {_quote(bundle.id)}",
                    f"alias = {_quote(bundle.alias)}",
                    f"path = {_quote(str(bundle.path))}",
                ]
            )
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self._private_parent and os.name != "nt":
            self.path.parent.chmod(0o700)
        atomic_write(self.path, "\n".join(lines) + "\n")
        if os.name != "nt":
            self.path.chmod(0o600)

    def list(self) -> list[BundleRef]:
        return [replace(item, available=item.path.is_dir()) for item in self._bundles]

    def get(self, alias_or_id: str) -> BundleRef | None:
        return next(
            (item for item in self.list() if item.alias == alias_or_id or item.id == alias_or_id),
            None,
        )

    def add(self, path: Path, alias: str | None = None) -> BundleRef:
        resolved = path.expanduser().resolve()
        if not resolved.is_dir():
            raise ValueError(f"bundle directory does not exist: {resolved}")
        existing_path = next((item for item in self._bundles if item.path == resolved), None)
        if existing_path:
            return existing_path
        base = slugify(alias or resolved.name)
        candidate = base
        counter = 2
        used = {item.alias for item in self._bundles}
        while candidate in used:
            candidate = f"{base}-{counter}"
            counter += 1
        ref = BundleRef(str(uuid.uuid4()), candidate, resolved)
        self._bundles.append(ref)
        self.save()
        return ref

    def remove(self, alias_or_id: str) -> BundleRef:
        ref = self.get(alias_or_id)
        if not ref:
            raise KeyError(alias_or_id)
        self._bundles = [item for item in self._bundles if item.id != ref.id]
        self.remotes.pop(ref.id, None)
        for collection in self.collections.values():
            while ref.id in collection:
                collection.remove(ref.id)
        self.save()
        return ref

    def rename(self, alias_or_id: str, alias: str) -> BundleRef:
        ref = self.get(alias_or_id)
        if not ref:
            raise KeyError(alias_or_id)
        normalized = slugify(alias)
        if any(item.alias == normalized and item.id != ref.id for item in self._bundles):
            raise ValueError(f"bundle alias already exists: {normalized}")
        replacement = replace(ref, alias=normalized)
        self._bundles = [replacement if item.id == ref.id else item for item in self._bundles]
        self.save()
        return replacement

    def create_collection(self, name: str, members: Iterable[str] = ()) -> None:
        if name in self.collections:
            raise ValueError(f"collection already exists: {name}")
        ids: builtins.list[str] = []
        for member in members:
            ref = self.get(member)
            if not ref:
                raise KeyError(member)
            ids.append(ref.id)
        self.collections[name] = ids
        self.save()

    def collection(self, name: str) -> builtins.list[BundleRef]:
        if name not in self.collections:
            raise KeyError(name)
        selected = set(self.collections[name])
        return [item for item in self.list() if item.id in selected]

    def add_to_collection(self, name: str, alias_or_id: str) -> BundleRef:
        if name not in self.collections:
            raise KeyError(name)
        ref = self.get(alias_or_id)
        if not ref:
            raise KeyError(alias_or_id)
        if ref.id not in self.collections[name]:
            self.collections[name].append(ref.id)
            self.save()
        return ref

    def remove_from_collection(self, name: str, alias_or_id: str) -> BundleRef:
        if name not in self.collections:
            raise KeyError(name)
        ref = self.get(alias_or_id)
        if not ref:
            raise KeyError(alias_or_id)
        if ref.id not in self.collections[name]:
            raise ValueError(f"bundle {ref.alias} is not in collection {name}")
        self.collections[name].remove(ref.id)
        self.save()
        return ref

    def save_search(
        self,
        name: str,
        query: str,
        *,
        bundles: Iterable[str] = (),
        collection: str | None = None,
    ) -> None:
        if not query.strip():
            raise ValueError("saved search query cannot be empty")
        if collection and collection not in self.collections:
            raise KeyError(collection)
        aliases: builtins.list[str] = []
        for value in bundles:
            ref = self.get(value)
            if not ref:
                raise KeyError(value)
            aliases.append(ref.alias)
        self.saved_searches[name] = {
            "query": query.strip(),
            "bundles": aliases,
            "collection": collection,
        }
        self.save()

    def delete_search(self, name: str) -> None:
        if name not in self.saved_searches:
            raise KeyError(name)
        del self.saved_searches[name]
        self.save()


def _has_concept(path: Path, max_files: int = 50) -> bool:
    checked = 0
    for markdown in iter_markdown(path):
        if markdown.name in {"index.md", "log.md"}:
            continue
        checked += 1
        try:
            frontmatter, _ = parse_frontmatter(read_text_nofollow(markdown))
            if str((frontmatter or {}).get("type") or "").strip():
                return True
        except (OSError, UnicodeDecodeError, ValueError):
            pass
        if checked >= max_files:
            break
    return False


def _root_marker(path: Path) -> bool:
    index = path / "index.md"
    try:
        frontmatter, _ = parse_frontmatter(read_text_nofollow(index))
        return bool((frontmatter or {}).get("okf_version"))
    except (OSError, UnicodeDecodeError, ValueError):
        return False


def _has_regular_index(path: Path) -> bool:
    try:
        return stat.S_ISREG((path / "index.md").lstat().st_mode)
    except OSError:
        return False


def discover_bundles(
    start: Path,
    *,
    max_depth: int = 5,
    exclude: Iterable[str] = EXCLUDED_DIRS,
    max_directories: int = 5000,
) -> list[BundleRef]:
    root = start.expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"discovery path does not exist: {root}")
    excluded = set(exclude)
    candidates: list[tuple[Path, str, str]] = []
    for visited, (directory, names, _) in enumerate(os.walk(root, followlinks=False), start=1):
        current = Path(directory)
        depth = len(current.relative_to(root).parts)
        names[:] = sorted(
            name
            for name in names
            if name not in excluded
            and not name.startswith(".")
            and depth < max_depth
            and not (current / name).is_symlink()
        )
        if visited > max_directories:
            break
        if _root_marker(current):
            candidates.append((current, "high", "root index declares okf_version"))
            names[:] = []
        elif _has_regular_index(current) and _has_concept(current):
            candidates.append((current, "medium", "index and typed concepts detected"))
            names[:] = []
    if not candidates and _has_concept(root):
        candidates.append((root, "low", "typed concepts detected without root marker"))
    refs: list[BundleRef] = []
    used: set[str] = set()
    for path, confidence, reason in candidates:
        alias = slugify(path.name)
        base, suffix = alias, 2
        while alias in used:
            alias = f"{base}-{suffix}"
            suffix += 1
        used.add(alias)
        refs.append(
            BundleRef(
                id=str(uuid.uuid5(uuid.NAMESPACE_URL, str(path))),
                alias=alias,
                path=path,
                source="local",
                confidence=confidence,
                reason=reason,
            )
        )
    return refs


def resolve_bundle(value: str | Path, registry: BundleRegistry) -> BundleRef:
    raw = str(value)
    registered = registry.get(raw)
    if registered:
        if not registered.available:
            raise ValueError(f"registered bundle is unavailable: {registered.path}")
        return registered
    path = Path(raw).expanduser()
    if path.is_dir():
        resolved = path.resolve()
        return BundleRef(
            str(uuid.uuid5(uuid.NAMESPACE_URL, str(resolved))),
            slugify(resolved.name),
            resolved,
            "explicit",
        )
    raise ValueError(f"unknown bundle alias or path: {raw}")
