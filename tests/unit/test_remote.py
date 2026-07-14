from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

from okfleet.remote import clone_remote, remote_destination, update_remote


def test_remote_destination_is_scoped_and_slugged(tmp_path: Path) -> None:
    destination = remote_destination("https://example.com/team/Knowledge.git", tmp_path)
    assert destination.parent == tmp_path
    assert destination.name.startswith("knowledge-")


def test_clone_terminates_options_and_preserves_scp_ssh_urls(tmp_path: Path, monkeypatch) -> None:
    captured: list[str] = []

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured.extend(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(subprocess, "run", run)

    clone_remote("git@example.com:team/knowledge.git", root=tmp_path)

    separator = captured.index("--")
    assert captured[separator + 1] == "git@example.com:team/knowledge.git"
    assert separator > captured.index("--depth")


@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes are not available")
def test_clone_uses_private_cache_directory(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "remotes"

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(subprocess, "run", run)
    clone_remote("https://example.com/team/knowledge.git", root=root)

    assert stat.S_IMODE(root.stat().st_mode) == 0o700


@pytest.mark.parametrize(
    "url",
    [
        "https://alice:secret@example.com/team/knowledge.git",
        "http://token@example.com/team/knowledge.git",
    ],
)
def test_clone_rejects_http_credentials(url: str, tmp_path: Path, monkeypatch) -> None:
    def unexpected_run(*args: object, **kwargs: object) -> None:
        raise AssertionError("git must not run for credential-bearing HTTP URLs")

    monkeypatch.setattr(subprocess, "run", unexpected_run)

    with pytest.raises(ValueError, match="must not contain embedded credentials"):
        clone_remote(url, root=tmp_path)


def test_clone_redacts_credentials_from_git_stderr(tmp_path: Path, monkeypatch) -> None:
    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        stderr = "fatal: unable to access 'https://alice:secret@example.com/private.git/'"
        return subprocess.CompletedProcess(command, 128, "", stderr)

    monkeypatch.setattr(subprocess, "run", run)

    with pytest.raises(RuntimeError) as exc_info:
        clone_remote("https://example.com/team/knowledge.git", root=tmp_path)

    error = str(exc_info.value)
    assert "alice" not in error
    assert "secret" not in error
    assert "https://[redacted]@example.com/private.git/" in error


def test_update_redacts_credentials_from_git_stderr(tmp_path: Path, monkeypatch) -> None:
    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        stderr = "fatal: https://alice:secret@example.com/private.git failed"
        return subprocess.CompletedProcess(command, 1, "", stderr)

    monkeypatch.setattr(subprocess, "run", run)

    with pytest.raises(RuntimeError) as exc_info:
        update_remote(tmp_path)

    assert "alice" not in str(exc_info.value)
    assert "secret" not in str(exc_info.value)
