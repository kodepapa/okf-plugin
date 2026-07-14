from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator
from pathlib import Path

from ..models import AgentEvent, AgentEventType, AgentSession, ProviderStatus, SessionMode
from .base import AgentProvider, ProviderError, bootstrap_prompt


class ClaudeProvider(AgentProvider):
    name = "claude"
    binary_name = "claude"

    def __init__(self, plugin_root: Path | None = None) -> None:
        self.plugin_root = plugin_root

    async def probe(self) -> ProviderStatus:
        binary = self.binary_path()
        if not binary:
            return ProviderStatus(
                self.name, False, None, None, None, error="claude executable not found"
            )
        rc, stdout, stderr = await self.command_output(binary, "--version")
        auth_rc, _, _ = await self.command_output(binary, "auth", "status")
        return ProviderStatus(
            self.name,
            rc == 0,
            binary,
            (stdout or stderr).strip() or None,
            auth_rc == 0,
            ("stream-json", "resume", "read-only", "staged-write", "plugin-dir"),
            None if rc == 0 else stderr.strip(),
        )

    def _command(self, session: AgentSession, message: str) -> list[str]:
        binary = self.binary_path()
        if not binary:
            raise ProviderError("claude executable not found")
        command = [
            binary,
            "-p",
            "--output-format",
            "stream-json",
            "--verbose",
            "--include-partial-messages",
            "--append-system-prompt",
            bootstrap_prompt(session.mode, session.scope),
        ]
        if session.native_id:
            command.extend(["--resume", session.native_id])
        if self.plugin_root and (self.plugin_root / ".claude-plugin").exists():
            command.extend(["--plugin-dir", str(self.plugin_root)])
        if session.mode == SessionMode.BUNDLE_WORK_STAGED:
            command.extend(
                ["--permission-mode", "acceptEdits", "--tools", "Read,Glob,Grep,Edit,Write"]
            )
        elif session.mode == SessionMode.FLEET_READ:
            # Fleet answers receive retrieved excerpts in the prompt. Disabling
            # tools prevents a cross-bundle chat from walking arbitrary paths.
            command.extend(["--permission-mode", "plan", "--tools", ""])
        else:
            command.extend(["--permission-mode", "plan", "--tools", "Read,Glob,Grep"])
        command.append(message)
        return command

    @staticmethod
    def _assistant_text(record: dict[str, object]) -> str:
        message = record.get("message")
        if not isinstance(message, dict):
            return ""
        content = message.get("content")
        if not isinstance(content, list):
            return ""
        return "".join(
            str(item.get("text", ""))
            for item in content
            if isinstance(item, dict) and item.get("type") == "text"
        )

    async def send(self, session: AgentSession, message: str) -> AsyncIterator[AgentEvent]:
        process = await asyncio.create_subprocess_exec(
            *self._command(session, message),
            cwd=session.cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        session.process = process
        assert process.stdout is not None
        saw_message_delta = False
        async for raw in process.stdout:
            line = raw.decode(errors="replace").strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                yield AgentEvent(AgentEventType.ERROR, line, {"raw": True})
                continue
            kind = record.get("type")
            if kind == "system" and record.get("subtype") == "init":
                session.native_id = str(record.get("session_id") or "") or session.native_id
                yield AgentEvent(AgentEventType.SESSION_STARTED, data=record)
            elif kind == "stream_event":
                event = record.get("event", {})
                if isinstance(event, dict):
                    delta = event.get("delta", {})
                    if isinstance(delta, dict) and delta.get("type") == "text_delta":
                        saw_message_delta = True
                        yield AgentEvent(
                            AgentEventType.MESSAGE_DELTA, str(delta.get("text", "")), record
                        )
            elif kind == "assistant":
                text = self._assistant_text(record)
                if text and not saw_message_delta:
                    yield AgentEvent(AgentEventType.MESSAGE_COMPLETED, text, record)
                message_record = record.get("message", {})
                if isinstance(message_record, dict):
                    for item in message_record.get("content", []):
                        if isinstance(item, dict) and item.get("type") == "tool_use":
                            yield AgentEvent(
                                AgentEventType.TOOL_STARTED, str(item.get("name", "")), item
                            )
            elif kind == "result":
                session.native_id = str(record.get("session_id") or "") or session.native_id
                if record.get("is_error"):
                    yield AgentEvent(
                        AgentEventType.TURN_FAILED, str(record.get("result", "")), record
                    )
                else:
                    yield AgentEvent(
                        AgentEventType.USAGE, data={"cost_usd": record.get("total_cost_usd")}
                    )
                    yield AgentEvent(
                        AgentEventType.TURN_COMPLETED, str(record.get("result", "")), record
                    )
        returncode = await process.wait()
        if returncode:
            assert process.stderr is not None
            stderr = (await process.stderr.read()).decode(errors="replace").strip()
            yield AgentEvent(
                AgentEventType.TURN_FAILED,
                re.sub(r"(?i)(api[_ -]?key\s*[=:]\s*)\S+", r"\1[redacted]", stderr),
                {"returncode": returncode},
            )
