from __future__ import annotations

from typing import Any

from .models import Bundle, Concept


def _metadata(concept: Concept) -> dict[str, Any]:
    return {
        "title": concept.title,
        "type": concept.concept_type,
        "description": concept.description,
        "tags": concept.tags,
        "resource": (concept.frontmatter or {}).get("resource"),
    }


def compare_bundles(left: Bundle, right: Bundle) -> dict[str, Any]:
    """Compare two bundles by stable concept ID and content/metadata hashes."""
    left_ids = set(left.concepts)
    right_ids = set(right.concepts)
    changed: list[dict[str, Any]] = []
    for concept_id in sorted(left_ids & right_ids):
        before = left.concepts[concept_id]
        after = right.concepts[concept_id]
        if before.content_hash == after.content_hash:
            continue
        before_metadata = _metadata(before)
        after_metadata = _metadata(after)
        changed.append(
            {
                "concept_id": concept_id,
                "metadata_changed": before_metadata != after_metadata,
                "body_changed": before.body != after.body,
                "before": before_metadata,
                "after": after_metadata,
            }
        )
    return {
        "schema_version": 1,
        "left": str(left.root),
        "right": str(right.root),
        "added": sorted(right_ids - left_ids),
        "removed": sorted(left_ids - right_ids),
        "changed": changed,
        "unchanged": len(left_ids & right_ids) - len(changed),
    }
