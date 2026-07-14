from __future__ import annotations

import shutil
from pathlib import Path

from okfleet.core import load_bundle
from okfleet.drift import compare_bundles


def test_compare_bundles_reports_added_and_changed(bundle_path: Path, tmp_path: Path) -> None:
    other = tmp_path / "other"
    shutil.copytree(bundle_path, other)
    metric = other / "metrics/revenue.md"
    metric.write_text(metric.read_text(encoding="utf-8") + "Changed.\n", encoding="utf-8")
    (other / "metrics/margin.md").write_text(
        "---\ntype: Metric\ntitle: Margin\ndescription: Margin.\n---\n\nDefinition.\n",
        encoding="utf-8",
    )
    result = compare_bundles(load_bundle(bundle_path), load_bundle(other))
    assert result["added"] == ["metrics/margin"]
    assert result["changed"][0]["concept_id"] == "metrics/revenue"
