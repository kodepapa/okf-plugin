from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def test_tui_capture_tool_exports_real_svg_gallery(bundle_path: Path, tmp_path: Path) -> None:
    output = tmp_path / "audit"
    script = Path(__file__).parents[2] / "tools" / "capture_tui_audit.py"

    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--source",
            str(bundle_path.parent),
            "--output",
            str(output),
            "--wide",
            "100x30",
            "--narrow",
            "60x24",
        ],
        check=False,
        capture_output=True,
        env={**os.environ, "NO_COLOR": "1", "TERM": "dumb", "COLORTERM": ""},
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["format"] == "SVG"
    assert manifest["provider_invoked"] is False
    assert manifest["render_environment"] == {
        "NO_COLOR": None,
        "TERM": "xterm-256color",
        "COLORTERM": "truecolor",
    }
    assert len(manifest["captures"]) == 9
    assert (output / "index.html").is_file()
    for capture in manifest["captures"]:
        svg = (output / capture["file"]).read_text(encoding="utf-8")
        assert svg.startswith('<svg class="rich-terminal"')
        assert "OKFleet" in svg
        assert any(color in svg.lower() for color in ("#3b82f6", "#60a5fa", "#38bdf8"))
