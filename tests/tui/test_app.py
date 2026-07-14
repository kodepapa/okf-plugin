from __future__ import annotations

from pathlib import Path

import pytest
from textual.widgets import Static

from okfleet.branding import PLAIN_MARK, brand_text
from okfleet.tui.app import OKFleetApp


@pytest.mark.asyncio
async def test_tui_mounts_and_discovers_bundle(bundle_path: Path) -> None:
    app = OKFleetApp(bundle_path.parent)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        assert app.refs
        assert any(ref.path == bundle_path for ref in app.refs)
        assert app.query_one("#brand", Static).content.plain == brand_text().plain


def test_terminal_brand_matches_plain_fleet_mark() -> None:
    assert brand_text().plain.replace("  OKFleet", "") == PLAIN_MARK


@pytest.mark.asyncio
async def test_tui_hides_inspector_at_narrow_width(bundle_path: Path) -> None:
    app = OKFleetApp(bundle_path.parent)
    async with app.run_test(size=(70, 30)) as pilot:
        await pilot.pause()
        assert app.query_one("#inspector").display is False
