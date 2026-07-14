from __future__ import annotations

from rich.text import Text

PLAIN_MARK = "  ●━━━━▶\n ●━━━━━━▶\n  ●━━━━▶"


def brand_text() -> Text:
    """Return the compact fleet mark and wordmark for terminal surfaces."""
    brand = Text()
    brand.append("  ●━━━━▶\n", style="#60a5fa")
    brand.append(" ●━━━━━━▶", style="#2563eb")
    brand.append("  OKFleet\n", style="bold #38bdf8")
    brand.append("  ●━━━━▶", style="#0ea5e9")
    return brand
