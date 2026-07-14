from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from textual.widgets import Input, Static, TabbedContent

from okfleet.branding import PLAIN_MARK, brand_text
from okfleet.tui.app import OKFleetApp
from okfleet.tui.screens import KeyboardHelp, SpotlightSearch
from okfleet.tui.widgets import VimMarkdown, VimOptionList, VimTree


@pytest.mark.asyncio
async def test_tui_mounts_and_discovers_bundle(bundle_path: Path) -> None:
    app = OKFleetApp(bundle_path.parent)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        assert app.refs
        assert any(ref.path == bundle_path for ref in app.refs)
        assert any(ref.path == bundle_path for ref in app.fleet_refs)
        assert app.query_one("#brand", Static).content.plain == brand_text().plain


def test_terminal_brand_matches_plain_fleet_mark() -> None:
    assert brand_text().plain.replace("  OKFleet", "") == PLAIN_MARK


@pytest.mark.asyncio
async def test_tui_starts_with_clean_two_pane_layout(bundle_path: Path) -> None:
    app = OKFleetApp(bundle_path.parent)
    async with app.run_test(size=(70, 30)) as pilot:
        await pilot.pause()
        assert app.query_one("#sidebar").display is True
        assert app.query_one("#main").display is True
        assert app.query_one("#chat-drawer").display is False
        assert app.query_one("#sidebar").region.width == 30


@pytest.mark.asyncio
async def test_vim_tree_navigation_opens_bundle_and_concept(bundle_path: Path) -> None:
    app = OKFleetApp(bundle_path.parent)
    async with app.run_test(size=(120, 40)) as pilot:
        tree = app.query_one("#bundle-tree", VimTree)
        local_node = next(node for node in tree.root.children if node.label.plain == "LOCAL")
        bundle_node = local_node.children[0]
        tree.move_cursor(bundle_node)

        await pilot.press("l")
        await pilot.pause()
        assert app.selected_ref is not None
        assert app.selected_ref.path == bundle_path
        assert bundle_node.is_expanded
        assert bundle_node.children

        await pilot.press("l")
        assert tree.cursor_node is bundle_node.children[0]
        await pilot.press("enter")
        await pilot.pause()
        assert app.selected_concept_id == bundle_node.children[0].data[2]

        await pilot.press("h")
        assert tree.cursor_node is bundle_node
        await pilot.press("G")
        assert tree.cursor_line == tree.last_line
        await pilot.press("g")
        assert tree.cursor_line == 0


@pytest.mark.asyncio
async def test_vim_pane_navigation_and_insert_mode_do_not_conflict(bundle_path: Path) -> None:
    app = OKFleetApp(bundle_path.parent)
    async with app.run_test(size=(120, 40)) as pilot:
        tree = app.query_one("#bundle-tree", VimTree)
        assert app.focused is tree

        await pilot.press("L")
        assert app.focused is app.query_one("#concept-view", VimMarkdown)
        await pilot.press("H")
        assert app.focused is tree

        await pilot.press("c")
        chat_input = app.query_one("#chat-input", Input)
        assert app.focused is chat_input
        await pilot.press("j", "k", "l", "q", "/")
        assert chat_input.value == "jklq/"

        await pilot.press("ctrl+k")
        await pilot.pause()
        assert isinstance(app.screen, SpotlightSearch)
        await pilot.press("escape")
        await pilot.pause()
        assert app.focused is chat_input
        await pilot.press("escape")
        assert app.focused is tree


@pytest.mark.asyncio
async def test_spotlight_search_opens_ranked_concept_result(bundle_path: Path) -> None:
    app = OKFleetApp(bundle_path.parent)
    async with app.run_test(size=(120, 40)) as pilot:
        tree = app.query_one("#bundle-tree", VimTree)
        await pilot.press("/")
        await pilot.pause()
        assert isinstance(app.screen, SpotlightSearch)
        search_input = app.screen.query_one("#spotlight-query", Input)
        assert app.focused is search_input

        await pilot.press(*"revenue")
        await pilot.pause(0.15)
        results = app.screen.query_one("#spotlight-results", VimOptionList)
        assert results.option_count >= 1
        assert search_input.value == "revenue"

        await pilot.press("enter")
        await pilot.pause()
        assert not isinstance(app.screen, SpotlightSearch)
        assert app.selected_ref is not None
        assert app.selected_ref.path == bundle_path
        assert app.selected_concept_id == "metrics/revenue"
        assert app.query_one("#tabs", TabbedContent).active == "concept-tab"
        assert tree.cursor_node is not None
        assert tree.cursor_node.data[2] == "metrics/revenue"


@pytest.mark.asyncio
async def test_spotlight_escape_restores_browse_focus(bundle_path: Path) -> None:
    app = OKFleetApp(bundle_path.parent)
    async with app.run_test(size=(120, 40)) as pilot:
        tree = app.query_one("#bundle-tree", VimTree)
        await pilot.press("/")
        await pilot.pause()
        assert isinstance(app.screen, SpotlightSearch)

        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, SpotlightSearch)
        assert app.focused is tree


@pytest.mark.asyncio
async def test_spotlight_ctrl_jk_navigates_without_reindexing_or_leaving_input(
    bundle_path: Path,
) -> None:
    app = OKFleetApp(bundle_path.parent)
    async with app.run_test(size=(120, 40)) as pilot:
        with patch.object(
            app.database,
            "index_bundle",
            side_effect=AssertionError("search input must not reindex bundles"),
        ):
            await pilot.press("/")
            await pilot.pause()
            search_input = app.screen.query_one("#spotlight-query", Input)
            await pilot.press(*"type:Metric type:Table")
            await pilot.pause(0.15)
            results = app.screen.query_one("#spotlight-results", VimOptionList)
            assert results.option_count == 2
            assert results.highlighted == 0

            query = search_input.value
            await pilot.press("ctrl+j")
            assert isinstance(app.screen, SpotlightSearch)
            assert app.focused is search_input
            assert search_input.value == query
            assert results.highlighted == 1

            await pilot.press("ctrl+k")
            assert results.highlighted == 0


@pytest.mark.asyncio
async def test_help_is_modal_and_q_closes_it_without_quitting(bundle_path: Path) -> None:
    app = OKFleetApp(bundle_path.parent)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("?")
        await pilot.pause()
        assert isinstance(app.screen, KeyboardHelp)
        await pilot.press("q")
        await pilot.pause()
        assert not isinstance(app.screen, KeyboardHelp)
        assert app.is_running


@pytest.mark.asyncio
async def test_narrow_chat_opens_as_drawer_and_escape_returns_to_browse(
    bundle_path: Path,
) -> None:
    app = OKFleetApp(bundle_path.parent)
    async with app.run_test(size=(70, 30)) as pilot:
        await pilot.press("c")
        assert app.query_one("#sidebar").display is True
        assert app.query_one("#main").display is True
        assert app.query_one("#chat-drawer").display is True
        assert app.query_one("#chat-drawer").has_class("full-screen")
        assert app.query_one("#chat-drawer").region.width == 70
        assert app.focused is app.query_one("#chat-input", Input)

        await pilot.press("escape")
        assert app.query_one("#sidebar").display is True
        assert app.query_one("#main").display is True
        assert app.query_one("#chat-drawer").display is False
        assert app.focused is app.query_one("#bundle-tree", VimTree)


@pytest.mark.asyncio
async def test_resizing_while_chatting_preserves_visible_chat_drawer(bundle_path: Path) -> None:
    app = OKFleetApp(bundle_path.parent)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("c")
        assert app.focused is app.query_one("#chat-input", Input)

        await pilot.resize_terminal(70, 30)
        await pilot.pause()
        assert app.query_one("#chat-drawer").display is True
        assert app.query_one("#chat-drawer").has_class("full-screen")
        assert app.focused is app.query_one("#chat-input", Input)
