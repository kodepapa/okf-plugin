from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

from typer.testing import CliRunner

from okfleet.cli import app
from okfleet.models import AgentEvent, AgentEventType, AgentSession, SessionMode
from okfleet.pending import PendingChangeStore
from okfleet.registry import BundleRegistry
from okfleet.search import SearchDatabase

runner = CliRunner()


class FakeProvider:
    name = "codex"

    def __init__(self, *, staged_addition: str | None = None) -> None:
        self.staged_addition = staged_addition
        self.prompts: list[str] = []
        self.sessions = 0

    async def start(
        self,
        *,
        mode: SessionMode,
        cwd: Path,
        scope: list[str] | None = None,
        metadata: dict[str, object] | None = None,
    ) -> AgentSession:
        self.sessions += 1
        session_id = f"00000000-0000-0000-0000-{self.sessions:012d}"
        return AgentSession(
            id=session_id,
            provider=self.name,
            mode=mode,
            cwd=cwd,
            native_id=f"native-{self.sessions}",
            scope=scope or [],
            metadata=metadata or {},
        )

    async def send(
        self, session: AgentSession, message: str
    ) -> AsyncIterator[AgentEvent]:
        self.prompts.append(message)
        if self.staged_addition and session.mode == SessionMode.BUNDLE_WORK_STAGED:
            concept = session.cwd / "metrics/revenue.md"
            concept.write_text(
                concept.read_text(encoding="utf-8") + self.staged_addition,
                encoding="utf-8",
            )
        yield AgentEvent(AgentEventType.MESSAGE_COMPLETED, text="fixture response")


def test_fleet_chat_and_session_lifecycle_use_a_provider_without_live_calls(
    bundle_path: Path, monkeypatch
) -> None:
    BundleRegistry().add(bundle_path, "main")
    provider = FakeProvider()
    monkeypatch.setattr("okfleet.cli.provider_for", lambda *_args, **_kwargs: provider)

    chatted = runner.invoke(
        app, ["chat", "recognized revenue", "--scope", "fleet", "--provider", "codex"]
    )
    session_id = "00000000-0000-0000-0000-000000000001"
    listed = runner.invoke(app, ["sessions", "list"])
    resumed = runner.invoke(
        app, ["sessions", "resume", session_id, "follow up"]
    )
    deleted = runner.invoke(app, ["sessions", "delete", session_id])

    assert chatted.exit_code == 0, chatted.output
    assert "fixture response" in chatted.stdout
    assert "[main:metrics/revenue]" in provider.prompts[0]
    assert listed.exit_code == 0, listed.output
    assert session_id in listed.stdout
    assert resumed.exit_code == 0, resumed.output
    assert provider.prompts[-1] == "follow up"
    assert deleted.exit_code == 0, deleted.output
    with SearchDatabase() as database:
        assert database.get_session(session_id) is None


def test_work_chat_changeset_show_apply_and_delete_are_complete_cli_workflows(
    bundle_path: Path, monkeypatch
) -> None:
    BundleRegistry().add(bundle_path, "main")
    first_addition = "\n" + ("staged CLI audit line " * 8).strip() + "\n"
    provider = FakeProvider(staged_addition=first_addition)
    monkeypatch.setattr("okfleet.cli.provider_for", lambda *_args, **_kwargs: provider)

    staged = runner.invoke(
        app, ["chat", "edit it", "--scope", "main", "--mode", "work"]
    )
    manifests = PendingChangeStore().list()
    assert staged.exit_code == 0, staged.output
    assert len(manifests) == 1
    changeset_id = str(manifests[0]["id"])

    listed = runner.invoke(app, ["changesets", "list"])
    shown = runner.invoke(
        app, ["changesets", "show", changeset_id], terminal_width=40
    )
    applied = runner.invoke(app, ["apply", changeset_id])

    assert listed.exit_code == 0, listed.output
    assert changeset_id in listed.stdout
    assert shown.exit_code == 0, shown.output
    assert first_addition.strip() in shown.stdout
    assert applied.exit_code == 0, applied.output
    assert first_addition.strip() in (bundle_path / "metrics/revenue.md").read_text(
        encoding="utf-8"
    )
    assert PendingChangeStore().list() == []

    second_addition = "\nthis staged change must be discarded\n"
    provider.staged_addition = second_addition
    staged_again = runner.invoke(
        app, ["chat", "edit again", "--scope", "main", "--mode", "work"]
    )
    second_id = str(PendingChangeStore().list()[0]["id"])
    deleted = runner.invoke(app, ["changesets", "delete", second_id])

    assert staged_again.exit_code == 0, staged_again.output
    assert deleted.exit_code == 0, deleted.output
    assert second_addition.strip() not in (bundle_path / "metrics/revenue.md").read_text(
        encoding="utf-8"
    )
    assert PendingChangeStore().list() == []
