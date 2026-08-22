"""Graphify collector — Phase 1A stub.

Graphify is an *optional* structural collector. Phase 1A ships a stub that
always reports ``status: skipped`` with ``diagnostic.reason: "not implemented"``
(build brief §1). Real graph query/path/explain integration is deferred; see
``docs/graphify-evaluation.md`` and ``docs/roadmap.md`` (Tier 2+, metrics-gated).

The stub still honors the enabled/disabled config switch so the compiler and
config surface behave exactly as they will once a real implementation lands.
"""

from __future__ import annotations

from .base import Collector, CollectorContext, EvidenceResult


class GraphifyCollector(Collector):
    name = "graphify"

    def collect(self, context: CollectorContext) -> EvidenceResult:
        return EvidenceResult(
            collector=self.name,
            status="skipped",
            diagnostic={
                "reason": "not implemented",
                "index_current": "unknown",
                "language_supported": "unknown",
                "roadmap": "structural collector deferred beyond Phase 1A",
            },
        )
