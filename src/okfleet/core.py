from __future__ import annotations

import difflib
import hashlib
import html
import io
import json
import os
import re
import stat
import tempfile
from collections import defaultdict, deque
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote, urlsplit

from ruamel.yaml import YAML

from .models import Bundle, Concept, ConceptLink, Diagnostic, Severity

RESERVED = {"index.md", "log.md"}
FRONTMATTER_RE = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*\r?\n?(.*)\Z", re.S)
LINK_RE = re.compile(r"(?<!!)\[([^\]]*)\]\(([^)\s]+)(?:\s+[\"'][^\"']*[\"'])?\)")
FENCE_RE = re.compile(r"^(```|~~~).*?^\1\s*$", re.M | re.S)
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
EXCLUDED_DIRS = {".git", ".hg", ".svn", ".venv", "venv", "node_modules", "dist", "build"}


def content_hash(data: str | bytes) -> str:
    raw = data.encode("utf-8") if isinstance(data, str) else data
    return hashlib.sha256(raw).hexdigest()


def _yaml() -> YAML:
    yaml = YAML(typ="rt")
    yaml.preserve_quotes = True
    yaml.default_flow_style = False
    yaml.width = 1000
    return yaml


def parse_frontmatter(text: str) -> tuple[dict[str, Any] | None, str]:
    if not text.startswith("---"):
        return None, text
    match = FRONTMATTER_RE.match(text)
    if not match:
        raise ValueError("unterminated frontmatter block")
    loaded = _yaml().load(match.group(1))
    if loaded is not None and not isinstance(loaded, dict):
        raise ValueError("frontmatter is not a YAML mapping")
    return dict(loaded or {}), match.group(2)


def render_concept(frontmatter: dict[str, Any], body: str) -> str:
    stream = io.StringIO()
    _yaml().dump(frontmatter, stream)
    normalized_body = body.lstrip("\r\n")
    return f"---\n{stream.getvalue()}---\n\n{normalized_body}".rstrip() + "\n"


def read_bytes_nofollow(path: Path) -> bytes:
    """Read a regular file without dereferencing a leaf symlink."""
    if path.is_symlink():
        raise OSError(f"refusing to read symlink: {path}")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError(f"refusing to read non-regular file: {path}")
        with os.fdopen(fd, "rb") as handle:
            fd = -1
            return handle.read()
    finally:
        if fd >= 0:
            os.close(fd)


def read_text_nofollow(path: Path) -> str:
    """Read a regular UTF-8 file without dereferencing a leaf symlink."""
    return read_bytes_nofollow(path).decode("utf-8")


def concept_id(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix().removesuffix(".md")


def iter_markdown(root: Path, *, include_hidden: bool = False) -> Iterable[Path]:
    root = root.resolve()
    for directory, names, files in os.walk(root, followlinks=False):
        current = Path(directory)
        names[:] = sorted(
            name
            for name in names
            if name not in EXCLUDED_DIRS
            and (include_hidden or not name.startswith("."))
            and not (current / name).is_symlink()
        )
        for name in sorted(files):
            path = current / name
            if (
                name.endswith(".md")
                and (include_hidden or not name.startswith("."))
                and not path.is_symlink()
            ):
                yield path


def parse_concept(root: Path, path: Path) -> Concept:
    root = root.resolve()
    path = path.parent.resolve() / path.name
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"concept path escapes bundle root: {path}") from exc
    try:
        source = read_text_nofollow(path)
    except UnicodeDecodeError as exc:
        return Concept(root, path, concept_id(root, path), None, "", "", "", str(exc))
    try:
        frontmatter, body = parse_frontmatter(source)
        return Concept(
            root,
            path,
            concept_id(root, path),
            frontmatter,
            body,
            source,
            content_hash(source),
        )
    except Exception as exc:
        return Concept(
            root,
            path,
            concept_id(root, path),
            None,
            "",
            source,
            content_hash(source),
            str(exc),
        )


def _line_for_offset(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _resolve_link(
    root: Path, source: Path, raw_target: str
) -> tuple[Path | None, str | None, bool]:
    target = unquote(urlsplit(raw_target).path)
    if not target:
        return None, None, True
    candidate = root / target.lstrip("/") if target.startswith("/") else source.parent / target
    try:
        resolved = candidate.resolve()
        resolved.relative_to(root)
    except (OSError, ValueError):
        return None, None, False
    target_id: str | None = None
    if resolved.suffix.lower() == ".md" and resolved.name not in RESERVED:
        target_id = concept_id(root, resolved)
    return resolved, target_id, resolved.exists()


def extract_links(concept: Concept) -> list[ConceptLink]:
    scrubbed = FENCE_RE.sub(lambda match: "\n" * match.group(0).count("\n"), concept.body)
    links: list[ConceptLink] = []
    for match in LINK_RE.finditer(scrubbed):
        label, target = match.group(1), match.group(2)
        split = urlsplit(target)
        if split.scheme or target.startswith(("mailto:", "tel:", "#")):
            continue
        resolved, target_id, exists = _resolve_link(concept.bundle_root, concept.path, target)
        line_start = scrubbed.rfind("\n", 0, match.start()) + 1
        line_end = scrubbed.find("\n", match.end())
        if line_end < 0:
            line_end = len(scrubbed)
        links.append(
            ConceptLink(
                source_id=concept.concept_id,
                raw_target=target,
                target_id=target_id,
                resolved_path=resolved,
                exists=exists,
                line=_line_for_offset(scrubbed, match.start()),
                label=label,
                context=scrubbed[line_start:line_end].strip(),
            )
        )
    return links


def load_bundle(path: Path) -> Bundle:
    root = path.expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"bundle directory does not exist: {root}")
    concepts: dict[str, Concept] = {}
    indexes: list[Path] = []
    logs: list[Path] = []
    for markdown in iter_markdown(root):
        if markdown.name == "index.md":
            indexes.append(markdown)
        elif markdown.name == "log.md":
            logs.append(markdown)
        else:
            concept = parse_concept(root, markdown)
            concept.links = extract_links(concept)
            concepts[concept.concept_id] = concept
    version = None
    root_index = root / "index.md"
    try:
        fm, _ = parse_frontmatter(read_text_nofollow(root_index))
        version = str((fm or {}).get("okf_version") or "") or None
    except (OSError, ValueError):
        pass
    return Bundle(root=root, concepts=concepts, indexes=indexes, logs=logs, version=version)


def inbound_links(bundle: Bundle) -> dict[str, list[ConceptLink]]:
    inbound: dict[str, list[ConceptLink]] = defaultdict(list)
    for concept in bundle.concepts.values():
        for link in concept.links:
            if link.target_id:
                inbound[link.target_id].append(link)
    return dict(inbound)


def validate_bundle(
    bundle: Bundle,
    *,
    include_health: bool = False,
    stale_after_days: int | None = None,
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    inbound = inbound_links(bundle)
    for concept in bundle.concepts.values():
        if concept.parse_error:
            diagnostics.append(
                Diagnostic("OKF002", Severity.ERROR, concept.parse_error, concept.path, 1)
            )
            continue
        if concept.frontmatter is None:
            diagnostics.append(
                Diagnostic("OKF001", Severity.ERROR, "missing frontmatter block", concept.path, 1)
            )
            continue
        if not str(concept.frontmatter.get("type") or "").strip():
            diagnostics.append(
                Diagnostic(
                    "OKF003",
                    Severity.ERROR,
                    "missing or empty required field 'type'",
                    concept.path,
                    1,
                )
            )
        if not concept.description.strip():
            diagnostics.append(
                Diagnostic(
                    "OKF101",
                    Severity.WARNING,
                    "missing description used by indexes and search",
                    concept.path,
                    1,
                )
            )
        for link in concept.links:
            if not link.exists:
                diagnostics.append(
                    Diagnostic(
                        "OKF102",
                        Severity.WARNING,
                        f"broken or escaping internal link: {link.raw_target}",
                        concept.path,
                        link.line,
                    )
                )
        if include_health and not concept.links and not inbound.get(concept.concept_id):
            diagnostics.append(
                Diagnostic(
                    "OKF202",
                    Severity.INFO,
                    "concept has no inbound or outbound concept links",
                    concept.path,
                )
            )
        if include_health and stale_after_days:
            raw_timestamp = concept.frontmatter.get("timestamp")
            if raw_timestamp:
                try:
                    timestamp = datetime.fromisoformat(str(raw_timestamp).replace("Z", "+00:00"))
                    if timestamp.tzinfo is None:
                        timestamp = timestamp.replace(tzinfo=UTC)
                    age = (datetime.now(UTC) - timestamp).days
                    if age > stale_after_days:
                        diagnostics.append(
                            Diagnostic(
                                "OKF201",
                                Severity.INFO,
                                f"concept is {age} days old (threshold {stale_after_days})",
                                concept.path,
                            )
                        )
                except ValueError:
                    diagnostics.append(
                        Diagnostic(
                            "OKF204", Severity.INFO, "timestamp is not ISO 8601", concept.path, 1
                        )
                    )
    for index_path in bundle.indexes:
        try:
            text = read_text_nofollow(index_path)
        except (OSError, UnicodeDecodeError) as exc:
            diagnostics.append(Diagnostic("OKF005", Severity.ERROR, str(exc), index_path, 1))
            continue
        if index_path.parent != bundle.root and text.startswith("---"):
            diagnostics.append(
                Diagnostic(
                    "OKF004",
                    Severity.ERROR,
                    "frontmatter is only allowed in bundle-root index.md",
                    index_path,
                    1,
                )
            )
    for log_path in bundle.logs:
        try:
            text = read_text_nofollow(log_path)
        except (OSError, UnicodeDecodeError) as exc:
            diagnostics.append(Diagnostic("OKF005", Severity.ERROR, str(exc), log_path, 1))
            continue
        for match in re.finditer(r"^##\s+(.+)$", text, re.M):
            heading = match.group(1).strip()
            if not DATE_RE.match(heading):
                diagnostics.append(
                    Diagnostic(
                        "OKF103",
                        Severity.WARNING,
                        f"log heading is not ISO YYYY-MM-DD: {heading}",
                        log_path,
                        _line_for_offset(text, match.start()),
                    )
                )
    return sorted(diagnostics, key=lambda d: (str(d.path), d.line or 0, d.code))


def _entry_line(concept: Concept) -> str:
    suffix = f" - {concept.description.strip()}" if concept.description.strip() else ""
    return f"* [{concept.title}]({concept.path.name}){suffix}"


def build_directory_index(bundle: Bundle, directory: Path) -> str:
    groups: dict[str, list[str]] = defaultdict(list)
    for concept in sorted(bundle.concepts.values(), key=lambda c: c.path.name.lower()):
        if concept.path.parent == directory:
            groups[concept.concept_type or "Concepts"].append(_entry_line(concept))
    subdirs: list[str] = []
    direct_children = sorted(
        {
            concept.path.relative_to(directory).parts[0]
            for concept in bundle.concepts.values()
            if concept.path.parent != directory and directory in concept.path.parents
        }
    )
    existing_descriptions: dict[str, str] = {}
    index_path = directory / "index.md"
    try:
        existing = read_text_nofollow(index_path)
        for match in re.finditer(r"^\*\s*\[[^\]]*\]\(([^)]+)\)\s*(?:-\s*(.*))?$", existing, re.M):
            if match.group(2):
                existing_descriptions[match.group(1)] = match.group(2).strip()
    except (OSError, UnicodeDecodeError):
        pass
    for name in direct_children:
        url = f"{name}/index.md"
        suffix = f" - {existing_descriptions[url]}" if url in existing_descriptions else ""
        subdirs.append(f"* [{name}]({url}){suffix}")
    sections: list[str] = []
    if subdirs:
        sections.append("# Subdirectories\n\n" + "\n".join(subdirs))
    for concept_type in sorted(groups, key=str.casefold):
        sections.append(f"# {concept_type}\n\n" + "\n".join(groups[concept_type]))
    body = "\n\n".join(sections) + ("\n" if sections else "")
    if directory == bundle.root:
        try:
            fm, _ = parse_frontmatter(read_text_nofollow(index_path))
            if fm and "okf_version" in fm:
                return render_concept({"okf_version": fm["okf_version"]}, body)
        except (OSError, ValueError):
            pass
    return body


def plan_indexes(bundle: Bundle) -> dict[Path, str]:
    directories = {bundle.root} | {concept.path.parent for concept in bundle.concepts.values()}
    changes: dict[Path, str] = {}
    for directory in sorted(directories):
        rendered = build_directory_index(bundle, directory)
        if not rendered:
            continue
        path = directory / "index.md"
        try:
            old = read_text_nofollow(path)
        except (OSError, UnicodeDecodeError):
            old = ""
        if old != rendered:
            changes[path] = rendered
    return changes


def unified_diff(path: Path, old: str, new: str, root: Path) -> str:
    relative = path.relative_to(root).as_posix()
    return "".join(
        difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            f"a/{relative}",
            f"b/{relative}",
        )
    )


def atomic_write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)


def atomic_write(path: Path, text: str) -> None:
    atomic_write_bytes(path, text.encode("utf-8"))


def apply_indexes(changes: dict[Path, str]) -> None:
    for path, text in changes.items():
        atomic_write(path, text)


def graph_neighborhood(bundle: Bundle, start: str | None = None, depth: int = 1) -> dict[str, Any]:
    adjacency: dict[str, set[str]] = defaultdict(set)
    edges: list[tuple[str, str]] = []
    for concept in bundle.concepts.values():
        for link in concept.links:
            if link.target_id and link.target_id in bundle.concepts:
                adjacency[concept.concept_id].add(link.target_id)
                adjacency[link.target_id].add(concept.concept_id)
                edges.append((concept.concept_id, link.target_id))
    selected = set(bundle.concepts)
    if start:
        selected = set()
        queue: deque[tuple[str, int]] = deque([(start, 0)])
        while queue:
            node, distance = queue.popleft()
            if node in selected or node not in bundle.concepts:
                continue
            selected.add(node)
            if distance < depth:
                queue.extend((neighbor, distance + 1) for neighbor in adjacency[node])
    return {
        "nodes": [bundle.concepts[node].summary_dict() for node in sorted(selected)],
        "edges": [
            {"source": source, "target": target, "kind": "markdown-link"}
            for source, target in edges
            if source in selected and target in selected
        ],
    }


def graph_mermaid(graph: dict[str, Any]) -> str:
    lines = ["flowchart LR"]
    ids: dict[str, str] = {}
    for index, node in enumerate(graph["nodes"]):
        node_id = f"n{index}"
        ids[node["id"]] = node_id
        label = str(node["title"]).replace('"', "'")
        lines.append(f'    {node_id}["{label}"]')
    for edge in graph["edges"]:
        if edge["source"] in ids and edge["target"] in ids:
            lines.append(f"    {ids[edge['source']]} --> {ids[edge['target']]}")
    return "\n".join(lines) + "\n"


def graph_dot(graph: dict[str, Any]) -> str:
    lines = ["digraph okfleet {"]
    for node in graph["nodes"]:
        node_id = json.dumps(node["id"])
        label = json.dumps(node["title"])
        lines.append(f"  {node_id} [label={label}];")
    for edge in graph["edges"]:
        lines.append(f"  {json.dumps(edge['source'])} -> {json.dumps(edge['target'])};")
    lines.append("}")
    return "\n".join(lines) + "\n"


def safe_concept_path(root: Path, raw_id: str) -> Path:
    candidate_id = raw_id.removesuffix(".md").lstrip("/")
    pure = PurePosixPath(candidate_id)
    if (
        not candidate_id
        or pure.is_absolute()
        or ".." in pure.parts
        or any(part.startswith(".") for part in pure.parts)
    ):
        raise ValueError(f"unsafe concept id: {raw_id}")
    target = (root / Path(*pure.parts)).with_suffix(".md").resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"concept id escapes bundle root: {raw_id}") from exc
    return target


def create_concept(
    root: Path,
    raw_id: str,
    concept_type: str,
    *,
    title: str | None = None,
    description: str = "",
    extra: dict[str, Any] | None = None,
    body: str = "Describe this concept.\n",
    write: bool = False,
) -> tuple[Path, str]:
    target = safe_concept_path(root, raw_id)
    if target.exists():
        raise FileExistsError(target)
    frontmatter: dict[str, Any] = {
        "type": concept_type,
        "title": title or target.stem.replace("_", " ").replace("-", " ").title(),
        "description": description,
        "timestamp": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        **(extra or {}),
    }
    text = render_concept(frontmatter, body)
    if write:
        atomic_write(target, text)
    return target, text


def move_concept(
    bundle: Bundle,
    old_id: str,
    new_id: str,
    *,
    update_links: bool = True,
    write: bool = False,
) -> dict[Path, str | None]:
    source = bundle.get(old_id)
    if not source:
        raise KeyError(old_id)
    destination = safe_concept_path(bundle.root, new_id)
    if destination.exists():
        raise FileExistsError(destination)
    changes: dict[Path, str | None] = {source.path: None, destination: source.source}
    if update_links:
        for concept in bundle.concepts.values():
            updated = concept.source
            for link in concept.links:
                if link.target_id != source.concept_id:
                    continue
                relative = os.path.relpath(destination, concept.path.parent).replace(os.sep, "/")
                updated = updated.replace(f"]({link.raw_target})", f"]({relative})")
            if updated != concept.source:
                changes[concept.path] = updated
    if write:
        atomic_write(destination, source.source)
        for path, text in changes.items():
            if path in {source.path, destination}:
                continue
            if text is not None:
                atomic_write(path, text)
        source.path.unlink()
    return changes


def escape_markdown(value: str) -> str:
    return html.escape(value, quote=False)
