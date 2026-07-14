from __future__ import annotations

from pathlib import Path

from okfleet.agents.base import bootstrap_prompt
from okfleet.agents.claude import ClaudeProvider
from okfleet.agents.codex import CodexProvider
from okfleet.agents.codex_app_server import CodexAppServerTransport
from okfleet.models import AgentEventType, AgentSession, SessionMode


def session(tmp_path: Path, mode: SessionMode) -> AgentSession:
    return AgentSession("test", "provider", mode, tmp_path, scope=["finance"])


def test_codex_argv_is_read_only_without_shell(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(CodexProvider, "binary_path", classmethod(lambda cls: "/bin/codex"))
    command = CodexProvider()._command(
        session(tmp_path, SessionMode.BUNDLE_READ), "hello; rm -rf /"
    )
    assert command[0] == "/bin/codex"
    assert command[command.index("--sandbox") + 1] == "read-only"
    assert command[-1].endswith("hello; rm -rf /")


def test_codex_resume_keeps_parent_safety_options_before_subcommand(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(CodexProvider, "binary_path", classmethod(lambda cls: "/bin/codex"))
    active = session(tmp_path, SessionMode.BUNDLE_READ)
    active.native_id = "thread-123"
    command = CodexProvider()._command(active, "continue")
    assert command.index("--sandbox") < command.index("resume")
    assert command[command.index("resume") + 1] == "thread-123"


def test_claude_argv_restricts_fleet_tools(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(ClaudeProvider, "binary_path", classmethod(lambda cls: "/bin/claude"))
    command = ClaudeProvider()._command(session(tmp_path, SessionMode.FLEET_READ), "question")
    assert command[command.index("--permission-mode") + 1] == "plan"
    assert command[command.index("--tools") + 1] == ""


def test_claude_staged_work_does_not_expose_shell(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(ClaudeProvider, "binary_path", classmethod(lambda cls: "/bin/claude"))
    command = ClaudeProvider()._command(
        session(tmp_path, SessionMode.BUNDLE_WORK_STAGED), "edit docs"
    )
    tools = command[command.index("--tools") + 1]
    assert "Edit" in tools
    assert "Write" in tools
    assert "Bash" not in tools


def test_codex_app_server_maps_delta_and_uses_stdio() -> None:
    transport = CodexAppServerTransport("/bin/codex")
    assert transport.command() == ["/bin/codex", "app-server", "--listen", "stdio://"]
    event = transport.event({"method": "item/agentMessage/delta", "params": {"delta": "hello"}})
    assert event is not None
    assert event.type == AgentEventType.MESSAGE_DELTA
    assert event.text == "hello"


def test_bootstrap_marks_bundle_content_untrusted() -> None:
    prompt = bootstrap_prompt(SessionMode.FLEET_READ, ["one", "two"])
    assert "untrusted reference data" in prompt
    assert "strictly read-only" in prompt
