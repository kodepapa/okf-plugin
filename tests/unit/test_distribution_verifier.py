from __future__ import annotations

import io
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).parents[2]
VERIFIER = ROOT / "tools/verify_distribution.py"

WHEEL_MEMBERS = {
    "okfleet/py.typed",
    "okfleet/provider_plugin/.claude-plugin/plugin.json",
    "okfleet/provider_plugin/skills/okf-author/SKILL.md",
    "okfleet/provider_plugin/skills/okf-read/SKILL.md",
}

SDIST_MEMBERS = {"AGENTS.md", "CHANGELOG.md", "LICENSE", "NOTICE", "README.md", "pyproject.toml"}


def _wheel(path: Path, *, include_typed_marker: bool = True) -> None:
    members = set(WHEEL_MEMBERS)
    if not include_typed_marker:
        members.remove("okfleet/py.typed")
    with zipfile.ZipFile(path, "w") as archive:
        for member in members:
            archive.writestr(member, "test\n")
        archive.writestr(
            "okfleet-0.5.0.dist-info/METADATA",
            "Metadata-Version: 2.4\nLicense-Expression: Apache-2.0\n",
        )
        archive.writestr(
            "okfleet-0.5.0.dist-info/entry_points.txt",
            "[console_scripts]\nokfleet = okfleet.cli:main\n",
        )


def _sdist(path: Path) -> None:
    with tarfile.open(path, "w:gz") as archive:
        for member in SDIST_MEMBERS:
            payload = b"test\n"
            info = tarfile.TarInfo(f"okfleet-0.5.0/{member}")
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))


def test_distribution_verifier_accepts_complete_archives(tmp_path: Path) -> None:
    wheel = tmp_path / "okfleet-0.5.0-py3-none-any.whl"
    sdist = tmp_path / "okfleet-0.5.0.tar.gz"
    _wheel(wheel)
    _sdist(sdist)

    result = subprocess.run(
        [sys.executable, str(VERIFIER), str(tmp_path)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_distribution_verifier_rejects_missing_typed_marker(tmp_path: Path) -> None:
    wheel = tmp_path / "okfleet-0.5.0-py3-none-any.whl"
    sdist = tmp_path / "okfleet-0.5.0.tar.gz"
    _wheel(wheel, include_typed_marker=False)
    _sdist(sdist)

    result = subprocess.run(
        [sys.executable, str(VERIFIER), str(tmp_path)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "okfleet/py.typed" in result.stderr
