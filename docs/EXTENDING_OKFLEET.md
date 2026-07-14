# Advanced OKFleet workflows and extension APIs

This document is the operational reference for the advanced capabilities shipped with OKFleet 0.5. All source-bundle writes remain preview-first, and every extension runs in the OKFleet process with the permissions of the user who installed it.

## Retrieval and reusable scopes

Lexical search uses SQLite FTS5 and supports `bundle:`, `type:`, `tag:`, and `id:` filters. Local semantic search is opt-in and dependency-free:

```bash
okfleet search 'where does recognized income come from' --semantic
okfleet searches save revenue-review 'type:Metric tag:finance' --collection production
okfleet searches run revenue-review --format json
```

The semantic implementation hashes normalized tokens into a local vector. It sends nothing to a provider and is intended for recall, not ranking-sensitive evaluation. FTS remains the deterministic default.

## Import and drift workflows

Built-in importer kinds are `openapi`, `dbt`, `sql`, and `catalog`. Import is a preview unless `--write` is present; `--replace` is separately required to overwrite an existing concept.

```bash
okfleet import ./openapi.yaml platform --kind openapi
okfleet import ./schema.sql warehouse --kind sql --write
okfleet compare warehouse warehouse-next
okfleet compare warehouse warehouse-next --format json
```

Import creates ordinary OKF Markdown, regenerates directory indexes on write, and records the source path in frontmatter. Drift output classifies concepts as added, removed, or changed and includes changed metadata fields and content hashes.

## Remote bundle cache

Remote sources are explicit shallow Git clones, not virtual filesystems:

```bash
okfleet bundles clone https://github.com/acme/knowledge.git --alias acme --ref main
okfleet bundles update acme
```

Clones live below the platform cache directory or `OKFLEET_REMOTE_CACHE`. The registry stores the origin and requested ref. Update performs only `git pull --ff-only`; it never resets local work, runs hooks through OKFleet, or deletes the cache when an alias is removed.

## Team policy packs

`okfleet validate BUNDLE --policy FILE` accepts TOML or JSON. A TOML pack can enforce global/type-specific fields, allowed or forbidden types, tags, and freshness:

```toml
[policy]
allowed_types = ["Metric", "Table", "API", "Playbook"]
required_fields = ["owner"]
required_tags = ["reviewed"]
freshness_days = 365

[policy.required_by_type]
Metric = ["formula", "grain"]
Table = ["resource"]

[policy.freshness_by_type]
Metric = 90
Playbook = 180
```

Policy findings join built-in diagnostics and therefore work with text, JSON, and SARIF output. `freshness_by_type` overrides the global target. Missing, malformed, or stale timestamps produce policy warnings.

## Python entry-point extensions

OKFleet discovers installed Python packages through three entry-point groups:

| Group | Contract | Used by |
|---|---|---|
| `okfleet.importers` | `(Path) -> list[ImportedConcept]` | `okfleet import --kind NAME` |
| `okfleet.diagnostics` | `(Bundle) -> Iterable[Diagnostic]` | `validate` and `health` |
| `okfleet.templates` | `(context: dict) -> dict` | `okfleet new --template NAME` |

Example registration:

```toml
[project.entry-points."okfleet.importers"]
protobuf = "acme_okfleet:import_protobuf"

[project.entry-points."okfleet.diagnostics"]
ownership = "acme_okfleet:ownership_diagnostics"

[project.entry-points."okfleet.templates"]
slo = "acme_okfleet:slo_template"
```

An importer returns `okfleet.importers.ImportedConcept` values. A diagnostic extension returns `okfleet.models.Diagnostic` values. A template returns `{"frontmatter": {...}, "body": "..."}` and receives `bundle`, `concept_id`, `type`, `title`, and `description` in its context. Diagnostic failures are converted to `EXTENSION_FAILED` warnings so one plugin cannot suppress core validation; importer and template failures stop their explicit command.

## Web explorer

```bash
okfleet web --path ~/work --host 127.0.0.1 --port 8765
```

The responsive web view exposes the same registry, discovery, search, concept, and health services as the CLI. Its API surface is read-only:

- `GET /api/bundles`
- `GET /api/search?q=...&bundle=...`
- `GET /api/concepts/{alias}/{concept-id}`
- `GET /api/health/{alias}`

Mutation methods return 405. Non-loopback binding requires `--allow-remote` because the built-in server intentionally has no authentication.

## Editor integration

`okfleet lsp` implements JSON-RPC/LSP over stdio. Configure an editor's generic language-server client for Markdown files inside OKF roots. It supports full-text synchronization, publish-diagnostics on open/change/save, document links, and go-to-definition for internal Markdown links.

Example Neovim setup:

```lua
vim.lsp.start({
  name = "okfleet",
  cmd = { "okfleet", "lsp" },
  root_dir = vim.fs.root(0, { "index.md" }),
})
```

An OKF root is recognized by `okf_version` in the root `index.md`. The server opens no socket and does not modify documents.
