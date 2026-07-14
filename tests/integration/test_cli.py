from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from okfleet.cli import app

runner = CliRunner()


def test_validate_json(bundle_path: Path) -> None:
    result = runner.invoke(app, ["validate", str(bundle_path), "--format", "json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["schema_version"] == 1
    assert payload["diagnostics"] == []


def test_list_and_graph(bundle_path: Path) -> None:
    listed = runner.invoke(app, ["list", str(bundle_path)])
    assert listed.exit_code == 0
    assert "metrics/revenue" in listed.stdout
    graph = runner.invoke(app, ["graph", f"{bundle_path}:metrics/revenue"])
    assert graph.exit_code == 0, graph.output
    assert "flowchart LR" in graph.stdout


def test_import_preview_then_write(bundle_path: Path, tmp_path: Path) -> None:
    source = tmp_path / "schema.sql"
    source.write_text(
        "CREATE TABLE analytics.customers (id BIGINT, email TEXT);\n", encoding="utf-8"
    )
    preview = runner.invoke(app, ["import", str(source), str(bundle_path), "--kind", "sql"])
    assert preview.exit_code == 0, preview.output
    assert "tables/analytics-customers.md" in preview.stdout
    assert not (bundle_path / "tables/analytics-customers.md").exists()

    written = runner.invoke(
        app, ["import", str(source), str(bundle_path), "--kind", "sql", "--write"]
    )
    assert written.exit_code == 0, written.output
    assert (bundle_path / "tables/analytics-customers.md").is_file()


def test_compare_and_semantic_search_cli(bundle_path: Path) -> None:
    compared = runner.invoke(
        app, ["compare", str(bundle_path), str(bundle_path), "--format", "json"]
    )
    assert compared.exit_code == 0, compared.output
    assert json.loads(compared.stdout)["changed"] == []

    searched = runner.invoke(
        app,
        [
            "search",
            "recognized income",
            "--bundle",
            str(bundle_path),
            "--semantic",
            "--format",
            "json",
        ],
    )
    assert searched.exit_code == 0, searched.output
    assert json.loads(searched.stdout)["hits"][0]["concept_id"] == "metrics/revenue"
