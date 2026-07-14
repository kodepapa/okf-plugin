from __future__ import annotations

import ipaddress
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from .core import load_bundle, validate_bundle
from .models import BundleRef
from .registry import BundleRegistry, discover_bundles
from .search import SearchDatabase

INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>OKFleet Web</title>
  <style>
    :root{color-scheme:dark;--bg:#091414;--panel:#102222;--line:#244141;--ink:#e8fbf5;--muted:#8fb5ad;--hot:#63e6be}
    *{box-sizing:border-box} body{margin:0;background:var(--bg);color:var(--ink);font:15px ui-monospace,SFMono-Regular,Menlo,monospace}
    header{display:flex;gap:1rem;align-items:center;padding:1rem 1.3rem;border-bottom:1px solid var(--line)}
    h1{font-size:1.1rem;margin:0;color:var(--hot)} input,select{background:#071010;color:var(--ink);border:1px solid var(--line);padding:.65rem;border-radius:.35rem}
    input{flex:1}.layout{display:grid;grid-template-columns:15rem 22rem 1fr;height:calc(100vh - 66px)}
    aside,section,main{overflow:auto;padding:1rem;border-right:1px solid var(--line)} button,.hit{display:block;width:100%;text-align:left;color:var(--ink);background:transparent;border:0;border-bottom:1px solid var(--line);padding:.65rem;cursor:pointer}
    button:hover,.hit:hover{background:var(--panel)} .type,.citation{color:var(--hot);font-size:.8rem}.muted{color:var(--muted)} pre{white-space:pre-wrap;line-height:1.55;font-family:inherit}
    @media(max-width:850px){.layout{grid-template-columns:1fr;height:auto}aside,section,main{border-right:0;border-bottom:1px solid var(--line);max-height:40vh}}
  </style>
</head>
<body>
<header><h1>OKFleet</h1><select id="bundle"><option value="">Entire fleet</option></select><input id="query" placeholder="Search knowledge…  type:Metric tag:pii"></header>
<div class="layout"><aside><div class="muted">BUNDLES</div><div id="bundles"></div></aside><section><div class="muted">RESULTS</div><div id="results"></div></section><main id="concept"><p class="muted">Select a concept to inspect its source.</p></main></div>
<script>
const el=id=>document.getElementById(id), esc=encodeURIComponent;
async function bundles(){const xs=await fetch('/api/bundles').then(r=>r.json());for(const x of xs){const b=document.createElement('button');b.textContent=`${x.alias} · ${x.concepts} concepts`;b.onclick=()=>{el('bundle').value=x.alias;search()};el('bundles').append(b);const o=document.createElement('option');o.value=x.alias;o.textContent=x.alias;el('bundle').append(o)}}
async function search(){const q=esc(el('query').value),b=esc(el('bundle').value);const xs=await fetch(`/api/search?q=${q}&bundle=${b}`).then(r=>r.json());el('results').replaceChildren();for(const x of xs){const row=document.createElement('button');row.className='hit';const title=document.createElement('div');title.textContent=x.title;const meta=document.createElement('div');meta.className='type';meta.textContent=`${x.concept_type} · ${x.citation}`;row.append(title,meta);row.onclick=()=>show(x.bundle_alias,x.concept_id);el('results').append(row)}}
async function show(alias,id){const path=id.split('/').map(esc).join('/');const x=await fetch(`/api/concepts/${esc(alias)}/${path}`).then(r=>r.json());const h=document.createElement('h2');h.textContent=x.title;const c=document.createElement('div');c.className='citation';c.textContent=x.citation;const d=document.createElement('p');d.textContent=x.description;const pre=document.createElement('pre');pre.textContent=x.source;el('concept').replaceChildren(h,c,d,pre)}
let timer;el('query').addEventListener('input',()=>{clearTimeout(timer);timer=setTimeout(search,120)});el('bundle').addEventListener('change',search);bundles().then(search);
</script>
</body></html>"""


class WebService:
    """Read-only application service shared by HTTP handlers and tests."""

    def __init__(
        self,
        registry: BundleRegistry | None = None,
        database: SearchDatabase | None = None,
        *,
        local_root: Path | None = None,
    ) -> None:
        self.registry = registry or BundleRegistry()
        self.database = database or SearchDatabase()
        self._owns_database = database is None
        self.local_root = local_root
        self.refs: dict[str, BundleRef] = {}
        self.refresh()

    def close(self) -> None:
        if self._owns_database:
            self.database.close()

    def refresh(self) -> None:
        candidates = list(self.registry.list())
        if self.local_root is not None:
            candidates.extend(discover_bundles(self.local_root))
        seen_paths: set[str] = set()
        self.refs = {}
        for ref in candidates:
            key = str(ref.path.expanduser().resolve())
            if not ref.available or key in seen_paths:
                continue
            try:
                bundle = load_bundle(ref.path)
                self.database.index_bundle(ref, bundle)
            except (OSError, ValueError):
                continue
            seen_paths.add(key)
            self.refs.setdefault(ref.alias, ref)

    def bundles(self) -> list[dict[str, Any]]:
        payload: list[dict[str, Any]] = []
        for ref in sorted(self.refs.values(), key=lambda item: item.alias.casefold()):
            bundle = load_bundle(ref.path)
            diagnostics = validate_bundle(bundle)
            item = ref.to_dict()
            item.update(
                concepts=len(bundle.concepts),
                diagnostics=len(diagnostics),
                version=bundle.version,
            )
            payload.append(item)
        return payload

    def search(self, query: str, bundle_alias: str | None = None) -> list[dict[str, Any]]:
        bundle_ids: list[str] | None = None
        if bundle_alias:
            ref = self.refs.get(bundle_alias)
            if ref is None:
                raise KeyError(bundle_alias)
            bundle_ids = [ref.id]
        return [
            hit.to_dict() for hit in self.database.search(query, bundle_ids=bundle_ids, limit=100)
        ]

    def concept(self, bundle_alias: str, concept_id: str) -> dict[str, Any]:
        ref = self.refs.get(bundle_alias)
        if ref is None:
            raise KeyError(bundle_alias)
        concept = load_bundle(ref.path).get(concept_id)
        if concept is None:
            raise KeyError(concept_id)
        payload = concept.summary_dict(ref.alias)
        payload.update(
            source=concept.source,
            body=concept.body,
            frontmatter=concept.frontmatter,
            links=[link.to_dict() for link in concept.links],
        )
        return payload

    def health(self, bundle_alias: str) -> list[dict[str, Any]]:
        ref = self.refs.get(bundle_alias)
        if ref is None:
            raise KeyError(bundle_alias)
        bundle = load_bundle(ref.path)
        return [item.to_dict(bundle.root) for item in validate_bundle(bundle, include_health=True)]


class OKFleetHTTPRequestHandler(BaseHTTPRequestHandler):
    service: WebService
    server_version = "OKFleetWeb/0.5"

    def _send(self, status: HTTPStatus, payload: object, content_type: str) -> None:
        if content_type == "application/json":
            body = json.dumps(payload, ensure_ascii=False, default=str).encode()
        else:
            body = str(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'unsafe-inline'; script-src 'unsafe-inline'",
        )
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        self._send(status, payload, "application/json")

    def do_GET(self) -> None:
        target = urlparse(self.path)
        query = parse_qs(target.query)
        try:
            if target.path == "/":
                self._send(HTTPStatus.OK, INDEX_HTML, "text/html")
            elif target.path == "/api/bundles":
                self._json(self.service.bundles())
            elif target.path == "/api/search":
                self._json(
                    self.service.search(
                        query.get("q", [""])[0], query.get("bundle", [""])[0] or None
                    )
                )
            elif target.path.startswith("/api/concepts/"):
                alias, concept_id = unquote(target.path.removeprefix("/api/concepts/")).split(
                    "/", 1
                )
                self._json(self.service.concept(alias, concept_id))
            elif target.path.startswith("/api/health/"):
                self._json(self.service.health(unquote(target.path.removeprefix("/api/health/"))))
            else:
                self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
        except (KeyError, ValueError) as exc:
            self._json({"error": str(exc)}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        self._json({"error": "OKFleet Web is read-only"}, HTTPStatus.METHOD_NOT_ALLOWED)

    def log_message(self, format: str, *args: object) -> None:
        return


def is_loopback_host(host: str) -> bool:
    if host.casefold() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


def serve_web(
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    local_root: Path | None = None,
    allow_remote: bool = False,
) -> None:
    if not allow_remote and not is_loopback_host(host):
        raise ValueError("non-loopback binding requires --allow-remote")
    service = WebService(local_root=local_root)

    class Handler(OKFleetHTTPRequestHandler):
        pass

    Handler.service = service
    server = ThreadingHTTPServer((host, port), Handler)
    try:
        print(f"OKFleet Web listening on http://{host}:{server.server_port}")
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        service.close()
