from __future__ import annotations

import hashlib
import math
import re
import sqlite3
from collections import Counter
from collections.abc import Iterable
from pathlib import Path

from .models import SearchHit
from .search import SearchDatabase

TOKEN_RE = re.compile(r"[a-zA-Z0-9_]{2,}")


class LocalHashEmbedding:
    """Deterministic, dependency-free local feature hashing.

    This is intentionally opt-in. It offers fuzzy weighted retrieval without
    sending bundle text anywhere and defines the provider seam for richer
    embedding implementations later.
    """

    def __init__(self, dimensions: int = 512) -> None:
        self.dimensions = dimensions

    def embed(self, text: str) -> dict[int, float]:
        counts = Counter(token.casefold() for token in TOKEN_RE.findall(text))
        vector: dict[int, float] = {}
        for token, count in counts.items():
            digest = hashlib.blake2b(token.encode(), digest_size=8).digest()
            raw = int.from_bytes(digest)
            index = raw % self.dimensions
            sign = -1.0 if raw & 1 else 1.0
            vector[index] = vector.get(index, 0.0) + sign * (1.0 + math.log(count))
        norm = math.sqrt(sum(value * value for value in vector.values())) or 1.0
        return {index: value / norm for index, value in vector.items()}


def _cosine(left: dict[int, float], right: dict[int, float]) -> float:
    if len(left) > len(right):
        left, right = right, left
    return sum(value * right.get(index, 0.0) for index, value in left.items())


def semantic_search(
    database: SearchDatabase,
    query: str,
    *,
    bundle_ids: Iterable[str] | None = None,
    limit: int = 20,
    provider: LocalHashEmbedding | None = None,
) -> list[SearchHit]:
    embedder = provider or LocalHashEmbedding()
    query_vector = embedder.embed(query)
    scope = list(bundle_ids or [])
    where = ""
    params: list[object] = []
    if scope:
        where = "WHERE c.bundle_id IN (" + ",".join("?" for _ in scope) + ")"
        params.extend(scope)
    rows = database.connection.execute(
        f"""
        SELECT c.*, b.alias FROM concepts c
        JOIN bundles b ON b.id=c.bundle_id {where}
        """,
        params,
    ).fetchall()
    ranked: list[tuple[float, sqlite3.Row]] = []
    for row in rows:
        document = "\n".join([row["title"], row["concept_type"], row["description"], row["body"]])
        ranked.append((_cosine(query_vector, embedder.embed(document)), row))
    ranked.sort(key=lambda item: (-item[0], str(item[1]["title"]).casefold()))
    return [
        SearchHit(
            bundle_id=row["bundle_id"],
            bundle_alias=row["alias"],
            concept_id=row["concept_id"],
            title=row["title"],
            concept_type=row["concept_type"],
            description=row["description"],
            snippet=row["body"][:240],
            score=score,
            path=Path(row["path"]),
        )
        for score, row in ranked[:limit]
        if score > 0
    ]
