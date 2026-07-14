from __future__ import annotations

from pathlib import Path

from okfleet.importers import plan_import


def test_sql_importer_plans_table_concept(bundle_path: Path, tmp_path: Path) -> None:
    source = tmp_path / "schema.sql"
    source.write_text(
        "CREATE TABLE analytics.orders (id STRING, amount NUMERIC);", encoding="utf-8"
    )
    changes = plan_import(source, bundle_path, kind="sql")
    path, content = next(iter(changes.items()))
    assert path.name == "analytics-orders.md"
    assert "resource: analytics.orders" in content
    assert "`amount`" in content


def test_openapi_importer_plans_api_and_endpoint(bundle_path: Path, tmp_path: Path) -> None:
    source = tmp_path / "openapi.json"
    source.write_text(
        '{"openapi":"3.1.0","info":{"title":"Billing","version":"1"},'
        '"paths":{"/invoices":{"get":{"operationId":"listInvoices"}}}}',
        encoding="utf-8",
    )
    changes = plan_import(source, bundle_path, kind="openapi")
    assert len(changes) == 2
    assert any("GET /invoices" in content for content in changes.values())
