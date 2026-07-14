from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .core import graph_neighborhood, inbound_links, load_bundle, validate_bundle
from .models import BundleRef
from .registry import BundleRegistry
from .search import SearchDatabase

READ_ONLY_TOOL = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)


def create_server(
    *,
    registry_path: Path | None = None,
    database_path: Path | None = None,
    allowed_aliases: set[str] | None = None,
) -> FastMCP:
    server = FastMCP("OKFleet read-only knowledge tools")
    registry = BundleRegistry(registry_path)

    def selected(alias: str) -> BundleRef:
        if allowed_aliases is not None and alias not in allowed_aliases:
            raise ValueError(f"bundle is outside this session scope: {alias}")
        ref = registry.get(alias)
        if not ref or not ref.available:
            raise ValueError(f"unknown or unavailable bundle: {alias}")
        return ref

    @server.tool(annotations=READ_ONLY_TOOL)
    def okfleet_list_bundles() -> list[dict[str, Any]]:
        """List readable registered OKF bundles in this session scope. This tool is read-only."""
        return [
            ref.to_dict()
            for ref in registry.list()
            if ref.available and (allowed_aliases is None or ref.alias in allowed_aliases)
        ]

    @server.tool(annotations=READ_ONLY_TOOL)
    def okfleet_search_concepts(
        query: str, bundles: list[str] | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        """Search OKF concepts and return bundle-qualified citations. This tool is read-only."""
        aliases = bundles or [ref["alias"] for ref in okfleet_list_bundles()]
        refs = [selected(alias) for alias in aliases]
        with SearchDatabase(database_path) as database:
            for ref in refs:
                database.index_bundle(ref, load_bundle(ref.path))
            return [
                hit.to_dict()
                for hit in database.search(
                    query, bundle_ids=[ref.id for ref in refs], limit=max(1, min(limit, 100))
                )
            ]

    @server.tool(annotations=READ_ONLY_TOOL)
    def okfleet_get_concept(
        bundle: str, concept_id: str, include_source: bool = False
    ) -> dict[str, Any]:
        """Read one OKF concept by bundle and ID. This tool is read-only."""
        ref = selected(bundle)
        concept = load_bundle(ref.path).get(concept_id)
        if not concept:
            raise ValueError(f"unknown concept: {bundle}:{concept_id}")
        result = concept.summary_dict(ref.alias)
        result["body"] = concept.body
        result["links"] = [link.to_dict() for link in concept.links]
        if include_source:
            result["source"] = concept.source
        return result

    @server.tool(annotations=READ_ONLY_TOOL)
    def okfleet_get_links(
        bundle: str, concept_id: str, direction: str = "both", depth: int = 1
    ) -> dict[str, Any]:
        """Read outgoing/incoming links or a graph neighborhood. This tool is read-only."""
        ref = selected(bundle)
        loaded = load_bundle(ref.path)
        concept = loaded.get(concept_id)
        if not concept:
            raise ValueError(f"unknown concept: {bundle}:{concept_id}")
        incoming = inbound_links(loaded).get(concept.concept_id, [])
        return {
            "citation": concept.citation(ref.alias),
            "outbound": [link.to_dict() for link in concept.links]
            if direction in {"both", "outbound"}
            else [],
            "inbound": [link.to_dict() for link in incoming]
            if direction in {"both", "inbound"}
            else [],
            "graph": graph_neighborhood(loaded, concept.concept_id, max(0, min(depth, 5))),
        }

    @server.tool(annotations=READ_ONLY_TOOL)
    def okfleet_get_bundle_health(
        bundle: str, severities: list[str] | None = None, limit: int = 200
    ) -> list[dict[str, Any]]:
        """Read validation and maintenance diagnostics for one bundle. This tool is read-only."""
        ref = selected(bundle)
        diagnostics = validate_bundle(
            load_bundle(ref.path), include_health=True, stale_after_days=180
        )
        allowed = set(severities or ["error", "warning", "info"])
        return [item.to_dict(ref.path) for item in diagnostics if item.severity.value in allowed][
            : max(1, min(limit, 1000))
        ]

    @server.tool(annotations=READ_ONLY_TOOL)
    def okfleet_get_index(bundle: str, directory: str = ".") -> dict[str, str]:
        """Read an OKF directory index. This tool is read-only."""
        ref = selected(bundle)
        target = (ref.path / directory / "index.md").resolve()
        try:
            target.relative_to(ref.path)
        except ValueError as exc:
            raise ValueError("directory escapes bundle root") from exc
        if not target.exists():
            raise ValueError(f"index does not exist: {directory}")
        return {
            "bundle": ref.alias,
            "directory": directory,
            "source": target.read_text(encoding="utf-8"),
        }

    return server


def serve(
    *,
    registry_path: Path | None = None,
    database_path: Path | None = None,
    allowed_aliases: set[str] | None = None,
) -> None:
    server = create_server(
        registry_path=registry_path,
        database_path=database_path,
        allowed_aliases=allowed_aliases,
    )
    server.run(transport="stdio")


def mcp_config(command: str = "okfleet") -> str:
    return (
        json.dumps(
            {"mcpServers": {"okfleet": {"command": command, "args": ["mcp", "serve"]}}},
            indent=2,
        )
        + "\n"
    )
