# Security and privacy

OKFleet is local-first. Bundle sources, indexes, registry metadata, session mappings, and staged snapshots remain on the machine. Model prompts necessarily send the question and selected bundle context to the provider chosen by the user under that provider's account and policies.

## Trust boundaries

- Bundle text is untrusted reference data, never executable instructions.
- Fleet chat is read-only. Claude receives no filesystem tools; Codex runs with a read-only sandbox in an empty temporary working directory.
- Work chat never targets the source bundle. It targets a private snapshot and exposes no shell to Claude; Codex uses workspace-write sandboxing rooted at the snapshot.
- Apply validates the staged bundle and compares the complete source tree against baseline hashes. Concurrent additions, edits, and deletions block apply.
- Writes use same-directory temporary files plus atomic replacement. Applied files are backed up for rollback if a later file fails.
- MCP exposes six read-only tools, each marked non-destructive, idempotent, and closed-world in its protocol annotations.
- The local web explorer exposes GET-only knowledge/search APIs. It binds to loopback by default and rejects non-loopback addresses unless the operator explicitly opts in.
- Remote bundles are cloned only by an explicit command into an isolated cache. Updates use `git pull --ff-only`; OKFleet never resets or executes repository code.
- Import commands preview changes by default. `--write` is required to create files, and concept paths remain root-contained.

## Deliberate exclusions

OKFleet does not inspect credential stores, print environment secrets, auto-approve provider requests, commit, push, open pull requests, or run agent-authored shell commands. Provider stderr is scrubbed for common API-key patterns before display.

Symlinks are not followed during bundle discovery, indexing, or staged copies. Concept paths and MCP index paths are resolved and checked against their bundle root to prevent traversal.

The web explorer has no authentication layer. Treat `--allow-remote` as an expert option and put an authenticated reverse proxy in front of it if remote access is required. The LSP uses stdio only and never opens a listening socket.

## Reporting

Do not include credentials, authenticated transcripts, or private bundle contents in an issue. Report the affected command, version, platform, minimal sanitized reproduction, and whether the behavior occurred in read or staged-work mode.
