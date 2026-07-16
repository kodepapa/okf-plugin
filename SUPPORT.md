# Support

OKFleet is an open-source project maintained on a best-effort basis. Public issues are the
shared support channel; response times are not guaranteed.

## Before opening an issue

1. Check the [README](README.md) and [advanced workflows](docs/EXTENDING_OKFLEET.md).
2. Search [existing issues](https://github.com/kodepapa/okfleet/issues) for the same symptom.
3. Run these local diagnostics:

   ```bash
   okfleet --version
   okfleet doctor --format json
   ```

   Review and sanitize output before sharing it. Never post credentials, private bundle
   content, authenticated provider transcripts, or sensitive filesystem paths.

## Where to ask

- **Reproducible defect:** open a bug report with a minimal sanitized bundle or fixture.
- **How-to question:** open a usage question and explain what you are trying to accomplish.
- **Product idea:** open a feature request focused on the developer problem and desired outcome.
- **Incorrect documentation:** open a documentation report with the affected page or command.
- **Security vulnerability:** follow the private process in
  [docs/SECURITY.md](docs/SECURITY.md). Never publish vulnerability details; if private
  reporting is unavailable, use only the sanitized fallback described in that policy.
- **Code contribution:** read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request.

Questions about Codex or Claude Code should include the provider CLI name and version, but not
account information or authenticated logs. Maintainers may ask for a provider-independent
fixture so the behavior can be reproduced safely.

Only the versions listed in [docs/SECURITY.md](docs/SECURITY.md#supported-versions) receive
security updates. Older versions may still receive community help, but fixes target supported
releases.
