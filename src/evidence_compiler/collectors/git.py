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

        # The compiler already bound identity with its own (larger) probe
        # budget; if this collector's shorter probe timed out on HEAD, reuse
        # the bound value rather than reporting "unknown" for a known commit.
        head = info.head
        head_state = info.head_state
        if head is None and head_state == "probe_timeout" and context.head:
            head = context.head
            head_state = "resolved"

        items: list[RawClaim] = []

        head_short = (head or "")[:12] or "unknown"
        if info.branch:
            branch = info.branch
        elif info.detached:
            branch = "(detached)"
        else:
            branch = "(unknown)"
        statement = f"HEAD {head_short} on branch {branch}"
        if head is None and head_state == "probe_timeout":
            statement += "  [git probe timed out; HEAD not resolved]"
        items.append(
            RawClaim(
                kind="git_meta",
                statement=statement,
                references=[],
                authority="authoritative",
                freshness="current",
                confidence=1.0,
                command="git rev-parse HEAD / --abbrev-ref HEAD",
                source_revision=head,
                extra={
                    "branch": info.branch,
                    "worktree_id": info.worktree_id,
                    "dirty_count": len(info.dirty_paths),
                    "head_state": head_state,
                    "detached": info.detached,
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
                    source_revision=head,
                    extra={"path": ref},
                )
            )

        status = "ok" if items else "empty"
        diagnostic: dict = {"dirty_count": len(info.dirty_paths), "head_state": head_state}
        if info.reason and head is None:
            diagnostic["reason"] = info.reason
        if status == "empty":
            diagnostic["reason"] = "no git metadata produced"
        return EvidenceResult(
            collector=self.name,
            status=status,
            items=items,
            diagnostic=diagnostic,
        )
