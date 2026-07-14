from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from .. import __version__
from ..models import AgentEvent, AgentEventType, AgentSession, SessionMode
from .base import ProviderError, bootstrap_prompt


class CodexAppServerTransport:
    """Minimal JSON-RPC client for Codex's experimental stdio app-server.

    OKFleet deliberately uses only the stable thread/turn subset. Every thread is
    sandboxed, approval requests are disabled, and the process is short-lived;
    provider-native thread IDs still make later turns resumable.
    """

    def __init__(self, binary: str) -> None:
        self.binary = binary
        self._next_id = 1

    def command(self) -> list[str]:
        return [self.binary, "app-server", "--listen", "stdio://"]

    async def probe(self) -> None:
        """Verify the JSON-RPC handshake without starting a model turn."""
        process = await asyncio.create_subprocess_exec(
            *self.command(),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            await asyncio.wait_for(
                self._request(
                    process,
                    "initialize",
                    {
                        "clientInfo": {
                            "name": "okfleet",
                            "title": "OKFleet",
                            "version": __version__,
                        },
                        "capabilities": {"experimentalApi": False},
                    },
                ),
                timeout=5,
            )
            await self._write(process, {"jsonrpc": "2.0", "method": "initialized"})
        finally:
            if process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=3)
                except TimeoutError:
                    process.kill()
                    await process.wait()

    async def _write(self, process: asyncio.subprocess.Process, record: dict[str, Any]) -> None:
        if process.stdin is None:
            raise ProviderError("Codex app-server stdin is unavailable")
        process.stdin.write((json.dumps(record, separators=(",", ":")) + "\n").encode())
        await process.stdin.drain()

    async def _request(
        self,
        process: asyncio.subprocess.Process,
        method: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        request_id = self._next_id
        self._next_id += 1
        await self._write(
            process,
            {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params},
        )
        if process.stdout is None:
            raise ProviderError("Codex app-server stdout is unavailable")
        while raw := await process.stdout.readline():
            try:
                record = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if record.get("id") != request_id:
                continue
            if "error" in record:
                error = record.get("error") or {}
                message = (
                    error.get("message", str(error)) if isinstance(error, dict) else str(error)
                )
                raise ProviderError(f"Codex app-server {method} failed: {message}")
            result = record.get("result")
            return result if isinstance(result, dict) else {}
        raise ProviderError(f"Codex app-server closed during {method}")

    @staticmethod
    def event(record: dict[str, Any]) -> AgentEvent | None:
        method = str(record.get("method") or "")
        params = record.get("params")
        data = params if isinstance(params, dict) else {}
        if method == "item/agentMessage/delta":
            return AgentEvent(AgentEventType.MESSAGE_DELTA, str(data.get("delta") or ""), data)
        if method == "item/completed":
            item = data.get("item")
            item = item if isinstance(item, dict) else data
            kind = str(item.get("type") or "")
            if kind in {"agentMessage", "agent_message"}:
                text = str(item.get("text") or item.get("message") or "")
                return AgentEvent(AgentEventType.MESSAGE_COMPLETED, text, item)
            if kind in {"fileChange", "file_change"}:
                return AgentEvent(AgentEventType.FILE_CHANGED, data=item)
            return AgentEvent(AgentEventType.TOOL_COMPLETED, str(item.get("name") or ""), item)
        if method == "item/started":
            item = data.get("item")
            item = item if isinstance(item, dict) else data
            return AgentEvent(AgentEventType.TOOL_STARTED, str(item.get("name") or ""), item)
        if method == "turn/diff/updated":
            return AgentEvent(AgentEventType.FILE_CHANGED, str(data.get("diff") or ""), data)
        if method == "turn/completed":
            turn = data.get("turn")
            turn = turn if isinstance(turn, dict) else data
            status = str(turn.get("status") or "completed")
            if status in {"failed", "cancelled", "interrupted"}:
                error = turn.get("error")
                return AgentEvent(AgentEventType.TURN_FAILED, str(error or status), data)
            return AgentEvent(AgentEventType.TURN_COMPLETED, data=data)
        if method in {"error", "turn/failed"}:
            return AgentEvent(
                AgentEventType.TURN_FAILED,
                str(data.get("message") or data.get("error") or "Codex turn failed"),
                data,
            )
        return None

    async def run(self, session: AgentSession, message: str) -> AsyncIterator[AgentEvent]:
        process = await asyncio.create_subprocess_exec(
            *self.command(),
            cwd=session.cwd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        session.process = process
        sandbox = (
            "workspace-write" if session.mode == SessionMode.BUNDLE_WORK_STAGED else "read-only"
        )
        try:
            await self._request(
                process,
                "initialize",
                {
                    "clientInfo": {"name": "okfleet", "title": "OKFleet", "version": __version__},
                    "capabilities": {"experimentalApi": False},
                },
            )
            await self._write(process, {"jsonrpc": "2.0", "method": "initialized"})
            thread_params: dict[str, Any] = {
                "cwd": str(session.cwd),
                "sandbox": sandbox,
                "approvalPolicy": "never",
                "developerInstructions": bootstrap_prompt(session.mode, session.scope),
            }
            if session.native_id:
                thread_params["threadId"] = session.native_id
                thread = await self._request(process, "thread/resume", thread_params)
            else:
                thread = await self._request(process, "thread/start", thread_params)
            thread_record = thread.get("thread")
            thread_record = thread_record if isinstance(thread_record, dict) else {}
            thread_id = str(thread_record.get("id") or session.native_id or "")
            if not thread_id:
                raise ProviderError("Codex app-server did not return a thread ID")
            session.native_id = thread_id
            yield AgentEvent(AgentEventType.SESSION_STARTED, data={"thread_id": thread_id})

            prompt = bootstrap_prompt(session.mode, session.scope) + "\n\nUser request:\n" + message
            await self._request(
                process,
                "turn/start",
                {
                    "threadId": thread_id,
                    "input": [{"type": "text", "text": prompt}],
                    "cwd": str(session.cwd),
                },
            )
            if process.stdout is None:
                raise ProviderError("Codex app-server stdout is unavailable")
            saw_message_delta = False
            while raw := await process.stdout.readline():
                try:
                    record = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                # With approvalPolicy=never these should not occur. If a newer
                # server asks anyway, reject without widening authority.
                if "id" in record and "method" in record:
                    await self._write(
                        process,
                        {
                            "jsonrpc": "2.0",
                            "id": record["id"],
                            "error": {"code": -32000, "message": "OKFleet denies approvals"},
                        },
                    )
                    continue
                event = self.event(record)
                if event:
                    if event.type == AgentEventType.MESSAGE_DELTA:
                        saw_message_delta = True
                    elif event.type == AgentEventType.MESSAGE_COMPLETED and saw_message_delta:
                        continue
                    yield event
                    if event.type in {AgentEventType.TURN_COMPLETED, AgentEventType.TURN_FAILED}:
                        break
        finally:
            if process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=3)
                except TimeoutError:
                    process.kill()
                    await process.wait()
