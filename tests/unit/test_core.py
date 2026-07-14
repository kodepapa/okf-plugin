from __future__ import annotations

from pathlib import Path

import pytest

from okfleet.core import (
    create_concept,
    graph_neighborhood,
    load_bundle,
    move_concept,
    parse_frontmatter,
    plan_indexes,
    safe_concept_path,
    validate_bundle,
)
from okfleet.models import Severity


def test_load_links_validate_and_graph(bundle_path: Path) -> None:
    bundle = load_bundle(bundle_path)
    assert bundle.version == "0.1"
    assert set(bundle.concepts) == {"metrics/revenue", "tables/orders"}
    revenue = bundle.get("metrics/revenue")
    assert revenue is not None
    assert revenue.links[0].target_id == "tables/orders"
    assert not [item for item in validate_bundle(bundle) if item.severity == Severity.ERROR]
    graph = graph_neighborhood(bundle, "metrics/revenue", 1)
    assert len(graph["nodes"]) == 2
    assert graph["edges"] == [
        {"source": "metrics/revenue", "target": "tables/orders", "kind": "markdown-link"},
        {"source": "tables/orders", "target": "metrics/revenue", "kind": "markdown-link"},
    ]


def test_validation_keeps_malformed_concepts_visible(bundle_path: Path) -> None:
    (bundle_path / "bad.md").write_text("plain markdown\n", encoding="utf-8")
    (bundle_path / "metrics/revenue.md").write_text(
        "---\ntype: Metric\ndescription: x\n---\n[missing](nope.md)\n", encoding="utf-8"
    )
    diagnostics = validate_bundle(load_bundle(bundle_path))
    assert {item.code for item in diagnostics} >= {"OKF001", "OKF102"}


def test_index_plan_and_create(bundle_path: Path) -> None:
    bundle = load_bundle(bundle_path)
    changes = plan_indexes(bundle)
    assert bundle_path / "metrics/index.md" in changes
    assert (
        "[Revenue](revenue.md) - Recognized revenue." in changes[bundle_path / "metrics/index.md"]
    )
    target, rendered = create_concept(
        bundle_path, "playbooks/month-close", "Playbook", title="Month Close"
    )
    assert target == bundle_path / "playbooks/month-close.md"
    assert "type: Playbook" in rendered
    assert not target.exists()


def test_move_repairs_inbound_links(bundle_path: Path) -> None:
    bundle = load_bundle(bundle_path)
    changes = move_concept(bundle, "tables/orders", "sources/orders")
    assert changes[bundle_path / "tables/orders.md"] is None
    assert changes[bundle_path / "sources/orders.md"]
    assert "../sources/orders.md" in str(changes[bundle_path / "metrics/revenue.md"])


@pytest.mark.parametrize("raw", ["../escape", "/../escape", ".hidden/x", ""])
def test_safe_concept_path_rejects_escape(bundle_path: Path, raw: str) -> None:
    with pytest.raises(ValueError):
        safe_concept_path(bundle_path, raw)


def test_frontmatter_must_be_mapping() -> None:
    with pytest.raises(ValueError, match="mapping"):
        parse_frontmatter("---\n- one\n- two\n---\nbody")
