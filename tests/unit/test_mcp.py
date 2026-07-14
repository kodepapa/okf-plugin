from __future__ import annotations

from pathlib import Path

import pytest

from okfleet.mcp_server import create_server


@pytest.mark.asyncio
async def test_all_mcp_tools_declare_read_only(bundle_path: Path, tmp_path: Path) -> None:
    server = create_server(
        registry_path=tmp_path / "config.toml",
        database_path=tmp_path / "index.db",
    )
    tools = await server.list_tools()
    assert len(tools) == 6
    for tool in tools:
        assert tool.annotations is not None
        assert tool.annotations.readOnlyHint is True
        assert tool.annotations.destructiveHint is False
        assert tool.annotations.openWorldHint is False
