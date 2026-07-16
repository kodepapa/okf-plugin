# Contributing to OKFleet

Thanks for helping make Open Knowledge Format tooling easier to use. OKFleet is both a
Python toolkit and the distribution repository for the `okf-read` and `okf-author` Agent
Skills, so changes must keep both surfaces working.

By participating, you agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md). For usage
help, read [SUPPORT.md](SUPPORT.md). Report vulnerabilities privately as described in
[docs/SECURITY.md](docs/SECURITY.md); do not open a public issue with exploit details,
credentials, private bundle content, or authenticated provider transcripts.

## Before you start

- Search existing issues and pull requests before opening a new one.
- Use the issue forms for bugs, feature proposals, documentation problems, and usage
  questions.
- Small fixes can go directly to a pull request. For a large feature or architecture change,
  open an issue first so the scope and safety model can be agreed before implementation.
- Read [AGENTS.md](AGENTS.md) and the
  [development plan](docs/OKFLEET_DEVELOPMENT_PLAN.md) before changing architecture,
  providers, staged writes, or the Agent Skills.

## Development setup

You need Git, Python 3.11 or newer, and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/YOUR-USER/okfleet.git
cd okfleet
uv sync --locked --extra dev
uv run pre-commit install
uv run okfleet doctor
```

Create a focused branch from the current `main` branch and keep unrelated changes out of the
same pull request.

## Project contracts

- Keep OKF parsing, validation, indexing, and write mechanics in the shared core. CLI, TUI,
  web, LSP, MCP, and provider adapters should call those services.
- Fleet chat is read-only. Work chat edits a private snapshot and requires explicit apply.
- Never read, copy, log, or test against Codex or Claude credentials.
- Unknown OKF types and frontmatter fields remain valid extension points.
- Never silently overwrite curated indexes or files changed since a staged snapshot.
- Provider behavior must be testable from sanitized protocol fixtures without a live account.

Changes to the standalone helper start in `skills/okf-author/scripts/okf.py`. Then synchronize
and verify the copy used by `okf-read`:

```bash
uv run python tools/sync_skill_helpers.py
uv run python tools/verify_generated.py
```

## Tests and quality checks

Add focused tests for behavior changes and run the smallest relevant test while iterating:

```bash
uv run pytest tests/unit/test_example.py
```

Before requesting review, run the repository checks:

```bash
make package
```

`make help` lists focused targets for linting, formatting, typing, tests, generated files,
pre-commit, and distributions. `make package` includes the complete `make check` quality gate.
The targets use the checked-in lockfile; CI runs the same commands.

The default suite uses sanitized fixtures and does not contact a model provider. Live provider
tests require explicit opt-in and locally authenticated provider CLIs.

For TUI changes, capture both wide and narrow layouts without invoking a provider:

```bash
uv run python tools/capture_tui_audit.py --source examples --output dist/tui-audit
```

Open `dist/tui-audit/index.html`, check keyboard-only navigation, and include before/after
screenshots for material visual changes.

## Pull requests

- Explain the user-visible outcome, trade-offs, and affected surfaces.
- Include tests and documentation where behavior changes.
- Keep generated files synchronized, but do not manually edit `CHANGELOG.md`; Release Please
  owns release notes and version files.
- Use a [Conventional Commit](https://www.conventionalcommits.org/) pull-request title, such as
  `fix: preserve literal brackets in source output` or `feat: add catalog policy checks`.
- Prefer squash merging so the pull-request title becomes the release commit.

Release Please interprets `fix:` as a patch, `feat:` as a minor, and `feat!:` or a
`BREAKING CHANGE:` footer as a major release. See
[docs/RELEASING.md](docs/RELEASING.md) for the maintainer release flow.
