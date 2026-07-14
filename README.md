# OKFleet

**The terminal workbench for a fleet of Open Knowledge Format bundles.**

OKFleet turns this repository from an agent-skills-only plugin into a complete local OKF toolkit. It can discover, browse, search, validate, graph, and safely improve [Open Knowledge Format](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md) bundles. Its TUI includes a provider-neutral chat workbench for Codex and Claude Code, while fleet-wide chat remains read-only.

## Highlights

- Full-screen Textual TUI with local/global bundle navigation, Markdown rendering, search, health, graph, chat, and staged diff/apply.
- CLI and Python library for deterministic OKF work without an AI provider.
- Conservative local discovery plus a global user registry.
- Incremental SQLite FTS5 search with field filters such as `type:Metric tag:finance`.
- Opt-in, dependency-free local semantic retrieval plus saved searches and named collections.
- Validation, health diagnostics, backlinks, broken links, staleness, and Mermaid/DOT/JSON graph exports.
- OpenAPI, dbt manifest, SQL DDL, and generic catalog importers; bundle drift comparison; policy packs; and Python entry-point extensions.
- Explicit cached Git remotes, a read-only local web explorer, and an LSP server for live diagnostics and internal-link navigation.
- Safe concept creation and move/rename with inbound-link repair.
- Codex app-server JSON-RPC with JSONL exec fallback, plus a Claude Code stream-JSON adapter, using the user's existing CLI authentication.
- Read-only fleet chat and a read-only MCP server.
- Staged bundle work: agents edit a snapshot, then the user reviews diagnostics/diffs before apply.
- Existing `okf-read` and `okf-author` Agent Skills remain installable and self-contained.

The detailed architecture and agent-ready work breakdown live in [docs/OKFLEET_DEVELOPMENT_PLAN.md](docs/OKFLEET_DEVELOPMENT_PLAN.md).

## Install for development

```bash
uv sync --extra dev
uv run okfleet doctor
uv run okfleet
```

The package targets Python 3.11+. The standalone helper embedded in each skill remains compatible with older Python installations and has no required third-party dependencies.

Once published, the intended user installs are:

```bash
uvx okfleet
# or
pipx install okfleet
```

## Quickstart

Open the TUI in the current path:

```bash
okfleet
```

Discover and register bundles:

```bash
okfleet discover ~/work
okfleet bundles add ~/work/knowledge/warehouse --alias warehouse
okfleet bundles list
okfleet collections create production warehouse
```

Search and inspect:

```bash
okfleet bundles refresh
okfleet search 'type:Metric revenue'
okfleet search 'customer lifetime value' --semantic
okfleet searches save finance-review 'tag:finance type:Metric' --bundle warehouse
okfleet searches run finance-review
okfleet show warehouse:metrics/net_revenue
okfleet graph warehouse:metrics/net_revenue --format mermaid
okfleet status warehouse --diff
```

Validate and maintain:

```bash
okfleet validate warehouse
okfleet health warehouse --stale-after 180
okfleet index warehouse
okfleet index warehouse --write
okfleet new warehouse metrics/gross-margin --type Metric --write
okfleet move warehouse:metrics/gross-margin metrics/gross_margin --write
```

Import, compare, and govern knowledge:

```bash
okfleet import ./openapi.yaml warehouse --kind openapi       # preview
okfleet import ./manifest.json warehouse --kind dbt --write
okfleet compare warehouse warehouse-next --format json
okfleet validate warehouse --policy ./okfleet-policy.toml
```

Use cached remote bundles and the read-only web explorer:

```bash
okfleet bundles clone https://github.com/acme/knowledge.git --alias acme
okfleet bundles update acme
okfleet web --path ~/work
```

`okfleet web` binds to `127.0.0.1:8765` by default. It has no mutation endpoints or authentication, so non-loopback binding is rejected unless `--allow-remote` is explicitly supplied.

For editor integration, configure a Language Server client to launch `okfleet lsp`. It publishes OKF diagnostics on open/change/save and makes internal Markdown links navigable.

Chat with one bundle or across the registered fleet:

```bash
okfleet chat 'How is net revenue defined?' --scope warehouse --provider codex
okfleet chat 'Compare revenue definitions across bundles' --scope fleet --provider claude
okfleet chat 'Improve the Orders documentation' --scope warehouse --mode work --provider codex
```

Work mode stages changes and prints a diff. Add `--apply` only when the completed staged result should be applied.
Without it, OKFleet persists the snapshot and prints an ID for `okfleet changesets show ID` and
`okfleet apply ID`. Provider-native conversations can be continued with `okfleet sessions resume`.

## TUI keys

| Key | Action |
|---|---|
| `/` | Search all loaded bundles. |
| `c` | Focus chat. |
| `v` | Show validation and health. |
| `d` | Toggle staged diff. |
| `Esc` | Cancel the active provider turn. |
| `Ctrl+X` | Discard the active staged snapshot. |
| `r` | Refresh bundles and index. |
| `Ctrl+P` | Open the command palette. |
| `?` | Show help. |
| `q` | Quit. |

## Agent skills and plugins

| Skill | Purpose |
|---|---|
| [`okf-author`](skills/okf-author/SKILL.md) | Create, edit, enrich, cross-link, index, log, and validate bundles. |
| [`okf-read`](skills/okf-read/SKILL.md) | Navigate bundles by progressive disclosure and answer source-grounded questions. |

Claude Code plugin:

```text
/plugin marketplace add kodepapa/okf-plugin
/plugin install okf@okf-plugin
```

Personal skill locations also remain supported:

```bash
ln -s "$(pwd)/skills/okf-author" ~/.claude/skills/okf-author
ln -s "$(pwd)/skills/okf-read" ~/.claude/skills/okf-read
ln -s "$(pwd)/skills/okf-author" ~/.agents/skills/okf-author
ln -s "$(pwd)/skills/okf-read" ~/.agents/skills/okf-read
```

The repository now also contains a Codex manifest at `.codex-plugin/plugin.json` and read-only MCP wiring in `.mcp.json`.

## Standalone helper compatibility

Both skills still bundle `scripts/okf.py`:

```bash
python3 skills/okf-author/scripts/okf.py validate <bundle>
python3 skills/okf-author/scripts/okf.py index <bundle> --write
python3 skills/okf-author/scripts/okf.py list <bundle>
```

The helper copies are checked for byte equality with:

```bash
uv run python tools/verify_generated.py
```

## Privacy and safety

- Bundle files and the search database stay local.
- OKFleet does not read or store provider credentials.
- Fleet chat starts in an empty temporary directory and receives retrieved, read-only context.
- Claude fleet chat has no filesystem tools; Codex fleet chat runs in a read-only sandbox.
- Bundle content is labelled untrusted reference data in provider prompts.
- Work sessions edit a private snapshot; apply uses source hashes to block stale overwrites.
- No command automatically commits, pushes, opens a pull request, or grants full provider access.

Provider and state overrides useful in automation:

| Variable | Purpose |
|---|---|
| `OKFLEET_CONFIG` | Registry/config TOML path. |
| `OKFLEET_DATABASE` | SQLite search/session database path. |
| `OKFLEET_CHANGESETS` | Persisted staged-work directory. |
| `OKFLEET_REMOTE_CACHE` | Explicit cache directory for cloned remote bundles. |
| `OKFLEET_CODEX_PROTOCOL=exec` | Force Codex JSONL fallback instead of app-server. |

See [advanced workflows and extension APIs](docs/EXTENDING_OKFLEET.md), [provider protocols](docs/PROVIDER_PROTOCOLS.md), [compatibility](docs/OKF_COMPATIBILITY.md), and [security](docs/SECURITY.md) for the operational contracts.

## Development

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest
uv build
```

`evals/evals.json` and `okf-skill-workspace/grade.py` retain the existing skill-evaluation workflow. The OKF v0.1 specification remains vendored in `skills/okf-author/references/spec.md` under its upstream Apache 2.0 license.
