"""The Evidence Compiler — scope, run collectors, assemble packet, rank, render.

This is the deterministic critical path. It runs collectors concurrently under
a bounded end-to-end deadline, isolates every collector failure, and always
produces a persisted :class:`EvidencePacket` plus a (possibly empty)
ContextBrief. It never raises into the caller for a collector problem — the
adapter's fail-open guarantee rests on that.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, replace

from . import gitprobe, scoping
from .collectors import BUILTIN_COLLECTORS, Collector, CollectorContext, run_collector_safely
from .collectors.base import EvidenceResult, RawClaim, RawNegative
from .config import Config, load_config
from .packet import (
    CollectorRun,
    CompilerAssessment,
    Correlation,
    EvidenceItem,
    EvidencePacket,
    Identity,
    NegativeEvidenceItem,
    Provenance,
    ScoreComponents,
    SourceClaim,
    Timing,
    new_id,
    utcnow_iso,
)
from .ranking import rank
from .rendering import RenderResult, render_brief


@dataclass
class CompileResult:
    packet: EvidencePacket
    brief: str
    storage_path: str | None
    render: RenderResult


def compile_packet(
    prompt: str,
    repository_root: str,
    *,
    cwd: str | None = None,
    active_file: str | None = None,
    session_id: str | None = None,
    turn_id: str | None = None,
    config: Config | None = None,
    collectors: list[Collector] | None = None,
    deadline_ms: int | None = None,
    persist: bool = True,
) -> CompileResult:
    start = time.perf_counter()
    stages: dict[str, float] = {}

    repository_root = _normroot(repository_root)
    cwd = _normroot(cwd or repository_root)
    cfg = config or load_config(repository_root)
    deadline = deadline_ms if deadline_ms is not None else cfg.deadline_ms

    # -- scope --------------------------------------------------------------
    t0 = time.perf_counter()
    task = scoping.build_task(prompt, active_file)
    git_info = gitprobe.probe(cwd, timeout_ms=min(cfg.collector_timeout_ms("git"), 1000))
    identity = Identity(
        repository_root=repository_root,
        session_id=session_id,
        turn_id=turn_id,
        worktree_id=git_info.worktree_id,
        head=git_info.head,
        branch=git_info.branch,
    )
    scope = scoping.build_scope(task, git_info.head)
    stages["scope_ms"] = _ms(t0)

    context = CollectorContext(
        repository_root=repository_root,
        cwd=cwd,
        prompt_text=prompt,
        prompt_hash=task.raw_prompt_hash,
        timeout_ms=0,  # per-collector value assigned in the runner
        worktree_id=git_info.worktree_id,
        active_file=active_file,
        extracted_symbols=task.extracted_symbols,
        dirty_paths=git_info.dirty_paths,
        head=git_info.head,
    )

    active = collectors if collectors is not None else _default_collectors()

    # -- collect (parallel, deadline-bounded, failure-isolated) -------------
    t0 = time.perf_counter()
    results, runs = _run_collectors(active, context, cfg, deadline)
    stages["collect_ms"] = _ms(t0)

    # -- assemble packet ----------------------------------------------------
    t0 = time.perf_counter()
    packet = EvidencePacket(
        identity=identity,
        correlation=Correlation(prompt_hash=task.raw_prompt_hash),
        task=task,
        scope=scope,
        collectors_run=runs,
    )
    packet.budget.min_tokens = cfg.budget["min_tokens"]
    packet.budget.default_tokens = cfg.budget["default_tokens"]
    packet.budget.max_tokens = cfg.budget["max_tokens"]

    for collector in active:
        result = results.get(collector.name)
        if result is None:
            continue
        for claim in result.items:
            packet.evidence.append(_to_item(claim, collector.name))
        for neg in result.negative_items:
            packet.negative_evidence.append(_to_negative(neg, collector.name))
    stages["assemble_ms"] = _ms(t0)

    # -- rank ---------------------------------------------------------------
    t0 = time.perf_counter()
    rank(packet)
    stages["rank_ms"] = _ms(t0)

    # -- render + reconcile budget -----------------------------------------
    # A trial render (read-only — rendering.py never mutates the packet) is
    # used to discover any items ranking selected but the renderer's more
    # precise token accounting cannot fit. Reconciliation applies BEFORE the
    # packet is used for its official render, so the packet is fully
    # finalized at that point and never mutated afterward (packet spec §1:
    # EvidencePacket is immutable truth; ContextBrief is only a derived,
    # budgeted view of it — never the other way around).
    t0 = time.perf_counter()
    trial = render_brief(packet)
    _reconcile_dropped(packet, trial)
    render = render_brief(packet) if trial.dropped_ids else trial
    packet.budget.injected_tokens = render.tokens
    stages["render_ms"] = _ms(t0)

    packet.timing = Timing(total_ms=_ms(start), stages=stages)

    # -- persist (best effort; never fatal) ---------------------------------
    storage_path: str | None = None
    if persist:
        try:
            from .storage import save_packet

            storage_path = save_packet(packet, cfg.storage_dir(repository_root))
        except Exception:  # noqa: BLE001 - persistence must not break the path
            storage_path = None

    return CompileResult(packet=packet, brief=render.text, storage_path=storage_path, render=render)


# --------------------------------------------------------------------------
# Collector execution
# --------------------------------------------------------------------------


def _default_collectors() -> list[Collector]:
    return [cls() for cls in BUILTIN_COLLECTORS]


def _run_collectors(
    collectors: list[Collector], context: CollectorContext, cfg: Config, deadline_ms: int
) -> tuple[dict[str, EvidenceResult], list[CollectorRun]]:
    """Run each enabled collector on its own daemon thread, bounded by an
    end-to-end deadline. Disabled collectors are recorded as ``skipped``;
    collectors still running at the deadline are recorded as ``timeout``.

    Daemon threads guarantee that a genuinely hung collector cannot hold up
    process exit for the adapter — we stop *waiting*, the packet is assembled
    from whatever finished, and the stray thread dies with the process.
    """
    results: dict[str, EvidenceResult] = {}
    threads: dict[str, threading.Thread] = {}
    enabled: list[Collector] = []
    runs_by_name: dict[str, CollectorRun] = {}

    for collector in collectors:
        name = collector.name
        if not cfg.collector_enabled(name):
            runs_by_name[name] = CollectorRun(
                name=name,
                status="skipped",
                duration_ms=0.0,
                diagnostic={"reason": "disabled in config"},
            )
            continue
        enabled.append(collector)

    def worker(col: Collector, ctx: CollectorContext) -> None:
        results[col.name] = run_collector_safely(col, ctx)

    launch = time.perf_counter()
    for collector in enabled:
        ctx = replace(context, timeout_ms=cfg.collector_timeout_ms(collector.name))
        t = threading.Thread(target=worker, args=(collector, ctx), daemon=True)
        threads[collector.name] = t
        t.start()

    deadline_at = launch + max(deadline_ms, 1) / 1000.0
    for name, t in threads.items():
        remaining = deadline_at - time.perf_counter()
        t.join(timeout=max(remaining, 0.0))

    for collector in enabled:
        name = collector.name
        result = results.get(name)
        if result is None:
            # never finished before the end-to-end deadline
            runs_by_name[name] = CollectorRun(
                name=name,
                status="timeout",
                duration_ms=round((time.perf_counter() - launch) * 1000.0, 3),
                diagnostic={"reason": "end-to-end deadline exceeded before collector returned"},
            )
        else:
            runs_by_name[name] = CollectorRun(
                name=name,
                status=result.status,
                duration_ms=result.duration_ms,
                diagnostic=dict(result.diagnostic or {}),
            )

    # preserve registration order in collectors_run
    ordered = [runs_by_name[c.name] for c in collectors if c.name in runs_by_name]
    return results, ordered


# --------------------------------------------------------------------------
# Raw → packet conversion
# --------------------------------------------------------------------------


def _to_item(claim: RawClaim, collector_name: str) -> EvidenceItem:
    return EvidenceItem(
        source_claim=SourceClaim(
            kind=claim.kind,
            statement=claim.statement,
            references=list(claim.references),
        ),
        provenance=Provenance(
            collector=collector_name,
            command=claim.command,
            captured_at=utcnow_iso(),
            source_revision=claim.source_revision,
            graph_hash=claim.graph_hash,
            extra=dict(claim.extra or {}),
        ),
        authority=claim.authority,
        freshness=claim.freshness,
        confidence=float(claim.confidence),
        compiler_assessment=CompilerAssessment(components=ScoreComponents()),
        status="omitted",
        id=new_id("ev"),
    )


def _to_negative(neg: RawNegative, collector_name: str) -> NegativeEvidenceItem:
    return NegativeEvidenceItem(
        query=neg.query,
        collector=collector_name,
        outcome=neg.outcome,
        searched_roots=list(neg.searched_roots),
        captured_at=utcnow_iso(),
        diagnostic=dict(neg.diagnostic or {}),
        id=new_id("ev_abs"),
    )


def _reconcile_dropped(packet: EvidencePacket, render: RenderResult) -> None:
    """Any item selected by ranking but dropped by the renderer's hard budget
    becomes an omitted item, so the packet stays consistent with the brief."""
    if not render.dropped_ids:
        return
    dropped = set(render.dropped_ids)
    for item in packet.evidence:
        if item.id in dropped:
            item.compiler_assessment.selected = False
            if not item.compiler_assessment.omitted_because:
                item.compiler_assessment.omitted_because = ["dropped to fit max token budget"]
            if item.status != "provisional":
                item.status = "omitted"
            if item.id not in packet.budget.omitted_evidence_ids:
                packet.budget.omitted_evidence_ids.append(item.id)


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------


def _ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000.0, 3)


def _normroot(path: str) -> str:
    import os

    return os.path.abspath(path).replace("\\", "/")
