from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from okfleet.core import load_bundle
from okfleet.registry import BundleRegistry, discover_bundles
from okfleet.search import SearchDatabase


def _symlink_or_skip(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target, target_is_directory=target.is_dir())
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlinks are unavailable on this platform: {exc}")


def test_registry_roundtrip(bundle_path: Path, tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    registry = BundleRegistry(config)
    ref = registry.add(bundle_path, "finance")
    assert ref.alias == "finance"
    loaded = BundleRegistry(config)
    assert loaded.get("finance") is not None
    loaded.create_collection("production")
    loaded.add_to_collection("production", "finance")
    assert [item.alias for item in loaded.collection("production")] == ["finance"]
    loaded.remove_from_collection("production", "finance")
    assert loaded.collection("production") == []
    loaded.save_search("money", "revenue", bundles=["finance"])
    assert BundleRegistry(config).saved_searches["money"]["query"] == "revenue"
    loaded.delete_search("money")
    loaded.remotes[ref.id] = {"url": "https://example.test/finance.git", "ref": "main"}
    loaded.save()
    assert BundleRegistry(config).remotes[ref.id]["ref"] == "main"
    renamed = loaded.rename("finance", "warehouse")
    assert renamed.alias == "warehouse"
    loaded.remove("warehouse")
    assert not BundleRegistry(config).list()


@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes are not available")
def test_registry_and_search_state_files_are_private(bundle_path: Path, tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    registry = BundleRegistry(config)
    ref = registry.add(bundle_path, "finance")

    database_path = tmp_path / "index.db"
    with SearchDatabase(database_path) as database:
        database.index_bundle(ref, load_bundle(bundle_path))
        assert stat.S_IMODE(database_path.stat().st_mode) == 0o600

    assert stat.S_IMODE(config.stat().st_mode) == 0o600


def test_registry_refuses_symlinked_configuration(tmp_path: Path) -> None:
    target = tmp_path / "target.toml"
    target.write_text("version = 1\n", encoding="utf-8")
    link = tmp_path / "config.toml"
    _symlink_or_skip(link, target)

    with pytest.raises(OSError, match="symlink"):
        BundleRegistry(link)


def test_discovery_finds_root_marker(bundle_path: Path, tmp_path: Path) -> None:
    refs = discover_bundles(tmp_path)
    assert [(ref.path, ref.confidence) for ref in refs] == [(bundle_path, "high")]


def test_discovery_does_not_treat_symlinked_index_as_root_marker(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    (candidate / "concept.md").write_text(
        "---\ntype: Note\ntitle: Note\ndescription: Local concept.\n---\n",
        encoding="utf-8",
    )
    external_index = tmp_path / "external-index.md"
    external_index.write_text('---\nokf_version: "999"\n---\n', encoding="utf-8")
    _symlink_or_skip(candidate / "index.md", external_index)

    refs = discover_bundles(candidate)

    assert [(ref.path, ref.confidence) for ref in refs] == [(candidate, "low")]


def test_discovery_ignores_symlinked_concepts(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    (candidate / "index.md").write_text("# Index\n", encoding="utf-8")
    external = tmp_path / "external-concept.md"
    external.write_text(
        "---\ntype: Secret\ntitle: External\ndescription: Must not be read.\n---\n",
        encoding="utf-8",
    )
    _symlink_or_skip(candidate / "external.md", external)

    assert discover_bundles(candidate) == []


def test_search_filters_and_incremental_index(bundle_path: Path, tmp_path: Path) -> None:
    registry = BundleRegistry(tmp_path / "config.toml")
    ref = registry.add(bundle_path, "finance")
    with SearchDatabase(tmp_path / "index.db") as database:
        assert database.index_bundle(ref, load_bundle(bundle_path)) == 2
        assert database.index_bundle(ref, load_bundle(bundle_path)) == 0
        hits = database.search("type:Metric revenue", bundle_ids=[ref.id])
        assert [hit.citation for hit in hits] == ["finance:metrics/revenue"]
        assert database.stats() == {"bundles": 1, "concepts": 2, "links": 2}
