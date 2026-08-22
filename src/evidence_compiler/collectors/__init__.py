"""Built-in collectors and the default registry."""

from __future__ import annotations

from .base import (
    Collector,
    CollectorContext,
    EvidenceResult,
    RawClaim,
    RawNegative,
    normalize_path,
    normalize_reference,
    run_collector_safely,
)
from .git import GitCollector
from .graphify import GraphifyCollector
from .ripgrep import RipgrepCollector

# Deterministic registration order (also the default run order).
BUILTIN_COLLECTORS: list[type[Collector]] = [
    GitCollector,
    RipgrepCollector,
    GraphifyCollector,
]

__all__ = [
    "Collector",
    "CollectorContext",
    "EvidenceResult",
    "RawClaim",
    "RawNegative",
    "GitCollector",
    "RipgrepCollector",
    "GraphifyCollector",
    "BUILTIN_COLLECTORS",
    "normalize_path",
    "normalize_reference",
    "run_collector_safely",
]
