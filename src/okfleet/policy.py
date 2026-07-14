from __future__ import annotations

import json
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .models import Bundle, Diagnostic, Severity


def load_policy(path: Path) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    if resolved.suffix.casefold() == ".json":
        data = json.loads(resolved.read_text(encoding="utf-8"))
    else:
        with resolved.open("rb") as handle:
            data = tomllib.load(handle)
    if not isinstance(data, dict):
        raise ValueError("policy pack must be an object")
    return data.get("policy", data) if isinstance(data.get("policy", data), dict) else data


def policy_diagnostics(bundle: Bundle, policy: dict[str, Any]) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    allowed_types = {str(item).casefold() for item in policy.get("allowed_types", [])}
    forbidden_types = {str(item).casefold() for item in policy.get("forbidden_types", [])}
    required_global = [str(item) for item in policy.get("required_fields", [])]
    required_by_type = policy.get("required_by_type", {})
    required_by_type = required_by_type if isinstance(required_by_type, dict) else {}
    freshness_global = policy.get("freshness_days")
    freshness_by_type = policy.get("freshness_by_type", {})
    freshness_by_type = freshness_by_type if isinstance(freshness_by_type, dict) else {}
    for concept in bundle.concepts.values():
        concept_type = concept.concept_type.casefold()
        if allowed_types and concept_type not in allowed_types:
            diagnostics.append(
                Diagnostic(
                    "POLICY_TYPE_NOT_ALLOWED",
                    Severity.ERROR,
                    f"concept type is not allowed by policy: {concept.concept_type}",
                    concept.path,
                    1,
                )
            )
        if concept_type in forbidden_types:
            diagnostics.append(
                Diagnostic(
                    "POLICY_TYPE_FORBIDDEN",
                    Severity.ERROR,
                    f"concept type is forbidden by policy: {concept.concept_type}",
                    concept.path,
                    1,
                )
            )
        typed_fields = required_by_type.get(concept.concept_type, [])
        fields = [*required_global, *(typed_fields if isinstance(typed_fields, list) else [])]
        for field in fields:
            if not (concept.frontmatter or {}).get(field):
                diagnostics.append(
                    Diagnostic(
                        "POLICY_REQUIRED_FIELD",
                        Severity.ERROR,
                        f"policy requires field '{field}' for {concept.concept_type}",
                        concept.path,
                        1,
                    )
                )
        required_tags = {str(item) for item in policy.get("required_tags", [])}
        for tag in sorted(required_tags - set(concept.tags)):
            diagnostics.append(
                Diagnostic(
                    "POLICY_REQUIRED_TAG",
                    Severity.WARNING,
                    f"policy requires tag '{tag}'",
                    concept.path,
                    1,
                )
            )
        freshness = freshness_by_type.get(
            concept.concept_type,
            freshness_by_type.get(concept_type, freshness_global),
        )
        if freshness is not None:
            try:
                threshold = int(freshness)
            except (TypeError, ValueError):
                threshold = 0
            raw_timestamp = (concept.frontmatter or {}).get("timestamp")
            if threshold > 0 and not raw_timestamp:
                diagnostics.append(
                    Diagnostic(
                        "POLICY_FRESHNESS_TIMESTAMP",
                        Severity.WARNING,
                        f"freshness target of {threshold} days requires a timestamp",
                        concept.path,
                        1,
                    )
                )
            elif threshold > 0:
                try:
                    timestamp = datetime.fromisoformat(str(raw_timestamp).replace("Z", "+00:00"))
                    if timestamp.tzinfo is None:
                        timestamp = timestamp.replace(tzinfo=UTC)
                    age = (datetime.now(UTC) - timestamp).days
                    if age > threshold:
                        diagnostics.append(
                            Diagnostic(
                                "POLICY_STALE",
                                Severity.WARNING,
                                f"concept is {age} days old; policy target is {threshold}",
                                concept.path,
                                1,
                            )
                        )
                except ValueError:
                    diagnostics.append(
                        Diagnostic(
                            "POLICY_FRESHNESS_TIMESTAMP",
                            Severity.WARNING,
                            "freshness policy requires an ISO 8601 timestamp",
                            concept.path,
                            1,
                        )
                    )
    return diagnostics
