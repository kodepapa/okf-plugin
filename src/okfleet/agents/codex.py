from __future__ import annotations

import asyncio
import json
import os
import re
from collections.abc import AsyncIterator

from ..models import AgentEvent, AgentEventType, AgentSession, ProviderStatus, SessionMode
from .base import AgentProvider, ProviderError, bootstrap_prompt
from .codex_app_server import CodexAppServerTransport


class CodexProvider(AgentProvider):
    name = "codex"
    binary_name = "codex"

    async def probe(self) -> ProviderStatus:
        binary = self.binary_path()
        if not binary:
            return ProviderStatus(
                self.name, False, None, None, None, error="codex executable not found"
            )
        rc, stdout, stderr = await self.command_output(binary, "--version")
        auth_rc, _, _ = await self.command_output(binary, "login", "status")
        version = (stdout or stderr).strip() or None
        capabilities = ["jsonl", "resume", "read-only", "staged-write", "exec-fallback"]
        try:
            await CodexAppServerTransport(binary).probe()
        except (OSError, ProviderError, TimeoutError):
            pass
        else:
            capabilities.append("app-server")
        return ProviderStatus(
            self.name,
            rc == 0,
            binary,
            version,
            auth_rc == 0,
            tuple(capabilities),
            None if rc == 0 else stderr.strip(),
        )

    def _command(self, session: AgentSession, message: str) -> list[str]:
        binary = self.binary_path()
        if not binary:
            raise ProviderError("codex executable not found")
        sandbox = (
            "workspace-write" if session.mode == SessionMode.BUNDLE_WORK_STAGED else "read-only"
        )
        prompt = bootstrap_prompt(session.mode, session.scope) + "\n\nUser request:\n" + message
        # Parent exec options must precede the `resume` subcommand. In particular,
        # `resume` does not declare --sandbox or --cd itself in current Codex CLIs.
        base = [
            binary,
            "exec",
            "--json",
            "--skip-git-repo-check",
            "--sandbox",
            sandbox,
            "--cd",
            str(session.cwd),
        ]
        if session.native_id:
            base.extend(["resume", session.native_id])
        base.append(prompt)
        return base

    async def _send_exec(self, session: AgentSession, message: str) -> AsyncIterator[AgentEvent]:
        process = await asyncio.create_subprocess_exec(
            *self._command(session, message),
            cwd=session.cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        session.process = process
        assert process.stdout is not None
        async for raw in process.stdout:
            line = raw.decode(errors="replace").strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                yield AgentEvent(AgentEventType.ERROR, line, {"raw": True})
                continue
            event_type = record.get("type", "")
            if event_type == "thread.started":
                session.native_id = record.get("thread_id")
                yield AgentEvent(AgentEventType.SESSION_STARTED, data=record)
            elif event_type == "item.started":
                item = record.get("item", {})
                yield AgentEvent(AgentEventType.TOOL_STARTED, item.get("command", ""), item)
            elif event_type == "item.completed":
                item = record.get("item", {})
                if item.get("type") == "agent_message":
                    yield AgentEvent(AgentEventType.MESSAGE_COMPLETED, item.get("text", ""), item)
                elif item.get("type") == "file_change":
                    yield AgentEvent(AgentEventType.FILE_CHANGED, data=item)
                else:
                    yield AgentEvent(AgentEventType.TOOL_COMPLETED, item.get("command", ""), item)
            elif event_type == "turn.completed":
                if record.get("usage"):
                    yield AgentEvent(AgentEventType.USAGE, data=record["usage"])
                yield AgentEvent(AgentEventType.TURN_COMPLETED, data=record)
            elif event_type in {"turn.failed", "error"}:
                yield AgentEvent(
                    AgentEventType.TURN_FAILED, record.get("message", "Codex turn failed"), record
                )
            elif event_type.endswith(".delta"):
                text = str(record.get("delta") or record.get("text") or "")
                yield AgentEvent(AgentEventType.MESSAGE_DELTA, text, record)
        returncode = await process.wait()
        if returncode:
            assert process.stderr is not None
            stderr = (await process.stderr.read()).decode(errors="replace").strip()
            yield AgentEvent(
                AgentEventType.TURN_FAILED,
                re.sub(r"(?i)(api[_ -]?key\s*[=:]\s*)\S+", r"\1[redacted]", stderr),
                {"returncode": returncode},
            )

    async def send(self, session: AgentSession, message: str) -> AsyncIterator[AgentEvent]:
        protocol = os.environ.get("OKFLEET_CODEX_PROTOCOL", "app-server").casefold()
        if protocol != "exec":
            binary = self.binary_path()
            if not binary:
                raise ProviderError("codex executable not found")
            emitted = False
            try:
                async for event in CodexAppServerTransport(binary).run(session, message):
                    emitted = True
                    yield event
                return
            except (OSError, ProviderError) as exc:
                if emitted:
                    yield AgentEvent(AgentEventType.TURN_FAILED, str(exc))
                    return
                yield AgentEvent(
                    AgentEventType.ERROR,
                    f"Codex app-server unavailable; using exec fallback: {exc}",
                )
        async for event in self._send_exec(session, message):
            yield event
