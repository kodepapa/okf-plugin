from __future__ import annotations

from pathlib import Path

import pytest

from okfleet.core import (
    create_concept,
    graph_neighborhood,
    load_bundle,
    move_concept,
    parse_concept,
    parse_frontmatter,
    plan_indexes,
    safe_concept_path,
    validate_bundle,
)
from okfleet.models import Severity


def _symlink_or_skip(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target, target_is_directory=target.is_dir())
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlinks are unavailable on this platform: {exc}")


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


def test_load_bundle_skips_symlinked_concept_files(bundle_path: Path, tmp_path: Path) -> None:
    external = tmp_path / "external-concept.md"
    external.write_text(
        "---\ntype: Secret\ntitle: External\ndescription: Must not be read.\n---\n\nOutside.\n",
        encoding="utf-8",
    )
    external_link = bundle_path / "metrics/external.md"
    _symlink_or_skip(external_link, external)
    alias = bundle_path / "metrics/revenue-alias.md"
    _symlink_or_skip(alias, bundle_path / "metrics/revenue.md")

    bundle = load_bundle(bundle_path)

    assert set(bundle.concepts) == {"metrics/revenue", "tables/orders"}
    with pytest.raises(OSError, match="symlink"):
        parse_concept(bundle_path, external_link)


def test_load_bundle_skips_symlinked_directories(bundle_path: Path, tmp_path: Path) -> None:
    external = tmp_path / "external-bundle-section"
    external.mkdir()
    (external / "leaked.md").write_text(
        "---\ntype: Secret\ntitle: Leaked\ndescription: Must not be read.\n---\n",
        encoding="utf-8",
    )
    _symlink_or_skip(bundle_path / "linked", external)

    bundle = load_bundle(bundle_path)

    assert "linked/leaked" not in bundle.concepts


def test_symlinked_root_index_is_not_a_bundle_marker(bundle_path: Path, tmp_path: Path) -> None:
    external = tmp_path / "external-index.md"
    external.write_text('---\nokf_version: "999"\n---\n\n# External\n', encoding="utf-8")
    root_index = bundle_path / "index.md"
    root_index.unlink()
    _symlink_or_skip(root_index, external)

    bundle = load_bundle(bundle_path)

    assert bundle.version is None
    assert root_index not in bundle.indexes
    planned = plan_indexes(bundle)
    assert root_index in planned
    assert "999" not in planned[root_index]
