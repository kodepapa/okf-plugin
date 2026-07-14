# Contributing to OKFleet

Read [docs/OKFLEET_DEVELOPMENT_PLAN.md](docs/OKFLEET_DEVELOPMENT_PLAN.md) and [AGENTS.md](AGENTS.md) before changing architecture or provider boundaries.

Use `uv sync --extra dev` to create the development environment. Every change should include focused tests and pass the commands listed in `AGENTS.md`.

Provider adapters must be testable from sanitized protocol fixtures without a live account. Never commit credentials, raw authenticated transcripts, or user bundle content.

Changes to the standalone helper must be made in `skills/okf-author/scripts/okf.py`, synchronized with `python tools/sync_skill_helpers.py`, and verified with `python tools/verify_generated.py`.

## Commit messages and releases

Use Conventional Commit subjects so Release Please can calculate the next version and generate useful release notes:

- `fix: ...` for a patch release.
- `feat: ...` for a minor release.
- `feat!: ...` or a `BREAKING CHANGE:` footer for a major release.
- `docs:`, `test:`, `refactor:`, `build:`, and `chore:` for non-feature maintenance.

Prefer squash-merging pull requests with a Conventional Commit PR title. See [docs/RELEASING.md](docs/RELEASING.md) for the complete release flow.
