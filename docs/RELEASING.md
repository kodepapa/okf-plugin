# Releasing OKFleet

OKFleet uses [Release Please](https://github.com/googleapis/release-please-action) in manifest mode. It reads Conventional Commits on `main`, maintains a release pull request, updates versions and `CHANGELOG.md`, and creates the Git tag and GitHub Release when that pull request is merged.

## Version sources

The release pull request keeps these files synchronized:

- `pyproject.toml`
- `uv.lock`
- `src/okfleet/__init__.py`
- `.codex-plugin/plugin.json`
- `.claude-plugin/plugin.json`
- `.release-please-manifest.json`
- `CHANGELOG.md`

The current version starts at `0.5.0`. Package-manager publication is intentionally separate
from Release Please. The workflow creates the version commit, tag, and GitHub Release, builds
the wheel and source distribution from that tag, verifies them, and attaches both artifacts to
the release. It does not publish to PyPI.

This repository was bootstrapped before its first tag. `release-please-config.json` therefore pins the last pre-automation commit with `bootstrap-sha`; Release Please will collect only later Conventional Commits for the first automated release. Remove `bootstrap-sha` after that release PR has been merged and tagged.

## Normal release flow

1. Merge changes into `main` using Conventional Commit subjects.
2. The `Release Please` workflow creates or updates one release pull request.
3. Review its version bump, changelog, and synchronized plugin versions.
4. Ensure CI passes, including the clean wheel installation and distribution smoke test, then merge the release pull request.
5. Release Please creates the `vX.Y.Z` tag and corresponding GitHub Release.
6. The release workflow rebuilds the tagged source, verifies its metadata and packaged assets,
   and attaches the wheel and source distribution to the GitHub Release.

Use `fix:` for patches, `feat:` for features, and `feat!:` or a `BREAKING CHANGE:` footer for breaking changes. Python repositories also treat `docs:` changes as releasable units.

## Repository settings

The workflow uses the repository `GITHUB_TOKEN` by default and needs write access to contents,
issues, and pull requests. In **Settings → Actions → General → Workflow permissions**, enable
**Allow GitHub Actions to create and approve pull requests**. Keep the repository's default
workflow permission at read-only; the release job declares its narrower write permissions in
the workflow.

Pull-request workflows created with the default `GITHUB_TOKEN` require maintainer approval
before their checks run. That is a reasonable default for this project. If Release Please pull
requests must run CI unattended, add a narrowly scoped fine-grained token or GitHub App token as
the `RELEASE_PLEASE_TOKEN` repository secret. The workflow uses that secret when present and
otherwise falls back to `GITHUB_TOKEN`; do not add a broad classic personal access token.

## Manual version request

To request a particular next version, include this footer in a Conventional Commit:

```text
Release-As: 1.0.0
```

Do not manually edit only one version file. If an emergency manual release is unavoidable,
update every file listed under **Version sources** and the release manifest together, then run
`uv lock --check`, `make package`, and `uvx --from twine==6.2.0 twine check dist/*`.
