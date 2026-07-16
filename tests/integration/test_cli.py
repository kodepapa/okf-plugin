from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from okfleet.cli import app
from okfleet.registry import BundleRegistry

runner = CliRunner()


def _write_bundle_marker(root: Path) -> None:
    root.mkdir(parents=True)
    (root / "index.md").write_text(
        '---\nokf_version: "0.1"\n---\n\n# Knowledge\n', encoding="utf-8"
    )


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


def test_structured_and_source_output_is_never_rich_wrapped_or_interpreted(
    bundle_path: Path,
) -> None:
    concept = bundle_path / "metrics/revenue.md"
    source = concept.read_text(encoding="utf-8").replace(
        "description: Recognized revenue.",
        "description: " + "recognized revenue and customer adjustments " * 8,
    )
    concept.write_text(source, encoding="utf-8")

    jsonl = runner.invoke(
        app,
        ["list", str(bundle_path), "--type", "Metric", "--format", "jsonl"],
        terminal_width=50,
    )
    shown = runner.invoke(
        app, ["show", f"{bundle_path}:metrics/revenue", "--source"], terminal_width=50
    )

    assert jsonl.exit_code == 0, jsonl.output
    records = [json.loads(line) for line in jsonl.stdout.splitlines()]
    assert len(records) == 1
    assert records[0]["id"] == "metrics/revenue"
    assert shown.exit_code == 0, shown.output
    assert shown.stdout == source


def test_text_search_preserves_matches_without_leaking_fts_or_markdown_markers(
    bundle_path: Path,
) -> None:
    alias = "a-long-but-valid-analytics-bundle-alias"
    BundleRegistry().add(bundle_path, alias)
    result = runner.invoke(app, ["search", "Calculated", "--bundle", alias])
    nested = runner.invoke(app, ["search", "Revenue", "--bundle", alias])

    assert result.exit_code == 0, result.output
    assert "Calculated" in result.stdout
    assert "[Calculated]" not in result.stdout
    assert nested.exit_code == 0, nested.output
    assert f"{alias}:metrics/revenue" in nested.stdout
    assert "[Revenue]]" not in nested.stdout
    assert "](../" not in nested.stdout


def test_index_preview_emits_an_unwrapped_unified_diff(bundle_path: Path) -> None:
    long_description = ("A deliberately long description " * 8).strip()
    concept = bundle_path / "metrics/revenue.md"
    concept.write_text(
        concept.read_text(encoding="utf-8").replace(
            "description: Recognized revenue.", f"description: {long_description}"
        ),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["index", str(bundle_path)], terminal_width=50)

    assert result.exit_code == 0, result.output
    assert long_description in result.stdout


def test_mcp_config_remains_valid_json_with_a_long_command() -> None:
    command = "/a/" + "very-long-directory/" * 8 + "okfleet"

    result = runner.invoke(
        app, ["mcp", "config", "--command", command], terminal_width=40
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["mcpServers"]["okfleet"]["command"] == command


def test_web_rejects_out_of_range_ports_without_a_traceback() -> None:
    result = runner.invoke(app, ["web", "--port", "70000"])

    assert result.exit_code == 2, result.output
    assert "65535" in result.output
    assert "Traceback" not in result.output


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


def test_discover_is_read_only_without_autoregister(tmp_path: Path) -> None:
    bundle = tmp_path / "scan" / "knowledge"
    _write_bundle_marker(bundle)

    result = runner.invoke(app, ["discover", str(tmp_path / "scan"), "--format", "json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["autoregister"] is False
    assert payload["registered_count"] == 0
    assert payload["already_registered_count"] == 0
    assert payload["bundles"][0]["source"] == "local"
    assert not Path(os.environ["OKFLEET_CONFIG"]).exists()


def test_discover_autoregister_is_idempotent_and_resolves_aliases(tmp_path: Path) -> None:
    existing = tmp_path / "registered" / "knowledge"
    existing.mkdir(parents=True)
    registry = BundleRegistry()
    registry.add(existing)

    scan = tmp_path / "scan"
    _write_bundle_marker(scan / "team-a" / "knowledge")
    _write_bundle_marker(scan / "team-b" / "knowledge")

    first = runner.invoke(app, ["discover", str(scan), "--autoregister", "--format", "json"])
    assert first.exit_code == 0, first.output
    first_payload = json.loads(first.stdout)
    assert first_payload["registered_count"] == 2
    assert first_payload["already_registered_count"] == 0
    assert [item["alias"] for item in first_payload["bundles"]] == [
        "knowledge-2",
        "knowledge-3",
    ]
    assert {item["registration"] for item in first_payload["bundles"]} == {"registered"}
    assert {item["source"] for item in first_payload["bundles"]} == {"global"}
    first_ids = {item["path"]: item["id"] for item in first_payload["bundles"]}

    second = runner.invoke(app, ["discover", str(scan), "-autoregister", "--format", "json"])
    assert second.exit_code == 0, second.output
    second_payload = json.loads(second.stdout)
    assert second_payload["registered_count"] == 0
    assert second_payload["already_registered_count"] == 2
    assert {item["registration"] for item in second_payload["bundles"]} == {"already-registered"}
    assert {item["path"]: item["id"] for item in second_payload["bundles"]} == first_ids
    assert len(BundleRegistry().list()) == 3


def test_discover_autoregister_preserves_existing_custom_alias(tmp_path: Path) -> None:
    bundle = tmp_path / "scan" / "knowledge"
    _write_bundle_marker(bundle)
    registered = BundleRegistry().add(bundle, "warehouse")

    result = runner.invoke(
        app, ["discover", str(tmp_path / "scan"), "--auto-register", "--format", "json"]
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["registered_count"] == 0
    assert payload["already_registered_count"] == 1
    assert payload["bundles"][0]["alias"] == "warehouse"
    assert payload["bundles"][0]["id"] == registered.id


def test_empty_search_scope_never_leaks_cached_results(bundle_path: Path) -> None:
    registry = BundleRegistry()
    registry.add(bundle_path, "main")
    populated = runner.invoke(app, ["search", "recognized", "--bundle", "main", "--format", "json"])
    assert populated.exit_code == 0, populated.output
    assert json.loads(populated.stdout)["hits"]

    registry.create_collection("empty")
    scoped = runner.invoke(
        app, ["search", "recognized", "--collection", "empty", "--format", "json"]
    )

    assert scoped.exit_code == 0, scoped.output
    assert json.loads(scoped.stdout)["hits"] == []


@pytest.mark.parametrize(
    "arguments",
    [
        ["bundles", "remove", "missing"],
        ["bundles", "rename", "missing", "new-name"],
        ["collections", "create", "team", "missing"],
        ["search", "query", "--collection", "missing"],
    ],
)
def test_registry_errors_are_clean_cli_errors(arguments: list[str]) -> None:
    result = runner.invoke(app, arguments)

    assert result.exit_code == 2, result.output
    assert "Traceback" not in result.output


def test_chat_rejects_nonsensical_modes_before_starting_provider() -> None:
    fleet_work = runner.invoke(app, ["chat", "question", "--scope", "fleet", "--mode", "work"])
    read_apply = runner.invoke(app, ["chat", "question", "--scope", "bundle", "--apply"])

    assert fleet_work.exit_code == 2, fleet_work.output
    assert "fleet scope is read-only" in fleet_work.output
    assert read_apply.exit_code == 2, read_apply.output
    assert "--apply requires bundle work mode" in read_apply.output


def test_index_rejects_write_and_check_together(bundle_path: Path) -> None:
    result = runner.invoke(app, ["index", str(bundle_path), "--write", "--check"])

    assert result.exit_code == 2, result.output
    assert "mutually exclusive" in result.output


def test_missing_import_and_policy_files_are_clean_cli_errors(
    bundle_path: Path, tmp_path: Path
) -> None:
    missing = tmp_path / "missing"
    imported = runner.invoke(app, ["import", str(missing), str(bundle_path), "--kind", "sql"])
    validated = runner.invoke(app, ["validate", str(bundle_path), "--policy", str(missing)])

    for result in (imported, validated):
        assert result.exit_code == 2, result.output
        assert "Traceback" not in result.output
