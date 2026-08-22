"""ContextBrief rendering (build brief §4)."""

from __future__ import annotations

from evidence_compiler.packet import (
    Correlation,
    EvidenceItem,
    EvidencePacket,
    Identity,
    NegativeEvidenceItem,
    Provenance,
    SourceClaim,
    Task,
)
from evidence_compiler.ranking import rank
from evidence_compiler.rendering import render_brief
from evidence_compiler.scoping import estimate_tokens


def _item(kind, statement, refs, authority="inferred", freshness="current", symbol=None):
    return EvidenceItem(
        source_claim=SourceClaim(kind=kind, statement=statement, references=refs),
        provenance=Provenance(collector="rg", extra={"symbol": symbol} if symbol else {}),
        authority=authority,
        freshness=freshness,
        confidence=0.6,
    )


def _packet(items, symbols=None, negatives=None, max_tokens=1200):
    p = EvidencePacket(
        identity=Identity(repository_root="/repo", head="abc123"),
        correlation=Correlation(prompt_hash="ph"),
        task=Task(raw_prompt_hash="ph", extracted_symbols=symbols or []),
    )
    p.budget.max_tokens = max_tokens
    p.evidence.extend(items)
    p.negative_evidence.extend(negatives or [])
    return p


def test_empty_selection_renders_nothing():
    # genuinely irrelevant: non-lexical kind, no symbol/active-file tie,
    # unknown freshness, inferred authority → score 0 → relevance none.
    p = _packet(
        [_item("other", "unrelated note", ["z.py:1"], freshness="unknown")],
        symbols=["Nonexistent"],
    )
    rank(p)
    result = render_brief(p)
    assert result.text == ""
    assert result.tokens == 0


def test_brief_within_max_token_budget():
    items = [
        _item("lexical_def", f"AlphaService number {i}", [f"src/f{i}.py:{i}"], symbol="AlphaService")
        for i in range(80)
    ]
    p = _packet(items, symbols=["AlphaService"], max_tokens=200)
    rank(p)
    result = render_brief(p)
    assert estimate_tokens(result.text) <= p.budget.max_tokens


def test_selected_reference_preserved():
    p = _packet(
        [_item("lexical_def", "AlphaService at src/alpha.py:3", ["src/alpha.py:3"], symbol="AlphaService")],
        symbols=["AlphaService"],
    )
    rank(p)
    result = render_brief(p)
    assert "src/alpha.py:3" in result.text
    assert "packet_id" in result.text


def test_provisional_marked_not_verified():
    p = _packet(
        [_item("git_dirty", "dirty: src/beta.py", ["src/beta.py"], authority="authoritative", freshness="dirty_overlay")],
    )
    rank(p)
    result = render_brief(p)
    if result.text:  # selected as repository context
        assert "provisional" in result.text.lower()


def test_omitted_items_scoring_reasons_never_surface_in_brief():
    # F-3 regression: an omitted item's `selected_because` (scoring context,
    # not a selection claim) must never appear in the rendered brief.
    p = _packet(
        [_item("other", "unrelated note", ["z.py:1"], freshness="unknown")],
        symbols=["Nonexistent"],
    )
    rank(p)
    item = p.evidence[0]
    assert item.compiler_assessment.selected is False
    assert item.compiler_assessment.omitted_because
    assert item.compiler_assessment.selected_because == ["no scope relationship found"]
    result = render_brief(p)
    assert result.text == ""
    assert "no scope relationship found" not in result.text


def test_absence_section_rendered():
    neg = NegativeEvidenceItem(query="OriginSystem", collector="rg", outcome="no_existing_reference", searched_roots=["."])
    p = _packet([], negatives=[neg])
    rank(p)
    result = render_brief(p)
    assert "OriginSystem" in result.text
    assert "Absence" in result.text
