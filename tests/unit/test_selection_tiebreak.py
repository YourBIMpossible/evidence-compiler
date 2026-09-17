"""Equal-score tie-break for budget selection: stem, distinct terms, path."""

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
from evidence_compiler.ranking import _item_tokens, rank, selection_key


def _item(kind, statement, refs, extra):
    return EvidenceItem(
        source_claim=SourceClaim(kind=kind, statement=statement, references=refs),
        provenance=Provenance(collector="ripgrep", extra=extra),
        authority="inferred",
        freshness="current",
        confidence=0.5,
    )


def _content(path, symbol, text=""):
    return _item("lexical_match", f"{symbol} at {path}:1  |  {text}", [f"{path}:1"], {"symbol": symbol})


def _stem(path, symbol):
    return _item(
        "lexical_filename",
        f"file name exactly matches `{symbol}`: {path}",
        [path],
        {"symbol": symbol, "evidence_source": "tracked_filename_stem", "exact_stem_match": True},
    )


def _packet(items, symbols, budget):
    p = EvidencePacket(
        identity=Identity(repository_root="/repo", head="h"),
        correlation=Correlation(prompt_hash="ph"),
        task=Task(raw_prompt_hash="ph", extracted_symbols=symbols),
    )
    p.budget.default_tokens = budget
    p.evidence.extend(items)
    return p


def _selected(p):
    return [e.source_claim.references[0] for e in p.evidence if e.compiler_assessment.selected]


def test_exact_stem_wins_equal_score_under_tight_budget():
    items = [_content("aaa/Invoke-NlFilterMonitor.ps1", "nl_filter"), _stem("backend/aec/nl_filter.py", "nl_filter")]
    p = _packet(copy.deepcopy(items), ["nl_filter"], 10_000)
    rank(p)
    scores = {e.compiler_assessment.final_score for e in p.evidence}
    assert len(scores) == 1  # frozen scores: a genuine tie
    costs = {e.source_claim.kind: _item_tokens(e) for e in p.evidence}
    budget = max(costs.values())  # room for exactly one item
    assert budget < sum(costs.values())
    tight = _packet(copy.deepcopy(items), ["nl_filter"], budget)
    rank(tight)
    assert _selected(tight) == ["backend/aec/nl_filter.py"]


def test_distinct_terms_then_path_break_remaining_ties():
    both = _content("zzz/b.py", "alpha", "alpha beta")
    one = _content("aaa/a.py", "alpha", "alpha only")
    syms = ["alpha", "beta"]
    assert selection_key(both, syms) < selection_key(one, syms)
    x, y = _content("B/x.py", "alpha"), _content("a/y.py", "alpha")
    assert selection_key(y, ["alpha"]) < selection_key(x, ["alpha"])


def test_tiebreak_never_overrides_a_higher_score():
    high = _content("zzz/high.py", "alpha")
    high.freshness = "current"
    low = _stem("aaa/alpha.py", "alpha")
    low.freshness = "stale"  # provisional penalty lowers the score
    p = _packet([high, low], ["alpha"], 10_000)
    rank(p)
    assert high.compiler_assessment.final_score > low.compiler_assessment.final_score
    assert selection_key(high, ["alpha"]) < selection_key(low, ["alpha"])


def test_scores_unchanged_by_tiebreak():
    items = [_content("a.py", "alpha"), _stem("alpha.py", "alpha")]
    p = _packet(copy.deepcopy(items), ["alpha"], 10_000)
    rank(p)
    assert [e.compiler_assessment.final_score for e in p.evidence] == [4.5, 4.5]
