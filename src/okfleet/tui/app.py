from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, ClassVar

from rich.text import Text
from textual import events, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widget import Widget
from textual.widgets import (
    Button,
    Input,
    Label,
    Select,
    Static,
    TabbedContent,
    TabPane,
    Tree,
)

from ..agents import provider_for
from ..branding import brand_text
from ..chat import ChatService
from ..core import graph_mermaid, graph_neighborhood, inbound_links, load_bundle, validate_bundle
from ..models import (
    AgentEventType,
    AgentSession,
    Bundle,
    BundleRef,
    ChangeSet,
    SessionMode,
    Severity,
)
from ..registry import BundleRegistry, discover_bundles
from ..search import SearchDatabase
from ..workspace import StagedWorkspace
from .screens import KeyboardHelp, SearchSelection, SpotlightSearch
from .widgets import VimMarkdown, VimTree


class OKFleetApp(App[None]):
    TITLE = "OKFleet"
    SUB_TITLE = "Open Knowledge Format workbench"
    CSS_PATH = "okfleet.tcss"

    _NAVIGATION_ACTIONS = frozenset(
        {
            "search",
            "focus_browse",
            "focus_chat",
            "focus_previous_pane",
            "focus_next_pane",
            "show_tab",
            "validate",
            "refresh",
            "show_diff",
            "help",
            "quit",
        }
    )

    BINDINGS: ClassVar[list[Binding | tuple[str, str] | tuple[str, str, str]]] = [
        Binding("ctrl+p", "command_palette", "Commands", show=True),
        Binding("slash", "search", "Search", show=True),
        Binding("ctrl+k", "global_search", "Search", show=False, priority=True),
        Binding("b", "focus_browse", "Browse", show=True),
        Binding("c", "focus_chat", "Chat", show=True),
        Binding("H", "focus_previous_pane", "Pane ←", show=True),
        Binding("L", "focus_next_pane", "Pane →", show=True),
        Binding("1", "show_tab('concept-tab')", "Concept", show=False),
        Binding("2", "show_tab('health-tab')", "Health", show=False),
        Binding("3", "show_tab('graph-tab')", "Graph", show=False),
        Binding("v", "validate", "Validate", show=True),
        Binding("r", "refresh", "Refresh", show=True),
        Binding("d", "show_diff", "Diff", show=True),
        Binding("ctrl+x", "discard_work", "Discard staged", show=False),
        Binding("ctrl+g", "cancel_chat", "Cancel turn", show=False),
        Binding("escape", "normal_mode", "Browse mode", show=False),
        Binding("question_mark", "help", "Help", show=True),
        Binding("q", "quit", "Quit", show=True),
    ]

    def __init__(self, start_path: Path) -> None:
        super().__init__()
        self.start_path = start_path.expanduser().resolve()
        self.registry = BundleRegistry()
        self.database = SearchDatabase()
        self.refs: list[BundleRef] = []
        self.fleet_refs: list[BundleRef] = []
        self.selected_ref: BundleRef | None = None
        self.selected_bundle: Bundle | None = None
        self.selected_concept_id: str | None = None
        self.chat_session: AgentSession | None = None
        self.chat_service: ChatService | None = None
        self.chat_transcript = (
            "Ask a read-only question across every bundle. Select a bundle to unlock staged work."
        )
        self.workspace: StagedWorkspace | None = None
        self.changeset: ChangeSet | None = None
        self._fleet_temp: tempfile.TemporaryDirectory[str] | None = None
        self._narrow = False
        self._narrow_pane = "library"
        self._chat_open = False
        self._focus_before_chat_id: str | None = None
        self._search_index_errors: dict[str, str] = {}

    def compose(self) -> ComposeResult:
        with Horizontal(id="topbar"):
            yield Static(brand_text(), id="brand")
            yield Static("OKF KNOWLEDGE WORKBENCH", id="product-label")
            yield Static("NORMAL", id="mode-indicator")
        with Horizontal(id="body"):
            with Vertical(id="sidebar"):
                with Horizontal(id="library-header"):
                    yield Static("LIBRARY", id="library-title")
                    yield Static("0 bundles", id="library-count")
                yield Label("LOCAL + GLOBAL", id="scope-label")
                yield VimTree("Bundles", id="bundle-tree")
            with Vertical(id="main"), TabbedContent(id="tabs"):
                with TabPane("Concept", id="concept-tab"):
                    yield VimMarkdown(
                        "# Find knowledge\n\nj/k move · l expand · Enter open\n\n"
                        "/ search every bundle · c chat with the current scope",
                        id="concept-view",
                    )
                with TabPane("Health", id="health-tab"):
                    yield VimMarkdown(
                        "# Health\n\nSelect a bundle to inspect its health.", id="health-view"
                    )
                with TabPane("Graph", id="graph-tab"):
                    yield VimMarkdown(
                        "# Graph\n\nSelect a bundle or concept to inspect relationships.",
                        id="graph-view",
                    )
            with Vertical(id="chat-drawer", classes="hidden"):
                with Horizontal(id="chat-header"):
                    yield Static("CHAT · ALL KNOWLEDGE", id="chat-title")
                    yield Static("Esc close", id="chat-close-hint")
                with Horizontal(id="chat-controls"):
                    yield Select(
                        [("Agent · Codex", "codex"), ("Agent · Claude Code", "claude")],
                        value="codex",
                        id="provider-select",
                        allow_blank=False,
                    )
                    yield Select(
                        [("Mode · Read-only", "read"), ("Mode · Work (staged)", "work")],
                        value="read",
                        id="mode-select",
                        allow_blank=False,
                    )
                yield VimMarkdown(self.chat_transcript, id="chat-transcript")
                yield Static("Ready", id="activity")
                yield Input(placeholder="Ask across all knowledge…", id="chat-input")
                yield Static("Enter send  ·  Ctrl-G cancel  ·  staged writes only", id="chat-hints")
                yield Static("", id="diff", classes="hidden")
                yield Button(
                    "Apply staged changes",
                    id="apply-button",
                    variant="success",
                    disabled=True,
                    classes="hidden",
                )
        yield Static(
            "j/k move  ·  Enter open  ·  / search  ·  c chat  ·  ? keys",
            id="status-bar",
        )

    def on_mount(self) -> None:
        self.refresh_tree()
        tree = self.query_one("#bundle-tree", VimTree)
        tree.show_root = False
        tree.root.expand()
        tree.focus()
        self._narrow = self.size.width <= 88
        self._sync_layout_classes()

    def on_resize(self, event: events.Resize) -> None:
        was_narrow = self._narrow
        self._narrow = event.size.width <= 88
        if self._narrow and not was_narrow and not self._chat_open:
            focused_id = self.focused.id if self.focused else None
            self._narrow_pane = (
                "content" if focused_id and focused_id != "bundle-tree" else "library"
            )
        self._sync_layout_classes()

    def _sync_layout_classes(self) -> None:
        body = self.query_one("#body", Horizontal)
        body.set_class(self._narrow, "narrow")
        body.set_class(self._chat_open, "chat-open")
        body.set_class(self._narrow and self._narrow_pane == "library", "library-pane")
        body.set_class(self._narrow and self._narrow_pane == "content", "content-pane")
        self.query_one("#chat-drawer", Vertical).set_class(self._narrow, "full-screen")

    def _show_narrow_pane(self, pane: str, *, focus: bool = True) -> None:
        if not self._narrow:
            return
        self._narrow_pane = pane
        self._sync_layout_classes()
        if not focus:
            return
        if pane == "library":
            self.query_one("#bundle-tree", VimTree).focus()
            return
        tabs = self.query_one("#tabs", TabbedContent)
        view_id = {
            "concept-tab": "#concept-view",
            "health-tab": "#health-view",
            "graph-tab": "#graph-view",
        }.get(tabs.active, "#concept-view")
        self.query_one(view_id, VimMarkdown).focus()

    def refresh_tree(self) -> None:
        tree = self.query_one("#bundle-tree", VimTree)
        tree.clear()
        local = discover_bundles(
            self.start_path, max_depth=int(self.registry.discovery.get("max_depth", 5))
        )
        global_refs = self.registry.list()
        self.refs = local + [
            item for item in global_refs if item.path not in {ref.path for ref in local}
        ]
        self.fleet_refs = self.refs
        tree.root.add_leaf("ALL KNOWLEDGE", data=("fleet",))
        local_node = tree.root.add("LOCAL", expand=True)
        for ref in local:
            local_node.add(f"{ref.alias}  [{ref.confidence}]", data=("bundle", ref))
        fleet_node = tree.root.add("GLOBAL", expand=True)
        for ref in global_refs:
            label = ref.alias if ref.available else f"{ref.alias}  [missing]"
            fleet_node.add(label, data=("bundle", ref), allow_expand=ref.available)
        tree.root.expand()
        count = len(self.refs)
        self.query_one("#library-count", Static).update(
            f"{count} bundle{'s' if count != 1 else ''}"
        )
        self._index_search_refs()

    def _index_search_refs(self) -> None:
        self._search_index_errors = {}
        for ref in self.refs:
            if not ref.available:
                continue
            try:
                self.database.index_bundle(ref, load_bundle(ref.path))
            except Exception as exc:
                self._search_index_errors[ref.id] = str(exc)

    def _populate_concepts(self, node: Any, ref: BundleRef) -> None:
        if node.children:
            return
        loaded = load_bundle(ref.path)
        for concept in sorted(loaded.concepts.values(), key=lambda item: item.concept_id):
            node.add_leaf(concept.concept_id, data=("concept", ref, concept.concept_id))

    def on_tree_node_expanded(self, event: Tree.NodeExpanded[Any]) -> None:
        data = event.node.data
        if isinstance(data, tuple) and data and data[0] == "bundle":
            self._populate_concepts(event.node, data[1])

    def on_tree_node_selected(self, event: Tree.NodeSelected[Any]) -> None:
        data = event.node.data
        if not isinstance(data, tuple):
            return
        if data[0] == "bundle":
            ref: BundleRef = data[1]
            if not ref.available:
                self.notify(f"Bundle is unavailable: {ref.path}", severity="error")
                return
            if not self.open_bundle(ref):
                return
            event.node.expand()
            self._populate_concepts(event.node, ref)
        elif data[0] == "concept":
            ref, concept_id = data[1], data[2]
            if (not self.selected_ref or self.selected_ref.id != ref.id) and not self.open_bundle(
                ref
            ):
                return
            self.open_concept(concept_id)
        elif data[0] == "fleet":
            if self.workspace and self.workspace.changeset().changes:
                self.notify(
                    "Apply or discard staged changes before leaving the bundle.",
                    severity="warning",
                )
                return
            if self.workspace:
                self.workspace.close()
                self.workspace = None
            self.selected_ref = None
            self.selected_bundle = None
            self.selected_concept_id = None
            self.chat_session = None
            self._set_chat_intro(
                "Ask a read-only question across every bundle. "
                "Select a bundle to unlock staged work."
            )
            mode_select = self.query_one("#mode-select", Select)
            mode_select.value = "read"
            mode_select.disabled = True
            self.query_one("#scope-label", Label).update("ALL KNOWLEDGE · READ ONLY")
            self.query_one("#chat-title", Static).update("CHAT · ALL KNOWLEDGE")
            self.query_one("#chat-input", Input).placeholder = "Ask across all knowledge…"
            self.query_one("#concept-view", VimMarkdown).update(
                "# Fleet\n\nAsk read-only questions across registered bundles. "
                "Answers must use bundle-qualified citations."
            )
            self._show_narrow_pane("content")

    def _set_chat_intro(self, message: str) -> None:
        self.chat_transcript = message
        self.query_one("#chat-transcript", VimMarkdown).update(message)
        self.query_one("#activity", Static).update("Ready")

    def open_bundle(self, ref: BundleRef) -> bool:
        if self.workspace and self.workspace.source_root != ref.path:
            if self.workspace.changeset().changes:
                self.notify(
                    "Apply or discard staged changes before switching bundles.",
                    severity="warning",
                )
                return False
            self.workspace.close()
            self.workspace = None
        scope_changed = not self.selected_ref or self.selected_ref.id != ref.id
        if scope_changed:
            self.chat_session = None
            self._set_chat_intro(
                f"Ask a read-only question about **{ref.alias}**, or switch to staged work "
                "to propose bundle changes."
            )
        self.selected_ref = ref
        self.selected_bundle = load_bundle(ref.path)
        self.selected_concept_id = None
        self.database.index_bundle(ref, self.selected_bundle)
        self.query_one("#mode-select", Select).disabled = False
        self.query_one("#scope-label", Label).update(
            f"{ref.alias} · {len(self.selected_bundle.concepts)} concepts"
        )
        self.query_one("#chat-title", Static).update(f"CHAT · {ref.alias}")
        self.query_one("#chat-input", Input).placeholder = f"Ask about {ref.alias}…"
        self.query_one("#concept-view", VimMarkdown).update(
            f"# {ref.alias}\n\n{len(self.selected_bundle.concepts)} concepts · OKF {self.selected_bundle.version or 'unspecified'}\n\nPath: `{ref.path}`"
        )
        self.update_health()
        self.update_graph()
        self._show_narrow_pane("content")
        return True

    def open_concept(self, concept_id: str) -> None:
        if not self.selected_bundle or not self.selected_ref:
            return
        concept = self.selected_bundle.get(concept_id)
        if not concept:
            return
        self.selected_concept_id = concept_id
        incoming = inbound_links(self.selected_bundle).get(concept_id, [])
        metadata = (
            f"\n\n---\n\n**Citation:** `{concept.citation(self.selected_ref.alias)}`  "
            f"\n**Type:** {concept.concept_type or 'missing'}  "
            f"\n**Path:** `{concept.path.relative_to(self.selected_ref.path)}`  "
            f"\n**Links:** {len(concept.links)} outbound · {len(incoming)} inbound"
        )
        self.query_one("#concept-view", VimMarkdown).update(
            f"# {concept.title}\n\n{concept.body}{metadata}"
        )
        self.query_one("#tabs", TabbedContent).active = "concept-tab"
        self.update_graph()
        self._show_narrow_pane("content")

    def update_health(self) -> None:
        if not self.selected_bundle or not self.selected_ref:
            return
        diagnostics = validate_bundle(
            self.selected_bundle, include_health=True, stale_after_days=180
        )
        lines = [f"# Health · {self.selected_ref.alias}", ""]
        if not diagnostics:
            lines.append("✅ No diagnostics.")
        else:
            for item in diagnostics:
                icon = {Severity.ERROR: "🔴", Severity.WARNING: "🟡", Severity.INFO: "🔵"}[
                    item.severity
                ]
                location = item.path.relative_to(self.selected_ref.path)
                lines.append(
                    f"- {icon} **{item.code}** `{location}:{item.line or 1}` — {item.message}"
                )
        self.query_one("#health-view", VimMarkdown).update("\n".join(lines))

    def update_graph(self) -> None:
        if not self.selected_bundle:
            return
        graph = graph_neighborhood(self.selected_bundle, self.selected_concept_id, 1)
        mermaid = graph_mermaid(graph)
        self.query_one("#graph-view", VimMarkdown).update(
            f"# Relationship graph\n\n```mermaid\n{mermaid}```\n\n{len(graph['nodes'])} nodes · {len(graph['edges'])} edges"
        )

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "chat-input" or not event.value.strip():
            return
        question = event.value.strip()
        event.input.value = ""
        self.run_chat(question)

    @work(exclusive=True, group="chat")
    async def run_chat(self, question: str) -> None:
        provider_name = str(self.query_one("#provider-select", Select).value)
        mode = str(self.query_one("#mode-select", Select).value)
        provider = provider_for(provider_name, plugin_root=self._plugin_root())
        self.chat_service = ChatService(provider, self.database)
        fleet_refs: list[BundleRef] | None = None
        try:
            if self.selected_ref:
                if mode == "work":
                    if not self.workspace:
                        self.workspace = StagedWorkspace(self.selected_ref.path)
                    desired_mode = SessionMode.BUNDLE_WORK_STAGED
                    if not (
                        self.chat_session
                        and self.chat_session.provider == provider_name
                        and self.chat_session.mode == desired_mode
                        and self.chat_session.scope == [self.selected_ref.alias]
                    ):
                        self.chat_session = await self.chat_service.start_bundle(
                            self.selected_ref, work=True, cwd=self.workspace.root
                        )
                else:
                    desired_mode = SessionMode.BUNDLE_READ
                    if not (
                        self.chat_session
                        and self.chat_session.provider == provider_name
                        and self.chat_session.mode == desired_mode
                        and self.chat_session.scope == [self.selected_ref.alias]
                    ):
                        self.chat_session = await self.chat_service.start_bundle(self.selected_ref)
            else:
                fleet_refs = [ref for ref in self.fleet_refs if ref.available]
                if not fleet_refs:
                    self.notify("No readable bundles are available.", severity="error")
                    return
                if not self._fleet_temp:
                    self._fleet_temp = tempfile.TemporaryDirectory(prefix="okfleet-read-")
                desired_scope = [ref.alias for ref in fleet_refs]
                if not (
                    self.chat_session
                    and self.chat_session.provider == provider_name
                    and self.chat_session.mode == SessionMode.FLEET_READ
                    and self.chat_session.scope == desired_scope
                ):
                    self.chat_session = await self.chat_service.start_fleet(
                        fleet_refs, Path(self._fleet_temp.name)
                    )
            self.chat_transcript += f"\n\n## You\n\n{question}\n\n## {provider_name.title()}\n\n"
            transcript = self.query_one("#chat-transcript", VimMarkdown)
            transcript.update(self.chat_transcript + "▌")
            activity = self.query_one("#activity", Static)
            async for event in self.chat_service.send(
                self.chat_session, question, fleet_refs=fleet_refs
            ):
                if event.type == AgentEventType.MESSAGE_DELTA:
                    self.chat_transcript += event.text
                    transcript.update(self.chat_transcript + "▌")
                elif event.type == AgentEventType.MESSAGE_COMPLETED and event.text:
                    if event.text not in self.chat_transcript[-len(event.text) - 20 :]:
                        self.chat_transcript += event.text
                    transcript.update(self.chat_transcript)
                elif event.type in {AgentEventType.TOOL_STARTED, AgentEventType.FILE_CHANGED}:
                    activity.update(
                        Text(f"{event.type.value}: {event.text or event.data}", style="dim")
                    )
                elif event.type in {AgentEventType.TURN_FAILED, AgentEventType.ERROR}:
                    activity.update(Text(event.text, style="bold red"))
                elif event.type == AgentEventType.TURN_COMPLETED:
                    activity.update("Turn complete")
            transcript.update(self.chat_transcript)
            if self.workspace:
                self.changeset = self.workspace.changeset()
                diff = (
                    "\n".join(change.diff for change in self.changeset.changes)
                    or "No staged changes."
                )
                diff_widget = self.query_one("#diff", Static)
                diff_widget.update(diff)
                diff_widget.remove_class("hidden")
                button = self.query_one("#apply-button", Button)
                button.disabled = not self.changeset.changes or bool(self.changeset.conflicts)
                button.remove_class("hidden")
        except Exception as exc:
            self.query_one("#activity", Static).update(Text(str(exc), style="bold red"))

    def _plugin_root(self) -> Path | None:
        from ..cli import _plugin_root

        return _plugin_root()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "apply-button" and self.workspace:
            try:
                changeset = self.workspace.apply()
                self.notify(f"Applied {len(changeset.changes)} staged file changes.")
                if self.selected_ref:
                    self.open_bundle(self.selected_ref)
                event.button.disabled = True
            except Exception as exc:
                self.notify(str(exc), severity="error")

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if isinstance(
            self.screen, (SpotlightSearch, KeyboardHelp)
        ) and action in self._NAVIGATION_ACTIONS | {"global_search"}:
            return False
        return not (
            isinstance(self.focused, (Input, Select)) and action in self._NAVIGATION_ACTIONS
        )

    def action_search(self) -> None:
        self.push_screen(
            SpotlightSearch(
                self.database,
                self.refs,
                current_bundle_id=self.selected_ref.id if self.selected_ref else None,
                index_errors=self._search_index_errors,
                on_select=self._open_search_selection,
            )
        )

    def action_global_search(self) -> None:
        self.action_search()

    def _open_search_selection(self, selection: SearchSelection) -> bool:
        ref = next((item for item in self.refs if item.id == selection.bundle_id), None)
        if ref is None or not ref.available:
            self.notify(
                "That bundle is no longer available. Refresh and try again.", severity="error"
            )
            return False
        if not self.open_bundle(ref):
            return False
        if selection.kind == "concept":
            if (
                not selection.concept_id
                or not self.selected_bundle
                or not self.selected_bundle.get(selection.concept_id)
            ):
                self.notify(
                    "That concept is no longer available. Refresh and try again.", severity="error"
                )
                return False
            self.open_concept(selection.concept_id)
        self.call_after_refresh(self._reveal_tree_selection, ref, selection.concept_id)
        return True

    def _reveal_tree_selection(self, ref: BundleRef, concept_id: str | None) -> None:
        tree = self.query_one("#bundle-tree", VimTree)
        stack = [tree.root]
        bundle_node: Any | None = None
        while stack:
            node = stack.pop()
            data = node.data
            if (
                isinstance(data, tuple)
                and len(data) >= 2
                and data[0] == "bundle"
                and data[1].id == ref.id
            ):
                bundle_node = node
                break
            stack.extend(reversed(node.children))
        if bundle_node is None:
            return
        if bundle_node.parent is not None:
            bundle_node.parent.expand()
        bundle_node.expand()
        self._populate_concepts(bundle_node, ref)
        target = bundle_node
        if concept_id:
            for child in bundle_node.children:
                data = child.data
                if isinstance(data, tuple) and len(data) >= 3 and data[2] == concept_id:
                    target = child
                    break
        self.call_after_refresh(tree.move_cursor, target)

    def action_focus_browse(self) -> None:
        if self._chat_open:
            self._chat_open = False
            self.query_one("#chat-drawer", Vertical).add_class("hidden")
        self.query_one("#mode-indicator", Static).update("NORMAL")
        self.query_one("#status-bar", Static).remove_class("chat-mode")
        self._show_narrow_pane("library")
        if not self._narrow:
            self._sync_layout_classes()
            self.query_one("#bundle-tree", VimTree).focus()

    def action_focus_chat(self) -> None:
        drawer = self.query_one("#chat-drawer", Vertical)
        self._focus_before_chat_id = self.focused.id if self.focused else None
        self._chat_open = True
        drawer.remove_class("hidden")
        self._sync_layout_classes()
        self.query_one("#mode-indicator", Static).update("INSERT · CHAT")
        self.query_one("#status-bar", Static).add_class("chat-mode")
        self.query_one("#chat-input", Input).focus()

    def action_normal_mode(self) -> None:
        was_chat_open = self._chat_open
        if was_chat_open:
            self._chat_open = False
            self.query_one("#chat-drawer", Vertical).add_class("hidden")
        self.query_one("#mode-indicator", Static).update("NORMAL")
        self.query_one("#status-bar", Static).remove_class("chat-mode")
        self._sync_layout_classes()
        if was_chat_open and self._focus_before_chat_id:
            prior = self.query(f"#{self._focus_before_chat_id}").first()
            if prior is not None:
                prior.focus()
                self._focus_before_chat_id = None
                return
        self._focus_before_chat_id = None
        self._show_narrow_pane("library")
        if not self._narrow:
            self.query_one("#bundle-tree", VimTree).focus()

    def _pane_targets(self) -> list[Widget]:
        tabs = self.query_one("#tabs", TabbedContent)
        view_id = {
            "concept-tab": "#concept-view",
            "health-tab": "#health-view",
            "graph-tab": "#graph-view",
        }.get(tabs.active, "#concept-view")
        targets: list[Widget] = [
            self.query_one("#bundle-tree", VimTree),
            self.query_one(view_id, VimMarkdown),
        ]
        if self._chat_open:
            targets.append(self.query_one("#chat-transcript", VimMarkdown))
        return targets

    def _focus_relative_pane(self, offset: int) -> None:
        if self._narrow and not self._chat_open:
            self._show_narrow_pane("content" if offset > 0 else "library")
            return
        targets = self._pane_targets()
        focused_id = self.focused.id if self.focused else None
        if focused_id == "bundle-tree":
            index = 0
        elif (
            focused_id
            in {
                "chat-transcript",
                "chat-input",
                "provider-select",
                "mode-select",
                "activity",
                "diff",
                "apply-button",
            }
            and len(targets) == 3
        ):
            index = 2
        else:
            index = 1
        targets[(index + offset) % len(targets)].focus()

    def action_focus_previous_pane(self) -> None:
        self._focus_relative_pane(-1)

    def action_focus_next_pane(self) -> None:
        self._focus_relative_pane(1)

    def action_show_tab(self, tab_id: str) -> None:
        self.query_one("#tabs", TabbedContent).active = tab_id
        self._show_narrow_pane("content")

    def action_validate(self) -> None:
        if not self.selected_bundle:
            self.notify("Select a bundle first.")
            return
        self.update_health()
        self.action_show_tab("health-tab")

    def action_refresh(self) -> None:
        self.refresh_tree()
        if self.selected_ref and self.selected_ref.available:
            self.open_bundle(self.selected_ref)
        self.notify("Refreshed bundles and index.")

    def action_show_diff(self) -> None:
        if not self.workspace:
            self.notify("No staged work session is active.")
            return
        changeset = self.workspace.changeset()
        diff = "\n".join(change.diff for change in changeset.changes) or "No staged changes."
        widget = self.query_one("#diff", Static)
        widget.update(diff)
        widget.toggle_class("hidden")

    async def action_cancel_chat(self) -> None:
        if self.chat_service and self.chat_session:
            await self.chat_service.provider.cancel(self.chat_session)
            self.query_one("#activity", Static).update("Turn cancelled")

    def action_discard_work(self) -> None:
        if not self.workspace:
            self.notify("No staged work session is active.")
            return
        self.workspace.close()
        self.workspace = None
        self.changeset = None
        if self.chat_session and self.chat_session.mode == SessionMode.BUNDLE_WORK_STAGED:
            self.chat_session = None
        self.query_one("#diff", Static).add_class("hidden")
        self.query_one("#apply-button", Button).add_class("hidden")
        self.notify("Discarded staged changes.")

    def action_help(self) -> None:
        self.push_screen(KeyboardHelp())

    def on_unmount(self) -> None:
        if self.workspace:
            self.workspace.close()
        if self._fleet_temp:
            self._fleet_temp.cleanup()
        self.database.close()


def run_tui(path: Path) -> None:
    OKFleetApp(path).run()
