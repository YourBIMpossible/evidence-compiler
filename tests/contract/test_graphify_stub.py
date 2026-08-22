"""Graphify Phase 1A stub: always skipped / not implemented (build brief §1)."""

from __future__ import annotations

from evidence_compiler.collectors.graphify import GraphifyCollector
from tests.support import make_context


def test_graphify_is_skipped_not_implemented(golden_repo):
    result = GraphifyCollector().collect(make_context(golden_repo, "anything"))
    assert result.status == "skipped"
    assert result.diagnostic.get("reason") == "not implemented"
    assert result.items == []
