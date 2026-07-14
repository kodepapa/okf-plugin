from __future__ import annotations

import os
import re
import subprocess
import uuid
from pathlib import Path

from platformdirs import user_cache_path


def default_remote_root() -> Path:
    configured = os.environ.get("OKFLEET_REMOTE_CACHE")
    return Path(configured).expanduser() if configured else user_cache_path("okfleet") / "remotes"


def remote_destination(url: str, root: Path | None = None) -> Path:
    name = re.sub(r"[^a-zA-Z0-9]+", "-", url.rsplit("/", 1)[-1]).strip("-")
    name = re.sub(r"-git$", "", name).casefold() or "bundle"
    return (root or default_remote_root()) / f"{name}-{uuid.uuid4().hex[:8]}"


def clone_remote(url: str, *, ref: str | None = None, root: Path | None = None) -> Path:
    if not url.strip():
        raise ValueError("remote URL cannot be empty")
    destination = remote_destination(url, root)
    destination.parent.mkdir(parents=True, exist_ok=True)
    command = ["git", "clone", "--depth", "1"]
    if ref:
        command.extend(["--branch", ref])
    command.extend([url, str(destination)])
    result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=300)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "git clone failed")
    return destination


def update_remote(path: Path) -> None:
    result = subprocess.run(
        ["git", "-C", str(path), "pull", "--ff-only"],
        check=False,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "git pull failed")
