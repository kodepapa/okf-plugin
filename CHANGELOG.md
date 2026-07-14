# Changelog

## [0.6.0](https://github.com/kodepapa/okf-plugin/compare/v0.5.0...v0.6.0) (2026-07-14)


### Features

* add Release Please workflow and updated branding ([6ecf0de](https://github.com/kodepapa/okf-plugin/commit/6ecf0de131fe071f70f1dce27cf928c4a81eaf2a))

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
