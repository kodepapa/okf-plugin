## What changed

Describe the user-visible outcome and the affected OKFleet surface.

## Verification

- [ ] Focused tests cover the change.
- [ ] `uv run ruff check .`
- [ ] `uv run ruff format --check .`
- [ ] `uv run mypy src`
- [ ] `uv run pytest --cov=okfleet`
- [ ] `uv run python tools/verify_generated.py`

## Safety and compatibility

- [ ] Fleet chat remains read-only and bundle writes remain staged by default.
- [ ] No credentials, private bundle content, or authenticated transcripts are included.
- [ ] Standalone skill helpers and plugin manifests remain synchronized where relevant.
