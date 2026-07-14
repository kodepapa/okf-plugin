from __future__ import annotations

from rich.text import Text

PLAIN_MARK = "●━━━▶"


def brand_text() -> Text:
    """Return the single-line fleet mark and wordmark for terminal chrome."""
    brand = Text(PLAIN_MARK, style="bold #3b82f6")
    brand.append("  OK", style="bold #60a5fa")
    brand.append("Fleet", style="bold #38bdf8")
    return brand
