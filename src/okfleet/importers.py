from __future__ import annotations

import importlib.metadata
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, cast

from ruamel.yaml import YAML

from .core import render_concept, safe_concept_path


@dataclass(slots=True)
class ImportedConcept:
    concept_id: str
    concept_type: str
    title: str
    description: str
    body: str
    extra: dict[str, Any] = field(default_factory=dict)


class Importer(Protocol):
    def __call__(self, source: Path) -> list[ImportedConcept]: ...


def _slug(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "-", value).strip("-").casefold() or "item"


def _structured(source: Path) -> object:
    text = source.read_text(encoding="utf-8")
    if source.suffix.casefold() == ".json":
        return cast(object, json.loads(text))
    return cast(object, YAML(typ="safe").load(text))


def import_openapi(source: Path) -> list[ImportedConcept]:
    data = _structured(source)
    if not isinstance(data, dict) or not (data.get("openapi") or data.get("swagger")):
        raise ValueError("source is not an OpenAPI document")
    raw_info = data.get("info")
    info: dict[Any, Any] = raw_info if isinstance(raw_info, dict) else {}
    api_title = str(info.get("title") or source.stem)
    api_slug = _slug(api_title)
    concepts = [
        ImportedConcept(
            f"apis/{api_slug}",
            "API",
            api_title,
            str(info.get("description") or f"Imported from {source.name}."),
            f"# Overview\n\nOpenAPI version `{data.get('openapi') or data.get('swagger')}`.\n",
            {"version": str(info.get("version") or "")},
        )
    ]
    raw_paths = data.get("paths")
    paths: dict[Any, Any] = raw_paths if isinstance(raw_paths, dict) else {}
    methods = {"get", "put", "post", "delete", "patch", "head", "options"}
    for route, operations in paths.items():
        if not isinstance(operations, dict):
            continue
        for method, operation in operations.items():
            if method.casefold() not in methods:
                continue
            operation = operation if isinstance(operation, dict) else {}
            operation_id = str(operation.get("operationId") or f"{method}-{route}")
            concepts.append(
                ImportedConcept(
                    f"apis/{api_slug}/{_slug(operation_id)}",
                    "API Endpoint",
                    str(operation.get("summary") or operation_id),
                    str(operation.get("description") or f"{method.upper()} {route}"),
                    f"# Endpoint\n\n`{method.upper()} {route}`\n\nPart of [{api_title}](../{api_slug}.md).\n",
                    {"method": method.upper(), "path": str(route), "operation_id": operation_id},
                )
            )
    return concepts


def import_dbt(source: Path) -> list[ImportedConcept]:
    data = _structured(source)
    if not isinstance(data, dict) or not isinstance(data.get("nodes"), dict):
        raise ValueError("source is not a dbt manifest")
    raw_sources = data.get("sources")
    sources: dict[Any, Any] = raw_sources if isinstance(raw_sources, dict) else {}
    nodes = data["nodes"]
    assert isinstance(nodes, dict)
    entries = {**sources, **nodes}
    concepts: list[ImportedConcept] = []
    for unique_id, node in entries.items():
        if not isinstance(node, dict) or node.get("resource_type") not in {
            "model",
            "seed",
            "snapshot",
            "source",
        }:
            continue
        name = str(node.get("name") or unique_id)
        raw_columns = node.get("columns")
        columns: dict[Any, Any] = raw_columns if isinstance(raw_columns, dict) else {}
        rows = ["| Column | Description |", "|---|---|"]
        for column_name, column in columns.items():
            description = column.get("description", "") if isinstance(column, dict) else ""
            rows.append(f"| `{column_name}` | {description} |")
        concepts.append(
            ImportedConcept(
                f"dbt/{_slug(str(unique_id))}",
                "dbt Model",
                name,
                str(node.get("description") or f"Imported dbt {node.get('resource_type')}."),
                "# Columns\n\n" + "\n".join(rows) + "\n",
                {
                    "resource": node.get("relation_name") or node.get("database"),
                    "dbt_unique_id": str(unique_id),
                },
            )
        )
    return concepts


CREATE_TABLE_RE = re.compile(
    r"CREATE\s+(?:OR\s+REPLACE\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([\w.`\"\[\]-]+)\s*\((.*?)\)\s*;",
    re.IGNORECASE | re.DOTALL,
)


def import_sql(source: Path) -> list[ImportedConcept]:
    concepts: list[ImportedConcept] = []
    for match in CREATE_TABLE_RE.finditer(source.read_text(encoding="utf-8")):
        resource = match.group(1).strip('`"[]')
        columns: list[str] = []
        for definition in match.group(2).split(","):
            parts = definition.strip().split()
            if len(parts) < 2 or parts[0].casefold() in {
                "primary",
                "foreign",
                "constraint",
                "unique",
                "check",
            }:
                continue
            column_name = parts[0].strip('`"[]')
            columns.append(f"| `{column_name}` | `{parts[1]}` |")
        body = "# Schema\n\n| Column | Type |\n|---|---|\n" + "\n".join(columns) + "\n"
        concepts.append(
            ImportedConcept(
                f"tables/{_slug(resource)}",
                "Table",
                resource.split(".")[-1],
                f"Table imported from {source.name}.",
                body,
                {"resource": resource},
            )
        )
    if not concepts:
        raise ValueError("no CREATE TABLE statements found")
    return concepts


def import_catalog(source: Path) -> list[ImportedConcept]:
    data = _structured(source)
    assets = data.get("assets") if isinstance(data, dict) else data
    if not isinstance(assets, list):
        raise ValueError("catalog must be a list or an object with an assets list")
    concepts: list[ImportedConcept] = []
    for index, asset in enumerate(assets):
        if not isinstance(asset, dict):
            continue
        identifier = str(asset.get("id") or asset.get("name") or f"asset-{index + 1}")
        concepts.append(
            ImportedConcept(
                f"catalog/{_slug(identifier)}",
                str(asset.get("type") or "Data Asset"),
                str(asset.get("title") or asset.get("name") or identifier),
                str(asset.get("description") or "Imported catalog asset."),
                str(asset.get("body") or "# Notes\n\nImported by OKFleet.\n"),
                {"resource": asset.get("resource") or asset.get("url")},
            )
        )
    return concepts


BUILTINS: dict[str, Importer] = {
    "openapi": import_openapi,
    "dbt": import_dbt,
    "sql": import_sql,
    "catalog": import_catalog,
}


def resolve_importer(kind: str) -> Importer:
    if kind in BUILTINS:
        return BUILTINS[kind]
    for entry in importlib.metadata.entry_points(group="okfleet.importers"):
        if entry.name == kind:
            loaded = entry.load()
            if callable(loaded):
                return cast(Importer, loaded)
    raise KeyError(kind)


def plan_import(
    source: Path,
    bundle_root: Path,
    *,
    kind: str,
    replace: bool = False,
) -> dict[Path, str]:
    changes: dict[Path, str] = {}
    for concept in resolve_importer(kind)(source.expanduser().resolve()):
        path = safe_concept_path(bundle_root, concept.concept_id)
        if path.exists() and not replace:
            raise FileExistsError(f"concept already exists: {concept.concept_id}")
        frontmatter = {
            "type": concept.concept_type,
            "title": concept.title,
            "description": concept.description,
            "source": str(source),
            **{
                key: value
                for key, value in concept.extra.items()
                if value is not None and value != ""
            },
        }
        changes[path] = render_concept(frontmatter, concept.body)
    return changes
