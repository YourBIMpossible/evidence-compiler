"""Git collector — HEAD, branch, and dirty-path evidence.

Enabled by default when a git work tree is detected; otherwise returns
``status: skipped`` with an explicit diagnostic (interface spec §5).
"""

from __future__ import annotations

from .. import gitprobe
from .base import Collector, CollectorContext, EvidenceResult, RawClaim, normalize_reference


class GitCollector(Collector):
    name = "git"

    def collect(self, context: CollectorContext) -> EvidenceResult:
        if not gitprobe.git_available():
            return EvidenceResult(
                collector=self.name,
                status="skipped",
                diagnostic={"reason": "git binary not found on PATH"},
            )

        info = gitprobe.probe(context.cwd or context.repository_root, timeout_ms=context.timeout_ms)
        if not info.is_repo:
            return EvidenceResult(
                collector=self.name,
                status="skipped",
                diagnostic={"reason": info.reason or "not a git work tree"},
            )

        items: list[RawClaim] = []

        head_short = (info.head or "")[:12] or "unknown"
        branch = info.branch or "(detached)"
        items.append(
            RawClaim(
                kind="git_meta",
                statement=f"HEAD {head_short} on branch {branch}",
                references=[],
                authority="authoritative",
                freshness="current",
                confidence=1.0,
                command="git rev-parse HEAD / --abbrev-ref HEAD",
                source_revision=info.head,
                extra={
                    "branch": info.branch,
                    "worktree_id": info.worktree_id,
                    "dirty_count": len(info.dirty_paths),
                },
            )
        )

        for path in info.dirty_paths:
            ref = normalize_reference(path, context.repository_root)
            items.append(
                RawClaim(
                    kind="git_dirty",
                    statement=f"dirty: {ref}",
                    references=[ref],
                    authority="authoritative",
                    freshness="dirty_overlay",
                    confidence=1.0,
                    command="git status --porcelain",
                    source_revision=info.head,
                    extra={"path": ref},
                )
            )

        status = "ok" if items else "empty"
        diagnostic: dict = {"dirty_count": len(info.dirty_paths)}
        if status == "empty":
            diagnostic["reason"] = "no git metadata produced"
        return EvidenceResult(
            collector=self.name,
            status=status,
            items=items,
            diagnostic=diagnostic,
        )
