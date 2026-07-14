# Releasing OKFleet

OKFleet uses [Release Please](https://github.com/googleapis/release-please-action) in manifest mode. It reads Conventional Commits on `main`, maintains a release pull request, updates versions and `CHANGELOG.md`, and creates the Git tag and GitHub Release when that pull request is merged.

## Version sources

The release pull request keeps these files synchronized:

- `pyproject.toml`
- `src/okfleet/__init__.py`
- `.codex-plugin/plugin.json`
- `.claude-plugin/plugin.json`
- `.release-please-manifest.json`
- `CHANGELOG.md`

The current version starts at `0.5.0`. Package-manager publication is intentionally separate from Release Please; the workflow creates the version commit, tag, and GitHub Release but does not publish to PyPI.

## Normal release flow

1. Merge changes into `main` using Conventional Commit subjects.
2. The `Release Please` workflow creates or updates one release pull request.
3. Review its version bump, changelog, and synchronized plugin versions.
4. Ensure CI passes, then merge the release pull request.
5. Release Please creates the `vX.Y.Z` tag and corresponding GitHub Release.

Use `fix:` for patches, `feat:` for features, and `feat!:` or a `BREAKING CHANGE:` footer for breaking changes. Python repositories also treat `docs:` changes as releasable units.

## Repository settings

The workflow uses the repository `GITHUB_TOKEN` and needs write access to contents, issues, and pull requests. In **Settings → Actions → General**, allow GitHub Actions to create pull requests.

GitHub does not trigger new workflow runs from pull requests created with the default `GITHUB_TOKEN`. If release pull requests must automatically trigger CI, create a narrowly scoped token, store it as a repository secret, and pass it to the action's `token` input.

## Manual version request

To request a particular next version, include this footer in a Conventional Commit:

```text
Release-As: 1.0.0
```

Do not manually edit only one version file. If an emergency manual release is unavoidable, update every file listed under **Version sources** and the release manifest together.
