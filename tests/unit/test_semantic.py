from __future__ import annotations

from pathlib import Path

from okfleet.core import load_bundle
from okfleet.registry import BundleRegistry
from okfleet.search import SearchDatabase
from okfleet.semantic import LocalHashEmbedding, semantic_search


def test_local_semantic_search_is_opt_in_and_deterministic(
    bundle_path: Path, tmp_path: Path
) -> None:
    ref = BundleRegistry(tmp_path / "config.toml").add(bundle_path, "finance")
    with SearchDatabase(tmp_path / "index.db") as database:
        database.index_bundle(ref, load_bundle(bundle_path))
        first = semantic_search(database, "recognized revenue", bundle_ids=[ref.id])
        second = semantic_search(database, "recognized revenue", bundle_ids=[ref.id])
    assert first[0].citation == "finance:metrics/revenue"
    assert [hit.citation for hit in first] == [hit.citation for hit in second]
    assert LocalHashEmbedding().embed("revenue") == LocalHashEmbedding().embed("revenue")
