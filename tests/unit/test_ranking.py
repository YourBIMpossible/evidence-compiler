"""Deterministic ranking (build brief §3)."""

from __future__ import annotations

import copy

from evidence_compiler.packet import (
    Correlation,
    EvidenceItem,
    EvidencePacket,
    Identity,
    Provenance,
    SourceClaim,
    Task,
)
from evidence_compiler.ranking import rank


def _item(kind, statement, refs, authority="inferred", freshness="current", symbol=None):
    prov = Provenance(collector="test", extra={"symbol": symbol} if symbol else {})
    return EvidenceItem(
        source_claim=SourceClaim(kind=kind, statement=statement, references=refs),
        provenance=prov,
        authority=authority,
        freshness=freshness,
        confidence=0.5,
    )


def _packet(items, symbols=None, active_file=None, budget_default=1000):
    p = EvidencePacket(
        identity=Identity(repository_root="/repo", head="h"),
        correlation=Correlation(prompt_hash="ph"),
        task=Task(raw_prompt_hash="ph", extracted_symbols=symbols or [], active_file=active_file),
    )
    p.budget.default_tokens = budget_default
    p.evidence.extend(items)
    return p


def test_ranking_is_deterministic():
    items = [
        _item("lexical_def", "AlphaService at src/alpha.py:3", ["src/alpha.py:3"], symbol="AlphaService"),
        _item("git_dirty", "dirty: src/beta.py", ["src/beta.py"], authority="authoritative", freshness="dirty_overlay"),
        _item("lexical_match", "AlphaService at src/beta.py:3", ["src/beta.py:3"], symbol="AlphaService"),
    ]
    p1 = _packet(copy.deepcopy(items), symbols=["AlphaService"], active_file="src/alpha.py")
    p2 = _packet(copy.deepcopy(items), symbols=["AlphaService"], active_file="src/alpha.py")
    rank(p1)
    rank(p2)
    assert p1.to_dict()["evidence"] == p2.to_dict()["evidence"]
    assert p1.budget.injected_tokens == p2.budget.injected_tokens


def test_every_item_has_reasons():
    items = [_item("lexical_def", "AlphaService at a.py:1", ["a.py:1"], symbol="AlphaService")]
    p = _packet(items, symbols=["AlphaService"])
    rank(p)
    for e in p.evidence:
        if e.compiler_assessment.selected:
            assert e.compiler_assessment.selected_because
        else:
            assert e.compiler_assessment.omitted_because


def test_components_populated_not_opaque():
    items = [_item("lexical_def", "AlphaService at a.py:1", ["a.py:1"], symbol="AlphaService")]
    p = _packet(items, symbols=["AlphaService"], active_file="a.py")
    rank(p)
    comp = p.evidence[0].compiler_assessment.components
    assert comp.direct_symbol > 0
    assert comp.lexical_reference > 0
    assert comp.active_file > 0
    # final score equals the component total (no hidden magic)
    assert abs(p.evidence[0].compiler_assessment.final_score - comp.total()) < 1e-6


def test_provisional_dirty_is_penalized_and_flagged():
    items = [_item("git_dirty", "dirty: b.py", ["b.py"], authority="authoritative", freshness="dirty_overlay")]
    p = _packet(items)
    rank(p)
    assert p.evidence[0].compiler_assessment.components.provisional_penalty > 0
    assert p.evidence[0].status == "provisional"


def test_budget_limits_selection():
    # many high-scoring items but a tiny budget → not all selected
    items = [
        _item("lexical_def", f"AlphaService match number {i} here", [f"src/f{i}.py:{i}"], symbol="AlphaService")
        for i in range(50)
    ]
    p = _packet(items, symbols=["AlphaService"], budget_default=60)
    rank(p)
    selected = [e for e in p.evidence if e.compiler_assessment.selected]
    assert 0 < len(selected) < 50
    assert p.budget.injected_tokens <= p.budget.default_tokens
    assert p.budget.omitted_evidence_ids


def test_duplicate_heavy_input_does_not_explode():
    items = [_item("lexical_match", "AlphaService at a.py:1", ["a.py:1"], symbol="AlphaService") for _ in range(200)]
    p = _packet(items, symbols=["AlphaService"])
    rank(p)  # must simply complete
    dup_penalized = [e for e in p.evidence if e.compiler_assessment.components.duplication_penalty > 0]
    assert len(dup_penalized) == 199  # all but the first
