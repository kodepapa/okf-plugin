from __future__ import annotations

from typing import Any, ClassVar

from textual.binding import Binding
from textual.widgets import Markdown, OptionList, Tree

BindingSpec = Binding | tuple[str, str] | tuple[str, str, str]


class VimTree(Tree[Any]):
    """A Tree with Vim aliases that stay local to the focused tree."""

    BINDINGS: ClassVar[list[BindingSpec]] = [
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("h", "collapse_or_parent", "Collapse", show=False),
        Binding("l", "expand_or_child", "Expand", show=False),
        Binding("g", "first", "First", show=False),
        Binding("G", "last", "Last", show=False),
        Binding("ctrl+d", "page_down", "Page down", show=False),
        Binding("ctrl+u", "page_up", "Page up", show=False),
    ]

    def action_collapse_or_parent(self) -> None:
        node = self.cursor_node
        if node is None:
            return
        if node.is_expanded:
            node.collapse()
        elif node.parent is not None:
            self.move_cursor(node.parent)

    def action_expand_or_child(self) -> None:
        node = self.cursor_node
        if node is None:
            return
        if node.children:
            if node.is_expanded:
                self.move_cursor(node.children[0])
            else:
                node.expand()
        else:
            self.action_select_cursor()

    def action_first(self) -> None:
        self.move_cursor_to_line(0)

    def action_last(self) -> None:
        self.move_cursor_to_line(self.last_line)


class VimMarkdown(Markdown):
    """Focusable Markdown with Vim scrolling."""

    can_focus = True

    BINDINGS: ClassVar[list[BindingSpec]] = [
        Binding("j", "scroll_down", "Down", show=False),
        Binding("k", "scroll_up", "Up", show=False),
        Binding("h", "scroll_left", "Left", show=False),
        Binding("l", "scroll_right", "Right", show=False),
        Binding("g", "scroll_home", "Top", show=False),
        Binding("G", "scroll_end", "Bottom", show=False),
        Binding("ctrl+d", "page_down", "Page down", show=False),
        Binding("ctrl+u", "page_up", "Page up", show=False),
    ]


class VimOptionList(OptionList):
    """An OptionList with Vim aliases for result navigation."""

    BINDINGS: ClassVar[list[BindingSpec]] = [
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("g", "first", "First", show=False),
        Binding("G", "last", "Last", show=False),
        Binding("ctrl+d", "page_down", "Page down", show=False),
        Binding("ctrl+u", "page_up", "Page up", show=False),
    ]
