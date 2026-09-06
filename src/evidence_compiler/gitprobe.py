"""Low-level git probes, used by both the compiler (identity binding) and the
git collector (evidence). Kept collector-agnostic and side-effect free.

Every call is bounded by a subprocess timeout and returns ``None`` / empty
rather than raising, so a missing or broken git never destabilizes callers.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field

# Smallest per-call budget: a git invocation below this is a guaranteed
# timeout on a loaded machine (Window 2: ``max(250 // 4, 50)`` = 62 ms let
# ``rev-parse HEAD`` time out 15× and bind packets to ``head: null``).
_MIN_CALL_MS = 100

# ``head_state`` vocabulary: why ``head`` is or is not populated.
HEAD_STATES = ("resolved", "probe_timeout", "unresolved")


@dataclass
class GitInfo:
    is_repo: bool = False
    head: str | None = None
    branch: str | None = None
    worktree_id: str | None = None
    dirty_paths: list[str] = field(default_factory=list)
    git_available: bool = True
    reason: str | None = None
    #: ``resolved`` (head is a commit), ``probe_timeout`` (git did not answer
    #: within budget — head unknown, NOT detached), ``unresolved`` (git
    #: answered but has no HEAD commit, e.g. an unborn branch).
    head_state: str = "unresolved"
    #: True when git reported HEAD is not on a branch.
    detached: bool = False
    #: ``resolved`` (``git status`` answered; ``dirty_paths`` is complete),
    #: ``probe_timeout`` (status did not answer within the remaining budget),
    #: ``error`` (status exited non-zero). Anything but ``resolved`` means the
    #: dirty overlay is unknown, *not* clean — consumers must not read an
    #: empty ``dirty_paths`` as "no uncommitted changes".
    dirty_state: str = "resolved"


def git_available() -> bool:
    return shutil.which("git") is not None


def _run(args: list[str], cwd: str, timeout_ms: int) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(timeout_ms, 1) / 1000.0,
            check=False,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None


class _Budget:
    """Shared wall-clock budget: each call gets the larger of an even share of
    what is left and the floor, never more than what is left."""

    def __init__(self, total_ms: int, calls: int) -> None:
        self._deadline = time.perf_counter() + max(total_ms, _MIN_CALL_MS) / 1000.0
        self._calls_left = max(calls, 1)

    def next_ms(self) -> int:
        remaining = int((self._deadline - time.perf_counter()) * 1000)
        share = remaining // self._calls_left
        self._calls_left = max(self._calls_left - 1, 1)
        return max(min(max(share, _MIN_CALL_MS), max(remaining, 1)), 1)


def probe(cwd: str, timeout_ms: int = 1000) -> GitInfo:
    """Collect identity-level git facts for ``cwd`` within ``timeout_ms`` total.

    The budget is shared across the individual git calls so a slow repo cannot
    blow past the caller's deadline; every call still gets at least
    ``_MIN_CALL_MS`` so a tight budget degrades to fewer answered probes, not
    to probes that cannot possibly answer.
    """
    if not git_available():
        return GitInfo(git_available=False, reason="git binary not found on PATH")

    budget = _Budget(timeout_ms, calls=6)

    # is this inside a work tree?
    inside = _run(["rev-parse", "--is-inside-work-tree"], cwd, budget.next_ms())
    if inside is None:
        return GitInfo(git_available=True, reason="git probe timed out or failed to launch")
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        return GitInfo(is_repo=False, reason="not a git work tree")

    head = _run(["rev-parse", "HEAD"], cwd, budget.next_ms())
    if head is None:
        head_val, head_state = None, "probe_timeout"
    elif head.returncode == 0 and head.stdout.strip():
        head_val, head_state = head.stdout.strip(), "resolved"
    else:
        head_val, head_state = None, "unresolved"

    branch = _run(["rev-parse", "--abbrev-ref", "HEAD"], cwd, budget.next_ms())
    branch_val = branch.stdout.strip() if branch and branch.returncode == 0 else None
    detached = False
    if branch_val == "HEAD":  # git's spelling of "not on a branch"
        branch_val = None
        detached = True

    worktree_id = _detect_worktree_id(cwd, budget)

    status = _run(["status", "--porcelain", "-z"], cwd, budget.next_ms())
    dirty: list[str] = []
    if status is None:
        dirty_state = "probe_timeout"
    elif status.returncode == 0:
        dirty, dirty_state = _parse_porcelain_z(status.stdout), "resolved"
    else:
        dirty_state = "error"

    reason = None
    if head_state == "probe_timeout":
        reason = "git rev-parse HEAD did not answer within budget"
    elif head_state == "unresolved":
        reason = "git has no HEAD commit (unborn branch)"

    return GitInfo(
        is_repo=True,
        head=head_val,
        branch=branch_val,
        worktree_id=worktree_id,
        dirty_paths=dirty,
        reason=reason,
        head_state=head_state,
        detached=detached,
        dirty_state=dirty_state,
    )


def _detect_worktree_id(cwd: str, budget: _Budget) -> str | None:
    """Return a stable id for a *linked* worktree, or ``None`` for the main tree."""
    git_dir = _run(["rev-parse", "--git-dir"], cwd, budget.next_ms())
    common_dir = _run(["rev-parse", "--git-common-dir"], cwd, budget.next_ms())
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
