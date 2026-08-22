"""Reusable test helpers and fake collectors (imported by tests, not a plugin)."""

from __future__ import annotations

import time

from evidence_compiler.collectors.base import (
    Collector,
    CollectorContext,
    EvidenceResult,
    RawClaim,
)


def make_context(repo: str, prompt: str, **kw) -> CollectorContext:
    return CollectorContext(
        repository_root=repo,
        cwd=kw.get("cwd", repo),
        prompt_text=prompt,
        prompt_hash="deadbeef",
        timeout_ms=kw.get("timeout_ms", 1000),
        active_file=kw.get("active_file"),
        extracted_symbols=kw.get("extracted_symbols", []),
        dirty_paths=kw.get("dirty_paths", []),
        head=kw.get("head"),
        config=kw.get("config", {}),
    )


class ThrowingCollector(Collector):
    name = "boom"

    def collect(self, context: CollectorContext) -> EvidenceResult:
        raise RuntimeError("intentional collector explosion")


class HangingCollector(Collector):
    name = "hang"

    def __init__(self, seconds: float = 30.0) -> None:
        self.seconds = seconds

    def collect(self, context: CollectorContext) -> EvidenceResult:
        time.sleep(self.seconds)  # far past any deadline
        return EvidenceResult(collector=self.name, status="ok")


class StaticCollector(Collector):
    """Emits fixed claims; useful for deterministic ranking/render tests."""

    name = "static"

    def __init__(self, claims: list[RawClaim], negatives=None):
        self.claims = claims
        self.negatives = negatives or []

    def collect(self, context: CollectorContext) -> EvidenceResult:
        return EvidenceResult(
            collector=self.name,
            status="ok" if self.claims else "empty",
            items=list(self.claims),
            negative_items=list(self.negatives),
        )
