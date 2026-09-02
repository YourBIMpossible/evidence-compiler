"""Collector plugin boundary (``docs/specifications/collector-interface-v1.md``).

A Collector is a *replaceable evidence source*. It gathers raw facts under a
hard timeout and emits provenance. It never decides task relevance, and it
never crashes the compiler: :func:`run_collector_safely` converts any
exception or overrun into a well-formed ``error`` / ``timeout`` result.
"""

from __future__ import annotations

import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from ..refs import split_line_suffix

# --------------------------------------------------------------------------
# Context in
# --------------------------------------------------------------------------


@dataclass
class CollectorContext:
    repository_root: str
    cwd: str
    prompt_text: str
    prompt_hash: str
    timeout_ms: int
    worktree_id: str | None = None
    active_file: str | None = None
    extracted_symbols: list[str] = field(default_factory=list)
    dirty_paths: list[str] = field(default_factory=list)
    head: str | None = None
    config: dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------
# Result out (logical EvidenceResult)
# --------------------------------------------------------------------------


@dataclass
class RawClaim:
    kind: str
    statement: str
    references: list[str] = field(default_factory=list)
    authority: str = "inferred"
    freshness: str = "unknown"
    confidence: float = 0.0
    # provenance sub-fields
    command: str | None = None
    source_revision: str | None = None
    graph_hash: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class RawNegative:
    query: str
    outcome: str
    searched_roots: list[str] = field(default_factory=list)
    diagnostic: dict[str, Any] = field(default_factory=dict)


@dataclass
class EvidenceResult:
    collector: str
    status: str  # ok | empty | timeout | error | skipped
    duration_ms: float = 0.0
    items: list[RawClaim] = field(default_factory=list)
    negative_items: list[RawNegative] = field(default_factory=list)
    diagnostic: dict[str, Any] = field(default_factory=dict)
    error_message: str | None = None


class Collector(ABC):
    """Base class. Subclasses implement :meth:`collect` only."""

    #: stable registration name, e.g. ``"git"``
    name: str = "collector"

    @abstractmethod
    def collect(self, context: CollectorContext) -> EvidenceResult:
        """Gather evidence for ``context``. Must honor ``context.timeout_ms``.

        Implementations should return a ``skipped``/``empty``/``timeout`` result
        rather than raising; :func:`run_collector_safely` is the last-resort
        isolation layer, not the primary error path.
        """
        raise NotImplementedError


def run_collector_safely(collector: Collector, context: CollectorContext) -> EvidenceResult:
    """Run ``collector.collect`` with failure isolation and duration capture.

    Any exception is downgraded to ``status: error`` with a diagnostic — a
    collector may never propagate a crash into the compiler process
    (interface spec §4, invariant 2).
    """
    start = time.perf_counter()
    try:
        result = collector.collect(context)
        if result.duration_ms == 0.0:
            result.duration_ms = _elapsed_ms(start)
        return result
    except Exception as exc:  # noqa: BLE001 - deliberate broad isolation boundary
        return EvidenceResult(
            collector=getattr(collector, "name", "unknown"),
            status="error",
            duration_ms=_elapsed_ms(start),
            diagnostic={"exception_type": type(exc).__name__},
            error_message=str(exc),
        )


def _elapsed_ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000.0, 3)


# --------------------------------------------------------------------------
# Path normalization (interface spec §4: repo-relative POSIX; accept Windows)
# --------------------------------------------------------------------------

def normalize_path(path: str, repository_root: str) -> str:
    """Return a repo-relative, POSIX-style path when ``path`` is inside the repo.

    Accepts Windows (``\\``) or POSIX input. Paths already relative are
    POSIX-normalized. Paths outside the repo are returned POSIX-normalized but
    absolute (never silently rewritten to a wrong repo-relative form).
    """
    if not path:
        return path
    raw = path.replace("\\", "/")
    root = (repository_root or "").replace("\\", "/").rstrip("/")

    candidate = raw
    if os.path.isabs(path) or (len(path) > 1 and path[1] == ":"):
        # absolute (POSIX or Windows drive) — try to relativize against root
        if root:
            try:
                rel = os.path.relpath(raw, root)
                rel_posix = rel.replace("\\", "/")
                if not rel_posix.startswith(".."):
                    return _posix_clean(rel_posix)
            except ValueError:
                # different drive on Windows; fall through to absolute form
                pass
        return _posix_clean(raw)
    return _posix_clean(candidate)


def normalize_reference(reference: str, repository_root: str) -> str:
    """Normalize a ``path`` or ``path:line[:col]`` reference, preserving the suffix."""
    if not reference:
        return reference
    path_part, suffix, _line = split_line_suffix(reference)
    return normalize_path(path_part, repository_root) + suffix


def _posix_clean(path: str) -> str:
    # Collapse redundant separators / dot segments without touching drive roots.
    if not path:
        return path
    parts = path.split("/")
    out: list[str] = []
    for i, part in enumerate(parts):
        if part == "" and i != 0:
            continue
        if part == ".":
            continue
        out.append(part)
    cleaned = "/".join(out)
    return cleaned or "."
