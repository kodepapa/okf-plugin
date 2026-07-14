from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )


def bundle_git_status(bundle_root: Path, *, include_diff: bool = False) -> dict[str, Any]:
    """Return Git state scoped to one bundle without changing repository state."""
    resolved = bundle_root.expanduser().resolve()
    top = _git(resolved, "rev-parse", "--show-toplevel")
    if top.returncode:
        return {"available": False, "bundle": str(resolved), "changes": []}
    repository = Path(top.stdout.strip()).resolve()
    try:
        relative = resolved.relative_to(repository)
    except ValueError:
        return {"available": False, "bundle": str(resolved), "changes": []}
    pathspec = relative.as_posix() if relative.parts else "."
    branch_result = _git(repository, "branch", "--show-current")
    status_result = _git(
        repository,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        "--",
        pathspec,
    )
    changes: list[dict[str, str]] = []
    for line in status_result.stdout.splitlines():
        if len(line) < 4:
            continue
        changes.append(
            {
                "index": line[0],
                "worktree": line[1],
                "path": line[3:],
            }
        )
    result: dict[str, Any] = {
        "available": True,
        "repository": str(repository),
        "bundle": str(resolved),
        "branch": branch_result.stdout.strip() or None,
        "changes": changes,
    }
    if include_diff:
        unstaged = _git(repository, "diff", "--", pathspec).stdout
        staged = _git(repository, "diff", "--cached", "--", pathspec).stdout
        result["diff"] = unstaged
        result["staged_diff"] = staged
    return result
