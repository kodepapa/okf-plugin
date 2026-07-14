from __future__ import annotations

from pathlib import Path

from okfleet.core import load_bundle
from okfleet.registry import BundleRegistry, discover_bundles
from okfleet.search import SearchDatabase


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


def test_discovery_finds_root_marker(bundle_path: Path, tmp_path: Path) -> None:
    refs = discover_bundles(tmp_path)
    assert [(ref.path, ref.confidence) for ref in refs] == [(bundle_path, "high")]


def test_search_filters_and_incremental_index(bundle_path: Path, tmp_path: Path) -> None:
    registry = BundleRegistry(tmp_path / "config.toml")
    ref = registry.add(bundle_path, "finance")
    with SearchDatabase(tmp_path / "index.db") as database:
        assert database.index_bundle(ref, load_bundle(bundle_path)) == 2
        assert database.index_bundle(ref, load_bundle(bundle_path)) == 0
        hits = database.search("type:Metric revenue", bundle_ids=[ref.id])
        assert [hit.citation for hit in hits] == ["finance:metrics/revenue"]
        assert database.stats() == {"bundles": 1, "concepts": 2, "links": 2}
