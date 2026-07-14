from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_okfleet_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OKFLEET_CONFIG", str(tmp_path / "state/config.toml"))
    monkeypatch.setenv("OKFLEET_DATABASE", str(tmp_path / "state/okfleet.db"))
    monkeypatch.setenv("OKFLEET_CHANGESETS", str(tmp_path / "state/changesets"))


@pytest.fixture()
def bundle_path(tmp_path: Path) -> Path:
    root = tmp_path / "bundle"
    (root / "metrics").mkdir(parents=True)
    (root / "tables").mkdir()
    (root / "index.md").write_text(
        '---\nokf_version: "0.1"\n---\n\n# Subdirectories\n', encoding="utf-8"
    )
    (root / "metrics/revenue.md").write_text(
        "---\ntype: Metric\ntitle: Revenue\ndescription: Recognized revenue.\n"
        "tags: [finance]\ntimestamp: 2026-07-14T00:00:00Z\n---\n\n"
        "Calculated from [orders](../tables/orders.md).\n",
        encoding="utf-8",
    )
    (root / "tables/orders.md").write_text(
        "---\ntype: Table\ntitle: Orders\ndescription: One row per order.\n---\n\n"
        "Feeds [revenue](../metrics/revenue.md).\n",
        encoding="utf-8",
    )
    (root / "log.md").write_text("# Log\n\n## 2026-07-14\n\n* Created.\n", encoding="utf-8")
    return root
