from __future__ import annotations

import importlib.metadata
from collections.abc import Callable, Iterable
from typing import Any

from .models import Bundle, Diagnostic, Severity

DiagnosticExtension = Callable[[Bundle], Iterable[Diagnostic]]
TemplateExtension = Callable[[dict[str, Any]], dict[str, Any]]


def diagnostic_extensions() -> list[tuple[str, DiagnosticExtension]]:
    loaded: list[tuple[str, DiagnosticExtension]] = []
    for entry in importlib.metadata.entry_points(group="okfleet.diagnostics"):
        extension = entry.load()
        if callable(extension):
            loaded.append((entry.name, extension))
    return loaded


def extension_diagnostics(bundle: Bundle) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    for name, extension in diagnostic_extensions():
        try:
            diagnostics.extend(extension(bundle))
        except Exception as exc:
            diagnostics.append(
                Diagnostic(
                    "EXTENSION_FAILED",
                    Severity.WARNING,
                    f"diagnostic extension {name!r} failed: {exc}",
                    bundle.root,
                )
            )
    return diagnostics


def load_template(name: str, context: dict[str, Any]) -> dict[str, Any]:
    for entry in importlib.metadata.entry_points(group="okfleet.templates"):
        if entry.name != name:
            continue
        extension = entry.load()
        if not callable(extension):
            break
        result = extension(context)
        if not isinstance(result, dict):
            raise TypeError(f"template {name!r} did not return an object")
        return result
    raise KeyError(name)
