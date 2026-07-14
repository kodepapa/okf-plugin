from __future__ import annotations

import json
import os
import re
import sqlite3
from collections.abc import Iterable
from contextlib import suppress
from pathlib import Path

from platformdirs import user_data_path

from .models import AgentSession, Bundle, BundleRef, SearchHit, SessionMode

SCHEMA_VERSION = 1
FILTER_RE = re.compile(r"\b(bundle|type|tag|id):(?:\"([^\"]+)\"|(\S+))")


def default_database_path() -> Path:
    configured = os.environ.get("OKFLEET_DATABASE")
    return Path(configured).expanduser() if configured else user_data_path("okfleet") / "okfleet.db"


class SearchDatabase:
    def __init__(self, path: Path | None = None) -> None:
        private_parent = path is None and "OKFLEET_DATABASE" not in os.environ
        self.path = path or default_database_path()
        if self.path.is_symlink():
            raise ValueError(f"refusing symlinked database path: {self.path}")
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if private_parent and os.name != "nt":
            self.path.parent.chmod(0o700)
        if not self.path.exists():
            flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0)
            descriptor = os.open(self.path, flags, 0o600)
            os.close(descriptor)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA journal_mode = WAL")
        self._migrate()
        self._harden_file_modes()

    @classmethod
    def open_reader(cls, path: Path) -> SearchDatabase:
        """Open an independent read-only connection to an initialized database."""
        if path.is_symlink():
            raise ValueError(f"refusing symlinked database path: {path}")
        database = cls.__new__(cls)
        database.path = path
        uri = f"{path.expanduser().resolve().as_uri()}?mode=ro"
        database.connection = sqlite3.connect(uri, uri=True)
        database.connection.row_factory = sqlite3.Row
        database.connection.execute("PRAGMA query_only = ON")
        return database

    def _harden_file_modes(self) -> None:
        if os.name == "nt":
            return
        for candidate in (self.path, Path(f"{self.path}-wal"), Path(f"{self.path}-shm")):
            with suppress(FileNotFoundError):
                candidate.chmod(0o600)

    def _migrate(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY
            );
            CREATE TABLE IF NOT EXISTS bundles (
                id TEXT PRIMARY KEY,
                alias TEXT NOT NULL UNIQUE,
                path TEXT NOT NULL,
                version TEXT,
                last_scan TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS concepts (
                bundle_id TEXT NOT NULL REFERENCES bundles(id) ON DELETE CASCADE,
                concept_id TEXT NOT NULL,
                path TEXT NOT NULL,
                title TEXT NOT NULL,
                concept_type TEXT NOT NULL,
                description TEXT NOT NULL,
                tags TEXT NOT NULL,
                resource TEXT,
                timestamp TEXT,
                body TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                parse_error TEXT,
                PRIMARY KEY (bundle_id, concept_id)
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS concepts_fts USING fts5(
                bundle_id UNINDEXED,
                concept_id,
                title,
                concept_type,
                description,
                tags,
                body,
                tokenize='unicode61 remove_diacritics 2'
            );
            CREATE TABLE IF NOT EXISTS links (
                bundle_id TEXT NOT NULL,
                source_id TEXT NOT NULL,
                target_id TEXT,
                raw_target TEXT NOT NULL,
                line INTEGER NOT NULL,
                exists_flag INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                provider TEXT NOT NULL,
                native_id TEXT,
                mode TEXT NOT NULL,
                cwd TEXT NOT NULL,
                scope_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                metadata_json TEXT NOT NULL
            );
            """
        )
        self.connection.execute(
            "INSERT OR IGNORE INTO schema_migrations(version) VALUES (?)", (SCHEMA_VERSION,)
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()
        self._harden_file_modes()

    def __enter__(self) -> SearchDatabase:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def index_bundle(self, ref: BundleRef, bundle: Bundle) -> int:
        changed = 0
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO bundles(id, alias, path, version, last_scan)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(id) DO UPDATE SET
                    alias=excluded.alias, path=excluded.path, version=excluded.version,
                    last_scan=CURRENT_TIMESTAMP
                """,
                (ref.id, ref.alias, str(ref.path), bundle.version),
            )
            current = {
                row["concept_id"]: row["content_hash"]
                for row in self.connection.execute(
                    "SELECT concept_id, content_hash FROM concepts WHERE bundle_id=?", (ref.id,)
                )
            }
            found = set(bundle.concepts)
            for concept_id in set(current) - found:
                self.connection.execute(
                    "DELETE FROM concepts WHERE bundle_id=? AND concept_id=?", (ref.id, concept_id)
                )
                self.connection.execute(
                    "DELETE FROM concepts_fts WHERE bundle_id=? AND concept_id=?",
                    (ref.id, concept_id),
                )
                changed += 1
            self.connection.execute("DELETE FROM links WHERE bundle_id=?", (ref.id,))
            for concept in bundle.concepts.values():
                if current.get(concept.concept_id) != concept.content_hash:
                    fm = concept.frontmatter or {}
                    self.connection.execute(
                        """
                        INSERT INTO concepts(
                            bundle_id, concept_id, path, title, concept_type, description,
                            tags, resource, timestamp, body, content_hash, parse_error
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(bundle_id, concept_id) DO UPDATE SET
                            path=excluded.path, title=excluded.title,
                            concept_type=excluded.concept_type, description=excluded.description,
                            tags=excluded.tags, resource=excluded.resource,
                            timestamp=excluded.timestamp, body=excluded.body,
                            content_hash=excluded.content_hash, parse_error=excluded.parse_error
                        """,
                        (
                            ref.id,
                            concept.concept_id,
                            str(concept.path),
                            concept.title,
                            concept.concept_type,
                            concept.description,
                            json.dumps(concept.tags),
                            fm.get("resource"),
                            str(fm.get("timestamp") or ""),
                            concept.body,
                            concept.content_hash,
                            concept.parse_error,
                        ),
                    )
                    self.connection.execute(
                        "DELETE FROM concepts_fts WHERE bundle_id=? AND concept_id=?",
                        (ref.id, concept.concept_id),
                    )
                    self.connection.execute(
                        "INSERT INTO concepts_fts VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (
                            ref.id,
                            concept.concept_id,
                            concept.title,
                            concept.concept_type,
                            concept.description,
                            " ".join(concept.tags),
                            concept.body,
                        ),
                    )
                    changed += 1
                for link in concept.links:
                    self.connection.execute(
                        "INSERT INTO links VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            ref.id,
                            concept.concept_id,
                            link.target_id,
                            link.raw_target,
                            link.line,
                            int(link.exists),
                        ),
                    )
        return changed

    def remove_bundle(self, bundle_id: str) -> None:
        with self.connection:
            self.connection.execute("DELETE FROM concepts_fts WHERE bundle_id=?", (bundle_id,))
            self.connection.execute("DELETE FROM links WHERE bundle_id=?", (bundle_id,))
            self.connection.execute("DELETE FROM bundles WHERE id=?", (bundle_id,))

    def parse_query(self, query: str) -> tuple[str, dict[str, list[str]]]:
        filters: dict[str, list[str]] = {}
        for match in FILTER_RE.finditer(query):
            filters.setdefault(match.group(1), []).append(match.group(2) or match.group(3))
        text = FILTER_RE.sub(" ", query).strip()
        return text, filters

    def search(
        self,
        query: str,
        *,
        bundle_ids: Iterable[str] | None = None,
        limit: int = 20,
    ) -> list[SearchHit]:
        text, filters = self.parse_query(query)
        scope = list(bundle_ids or [])
        conditions: list[str] = []
        params: list[object] = []
        if scope:
            conditions.append("c.bundle_id IN (" + ",".join("?" for _ in scope) + ")")
            params.extend(scope)
        if filters.get("bundle"):
            values = filters["bundle"]
            conditions.append("b.alias IN (" + ",".join("?" for _ in values) + ")")
            params.extend(values)
        if filters.get("type"):
            values = filters["type"]
            conditions.append(
                "lower(c.concept_type) IN (" + ",".join("lower(?)" for _ in values) + ")"
            )
            params.extend(values)
        if filters.get("tag"):
            for value in filters["tag"]:
                conditions.append("c.tags LIKE ?")
                params.append(f'%"{value}"%')
        if filters.get("id"):
            for value in filters["id"]:
                conditions.append("c.concept_id LIKE ?")
                params.append(f"%{value}%")
        where = (" AND " + " AND ".join(conditions)) if conditions else ""
        if text:
            fts = " ".join(f'"{token.replace(chr(34), chr(34) * 2)}"*' for token in text.split())
            sql = f"""
                SELECT c.*, b.alias,
                       snippet(concepts_fts, 6, '[', ']', ' … ', 20) AS hit_snippet,
                       bm25(concepts_fts, 0, 8, 6, 4, 5, 3, 1) AS rank
                FROM concepts_fts
                JOIN concepts c ON c.bundle_id=concepts_fts.bundle_id
                               AND c.concept_id=concepts_fts.concept_id
                JOIN bundles b ON b.id=c.bundle_id
                WHERE concepts_fts MATCH ? {where}
                ORDER BY rank ASC, c.title COLLATE NOCASE ASC
                LIMIT ?
            """
            rows = self.connection.execute(sql, [fts, *params, limit]).fetchall()
        else:
            sql = f"""
                SELECT c.*, b.alias, substr(c.body, 1, 240) AS hit_snippet, 0.0 AS rank
                FROM concepts c JOIN bundles b ON b.id=c.bundle_id
                WHERE 1=1 {where}
                ORDER BY c.title COLLATE NOCASE ASC LIMIT ?
            """
            rows = self.connection.execute(sql, [*params, limit]).fetchall()
        return [
            SearchHit(
                bundle_id=row["bundle_id"],
                bundle_alias=row["alias"],
                concept_id=row["concept_id"],
                title=row["title"],
                concept_type=row["concept_type"],
                description=row["description"],
                snippet=row["hit_snippet"] or row["description"],
                score=-float(row["rank"]),
                path=Path(row["path"]),
            )
            for row in rows
        ]

    def stats(self) -> dict[str, int]:
        return {
            "bundles": self.connection.execute("SELECT count(*) FROM bundles").fetchone()[0],
            "concepts": self.connection.execute("SELECT count(*) FROM concepts").fetchone()[0],
            "links": self.connection.execute("SELECT count(*) FROM links").fetchone()[0],
        }

    def save_session(self, session: AgentSession) -> None:
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO sessions(id, provider, native_id, mode, cwd, scope_json, created_at, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET native_id=excluded.native_id,
                    scope_json=excluded.scope_json, metadata_json=excluded.metadata_json
                """,
                (
                    session.id,
                    session.provider,
                    session.native_id,
                    session.mode.value,
                    str(session.cwd),
                    json.dumps(session.scope),
                    session.created_at,
                    json.dumps(session.metadata),
                ),
            )

    def list_sessions(self) -> list[AgentSession]:
        rows = self.connection.execute("SELECT * FROM sessions ORDER BY created_at DESC").fetchall()
        return [
            AgentSession(
                id=row["id"],
                provider=row["provider"],
                native_id=row["native_id"],
                mode=SessionMode(row["mode"]),
                cwd=Path(row["cwd"]),
                scope=json.loads(row["scope_json"]),
                created_at=row["created_at"],
                metadata=json.loads(row["metadata_json"]),
            )
            for row in rows
        ]

    def get_session(self, session_id: str) -> AgentSession | None:
        return next((session for session in self.list_sessions() if session.id == session_id), None)

    def delete_session(self, session_id: str) -> bool:
        with self.connection:
            cursor = self.connection.execute("DELETE FROM sessions WHERE id=?", (session_id,))
        return bool(cursor.rowcount)

    def clear_derived(self) -> None:
        with self.connection:
            self.connection.execute("DELETE FROM concepts_fts")
            self.connection.execute("DELETE FROM links")
            self.connection.execute("DELETE FROM concepts")
            self.connection.execute("DELETE FROM bundles")
