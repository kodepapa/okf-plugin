from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import ClassVar, Literal

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

from ..models import BundleRef, SearchHit
from ..search import SearchDatabase
from .widgets import BindingSpec, VimMarkdown, VimOptionList


@dataclass(slots=True, frozen=True)
class SearchSelection:
    kind: Literal["bundle", "concept"]
    bundle_id: str
    concept_id: str | None = None


class SpotlightSearch(ModalScreen[SearchSelection | None]):
    """Fast, keyboard-first navigation across local and global bundles."""

    BINDINGS: ClassVar[list[BindingSpec]] = [
        Binding("escape", "close", "Close", show=False, priority=True),
        Binding("up", "previous_result", "Previous", show=False, priority=True),
        Binding("down", "next_result", "Next", show=False, priority=True),
        Binding("ctrl+k", "previous_result", "Previous", show=False, priority=True),
        Binding("ctrl+j", "next_result", "Next", show=False, priority=True),
        Binding("ctrl+p", "previous_result", "Previous", show=False, priority=True),
        Binding("ctrl+n", "next_result", "Next", show=False, priority=True),
        Binding("enter", "accept", "Open", show=False, priority=True),
        Binding("f2", "toggle_scope", "Scope", show=False, priority=True),
    ]

    def __init__(
        self,
        database: SearchDatabase,
        refs: list[BundleRef],
        *,
        current_bundle_id: str | None,
        index_errors: dict[str, str] | None = None,
        on_select: Callable[[SearchSelection], bool],
    ) -> None:
        super().__init__()
        self.database = database
        self.refs = [ref for ref in refs if ref.available]
        self.current_bundle_id = current_bundle_id
        self.index_errors = dict(index_errors or {})
        self.on_select = on_select
        self.current_scope = False
        self.result_selections: list[SearchSelection] = []
        self.query_generation = 0

    def compose(self) -> ComposeResult:
        with Vertical(id="spotlight"):
            with Horizontal(id="spotlight-search-row"):
                yield Static("⌕", id="spotlight-icon")
                yield Input(
                    placeholder="Search bundles, concepts, type:Metric, tag:finance…",
                    id="spotlight-query",
                )
                yield Static("ALL", id="spotlight-scope")
            yield Static("", id="spotlight-meta")
            yield VimOptionList(id="spotlight-results", markup=False)
            yield Static("No searchable bundles are available.", id="spotlight-empty")
            yield Static(
                "↑↓ or Ctrl-J/K move   Enter open   F2 scope   Esc close",
                id="spotlight-hints",
            )

    def on_mount(self) -> None:
        self.query_one("#spotlight-query", Input).focus()
        self._render_results("")

    def _scoped_refs(self) -> list[BundleRef]:
        if not self.current_scope or self.current_bundle_id is None:
            return self.refs
        return [ref for ref in self.refs if ref.id == self.current_bundle_id]

    @staticmethod
    def _bundle_row(ref: BundleRef) -> Text:
        row = Text()
        row.append("▣  ", style="bold #3b82f6")
        row.append(ref.alias, style="bold")
        row.append("  ·  ", style="dim")
        row.append(f"{ref.source.upper()} BUNDLE", style="dim")
        return row

    @staticmethod
    def _concept_row(hit: SearchHit) -> Text:
        row = Text()
        row.append("◆  ", style="bold #60a5fa")
        row.append(hit.title, style="bold")
        row.append("  ·  ", style="dim")
        row.append(hit.concept_type or "Concept", style="dim")
        row.append("\n   ")
        row.append(hit.citation, style="dim")
        return row

    def _matching_bundles(self, refs: list[BundleRef], query: str) -> list[BundleRef]:
        needle = query.casefold().strip()
        if not needle:
            return refs
        if ":" in needle:
            return []
        return [ref for ref in refs if needle in f"{ref.alias} {ref.path} {ref.source}".casefold()]

    def _render_results(self, query: str) -> None:
        refs = self._scoped_refs()
        selections: list[SearchSelection] = []
        options: list[Option] = []

        for ref in self._matching_bundles(refs, query):
            selections.append(SearchSelection("bundle", ref.id))
            options.append(Option(self._bundle_row(ref)))

        if query:
            try:
                hits = self.database.search(
                    query,
                    bundle_ids=[ref.id for ref in refs],
                    limit=max(1, 30 - len(options)),
                )
            except Exception as exc:
                self.result_selections = []
                self.query_one("#spotlight-results", VimOptionList).set_options([])
                self.query_one("#spotlight-empty", Static).update(f"Search failed: {exc}")
                self.query_one("#spotlight-empty", Static).display = True
                return
            for hit in hits:
                selections.append(SearchSelection("concept", hit.bundle_id, hit.concept_id))
                options.append(Option(self._concept_row(hit)))

        self.result_selections = selections
        results = self.query_one("#spotlight-results", VimOptionList)
        results.set_options(options)
        results.highlighted = 0 if options else None
        results.display = bool(options)
        empty = self.query_one("#spotlight-empty", Static)
        empty.display = not options
        if not options:
            empty.update("No matches. Try a title, concept ID, type:Metric, or tag:finance.")

        scope = "All bundles"
        if self.current_scope and refs:
            scope = f"Current · {refs[0].alias}"
        self.query_one("#spotlight-scope", Static).update(
            "CURRENT" if self.current_scope else "ALL"
        )
        index_status = (
            f"  ·  {len(self.index_errors)} index error{'s' if len(self.index_errors) != 1 else ''}"
            if self.index_errors
            else ""
        )
        self.query_one("#spotlight-meta", Static).update(
            f"{scope}  ·  {len(refs)} bundle{'s' if len(refs) != 1 else ''}  ·  "
            f"{len(options)} result{'s' if len(options) != 1 else ''}{index_status}"
        )

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "spotlight-query":
            return
        self.query_generation += 1
        generation = self.query_generation
        query = event.value.strip()
        if not query:
            self._render_results("")
            return
        self._debounced_render(query, generation)

    @work(exclusive=True, group="spotlight-query")
    async def _debounced_render(self, query: str, generation: int) -> None:
        await asyncio.sleep(0.09)
        if generation == self.query_generation:
            self._render_results(query)

    def action_previous_result(self) -> None:
        results = self.query_one("#spotlight-results", VimOptionList)
        if results.option_count:
            results.action_cursor_up()

    def action_next_result(self) -> None:
        results = self.query_one("#spotlight-results", VimOptionList)
        if results.option_count:
            results.action_cursor_down()

    def action_accept(self) -> None:
        results = self.query_one("#spotlight-results", VimOptionList)
        index = results.highlighted
        if index is not None:
            self._accept_index(index)

    def _accept_index(self, index: int) -> None:
        if index >= len(self.result_selections):
            return
        selection = self.result_selections[index]
        if self.on_select(selection):
            self.dismiss(selection)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_list.id == "spotlight-results":
            self._accept_index(event.option_index)

    def action_toggle_scope(self) -> None:
        if self.current_bundle_id is None:
            self.notify("Select a bundle before using current-bundle scope.")
            return
        self.current_scope = not self.current_scope
        query = self.query_one("#spotlight-query", Input).value.strip()
        self.query_generation += 1
        self._render_results(query)

    def action_close(self) -> None:
        self.dismiss(None)


class KeyboardHelp(ModalScreen[None]):
    BINDINGS: ClassVar[list[BindingSpec]] = [
        Binding("escape,q,question_mark", "close", "Close", show=False, priority=True)
    ]

    def compose(self) -> ComposeResult:
        yield VimMarkdown(
            """# Keys

| Key | Action | Key | Action |
|---|---|---|---|
| `j/k` | Move / scroll | `h/l` | Collapse / expand |
| `g/G` | First / last | `Ctrl-U/D` | Page up / down |
| `H/L` | Switch pane | `1/2/3` | Concept / Health / Graph |
| `Enter` | Open | `/` | Spotlight search |
| `b/c` | Library / chat | `Esc` | Normal mode |
| `v/r/d` | Validate / refresh / diff | `Ctrl-P` | Commands |
| `Ctrl-G/X` | Cancel / discard | `q` | Quit |

Vim keys stay local to navigation widgets. Inputs remain in insert mode; press `Esc` to return.
""",
            id="keyboard-help",
        )

    def on_mount(self) -> None:
        self.query_one("#keyboard-help", VimMarkdown).focus()

    def action_close(self) -> None:
        self.dismiss(None)
