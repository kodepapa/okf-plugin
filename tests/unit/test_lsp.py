import io
import json
from pathlib import Path

from okfleet.lsp import LSPServer, document_links, read_message, write_message


def test_lsp_initialize_and_live_frontmatter_diagnostics(tmp_path: Path) -> None:
    server = LSPServer()
    response, _ = server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    assert response is not None
    assert response["result"]["serverInfo"]["name"] == "OKFleet"

    uri = (tmp_path / "metric.md").as_uri()
    _, notifications = server.handle(
        {
            "jsonrpc": "2.0",
            "method": "textDocument/didOpen",
            "params": {
                "textDocument": {
                    "uri": uri,
                    "text": "---\ntitle: Revenue\ndescription: Money\n---\n",
                }
            },
        }
    )
    diagnostics = notifications[0]["params"]["diagnostics"]
    assert diagnostics[0]["code"] == "OKF003"


def test_lsp_content_length_framing_roundtrip() -> None:
    stream = io.BytesIO()
    message = {"jsonrpc": "2.0", "id": 1, "method": "shutdown"}
    write_message(stream, message)
    stream.seek(0)
    assert read_message(stream) == message
    assert json.loads(json.dumps(message)) == message


def test_lsp_exposes_internal_markdown_links_for_navigation(tmp_path: Path) -> None:
    (tmp_path / "index.md").write_text("---\nokf_version: 0.5\n---\n", encoding="utf-8")
    source = tmp_path / "source.md"
    target = tmp_path / "target.md"
    target.write_text("# Target\n", encoding="utf-8")
    links = document_links(source.as_uri(), "See [target](target.md).")
    assert links[0]["target"] == target.as_uri()
