from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import tempfile
from collections import Counter
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.padding import Padding
from rich.table import Table
from rich.text import Text
from watchfiles import watch

from . import __version__
from .agents import provider_for
from .chat import ChatService
from .core import (
    apply_indexes,
    atomic_write,
    create_concept,
    graph_dot,
    graph_mermaid,
    graph_neighborhood,
    inbound_links,
    load_bundle,
    move_concept,
    plan_indexes,
    unified_diff,
    validate_bundle,
)
from .drift import compare_bundles
from .extensions import extension_diagnostics, load_template
from .git import bundle_git_status
from .importers import BUILTINS as BUILTIN_IMPORTERS
from .importers import plan_import
from .mcp_server import mcp_config
from .mcp_server import serve as serve_mcp
from .models import AgentEventType, BundleRef, Diagnostic, Severity
from .pending import PendingChangeStore
from .policy import load_policy, policy_diagnostics
from .registry import BundleRegistry, discover_bundles, resolve_bundle
from .remote import clone_remote, update_remote
from .search import SearchDatabase, default_database_path
from .semantic import semantic_search
from .workspace import StagedWorkspace

app = typer.Typer(
    name="okfleet",
    help="The terminal workbench for a fleet of Open Knowledge Format bundles.",
    add_completion=True,
    invoke_without_command=True,
    no_args_is_help=False,
)
bundles_app = typer.Typer(help="Manage the global bundle registry.")
collections_app = typer.Typer(help="Manage named bundle collections.")
searches_app = typer.Typer(help="Manage reusable fleet searches.")
sessions_app = typer.Typer(help="Inspect saved provider sessions.")
changesets_app = typer.Typer(help="Review persisted staged work sessions.")
cache_app = typer.Typer(help="Inspect or rebuild local derived state.")
mcp_app = typer.Typer(help="Run or configure the read-only OKFleet MCP server.")
app.add_typer(bundles_app, name="bundles")
app.add_typer(collections_app, name="collections")
app.add_typer(searches_app, name="searches")
app.add_typer(sessions_app, name="sessions")
app.add_typer(changesets_app, name="changesets")
app.add_typer(cache_app, name="cache")
app.add_typer(mcp_app, name="mcp")

console = Console()
error_console = Console(stderr=True)


class TextJsonFormat(StrEnum):
    TEXT = "text"
    JSON = "json"


class ConceptListFormat(StrEnum):
    TEXT = "text"
    JSON = "json"
    JSONL = "jsonl"


class ValidationFormat(StrEnum):
    TEXT = "text"
    JSON = "json"
    SARIF = "sarif"


class GraphFormat(StrEnum):
    MERMAID = "mermaid"
    DOT = "dot"
    JSON = "json"


class LinkDirection(StrEnum):
    BOTH = "both"
    OUTBOUND = "outbound"
    INBOUND = "inbound"


class ChatMode(StrEnum):
    READ = "read"
    WORK = "work"


class ProviderName(StrEnum):
    CODEX = "codex"
    CLAUDE = "claude"
    CLAUDE_CODE = "claude-code"


def _registry(path: Path | None = None) -> BundleRegistry:
    return BundleRegistry(path)


def _plugin_root() -> Path | None:
    configured = os.environ.get("OKFLEET_PLUGIN_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / ".claude-plugin").exists() and (parent / "skills").exists():
            return parent
    packaged = Path(__file__).resolve().parent / "provider_plugin"
    return packaged if (packaged / ".claude-plugin").exists() else None


def _json(data: Any) -> None:
    _raw_output(json.dumps(data, default=str, indent=2), end="\n")


def _raw_output(text: str, *, end: str = "") -> None:
    """Write structured or source output without Rich interpreting or wrapping it."""
    sys.stdout.write(text)
    sys.stdout.write(end)
    sys.stdout.flush()


def _ref(value: str, registry_path: Path | None = None) -> BundleRef:
    try:
        return resolve_bundle(value, _registry(registry_path))
    except ValueError as exc:
        error_console.print(f"[red]error:[/] {exc}")
        raise typer.Exit(2) from exc


def _search_snippet(snippet: str, query: str) -> Text:
    """Turn FTS match markers and Markdown links into a compact readable excerpt."""
    terms = {
        token.casefold().rstrip("*")
        for token in re.findall(r"[\w-]+\*?", query)
        if token.rstrip("*")
    }

    def unmark(match: re.Match[str]) -> str:
        value = match.group(1)
        folded = value.casefold()
        if any(folded == term or folded.startswith(term) for term in terms):
            return value
        return match.group(0)

    clean = re.sub(r"\[([^\[\]\n]+)\]", unmark, snippet)
    clean = re.sub(r"\[([^\]\n]+)\]\([^\n)]+\)", r"\1", clean)
    clean = " ".join(clean.split())
    rendered = Text(clean)
    if terms:
        pattern = "|".join(
            re.escape(term) + r"\w*" for term in sorted(terms, key=len, reverse=True)
        )
        rendered.highlight_regex(rf"(?i)\b(?:{pattern})\b", style="bold cyan")
    return rendered


def _diagnostic_table(diagnostics: list[Diagnostic], root: Path) -> Table:
    table = Table("Severity", "Code", "Location", "Message", expand=True)
    colors = {Severity.ERROR: "red", Severity.WARNING: "yellow", Severity.INFO: "cyan"}
    for item in diagnostics:
        try:
            location = str(item.path.relative_to(root))
        except ValueError:
            location = str(item.path)
        if item.line:
            location += f":{item.line}"
        table.add_row(
            f"[{colors[item.severity]}]{item.severity.value.upper()}[/]",
            item.code,
            location,
            item.message,
        )
    return table


def _sarif(diagnostics: list[Diagnostic], root: Path) -> dict[str, Any]:
    rules = {
        item.code: {
            "id": item.code,
            "shortDescription": {"text": item.message.split(":", 1)[0]},
        }
        for item in diagnostics
    }
    levels = {Severity.ERROR: "error", Severity.WARNING: "warning", Severity.INFO: "note"}
    return {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "OKFleet",
                        "version": __version__,
                        "rules": list(rules.values()),
                    }
                },
                "results": [
                    {
                        "ruleId": item.code,
                        "level": levels[item.severity],
                        "message": {"text": item.message},
                        "locations": [
                            {
                                "physicalLocation": {
                                    "artifactLocation": {
                                        "uri": item.path.relative_to(root).as_posix()
                                    },
                                    "region": {
                                        "startLine": item.line or 1,
                                        "startColumn": item.column or 1,
                                    },
                                }
                            }
                        ],
                    }
                    for item in diagnostics
                ],
            }
        ],
    }


@app.callback()
def root(
    ctx: typer.Context,
    version: Annotated[bool, typer.Option("--version", help="Show the OKFleet version.")] = False,
) -> None:
    if version:
        console.print(f"OKFleet {__version__}")
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        from .tui.app import run_tui

        run_tui(Path.cwd())


@app.command()
def tui(path: Annotated[Path | None, typer.Argument()] = None) -> None:
    """Open the full-screen OKFleet terminal workbench."""
    from .tui.app import run_tui

    run_tui(path or Path.cwd())


@app.command()
def web(
    host: Annotated[str, typer.Option(help="Address to bind.")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="TCP port to bind.", min=0, max=65535)] = 8765,
    local_root: Annotated[
        Path | None, typer.Option("--path", help="Also discover bundles below this path.")
    ] = None,
    allow_remote: Annotated[
        bool, typer.Option(help="Allow a non-loopback bind; no authentication is provided.")
    ] = False,
) -> None:
    """Serve the read-only fleet explorer in a local browser."""
    from .web import serve_web

    try:
        serve_web(
            host=host,
            port=port,
            local_root=(local_root or Path.cwd()).resolve(),
            allow_remote=allow_remote,
        )
    except (OSError, ValueError) as exc:
        error_console.print(f"[red]error:[/] {exc}")
        raise typer.Exit(2) from exc


@app.command()
def lsp() -> None:
    """Run the OKF diagnostics language server over stdio."""
    from .lsp import run_lsp

    run_lsp()


@app.command()
def discover(
    path: Annotated[Path | None, typer.Argument()] = None,
    depth: Annotated[int, typer.Option("--depth", min=0, max=20)] = 5,
    format: Annotated[TextJsonFormat, typer.Option("--format")] = TextJsonFormat.TEXT,
    autoregister: Annotated[
        bool,
        typer.Option(
            "--autoregister",
            "--auto-register",
            "-a",
            "-autoregister",
            help="Add every discovered bundle to the global registry.",
        ),
    ] = False,
) -> None:
    """Discover likely OKF bundle roots; registration is opt-in."""
    try:
        refs = discover_bundles(path or Path.cwd(), max_depth=depth)
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="PATH") from exc

    records = [ref.to_dict() for ref in refs]
    registered_count = 0
    already_registered_count = 0
    if autoregister and refs:
        try:
            registrations = _registry().add_many((ref.path, None) for ref in refs)
        except (OSError, ValueError) as exc:
            error_console.print(f"[red]error:[/] could not update registry: {exc}")
            raise typer.Exit(2) from exc
        records = []
        for discovered, (registered, added) in zip(refs, registrations, strict=True):
            record = registered.to_dict()
            record.update(
                {
                    "confidence": discovered.confidence,
                    "reason": discovered.reason,
                    "registration": "registered" if added else "already-registered",
                }
            )
            records.append(record)
            registered_count += int(added)
            already_registered_count += int(not added)

    if format == TextJsonFormat.JSON:
        _json(
            {
                "schema_version": 1,
                "autoregister": autoregister,
                "registered_count": registered_count,
                "already_registered_count": already_registered_count,
                "bundles": records,
            }
        )
        return
    if not refs:
        console.print("No OKF bundles found.")
        return
    columns = ["Alias", "Path", "Confidence", "Reason"]
    if autoregister:
        columns.append("Registration")
    table = Table(*columns)
    for ref, record in zip(refs, records, strict=True):
        row = [str(record["alias"]), str(record["path"]), ref.confidence, ref.reason]
        if autoregister:
            row.append(str(record["registration"]))
        table.add_row(*row)
    console.print(table)
    if autoregister:
        console.print(
            f"Registered {registered_count} new bundle(s); "
            f"{already_registered_count} already registered."
        )


@bundles_app.command("list")
def bundles_list(
    format: Annotated[TextJsonFormat, typer.Option("--format")] = TextJsonFormat.TEXT,
) -> None:
    """List globally registered bundles and their availability."""
    refs = _registry().list()
    if format == TextJsonFormat.JSON:
        _json({"schema_version": 1, "bundles": [ref.to_dict() for ref in refs]})
        return
    table = Table("Alias", "Path", "Status")
    for ref in refs:
        table.add_row(ref.alias, str(ref.path), "available" if ref.available else "[red]missing[/]")
    console.print(table)


@bundles_app.command("add")
def bundles_add(path: Path, alias: Annotated[str | None, typer.Option("--alias")] = None) -> None:
    """Register an existing local bundle without changing its files."""
    try:
        ref = _registry().add(path, alias)
    except (OSError, ValueError) as exc:
        raise typer.BadParameter(str(exc), param_hint="PATH") from exc
    console.print(f"Registered [bold]{ref.alias}[/] → {ref.path}")


@bundles_app.command("remove")
def bundles_remove(alias: str) -> None:
    """Forget a registered bundle without deleting its files."""
    try:
        ref = _registry().remove(alias)
    except KeyError as exc:
        raise typer.BadParameter(f"unknown bundle: {alias}", param_hint="ALIAS") from exc
    with SearchDatabase() as database:
        database.remove_bundle(ref.id)
    console.print(f"Removed [bold]{ref.alias}[/] from the registry (bundle files were untouched).")


@bundles_app.command("rename")
def bundles_rename(alias: str, new_alias: str) -> None:
    """Change a bundle's registry alias."""
    try:
        ref = _registry().rename(alias, new_alias)
    except KeyError as exc:
        raise typer.BadParameter(f"unknown bundle: {alias}", param_hint="ALIAS") from exc
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="NEW_ALIAS") from exc
    console.print(f"Renamed bundle alias to [bold]{ref.alias}[/].")


@bundles_app.command("refresh")
def bundles_refresh() -> None:
    """Refresh the derived search index for every available bundle."""
    total = 0
    with SearchDatabase() as database:
        for ref in _registry().list():
            if ref.available:
                total += database.index_bundle(ref, load_bundle(ref.path))
    console.print(f"Indexed {total} changed concept(s).")


@bundles_app.command("clone")
def bundles_clone(
    url: str,
    alias: Annotated[str | None, typer.Option("--alias")] = None,
    ref_name: Annotated[str | None, typer.Option("--ref")] = None,
) -> None:
    """Clone and register a remote bundle in OKFleet's explicit cache."""
    try:
        path = clone_remote(url, ref=ref_name)
    except (ValueError, RuntimeError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    registry = _registry()
    registered = registry.add(path, alias)
    registry.remotes[registered.id] = {"url": url, "ref": ref_name or ""}
    registry.save()
    console.print(f"Cloned {registered.alias} → {path}")


@bundles_app.command("update")
def bundles_update(alias: str) -> None:
    """Fast-forward a registered remote cache; local edits are never reset."""
    registry = _registry()
    ref = registry.get(alias)
    if not ref or ref.id not in registry.remotes:
        raise typer.BadParameter(f"bundle is not a registered remote: {alias}")
    try:
        update_remote(ref.path)
    except RuntimeError as exc:
        raise typer.BadParameter(str(exc)) from exc
    console.print(f"Updated {ref.alias}.")


@collections_app.command("list")
def collections_list() -> None:
    """List named collections and their registered bundle aliases."""
    registry = _registry()
    table = Table("Collection", "Bundles")
    for name, ids in sorted(registry.collections.items()):
        aliases = [item.alias for item in registry.list() if item.id in ids]
        table.add_row(name, ", ".join(aliases))
    console.print(table)


@collections_app.command("create")
def collections_create(
    name: str, bundles: Annotated[list[str] | None, typer.Argument()] = None
) -> None:
    """Create a collection, optionally with initial bundle members."""
    try:
        _registry().create_collection(name, bundles or [])
    except KeyError as exc:
        raise typer.BadParameter(f"unknown bundle: {exc.args[0]}") from exc
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="NAME") from exc
    console.print(f"Created collection [bold]{name}[/].")


@collections_app.command("add")
def collections_add(name: str, bundle: str) -> None:
    """Add a registered bundle to a collection."""
    registry = _registry()
    try:
        ref = registry.add_to_collection(name, bundle)
    except KeyError as exc:
        raise typer.BadParameter(f"unknown collection or bundle: {exc.args[0]}") from exc
    console.print(f"Added [bold]{ref.alias}[/] to [bold]{name}[/].")


@collections_app.command("remove")
def collections_remove(name: str, bundle: str) -> None:
    """Remove a bundle from a collection."""
    registry = _registry()
    try:
        ref = registry.remove_from_collection(name, bundle)
    except (KeyError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    console.print(f"Removed [bold]{ref.alias}[/] from [bold]{name}[/].")


@collections_app.command("delete")
def collections_delete(name: str) -> None:
    """Delete a collection without changing its bundles."""
    registry = _registry()
    if name not in registry.collections:
        raise typer.BadParameter(f"unknown collection: {name}")
    del registry.collections[name]
    registry.save()
    console.print(f"Deleted collection [bold]{name}[/].")


@app.command("list")
def list_concepts(
    bundle: str,
    concept_type: Annotated[str | None, typer.Option("--type")] = None,
    tag: Annotated[str | None, typer.Option("--tag")] = None,
    format: Annotated[ConceptListFormat, typer.Option("--format")] = ConceptListFormat.TEXT,
) -> None:
    """List and filter concepts in one bundle."""
    ref = _ref(bundle)
    loaded = load_bundle(ref.path)
    concepts = [
        concept
        for concept in loaded.concepts.values()
        if (not concept_type or concept.concept_type.casefold() == concept_type.casefold())
        and (not tag or tag in concept.tags)
    ]
    concepts.sort(key=lambda item: item.concept_id)
    if format in {ConceptListFormat.JSON, ConceptListFormat.JSONL}:
        records = [item.summary_dict(ref.alias) for item in concepts]
        if format == ConceptListFormat.JSONL:
            for record in records:
                _raw_output(json.dumps(record, default=str), end="\n")
        else:
            _json({"schema_version": 1, "concepts": records})
        return
    for concept in concepts:
        console.print(
            f"{concept.concept_id}  [{concept.concept_type or '?'}]  {concept.description}"
        )


@app.command()
def show(reference: str, source: Annotated[bool, typer.Option("--source")] = False) -> None:
    """Render one concept given BUNDLE:CONCEPT_ID."""
    if ":" not in reference:
        raise typer.BadParameter("reference must be BUNDLE:CONCEPT_ID")
    bundle_name, concept_id = reference.split(":", 1)
    ref = _ref(bundle_name)
    concept = load_bundle(ref.path).get(concept_id)
    if not concept:
        raise typer.BadParameter(f"unknown concept: {reference}")
    if source:
        _raw_output(concept.source)
    else:
        console.print(Markdown(concept.body))


@app.command()
def search(
    query: str,
    bundle: Annotated[list[str] | None, typer.Option("--bundle")] = None,
    collection: Annotated[str | None, typer.Option("--collection")] = None,
    limit: Annotated[int, typer.Option("--limit", min=1, max=1000)] = 20,
    format: Annotated[TextJsonFormat, typer.Option("--format")] = TextJsonFormat.TEXT,
    semantic: Annotated[
        bool, typer.Option("--semantic", help="Use opt-in local hash embeddings.")
    ] = False,
) -> None:
    """Search registered bundles, selected bundles, or one collection."""
    registry = _registry()
    try:
        refs = registry.collection(collection) if collection else registry.list()
    except KeyError as exc:
        raise typer.BadParameter(
            f"unknown collection: {collection}", param_hint="--collection"
        ) from exc
    if bundle:
        try:
            selected_refs = [resolve_bundle(value, registry) for value in bundle]
        except ValueError as exc:
            error_console.print(f"[red]error:[/] {exc}")
            raise typer.Exit(2) from exc
        if collection:
            allowed = {ref.id for ref in refs}
            refs = [ref for ref in selected_refs if ref.id in allowed]
        else:
            refs = selected_refs
        refs = list({ref.id: ref for ref in refs}.values())
    refs = [ref for ref in refs if ref.available]
    hits = []
    if refs:
        with SearchDatabase() as database:
            for ref in refs:
                database.index_bundle(ref, load_bundle(ref.path))
            bundle_ids = [ref.id for ref in refs]
            hits = (
                semantic_search(database, query, bundle_ids=bundle_ids, limit=limit)
                if semantic
                else database.search(query, bundle_ids=bundle_ids, limit=limit)
            )
    if format == TextJsonFormat.JSON:
        _json({"schema_version": 1, "hits": [hit.to_dict() for hit in hits]})
        return
    if not hits:
        console.print("No matches.")
        return
    for index, hit in enumerate(hits):
        if index:
            _raw_output("\n")
        _raw_output(hit.citation, end="\n")
        console.print(Padding(Text(f"{hit.concept_type or '?'} · {hit.description}"), (0, 0, 0, 2)))
        console.print(Padding(_search_snippet(hit.snippet, query), (0, 0, 0, 2)))


@searches_app.command("list")
def searches_list() -> None:
    """List reusable fleet searches."""
    registry = _registry()
    table = Table("Name", "Query", "Bundles", "Collection")
    for name, saved in sorted(registry.saved_searches.items()):
        table.add_row(
            name,
            str(saved.get("query", "")),
            ", ".join(str(item) for item in saved.get("bundles", [])),
            str(saved.get("collection") or ""),
        )
    console.print(table)


@searches_app.command("save")
def searches_save(
    name: str,
    query: str,
    bundle: Annotated[list[str] | None, typer.Option("--bundle")] = None,
    collection: Annotated[str | None, typer.Option("--collection")] = None,
) -> None:
    """Save a query and its optional bundle or collection scope."""
    try:
        _registry().save_search(name, query, bundles=bundle or [], collection=collection)
    except (KeyError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    console.print(f"Saved search [bold]{name}[/].")


@searches_app.command("run")
def searches_run(
    name: str,
    limit: Annotated[int, typer.Option("--limit", min=1, max=1000)] = 20,
    format: Annotated[TextJsonFormat, typer.Option("--format")] = TextJsonFormat.TEXT,
) -> None:
    """Run a saved search with its recorded scope."""
    saved = _registry().saved_searches.get(name)
    if not saved:
        raise typer.BadParameter(f"unknown saved search: {name}")
    search(
        str(saved["query"]),
        bundle=[str(item) for item in saved.get("bundles", [])] or None,
        collection=str(saved["collection"]) if saved.get("collection") else None,
        limit=limit,
        format=format,
        semantic=False,
    )


@searches_app.command("delete")
def searches_delete(name: str) -> None:
    """Delete a saved search."""
    try:
        _registry().delete_search(name)
    except KeyError as exc:
        raise typer.BadParameter(f"unknown saved search: {name}") from exc
    console.print(f"Deleted saved search {name}.")


@app.command()
def status(
    bundle: str,
    diff: Annotated[
        bool, typer.Option("--diff", help="Include staged and unstaged diffs.")
    ] = False,
    format: Annotated[TextJsonFormat, typer.Option("--format")] = TextJsonFormat.TEXT,
) -> None:
    """Show Git state scoped to an OKF bundle."""
    ref = _ref(bundle)
    data = {"schema_version": 1, **bundle_git_status(ref.path, include_diff=diff)}
    if format == TextJsonFormat.JSON:
        _json(data)
        return
    if not data["available"]:
        console.print(f"[yellow]{ref.alias} is not inside a Git repository.[/]")
        return
    console.print(f"[bold]{ref.alias}[/] · {data['branch'] or 'detached'} · {data['repository']}")
    table = Table("Index", "Worktree", "Path")
    for change in data["changes"]:
        table.add_row(change["index"], change["worktree"], change["path"])
    console.print(table)
    if diff:
        if data.get("staged_diff"):
            console.print("\n[bold]Staged[/]")
            _raw_output(data["staged_diff"])
        if data.get("diff"):
            console.print("\n[bold]Unstaged[/]")
            _raw_output(data["diff"])


@app.command()
def compare(
    left: str,
    right: str,
    format: Annotated[TextJsonFormat, typer.Option("--format")] = TextJsonFormat.TEXT,
) -> None:
    """Compare two OKF bundles and report concept drift."""
    left_ref = _ref(left)
    right_ref = _ref(right)
    result = compare_bundles(load_bundle(left_ref.path), load_bundle(right_ref.path))
    if format == TextJsonFormat.JSON:
        _json(result)
        return
    console.print(
        f"[bold]{left_ref.alias} → {right_ref.alias}[/] · "
        f"{len(result['added'])} added · {len(result['removed'])} removed · "
        f"{len(result['changed'])} changed · {result['unchanged']} unchanged"
    )
    table = Table("State", "Concept", "Detail")
    for concept_id in result["added"]:
        table.add_row("added", concept_id, "")
    for concept_id in result["removed"]:
        table.add_row("removed", concept_id, "")
    for item in result["changed"]:
        detail = ", ".join(
            key.removesuffix("_changed")
            for key in ("metadata_changed", "body_changed")
            if item[key]
        )
        table.add_row("changed", item["concept_id"], detail)
    console.print(table)


@app.command("import")
def import_data(
    source: Path,
    bundle: str,
    kind: Annotated[
        str, typer.Option("--kind", help="openapi, dbt, sql, catalog, or plugin importer")
    ],
    write: Annotated[bool, typer.Option("--write")] = False,
    replace: Annotated[bool, typer.Option("--replace")] = False,
) -> None:
    """Import structured developer knowledge into an OKF bundle."""
    ref = _ref(bundle)
    try:
        changes = plan_import(source, ref.path, kind=kind, replace=replace)
    except (KeyError, OSError, ValueError) as exc:
        available = ", ".join(sorted(BUILTIN_IMPORTERS))
        raise typer.BadParameter(f"{exc}; built-in importers: {available}") from exc
    if write:
        for path, content in changes.items():
            atomic_write(path, content)
        apply_indexes(plan_indexes(load_bundle(ref.path)))
        console.print(f"Imported {len(changes)} concept(s).")
        return
    for path, content in changes.items():
        console.print(f"[bold]{path.relative_to(ref.path)}[/]")
        _raw_output(content)
    console.print(f"Previewed {len(changes)} concept(s); add --write to apply.")


def _validate_command(
    bundle: str,
    format: ValidationFormat,
    health: bool,
    stale_after: int,
    policy: Path | None = None,
    extensions: bool = True,
) -> None:
    ref = _ref(bundle)
    loaded = load_bundle(ref.path)
    diagnostics = validate_bundle(
        loaded,
        include_health=health,
        stale_after_days=stale_after if health else None,
    )
    if policy:
        try:
            policy_pack = load_policy(policy)
        except (OSError, ValueError) as exc:
            raise typer.BadParameter(str(exc), param_hint="--policy") from exc
        diagnostics.extend(policy_diagnostics(loaded, policy_pack))
    if extensions:
        diagnostics.extend(extension_diagnostics(loaded))
    if format == ValidationFormat.JSON:
        _json(
            {"schema_version": 1, "diagnostics": [item.to_dict(ref.path) for item in diagnostics]}
        )
    elif format == ValidationFormat.SARIF:
        _json(_sarif(diagnostics, ref.path))
    else:
        console.print(_diagnostic_table(diagnostics, ref.path))
        counts = Counter(item.severity.value for item in diagnostics)
        console.print(
            f"{counts['error']} error(s), {counts['warning']} warning(s), {counts['info']} info"
        )
    if any(item.severity == Severity.ERROR for item in diagnostics):
        raise typer.Exit(1)


@app.command()
def validate(
    bundle: str,
    format: Annotated[ValidationFormat, typer.Option("--format")] = ValidationFormat.TEXT,
    policy: Annotated[Path | None, typer.Option("--policy")] = None,
    extensions: Annotated[bool, typer.Option("--extensions/--no-extensions")] = True,
) -> None:
    """Validate hard OKF conformance plus compatibility warnings."""
    _validate_command(bundle, format, False, 0, policy, extensions)


@app.command()
def health(
    bundle: str,
    stale_after: Annotated[int, typer.Option("--stale-after", min=1)] = 180,
    format: Annotated[ValidationFormat, typer.Option("--format")] = ValidationFormat.TEXT,
    policy: Annotated[Path | None, typer.Option("--policy")] = None,
) -> None:
    """Run validation plus staleness and graph-quality checks."""
    _validate_command(bundle, format, True, stale_after, policy)


@app.command()
def index(
    bundle: str,
    write: Annotated[bool, typer.Option("--write")] = False,
    check: Annotated[bool, typer.Option("--check")] = False,
) -> None:
    """Preview, write, or check generated directory indexes."""
    if write and check:
        raise typer.BadParameter("--write and --check are mutually exclusive")
    ref = _ref(bundle)
    loaded = load_bundle(ref.path)
    changes = plan_indexes(loaded)
    if write:
        apply_indexes(changes)
        for path in changes:
            console.print(f"wrote {path.relative_to(ref.path)}")
    else:
        for path, new in changes.items():
            old = path.read_text(encoding="utf-8") if path.exists() else ""
            _raw_output(unified_diff(path, old, new, ref.path))
    console.print(f"{len(changes)} index file(s) {'written' if write else 'would change'}")
    if check and changes:
        raise typer.Exit(1)


@app.command()
def links(
    reference: str,
    direction: Annotated[LinkDirection, typer.Option("--direction")] = LinkDirection.BOTH,
) -> None:
    """Show inbound, outbound, or bidirectional concept links."""
    if ":" not in reference:
        raise typer.BadParameter("reference must be BUNDLE:CONCEPT_ID")
    bundle_name, concept_id = reference.split(":", 1)
    ref = _ref(bundle_name)
    loaded = load_bundle(ref.path)
    concept = loaded.get(concept_id)
    if not concept:
        raise typer.BadParameter(f"unknown concept: {reference}")
    table = Table("Direction", "Concept", "Target", "Status", "Line")
    if direction in {LinkDirection.BOTH, LinkDirection.OUTBOUND}:
        for item in concept.links:
            table.add_row(
                "out",
                concept.concept_id,
                item.target_id or item.raw_target,
                "ok" if item.exists else "broken",
                str(item.line),
            )
    if direction in {LinkDirection.BOTH, LinkDirection.INBOUND}:
        for item in inbound_links(loaded).get(concept.concept_id, []):
            table.add_row("in", item.source_id, concept.concept_id, "ok", str(item.line))
    console.print(table)


@app.command()
def graph(
    scope: str,
    depth: Annotated[int, typer.Option("--depth", min=0, max=10)] = 1,
    format: Annotated[GraphFormat, typer.Option("--format")] = GraphFormat.MERMAID,
) -> None:
    """Render a bundle or concept-neighborhood graph."""
    bundle_name, _, concept_id = scope.partition(":")
    ref = _ref(bundle_name)
    data = graph_neighborhood(load_bundle(ref.path), concept_id or None, depth)
    if format == GraphFormat.JSON:
        _json(data)
    elif format == GraphFormat.DOT:
        _raw_output(graph_dot(data), end="\n")
    else:
        _raw_output(graph_mermaid(data), end="\n")


@app.command("new")
def new_concept(
    bundle: str,
    concept_id: str,
    concept_type: Annotated[str, typer.Option("--type")],
    title: Annotated[str | None, typer.Option("--title")] = None,
    description: Annotated[str, typer.Option("--description")] = "",
    template: Annotated[str | None, typer.Option("--template")] = None,
    write: Annotated[bool, typer.Option("--write")] = False,
) -> None:
    """Preview or create a typed concept and refresh its indexes."""
    ref = _ref(bundle)
    extra: dict[str, Any] = {}
    body = "Describe this concept.\n"
    if template:
        try:
            template_data = load_template(
                template,
                {
                    "bundle": str(ref.path),
                    "concept_id": concept_id,
                    "type": concept_type,
                    "title": title,
                    "description": description,
                },
            )
        except (KeyError, TypeError) as exc:
            raise typer.BadParameter(str(exc)) from exc
        raw_frontmatter = template_data.get("frontmatter", {})
        if isinstance(raw_frontmatter, dict):
            extra = dict(raw_frontmatter)
            concept_type = str(extra.pop("type", concept_type))
            title = str(extra.pop("title", title or "")) or title
            description = str(extra.pop("description", description))
        body = str(template_data.get("body") or body)
    path, text = create_concept(
        ref.path,
        concept_id,
        concept_type,
        title=title,
        description=description,
        extra=extra,
        body=body,
        write=write,
    )
    if write:
        apply_indexes(plan_indexes(load_bundle(ref.path)))
        console.print(f"created {path.relative_to(ref.path)}")
    else:
        console.print(f"Would create {path.relative_to(ref.path)}:\n")
        _raw_output(text)


@app.command()
def move(
    reference: str,
    new_id: str,
    update_links: Annotated[bool, typer.Option("--update-links/--no-update-links")] = True,
    write: Annotated[bool, typer.Option("--write")] = False,
) -> None:
    """Preview or move a concept, optionally repairing inbound links."""
    if ":" not in reference:
        raise typer.BadParameter("reference must be BUNDLE:CONCEPT_ID")
    bundle_name, old_id = reference.split(":", 1)
    ref = _ref(bundle_name)
    loaded = load_bundle(ref.path)
    changes = move_concept(loaded, old_id, new_id, update_links=update_links, write=write)
    if write:
        apply_indexes(plan_indexes(load_bundle(ref.path)))
    for path, text in changes.items():
        action = "delete" if text is None else "write"
        console.print(f"{action} {path.relative_to(ref.path)}")


@app.command("watch")
def watch_bundle(bundle: str = typer.Argument(..., metavar="BUNDLE")) -> None:
    """Continuously validate and reindex a bundle on filesystem changes."""
    ref = _ref(bundle)
    console.print(f"Watching {ref.path}; Ctrl+C to stop.")
    for _changes in watch(ref.path):
        loaded = load_bundle(ref.path)
        diagnostics = validate_bundle(loaded)
        with SearchDatabase() as database:
            changed = database.index_bundle(ref, loaded)
        errors = sum(item.severity == Severity.ERROR for item in diagnostics)
        console.print(f"refreshed: {changed} concept(s), {errors} error(s)")


async def _doctor() -> list[dict[str, Any]]:
    statuses = await asyncio.gather(
        provider_for("codex").probe(),
        provider_for("claude", plugin_root=_plugin_root()).probe(),
    )
    return [status.to_dict() for status in statuses]


@app.command()
def doctor(
    format: Annotated[TextJsonFormat, typer.Option("--format")] = TextJsonFormat.TEXT,
) -> None:
    """Check package, registry, cache, providers, auth, and bundled skills."""
    statuses = asyncio.run(_doctor())
    data = {
        "schema_version": 1,
        "okfleet_version": __version__,
        "python": sys.version.split()[0],
        "registry": str(_registry().path),
        "database": str(default_database_path()),
        "plugin_root": str(_plugin_root()) if _plugin_root() else None,
        "providers": statuses,
    }
    if format == TextJsonFormat.JSON:
        _json(data)
        return
    console.print(f"OKFleet {__version__} · Python {data['python']}")
    console.print(
        f"Registry: {data['registry']}\nDatabase: {data['database']}\nPlugin: {data['plugin_root'] or '[yellow]not found[/]'}"
    )
    table = Table("Provider", "Version", "Available", "Authenticated", "Capabilities", "Error")
    for status in statuses:
        table.add_row(
            status["name"],
            status["version"] or "—",
            "yes" if status["available"] else "no",
            "unknown"
            if status["authenticated"] is None
            else ("yes" if status["authenticated"] else "no"),
            ", ".join(status["capabilities"]),
            status["error"] or "",
        )
    console.print(table)


async def _run_chat(
    provider_name: str,
    question: str,
    scope: str,
    mode: ChatMode,
    apply: bool,
) -> None:
    registry = _registry()
    provider = provider_for(provider_name, plugin_root=_plugin_root())
    with SearchDatabase() as database:
        service = ChatService(provider, database)
        workspace: StagedWorkspace | None = None
        fleet_refs: list[BundleRef] | None = None
        if scope == "fleet":
            fleet_refs = [ref for ref in registry.list() if ref.available]
            if not fleet_refs:
                raise ValueError("fleet chat needs registered bundles")
            temp = tempfile.TemporaryDirectory(prefix="okfleet-read-")
            session = await service.start_fleet(fleet_refs, Path(temp.name))
        else:
            ref = resolve_bundle(scope, registry)
            if mode == ChatMode.WORK:
                workspace = StagedWorkspace(ref.path)
                session = await service.start_bundle(ref, work=True, cwd=workspace.root)
            else:
                session = await service.start_bundle(ref)
        async for event in service.send(session, question, fleet_refs=fleet_refs):
            if event.type == AgentEventType.MESSAGE_DELTA:
                console.print(event.text, end="", markup=False)
            elif event.type == AgentEventType.MESSAGE_COMPLETED:
                console.print(event.text, markup=False)
            elif event.type in {AgentEventType.TOOL_STARTED, AgentEventType.FILE_CHANGED}:
                error_console.print(f"[dim]{event.type.value}: {event.text or event.data}[/]")
            elif event.type in {AgentEventType.TURN_FAILED, AgentEventType.ERROR}:
                error_console.print(f"[red]{event.text}[/]")
        if workspace:
            changeset = workspace.changeset()
            console.print(f"\n[bold]Staged changes ({len(changeset.changes)} files)[/]")
            for change in changeset.changes:
                _raw_output(change.diff)
            if changeset.diagnostics:
                console.print(_diagnostic_table(changeset.diagnostics, workspace.root))
            if apply:
                workspace.apply()
                console.print("[green]Applied staged changes.[/]")
            else:
                changeset_id = PendingChangeStore().save(workspace, changeset)
                console.print(
                    "Changes were not applied. Review and accept later with "
                    f"[bold]okfleet apply {changeset_id}[/]."
                )
            workspace.close()


@app.command()
def chat(
    question: str,
    scope: Annotated[str, typer.Option("--scope", help="Bundle alias/path or 'fleet'.")] = "fleet",
    provider: Annotated[ProviderName, typer.Option("--provider")] = ProviderName.CODEX,
    mode: Annotated[ChatMode, typer.Option("--mode")] = ChatMode.READ,
    apply: Annotated[
        bool, typer.Option("--apply", help="Apply a completed staged work turn.")
    ] = False,
) -> None:
    """Ask one provider-backed question in bundle, work, or fleet mode."""
    if scope == "fleet" and mode == ChatMode.WORK:
        raise typer.BadParameter("fleet scope is read-only", param_hint="--mode")
    if apply and mode != ChatMode.WORK:
        raise typer.BadParameter(
            "--apply requires bundle work mode (--mode work)", param_hint="--apply"
        )
    try:
        asyncio.run(_run_chat(provider, question, scope, mode, apply))
    except (ValueError, RuntimeError) as exc:
        error_console.print(f"[red]error:[/] {exc}")
        raise typer.Exit(2) from exc


@app.command("apply")
def apply_changeset(
    changeset_id: str,
    allow_invalid: Annotated[
        bool, typer.Option("--allow-invalid", help="Apply even when validation has errors.")
    ] = False,
) -> None:
    """Apply a persisted staged work session after conflict and validation checks."""
    store = PendingChangeStore()
    try:
        changeset = store.apply(changeset_id, allow_invalid=allow_invalid)
    except (KeyError, ValueError, RuntimeError) as exc:
        error_console.print(f"[red]error:[/] {exc}")
        raise typer.Exit(2) from exc
    console.print(f"[green]Applied {len(changeset.changes)} file change(s).[/]")


@changesets_app.command("list")
def changesets_list() -> None:
    """List persisted staged work sessions."""
    manifests = PendingChangeStore().list()
    if not manifests:
        console.print("No staged changesets.")
        return
    for index, manifest in enumerate(manifests):
        if index:
            _raw_output("\n")
        _raw_output(str(manifest.get("id", "")), end="\n")
        console.print(
            f"  Created: {manifest.get('created_at', '')}\n"
            f"  Source: {manifest.get('source_root', '')}\n"
            f"  Files: {len(manifest.get('files', []))} · "
            f"Diagnostics: {len(manifest.get('diagnostics', []))}",
            markup=False,
        )


@changesets_app.command("show")
def changesets_show(changeset_id: str) -> None:
    """Show diffs, conflicts, and diagnostics for one changeset."""
    store = PendingChangeStore()
    try:
        workspace = store.open(changeset_id)
    except (KeyError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    try:
        changeset = workspace.changeset()
        for change in changeset.changes:
            _raw_output(change.diff)
        if changeset.conflicts:
            error_console.print("[red]Conflicts:[/] " + ", ".join(changeset.conflicts))
        if changeset.diagnostics:
            console.print(_diagnostic_table(changeset.diagnostics, workspace.root))
    finally:
        workspace.close()


@changesets_app.command("delete")
def changesets_delete(changeset_id: str) -> None:
    """Delete a staged changeset without touching its source bundle."""
    try:
        PendingChangeStore().delete(changeset_id)
    except KeyError as exc:
        raise typer.BadParameter(f"unknown changeset: {changeset_id}") from exc
    console.print(f"Deleted staged changeset {changeset_id}.")


@sessions_app.command("list")
def sessions_list() -> None:
    """List saved provider-native session mappings."""
    with SearchDatabase() as database:
        sessions = database.list_sessions()
    if not sessions:
        console.print("No saved sessions.")
        return
    for index, session in enumerate(sessions):
        if index:
            _raw_output("\n")
        _raw_output(session.id, end="\n")
        console.print(
            f"  Provider: {session.provider} · Mode: {session.mode.value}\n"
            f"  Scope: {', '.join(session.scope) or '—'}\n"
            f"  Created: {session.created_at}\n"
            f"  Native ID: {session.native_id or '—'}",
            markup=False,
        )


async def _resume_session(session_id: str, question: str) -> None:
    with SearchDatabase() as database:
        session = database.get_session(session_id)
        if not session:
            raise ValueError(f"unknown session: {session_id}")
        if not session.native_id:
            raise ValueError(f"session {session_id} has no provider-native resume ID")
        provider = provider_for(session.provider, plugin_root=_plugin_root())
        async for event in provider.send(session, question):
            if event.type == AgentEventType.MESSAGE_DELTA:
                console.print(event.text, end="", markup=False)
            elif event.type == AgentEventType.MESSAGE_COMPLETED:
                console.print(event.text, markup=False)
            elif event.type in {AgentEventType.TOOL_STARTED, AgentEventType.FILE_CHANGED}:
                error_console.print(f"[dim]{event.type.value}: {event.text or event.data}[/]")
            elif event.type in {AgentEventType.TURN_FAILED, AgentEventType.ERROR}:
                error_console.print(f"[red]{event.text}[/]")
        database.save_session(session)


@sessions_app.command("resume")
def sessions_resume(session_id: str, question: str) -> None:
    """Continue a saved provider-native conversation."""
    try:
        asyncio.run(_resume_session(session_id, question))
    except (ValueError, RuntimeError) as exc:
        error_console.print(f"[red]error:[/] {exc}")
        raise typer.Exit(2) from exc


@sessions_app.command("delete")
def sessions_delete(session_id: str) -> None:
    """Delete an OKFleet session mapping, leaving provider history intact."""
    with SearchDatabase() as database:
        removed = database.delete_session(session_id)
    if not removed:
        raise typer.BadParameter(f"unknown session: {session_id}")
    console.print(
        f"Deleted OKFleet session mapping {session_id}; provider-native history was untouched."
    )


@cache_app.command("status")
def cache_status() -> None:
    """Print machine-readable statistics for the derived search cache."""
    with SearchDatabase() as database:
        _json({"schema_version": 1, "path": str(database.path), **database.stats()})


@cache_app.command("rebuild")
def cache_rebuild() -> None:
    """Clear and rebuild derived search data from available bundles."""
    registry = _registry()
    with SearchDatabase() as database:
        database.clear_derived()
        changed = sum(
            database.index_bundle(ref, load_bundle(ref.path))
            for ref in registry.list()
            if ref.available
        )
    console.print(f"Rebuilt cache with {changed} concept(s).")


@cache_app.command("clear")
def cache_clear() -> None:
    """Delete derived search data without touching registry or bundles."""
    path = default_database_path()
    for candidate in [path, path.with_name(path.name + "-wal"), path.with_name(path.name + "-shm")]:
        candidate.unlink(missing_ok=True)
    console.print(f"Cleared derived cache at {path}. Registry and bundles were untouched.")


@mcp_app.command("serve")
def mcp_serve(
    registry_path: Annotated[Path | None, typer.Option("--registry-path")] = None,
    database_path: Annotated[Path | None, typer.Option("--database-path")] = None,
    bundle: Annotated[list[str] | None, typer.Option("--bundle")] = None,
) -> None:
    """Serve read-only OKFleet tools over MCP stdio."""
    serve_mcp(
        registry_path=registry_path,
        database_path=database_path,
        allowed_aliases=set(bundle) if bundle else None,
    )


@mcp_app.command("config")
def print_mcp_config(
    command: Annotated[
        str, typer.Option("--command", help="Executable used to launch OKFleet.")
    ] = "okfleet",
) -> None:
    """Print a provider-compatible MCP configuration snippet."""
    _raw_output(mcp_config(command), end="\n")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
