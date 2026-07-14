# OKFleet agent guide

## Repository intent

OKFleet is both an installable Python OKF toolkit and a distribution repository for the `okf-read` and `okf-author` Agent Skills. Preserve both surfaces.

## Code discovery

Prefer the codebase-memory MCP graph in this order:

1. `search_graph`
2. `trace_path`
3. `get_code_snippet`
4. `query_graph`
5. `get_architecture`

Use text search for literal messages, config, docs, and generated artifacts, or after the graph is insufficient.

## Architecture rules

- Keep OKF mechanics in `src/okfleet/core.py` and domain records in `src/okfleet/models.py`.
- CLI/TUI/MCP/provider code should call shared services rather than reimplement parsing or validation.
- Keep fleet chat read-only and work chat staged by default.
- Do not read, copy, or log Codex/Claude credentials.
- Keep both standalone skill helpers byte-identical; run `python tools/verify_generated.py`.
- Unknown OKF types and frontmatter fields are allowed.
- Never silently overwrite curated indexes or source files changed since a staged snapshot.

## Verification

```bash
uv sync --extra dev
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest
uv run python tools/verify_generated.py
uv build
```

Live provider tests require explicit user opt-in and authenticated local CLIs.

