"""Low-level git probes, used by both the compiler (identity binding) and the
git collector (evidence). Kept collector-agnostic and side-effect free.

Every call is bounded by a subprocess timeout and returns ``None`` / empty
rather than raising, so a missing or broken git never destabilizes callers.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field


@dataclass
class GitInfo:
    is_repo: bool = False
    head: str | None = None
    branch: str | None = None
    worktree_id: str | None = None
    dirty_paths: list[str] = field(default_factory=list)
    git_available: bool = True
    reason: str | None = None


def git_available() -> bool:
    return shutil.which("git") is not None


def _run(args: list[str], cwd: str, timeout_ms: int) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=max(timeout_ms, 1) / 1000.0,
            check=False,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None


def probe(cwd: str, timeout_ms: int = 1000) -> GitInfo:
    """Collect identity-level git facts for ``cwd`` within ``timeout_ms`` total.

    The budget is shared across the individual git calls so a slow repo cannot
    blow past the caller's deadline.
    """
    if not git_available():
        return GitInfo(git_available=False, reason="git binary not found on PATH")

    # is this inside a work tree?
    inside = _run(["rev-parse", "--is-inside-work-tree"], cwd, timeout_ms)
    if inside is None:
        return GitInfo(git_available=True, reason="git probe timed out or failed to launch")
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        return GitInfo(is_repo=False, reason="not a git work tree")

    per_call = max(timeout_ms // 4, 50)

    head = _run(["rev-parse", "HEAD"], cwd, per_call)
    head_val = head.stdout.strip() if head and head.returncode == 0 else None

    branch = _run(["rev-parse", "--abbrev-ref", "HEAD"], cwd, per_call)
    branch_val = branch.stdout.strip() if branch and branch.returncode == 0 else None
    if branch_val == "HEAD":  # detached
        branch_val = None

    worktree_id = _detect_worktree_id(cwd, per_call)

    status = _run(["status", "--porcelain", "-z"], cwd, per_call)
    dirty: list[str] = []
    if status and status.returncode == 0:
        dirty = _parse_porcelain_z(status.stdout)

    return GitInfo(
        is_repo=True,
        head=head_val,
        branch=branch_val,
        worktree_id=worktree_id,
        dirty_paths=dirty,
    )


def _detect_worktree_id(cwd: str, timeout_ms: int) -> str | None:
    """Return a stable id for a *linked* worktree, or ``None`` for the main tree."""
    git_dir = _run(["rev-parse", "--git-dir"], cwd, timeout_ms)
    common_dir = _run(["rev-parse", "--git-common-dir"], cwd, timeout_ms)
    if not (git_dir and common_dir and git_dir.returncode == 0 and common_dir.returncode == 0):
        return None
    gd = os.path.normpath(git_dir.stdout.strip())
    cd = os.path.normpath(common_dir.stdout.strip())
    if gd == cd:
        return None  # main work tree
    # linked worktree git-dir looks like <common>/worktrees/<name>
    return os.path.basename(gd) or gd


def _parse_porcelain_z(raw: str) -> list[str]:
    """Parse ``git status --porcelain -z`` output into a sorted path list.

    NUL-delimited; rename/copy entries carry two paths. We record the
    destination path (the current on-disk name).
    """
    paths: list[str] = []
    tokens = [t for t in raw.split("\0") if t != ""]
    i = 0
    while i < len(tokens):
        entry = tokens[i]
        xy = entry[:2]
        path = entry[3:] if len(entry) > 3 else ""
        if xy and (xy[0] in "RC" or xy[1] in "RC"):
            # rename/copy: next token is the source; keep destination (this one)
            i += 2
        else:
            i += 1
        if path:
            paths.append(path.replace("\\", "/"))
    return sorted(set(paths))
