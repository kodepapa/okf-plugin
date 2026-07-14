from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, BinaryIO, cast
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

from .core import load_bundle, parse_frontmatter, validate_bundle
from .models import Diagnostic, Severity

MARKDOWN_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


def uri_to_path(uri: str) -> Path:
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        raise ValueError("OKFleet LSP supports file:// documents only")
    return Path(url2pathname(unquote(parsed.path))).resolve()


def path_to_uri(path: Path) -> str:
    return path.resolve().as_uri()


def find_bundle_root(path: Path) -> Path | None:
    for parent in (path.parent, *path.parents):
        index = parent / "index.md"
        if not index.is_file():
            continue
        try:
            frontmatter, _ = parse_frontmatter(index.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if frontmatter and frontmatter.get("okf_version"):
            return parent
    return None


def document_diagnostics(path: Path, text: str) -> list[Diagnostic]:
    if path.name == "log.md":
        return []
    if path.name == "index.md":
        if path.parent.name and text.startswith("---"):
            root = find_bundle_root(path)
            if root is not None and path.parent != root:
                return [
                    Diagnostic(
                        "OKF004",
                        Severity.ERROR,
                        "frontmatter is only allowed in bundle-root index.md",
                        path,
                        1,
                    )
                ]
        return []
    try:
        frontmatter, _ = parse_frontmatter(text)
    except ValueError as exc:
        return [Diagnostic("OKF002", Severity.ERROR, str(exc), path, 1)]
    diagnostics: list[Diagnostic] = []
    if frontmatter is None:
        return [Diagnostic("OKF001", Severity.ERROR, "missing frontmatter block", path, 1)]
    if not str(frontmatter.get("type") or "").strip():
        diagnostics.append(
            Diagnostic("OKF003", Severity.ERROR, "missing or empty required field 'type'", path, 1)
        )
    if not str(frontmatter.get("description") or "").strip():
        diagnostics.append(
            Diagnostic(
                "OKF101",
                Severity.WARNING,
                "missing description used by indexes and search",
                path,
                1,
            )
        )
    return diagnostics


def lsp_diagnostic(diagnostic: Diagnostic) -> dict[str, Any]:
    severity = {Severity.ERROR: 1, Severity.WARNING: 2, Severity.INFO: 3}[diagnostic.severity]
    line = max(0, (diagnostic.line or 1) - 1)
    column = max(0, (diagnostic.column or 1) - 1)
    return {
        "range": {
            "start": {"line": line, "character": column},
            "end": {"line": line, "character": column + 1},
        },
        "severity": severity,
        "code": diagnostic.code,
        "source": "okfleet",
        "message": diagnostic.message,
    }


def _position(text: str, offset: int) -> dict[str, int]:
    prefix = text[:offset]
    line = prefix.count("\n")
    newline = prefix.rfind("\n")
    return {"line": line, "character": offset if newline < 0 else offset - newline - 1}


def document_links(uri: str, text: str) -> list[dict[str, Any]]:
    path = uri_to_path(uri)
    root = find_bundle_root(path) or path.parent
    links: list[dict[str, Any]] = []
    for match in MARKDOWN_LINK_RE.finditer(text):
        raw = match.group(1).strip().split(maxsplit=1)[0].strip("<>")
        target = raw.split("#", 1)[0]
        if not target or "://" in target or target.startswith("mailto:"):
            continue
        resolved = (path.parent / unquote(target)).resolve()
        if not resolved.is_relative_to(root) or not resolved.is_file():
            continue
        links.append(
            {
                "range": {
                    "start": _position(text, match.start(1)),
                    "end": _position(text, match.end(1)),
                },
                "target": path_to_uri(resolved),
            }
        )
    return links


def publish(uri: str, diagnostics: list[Diagnostic]) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "method": "textDocument/publishDiagnostics",
        "params": {"uri": uri, "diagnostics": [lsp_diagnostic(item) for item in diagnostics]},
    }


class LSPServer:
    def __init__(self) -> None:
        self.documents: dict[str, str] = {}
        self.shutdown_requested = False
        self.exit_requested = False

    def _response(self, message: dict[str, Any], result: object) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": message["id"], "result": result}

    def _bundle_notifications(self, root: Path) -> list[dict[str, Any]]:
        grouped: defaultdict[Path, list[Diagnostic]] = defaultdict(list)
        try:
            bundle = load_bundle(root)
            for diagnostic in validate_bundle(bundle):
                grouped[diagnostic.path].append(diagnostic)
        except (OSError, ValueError):
            return []
        paths = set(grouped)
        paths.update(
            uri_to_path(uri) for uri in self.documents if find_bundle_root(uri_to_path(uri)) == root
        )
        return [publish(path_to_uri(path), grouped[path]) for path in sorted(paths)]

    def handle(self, message: dict[str, Any]) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        method = message.get("method")
        params = message.get("params") or {}
        notifications: list[dict[str, Any]] = []
        if method == "initialize":
            result = {
                "serverInfo": {"name": "OKFleet", "version": "0.5.0"},
                "capabilities": {
                    "textDocumentSync": {
                        "openClose": True,
                        "change": 1,
                        "save": {"includeText": True},
                    },
                    "documentLinkProvider": {"resolveProvider": False},
                    "definitionProvider": True,
                },
            }
            return self._response(message, result), notifications
        if method == "shutdown":
            self.shutdown_requested = True
            return self._response(message, None), notifications
        if method == "exit":
            self.exit_requested = True
            return None, notifications
        if method == "textDocument/documentLink":
            uri = str(params["textDocument"]["uri"])
            text = self.documents.get(uri)
            if text is None:
                try:
                    text = uri_to_path(uri).read_text(encoding="utf-8")
                except OSError:
                    text = ""
            return self._response(message, document_links(uri, text)), notifications
        if method == "textDocument/definition":
            uri = str(params["textDocument"]["uri"])
            text = self.documents.get(uri, "")
            position = params.get("position") or {}
            locations = []
            for link in document_links(uri, text):
                start, end = link["range"]["start"], link["range"]["end"]
                if (
                    int(position.get("line", -1)) == start["line"]
                    and start["character"] <= int(position.get("character", -1)) <= end["character"]
                ):
                    locations.append(
                        {
                            "uri": link["target"],
                            "range": {
                                "start": {"line": 0, "character": 0},
                                "end": {"line": 0, "character": 0},
                            },
                        }
                    )
            return self._response(message, locations or None), notifications
        if method in {"textDocument/didOpen", "textDocument/didChange"}:
            document = params["textDocument"]
            uri = str(document["uri"])
            if method == "textDocument/didOpen":
                text = str(document.get("text") or "")
            else:
                changes = params.get("contentChanges") or []
                text = (
                    str(changes[-1].get("text") or "") if changes else self.documents.get(uri, "")
                )
            self.documents[uri] = text
            notifications.append(publish(uri, document_diagnostics(uri_to_path(uri), text)))
        elif method == "textDocument/didSave":
            document = params["textDocument"]
            uri = str(document["uri"])
            if "text" in params:
                self.documents[uri] = str(params["text"])
            root = find_bundle_root(uri_to_path(uri))
            if root is not None:
                notifications.extend(self._bundle_notifications(root))
            else:
                notifications.append(
                    publish(
                        uri, document_diagnostics(uri_to_path(uri), self.documents.get(uri, ""))
                    )
                )
        elif method == "textDocument/didClose":
            uri = str(params["textDocument"]["uri"])
            self.documents.pop(uri, None)
            notifications.append(publish(uri, []))
        elif "id" in message:
            return self._response(message, None), notifications
        return None, notifications


def read_message(stream: BinaryIO) -> dict[str, Any] | None:
    headers: dict[str, str] = {}
    while True:
        line = stream.readline()
        if not line:
            return None
        if line in {b"\r\n", b"\n"}:
            break
        key, _, value = line.decode("ascii").partition(":")
        headers[key.casefold()] = value.strip()
    length = int(headers.get("content-length", "0"))
    if length <= 0:
        return None
    return cast(dict[str, Any], json.loads(stream.read(length).decode("utf-8")))


def write_message(stream: BinaryIO, message: dict[str, Any]) -> None:
    body = json.dumps(message, separators=(",", ":")).encode()
    stream.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii"))
    stream.write(body)
    stream.flush()


def run_lsp(input_stream: BinaryIO | None = None, output_stream: BinaryIO | None = None) -> None:
    input_stream = input_stream or sys.stdin.buffer
    output_stream = output_stream or sys.stdout.buffer
    server = LSPServer()
    while not server.exit_requested:
        message = read_message(input_stream)
        if message is None:
            break
        response, notifications = server.handle(message)
        if response is not None:
            write_message(output_stream, response)
        for notification in notifications:
            write_message(output_stream, notification)
