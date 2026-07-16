#!/usr/bin/env python3
"""Capture repeatable, real Textual renders of the OKFleet TUI.

The tool drives ``OKFleetApp`` through Textual's headless ``Pilot`` and exports
the compositor output with ``App.save_screenshot``. It does not invoke Codex or
Claude and uses an isolated temporary OKFleet registry/database.
"""

from __future__ import annotations

import argparse
import asyncio
import html
import json
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path

import textual

from okfleet.tui.app import OKFleetApp

_STATE_ENV = {
    "OKFLEET_CONFIG": "config.toml",
    "OKFLEET_DATABASE": "okfleet.db",
    "OKFLEET_CHANGESETS": "changesets",
    "OKFLEET_REMOTE_CACHE": "remotes",
}
_RENDER_ENV = {
    "TERM": "xterm-256color",
    "COLORTERM": "truecolor",
}


@dataclass(frozen=True)
class Capture:
    name: str
    title: str
    width: int
    height: int
    interaction: str


def _size(value: str) -> tuple[int, int]:
    try:
        width, height = (int(part) for part in value.lower().split("x", maxsplit=1))
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError("size must be WIDTHxHEIGHT, for example 120x40") from exc
    if width < 40 or height < 20:
        raise argparse.ArgumentTypeError("size must be at least 40x20")
    return width, height


@contextmanager
def _isolated_state(root: Path) -> Iterator[None]:
    managed_names = {*_STATE_ENV, *_RENDER_ENV, "NO_COLOR"}
    previous = {name: os.environ.get(name) for name in managed_names}
    root.mkdir(parents=True, exist_ok=True)
    try:
        for name, relative_path in _STATE_ENV.items():
            os.environ[name] = str(root / relative_path)
        os.environ.pop("NO_COLOR", None)
        os.environ.update(_RENDER_ENV)
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


async def _capture(
    source: Path,
    output: Path,
    capture: Capture,
    *,
    query: str,
) -> Path:
    app = OKFleetApp(source)
    async with app.run_test(size=(capture.width, capture.height)) as pilot:
        await pilot.pause()
        if capture.interaction.startswith("spotlight") or capture.interaction == "selected-concept":
            await pilot.press("/")
            await pilot.pause()
            if capture.interaction in {"spotlight-query", "selected-concept"}:
                await pilot.press(*query)
                await pilot.pause(0.15)
            if capture.interaction == "selected-concept":
                await pilot.press("enter")
                await pilot.pause()
        elif capture.interaction == "chat":
            await pilot.press("c")
            await pilot.pause()
        elif capture.interaction == "help":
            await pilot.press("?")
            await pilot.pause()
        filename = f"{capture.name}.svg"
        return Path(app.save_screenshot(filename=filename, path=str(output)))


def _gallery(captures: list[Capture]) -> str:
    figures = []
    for capture in captures:
        filename = f"{capture.name}.svg"
        figures.append(
            "\n".join(
                [
                    "<figure>",
                    f'  <a href="{filename}"><img src="{filename}" '
                    f'alt="{html.escape(capture.title)}"></a>',
                    f"  <figcaption><strong>{html.escape(capture.title)}</strong>",
                    f"    <span>{capture.width}x{capture.height} · "
                    f"{html.escape(capture.interaction)}</span>",
                    "  </figcaption>",
                    "</figure>",
                ]
            )
        )
    cards = "\n".join(figures)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>OKFleet TUI visual audit</title>
  <style>
    :root {{ color-scheme: dark; font-family: Inter, ui-sans-serif, system-ui, sans-serif; }}
    body {{ margin: 0; padding: 2rem; background: #070b14; color: #e5e7eb; }}
    header {{ max-width: 72rem; margin: 0 auto 1.5rem; }}
    h1 {{ margin: 0 0 .4rem; color: #60a5fa; }}
    p {{ margin: 0; color: #94a3b8; }}
    main {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(34rem, 1fr));
            gap: 1.25rem; max-width: 120rem; margin: auto; }}
    figure {{ margin: 0; overflow: hidden; border: 1px solid #1e3a5f; border-radius: .75rem;
              background: #0b1220; box-shadow: 0 1rem 3rem #0008; }}
    img {{ display: block; width: 100%; height: auto; background: #111; }}
    figcaption {{ display: flex; justify-content: space-between; gap: 1rem; padding: .8rem 1rem; }}
    figcaption span {{ color: #94a3b8; font-size: .9rem; }}
    @media (max-width: 40rem) {{ body {{ padding: .75rem; }} main {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
  <header>
    <h1>OKFleet TUI visual audit</h1>
    <p>Real Textual compositor output. Select a frame to inspect the SVG at full resolution.</p>
  </header>
  <main>
{cards}
  </main>
</body>
</html>
"""


async def capture_all(
    source: Path,
    output: Path,
    *,
    wide: tuple[int, int],
    narrow: tuple[int, int],
    query: str,
) -> list[Capture]:
    captures = [
        Capture("wide-initial", "Wide · initial library", *wide, "initial"),
        Capture("wide-spotlight", "Wide · Spotlight open", *wide, "spotlight"),
        Capture(
            "wide-spotlight-query",
            f"Wide · Spotlight query: {query}",
            *wide,
            "spotlight-query",
        ),
        Capture(
            "wide-selected-concept",
            f"Wide · selected concept: {query}",
            *wide,
            "selected-concept",
        ),
        Capture("wide-help", "Wide · keyboard help", *wide, "help"),
        Capture("wide-chat", "Wide · chat drawer", *wide, "chat"),
        Capture("narrow-initial", "Narrow · initial library", *narrow, "initial"),
        Capture(
            "narrow-spotlight-query",
            f"Narrow · Spotlight query: {query}",
            *narrow,
            "spotlight-query",
        ),
        Capture("narrow-chat", "Narrow · full-screen chat", *narrow, "chat"),
    ]
    output.mkdir(parents=True, exist_ok=True)
    with (
        tempfile.TemporaryDirectory(prefix="okfleet-tui-audit-") as state,
        _isolated_state(Path(state)),
    ):
        for capture in captures:
            await _capture(source, output, capture, query=query)

    manifest = {
        "renderer": f"Textual {textual.__version__} App.save_screenshot",
        "format": "SVG",
        "source": str(source),
        "query": query,
        "provider_invoked": False,
        "render_environment": {"NO_COLOR": None, **_RENDER_ENV},
        "captures": [{**asdict(capture), "file": f"{capture.name}.svg"} for capture in captures],
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (output / "index.html").write_text(_gallery(captures), encoding="utf-8")
    return captures


def main() -> None:
    repository = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description="Capture a browser-viewable visual audit of the real OKFleet Textual TUI."
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=repository / "examples",
        help="Path to discover OKF bundles beneath (default: examples).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=repository / "dist" / "tui-audit",
        help="Output directory for SVG frames and the HTML gallery.",
    )
    parser.add_argument("--wide", type=_size, default=(120, 40), metavar="WIDTHxHEIGHT")
    parser.add_argument("--narrow", type=_size, default=(70, 30), metavar="WIDTHxHEIGHT")
    parser.add_argument("--query", default="revenue", help="Spotlight query to capture.")
    args = parser.parse_args()

    source = args.source.expanduser().resolve()
    output = args.output.expanduser().resolve()
    if not source.is_dir():
        parser.error(f"source is not a directory: {source}")
    if not args.query.strip():
        parser.error("query may not be empty")

    captures = asyncio.run(
        capture_all(
            source,
            output,
            wide=args.wide,
            narrow=args.narrow,
            query=args.query.strip(),
        )
    )
    print(f"Captured {len(captures)} TUI states in {output}")
    print(f"Open {output / 'index.html'}")


if __name__ == "__main__":
    main()
