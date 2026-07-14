from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).parents[2]


def test_claude_uses_canonical_agent_guide() -> None:
    claude_guide = ROOT / "CLAUDE.md"

    assert claude_guide.is_symlink()
    assert os.readlink(claude_guide) == "AGENTS.md"
    assert claude_guide.resolve() == (ROOT / "AGENTS.md").resolve()


def test_claude_skills_use_canonical_skill_directories() -> None:
    for skill_name in ("okf-author", "okf-read"):
        claude_skill = ROOT / ".claude" / "skills" / skill_name
        canonical_skill = ROOT / "skills" / skill_name

        assert claude_skill.is_symlink()
        assert os.readlink(claude_skill) == f"../../skills/{skill_name}"
        assert claude_skill.resolve() == canonical_skill.resolve()


def test_codex_manifest_uses_okfleet_brand_identity() -> None:
    manifest = json.loads((ROOT / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))

    assert manifest["interface"]["displayName"] == "OKFleet"
    assert manifest["interface"]["brandColor"] == "#2563EB"
