# Changelog

## Unreleased

- Renamed the canonical repository and plugin marketplace identity from `okf-plugin` to
  `okfleet`.
- Added idempotent `discover --autoregister` batch registration with deterministic alias
  collision handling.
- Tightened CLI contracts, including scoped-search isolation, validated option choices, clean
  registry errors, complete help summaries, and safe chat/index mode combinations.
- Simplified the TUI into a focused two-pane library and document workspace with a compact
  Spotlight search and an on-demand, responsive chat drawer.
- Added canonical `CLAUDE.md` and Claude project-skill symlinks while keeping shared agent
  instructions and skills single-sourced.
- Hardened bundle reads and staged apply against symlink traversal and race paths.
- Fixed threaded web search by using independent read-only SQLite connections per request.
- Added an Apache 2.0 project license, typed-package marker, dependency automation, stronger
  pre-commit checks, coverage enforcement, and distribution smoke tests.

## 0.5.0 - 2026-07-14

- Introduced the OKFleet Python library, CLI, and Textual TUI.
- Added local discovery, global registry, collections, FTS5 search, validation/health, links, and graph exports.
- Added read-only MCP tools with protocol annotations, Codex app-server/exec transports, and a Claude Code stream-JSON adapter.
- Added read-only fleet chat and staged bundle work with diff/conflict/apply handling.
- Added persisted change-set review/apply, provider-native session resume, collections, and bundle-scoped Git status/diffs.
- Added a Codex plugin manifest while preserving the Claude plugin and existing Agent Skills.
- Preserved the standalone `validate`, `index`, and `list` helper commands.
- Added opt-in local semantic retrieval, saved searches, structured importers, bundle drift reports, policy packs, and extension entry points.
- Added explicit Git-backed remote caches, a read-only local web explorer, and an LSP server for diagnostics and internal-link navigation.
- Added a compact OKFleet visual identity shared by the README and TUI terminal artwork.
- Added manifest-driven Release Please automation for synchronized Python and plugin releases.
- Reworked the TUI around Vim navigation, interactive Spotlight search, contextual keyboard help, and a narrow-terminal chat drawer.
