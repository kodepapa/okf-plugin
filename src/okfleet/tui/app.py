from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, ClassVar

from rich.text import Text
from textual import events, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    Markdown,
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


class OKFleetApp(App[None]):
    TITLE = "OKFleet"
    SUB_TITLE = "Open Knowledge Format workbench"

    CSS = """
    Screen { layout: vertical; }
    #body { height: 1fr; }
    #sidebar { width: 30; min-width: 22; border-right: solid $primary; }
    #main { width: 1fr; }
    #inspector { width: 42; min-width: 30; border-left: solid $primary; }
    #bundle-tree { height: 1fr; }
    #brand { height: 4; padding: 0 1; margin-top: 1; }
    #scope-label { height: auto; padding: 0 1; color: $text-muted; }
    #search-input { margin: 0 1; }
    #tabs { height: 1fr; }
    TabPane { padding: 1 2; overflow: auto; }
    #chat-transcript { height: 1fr; overflow-y: auto; padding: 1; }
    #chat-input { margin: 0 1; }
    #chat-controls { height: auto; padding: 0 1; }
    #provider-select { width: 16; }
    #mode-select { width: 18; }
    #activity { height: 4; color: $text-muted; padding: 0 1; }
    #diff { height: 12; overflow: auto; padding: 1; border-top: solid $secondary; }
    #apply-button { margin: 0 1 1 1; width: 1fr; }
    .hidden { display: none; }
    """

    BINDINGS: ClassVar[list[Binding | tuple[str, str] | tuple[str, str, str]]] = [
        Binding("ctrl+p", "command_palette", "Commands", show=True),
        Binding("slash", "focus_search", "Search", show=True),
        Binding("c", "focus_chat", "Chat", show=True),
        Binding("v", "validate", "Validate", show=True),
        Binding("r", "refresh", "Refresh", show=True),
        Binding("d", "show_diff", "Diff", show=True),
        Binding("ctrl+x", "discard_work", "Discard staged", show=False),
        Binding("escape", "cancel_chat", "Cancel turn", show=False),
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
            "# Chat\n\nChoose a provider and ask about the selected bundle or fleet."
        )
        self.workspace: StagedWorkspace | None = None
        self.changeset: ChangeSet | None = None
        self._fleet_temp: tempfile.TemporaryDirectory[str] | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="body"):
            with Vertical(id="sidebar"):
                yield Static(brand_text(), id="brand")
                yield Label("LOCAL / FLEET", id="scope-label")
                yield Tree("Bundles", id="bundle-tree")
            with Vertical(id="main"):
                yield Input(
                    placeholder="Search concepts (type:Metric tag:finance)", id="search-input"
                )
                with TabbedContent(id="tabs"):
                    with TabPane("Concept", id="concept-tab"):
                        yield Markdown("# Select a concept", id="concept-view")
                    with TabPane("Search", id="search-tab"):
                        yield Markdown("Enter a query above.", id="search-results")
                    with TabPane("Health", id="health-tab"):
                        yield Markdown("Select a bundle.", id="health-view")
                    with TabPane("Graph", id="graph-tab"):
                        yield Markdown("Select a bundle or concept.", id="graph-view")
            with Vertical(id="inspector"):
                with Horizontal(id="chat-controls"):
                    yield Select(
                        [("Codex", "codex"), ("Claude Code", "claude")],
                        value="codex",
                        id="provider-select",
                        allow_blank=False,
                    )
                    yield Select(
                        [("Read", "read"), ("Work · staged", "work")],
                        value="read",
                        id="mode-select",
                        allow_blank=False,
                    )
                yield Markdown(self.chat_transcript, id="chat-transcript")
                yield Static("Ready", id="activity")
                yield Input(placeholder="Ask OKFleet…", id="chat-input")
                yield Static("", id="diff", classes="hidden")
                yield Button(
                    "Apply staged changes",
                    id="apply-button",
                    variant="success",
                    disabled=True,
                    classes="hidden",
                )
        yield Footer()

    def on_mount(self) -> None:
        self.refresh_tree()
        self.query_one("#bundle-tree", Tree).root.expand()

    def on_resize(self, event: events.Resize) -> None:
        self.query_one("#inspector", Vertical).display = event.size.width > 75

    def refresh_tree(self) -> None:
        tree = self.query_one("#bundle-tree", Tree)
        tree.clear()
        local = discover_bundles(
            self.start_path, max_depth=int(self.registry.discovery.get("max_depth", 5))
        )
        global_refs = self.registry.list()
        self.fleet_refs = global_refs
        self.refs = local + [
            item for item in global_refs if item.path not in {ref.path for ref in local}
        ]
        local_node = tree.root.add("LOCAL", expand=True)
        for ref in local:
            local_node.add(f"{ref.alias}  [{ref.confidence}]", data=("bundle", ref))
        fleet_node = tree.root.add("FLEET", data=("fleet",), expand=True)
        for ref in global_refs:
            label = ref.alias if ref.available else f"{ref.alias}  [missing]"
            fleet_node.add(label, data=("bundle", ref), allow_expand=ref.available)
        tree.root.expand()

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
            self.query_one("#scope-label", Label).update("FLEET · read-only")
            self.query_one("#concept-view", Markdown).update(
                "# Fleet\n\nAsk read-only questions across registered bundles. "
                "Answers must use bundle-qualified citations."
            )

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
        if not self.selected_ref or self.selected_ref.id != ref.id:
            self.chat_session = None
        self.selected_ref = ref
        self.selected_bundle = load_bundle(ref.path)
        self.selected_concept_id = None
        self.database.index_bundle(ref, self.selected_bundle)
        self.query_one("#scope-label", Label).update(f"{ref.alias}\n{ref.path}")
        self.query_one("#concept-view", Markdown).update(
            f"# {ref.alias}\n\n{len(self.selected_bundle.concepts)} concepts · OKF {self.selected_bundle.version or 'unspecified'}\n\nPath: `{ref.path}`"
        )
        self.update_health()
        self.update_graph()
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
        self.query_one("#concept-view", Markdown).update(
            f"# {concept.title}\n\n{concept.body}{metadata}"
        )
        self.query_one("#tabs", TabbedContent).active = "concept-tab"
        self.update_graph()

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
        self.query_one("#health-view", Markdown).update("\n".join(lines))

    def update_graph(self) -> None:
        if not self.selected_bundle:
            return
        graph = graph_neighborhood(self.selected_bundle, self.selected_concept_id, 1)
        mermaid = graph_mermaid(graph)
        self.query_one("#graph-view", Markdown).update(
            f"# Relationship graph\n\n```mermaid\n{mermaid}```\n\n{len(graph['nodes'])} nodes · {len(graph['edges'])} edges"
        )

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "search-input":
            return
        query = event.value.strip()
        if not query:
            self.query_one("#search-results", Markdown).update("Enter a query above.")
            return
        refs = [ref for ref in self.refs if ref.available]
        for ref in refs:
            self.database.index_bundle(ref, load_bundle(ref.path))
        hits = self.database.search(query, bundle_ids=[ref.id for ref in refs], limit=30)
        lines = [f"# Search · {query}", ""]
        lines.extend(
            f"- **`{hit.citation}`** · {hit.concept_type or 'Concept'} — {hit.description or hit.snippet}"
            for hit in hits
        )
        if not hits:
            lines.append("No matches.")
        self.query_one("#search-results", Markdown).update("\n".join(lines))
        self.query_one("#tabs", TabbedContent).active = "search-tab"

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
            transcript = self.query_one("#chat-transcript", Markdown)
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

    def action_focus_search(self) -> None:
        self.query_one("#search-input", Input).focus()

    def action_focus_chat(self) -> None:
        inspector = self.query_one("#inspector", Vertical)
        if inspector.display:
            self.query_one("#chat-input", Input).focus()
        else:
            self.notify("Chat panel is hidden at this terminal width; widen the terminal.")

    def action_validate(self) -> None:
        if not self.selected_bundle:
            self.notify("Select a bundle first.")
            return
        self.update_health()
        self.query_one("#tabs", TabbedContent).active = "health-tab"

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
        self.notify(
            "Use the sidebar to browse, / to search, c to chat, v for health, d for staged diff, Esc to cancel a turn, Ctrl+X to discard staged work, and Ctrl+P for commands.",
            timeout=8,
        )

    def on_unmount(self) -> None:
        if self.workspace:
            self.workspace.close()
        if self._fleet_temp:
            self._fleet_temp.cleanup()
        self.database.close()


def run_tui(path: Path) -> None:
    OKFleetApp(path).run()
