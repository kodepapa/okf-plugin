from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass(slots=True, frozen=True)
class Diagnostic:
    code: str
    severity: Severity
    message: str
    path: Path
    line: int | None = None
    column: int | None = None
    fix_id: str | None = None

    def to_dict(self, root: Path | None = None) -> dict[str, Any]:
        data = asdict(self)
        try:
            data["path"] = str(self.path.relative_to(root)) if root else str(self.path)
        except ValueError:
            data["path"] = str(self.path)
        data["severity"] = self.severity.value
        return data


@dataclass(slots=True, frozen=True)
class ConceptLink:
    source_id: str
    raw_target: str
    target_id: str | None
    resolved_path: Path | None
    exists: bool
    line: int
    label: str = ""
    context: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["resolved_path"] = str(self.resolved_path) if self.resolved_path else None
        return data


@dataclass(slots=True)
class Concept:
    bundle_root: Path
    path: Path
    concept_id: str
    frontmatter: dict[str, Any] | None
    body: str
    source: str
    content_hash: str
    parse_error: str | None = None
    links: list[ConceptLink] = field(default_factory=list)

    @property
    def title(self) -> str:
        title = (self.frontmatter or {}).get("title")
        return str(title) if title else self.path.stem.replace("_", " ").replace("-", " ").title()

    @property
    def description(self) -> str:
        return str((self.frontmatter or {}).get("description") or "")

    @property
    def concept_type(self) -> str:
        return str((self.frontmatter or {}).get("type") or "")

    @property
    def tags(self) -> list[str]:
        value = (self.frontmatter or {}).get("tags") or []
        if isinstance(value, str):
            return [value]
        return [str(item) for item in value]

    def citation(self, alias: str | None = None) -> str:
        return f"{alias}:{self.concept_id}" if alias else self.concept_id

    def summary_dict(self, alias: str | None = None) -> dict[str, Any]:
        fm = self.frontmatter or {}
        return {
            "id": self.concept_id,
            "citation": self.citation(alias),
            "title": self.title,
            "type": self.concept_type,
            "description": self.description,
            "tags": self.tags,
            "resource": fm.get("resource"),
            "timestamp": fm.get("timestamp"),
            "path": str(self.path.relative_to(self.bundle_root)),
            "parse_error": self.parse_error,
        }


@dataclass(slots=True)
class Bundle:
    root: Path
    concepts: dict[str, Concept]
    indexes: list[Path] = field(default_factory=list)
    logs: list[Path] = field(default_factory=list)
    version: str | None = None

    def get(self, concept_id: str) -> Concept | None:
        return self.concepts.get(concept_id.removesuffix(".md").lstrip("/"))


@dataclass(slots=True, frozen=True)
class BundleRef:
    id: str
    alias: str
    path: Path
    source: str = "global"
    available: bool = True
    confidence: str = "explicit"
    reason: str = "registered"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["path"] = str(self.path)
        return data


@dataclass(slots=True, frozen=True)
class SearchHit:
    bundle_id: str
    bundle_alias: str
    concept_id: str
    title: str
    concept_type: str
    description: str
    snippet: str
    score: float
    path: Path

    @property
    def citation(self) -> str:
        return f"{self.bundle_alias}:{self.concept_id}"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["path"] = str(self.path)
        data["citation"] = self.citation
        return data


class SessionMode(StrEnum):
    BUNDLE_READ = "bundle-read"
    BUNDLE_WORK_STAGED = "bundle-work-staged"
    FLEET_READ = "fleet-read"


class AgentEventType(StrEnum):
    SESSION_STARTED = "session.started"
    MESSAGE_DELTA = "message.delta"
    MESSAGE_COMPLETED = "message.completed"
    TOOL_STARTED = "tool.started"
    TOOL_UPDATED = "tool.updated"
    TOOL_COMPLETED = "tool.completed"
    FILE_CHANGED = "file.changed"
    PERMISSION_REQUESTED = "permission.requested"
    USAGE = "usage"
    TURN_COMPLETED = "turn.completed"
    TURN_FAILED = "turn.failed"
    ERROR = "error"


@dataclass(slots=True, frozen=True)
class AgentEvent:
    type: AgentEventType
    text: str = ""
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type.value, "text": self.text, "data": self.data}


@dataclass(slots=True)
class AgentSession:
    id: str
    provider: str
    mode: SessionMode
    cwd: Path
    native_id: str | None = None
    scope: list[str] = field(default_factory=list)
    process: Any | None = None
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class ProviderStatus:
    name: str
    available: bool
    binary: str | None
    version: str | None
    authenticated: bool | None
    capabilities: tuple[str, ...] = ()
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class FileChange:
    path: str
    kind: str
    before_hash: str | None
    after_hash: str | None
    diff: str


@dataclass(slots=True)
class ChangeSet:
    id: str
    source_root: Path
    staged_root: Path
    changes: list[FileChange]
    baseline_hashes: dict[str, str]
    diagnostics: list[Diagnostic] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)

    @property
    def applicable(self) -> bool:
        return not self.conflicts and not any(
            d.severity == Severity.ERROR for d in self.diagnostics
        )
