from __future__ import annotations

from pathlib import Path

import pytest

from okfleet.tui.app import OKFleetApp


@pytest.mark.asyncio
async def test_tui_mounts_and_discovers_bundle(bundle_path: Path) -> None:
    app = OKFleetApp(bundle_path.parent)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        assert app.refs
        assert any(ref.path == bundle_path for ref in app.refs)


@pytest.mark.asyncio
async def test_tui_hides_inspector_at_narrow_width(bundle_path: Path) -> None:
    app = OKFleetApp(bundle_path.parent)
    async with app.run_test(size=(70, 30)) as pilot:
        await pilot.pause()
        assert app.query_one("#inspector").display is False
