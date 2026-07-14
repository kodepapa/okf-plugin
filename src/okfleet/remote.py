from __future__ import annotations

import os
import re
import subprocess
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from platformdirs import user_cache_path

_URL_CREDENTIALS = re.compile(r"(?i)(https?://)[^/\s@]+@")


def default_remote_root() -> Path:
    configured = os.environ.get("OKFLEET_REMOTE_CACHE")
    return Path(configured).expanduser() if configured else user_cache_path("okfleet") / "remotes"


def remote_destination(url: str, root: Path | None = None) -> Path:
    name = re.sub(r"[^a-zA-Z0-9]+", "-", url.rsplit("/", 1)[-1]).strip("-")
    name = re.sub(r"-git$", "", name).casefold() or "bundle"
    return (root or default_remote_root()) / f"{name}-{uuid.uuid4().hex[:8]}"


def _validate_remote_url(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme.casefold() in {"http", "https"} and parsed.username is not None:
        raise ValueError("HTTP(S) remote URLs must not contain embedded credentials")


def _redact_url_credentials(message: str) -> str:
    return _URL_CREDENTIALS.sub(r"\1[redacted]@", message)


def clone_remote(url: str, *, ref: str | None = None, root: Path | None = None) -> Path:
    if not url.strip():
        raise ValueError("remote URL cannot be empty")
    _validate_remote_url(url)
    destination = remote_destination(url, root)
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name != "nt":
        destination.parent.chmod(0o700)
    command = ["git", "clone", "--depth", "1"]
    if ref:
        command.extend(["--branch", ref])
    command.extend(["--", url, str(destination)])
    result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=300)
    if result.returncode:
        error = _redact_url_credentials(result.stderr.strip())
        raise RuntimeError(error or "git clone failed")
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
        error = _redact_url_credentials(result.stderr.strip())
        raise RuntimeError(error or "git pull failed")
