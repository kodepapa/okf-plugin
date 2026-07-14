import io
import json
from pathlib import Path

from okfleet.registry import BundleRegistry
from okfleet.search import SearchDatabase
from okfleet.web import OKFleetHTTPRequestHandler, WebService, is_loopback_host


def test_web_service_exposes_read_only_fleet_data(bundle_path: Path, tmp_path: Path) -> None:
    registry = BundleRegistry(tmp_path / "config.toml")
    registry.add(bundle_path, "finance")
    database = SearchDatabase(tmp_path / "search.sqlite3")
    service = WebService(registry, database)

    bundles = service.bundles()
    assert bundles[0]["alias"] == "finance"
    assert bundles[0]["concepts"] == 2
    hits = service.search("revenue", "finance")
    assert hits[0]["citation"] == "finance:metrics/revenue"
    concept = service.concept("finance", "metrics/revenue")
    assert concept["type"] == "Metric"
    assert "source" in concept

    database.close()


def test_web_requires_explicit_opt_in_for_remote_binding() -> None:
    assert is_loopback_host("127.0.0.1")
    assert is_loopback_host("::1")
    assert is_loopback_host("localhost")
    assert not is_loopback_host("0.0.0.0")


def test_web_http_api_serves_bundle_inventory(bundle_path: Path, tmp_path: Path) -> None:
    registry = BundleRegistry(tmp_path / "config.toml")
    registry.add(bundle_path, "finance")
    database = SearchDatabase(tmp_path / "search.sqlite3")
    service = WebService(registry, database)

    class Handler(OKFleetHTTPRequestHandler):
        pass

    class Request:
        def __init__(self, target: str) -> None:
            self.input = io.BytesIO(f"GET {target} HTTP/1.1\r\nHost: localhost\r\n\r\n".encode())
            self.output = bytearray()

        def makefile(self, mode: str, buffering: int = -1) -> io.BytesIO:
            return self.input

        def sendall(self, data: bytes) -> None:
            self.output.extend(data)

    Handler.service = service
    request = Request("/api/bundles")
    try:
        Handler(request, ("127.0.0.1", 12345), None)  # type: ignore[arg-type]
        headers, body = bytes(request.output).split(b"\r\n\r\n", 1)
        payload = json.loads(body)
        assert payload[0]["alias"] == "finance"
        assert b"Cache-Control: no-store" in headers

        concept_request = Request("/api/concepts/finance/metrics/revenue")
        Handler(concept_request, ("127.0.0.1", 12345), None)  # type: ignore[arg-type]
        _, concept_body = bytes(concept_request.output).split(b"\r\n\r\n", 1)
        assert json.loads(concept_body)["citation"] == "finance:metrics/revenue"
    finally:
        database.close()
