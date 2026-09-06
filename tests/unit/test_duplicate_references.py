"""Duplicate rendered references fold into one brief line (dogfood gap 5).

Two selected items that cite exactly the same reference(s) from the same
collector and kind render once; the folded item's symbol appears on the
survivor's ``why`` line and the packet records the fold. Distinct references
(other line, other column, other collector, other kind, malformed strings) are
never merged.
"""

from __future__ import annotations

from evidence_compiler import compiler as compiler_mod
from evidence_compiler.collectors.base import RawClaim
from evidence_compiler.packet import (
    Correlation,
    EvidenceItem,
    EvidencePacket,
    Identity,
    Provenance,
    SourceClaim,
    Task,
)
from evidence_compiler.refs import split_line_suffix
from evidence_compiler.rendering import (
    duplicate_reference_key,
    fold_duplicate_references,
    render_brief,
)
from tests.support import StaticCollector


def _item(refs, *, symbol, collector="rg", kind="lexical_ref", statement=None, score=1.0):
    statement = statement or f"{symbol} at {', '.join(refs)}  |  snippet"
    item = EvidenceItem(
        source_claim=SourceClaim(kind=kind, statement=statement, references=list(refs)),
        provenance=Provenance(collector=collector, extra={"symbol": symbol}),
        authority="inferred",
        freshness="current",
        confidence=0.6,
    )
    item.compiler_assessment.selected = True
    item.compiler_assessment.final_score = score
    item.compiler_assessment.selected_because = [f"references prompt symbol '{symbol}'"]
    return item


def _packet(items, max_tokens=1200):
    p = EvidencePacket(
        identity=Identity(repository_root="/repo", head="abc123"),
        correlation=Correlation(prompt_hash="ph"),
        task=Task(raw_prompt_hash="ph", extracted_symbols=["pyproject.toml", "toml"]),
    )
    p.budget.max_tokens = max_tokens
    p.evidence.extend(items)
    return p


def _brief_lines(text):
    return [line for line in text.splitlines() if line.startswith("- [")]


def _body(text):
    """Brief text without the header line (which carries the random packet id)."""
    return "\n".join(text.splitlines()[1:])


# -- identical references fold ---------------------------------------------


def test_identical_references_render_once_with_also_symbol():
    a = _item(["pyproject.toml:3"], symbol="pyproject.toml", score=0.9)
    b = _item(["pyproject.toml:3"], symbol="toml", score=0.7)
    r = render_brief(_packet([a, b]))
    assert len(_brief_lines(r.text)) == 1
    assert "pyproject.toml at pyproject.toml:3" in r.text
    assert "also matches toml" in r.text
    assert r.rendered_ids == [a.id]
    assert r.merged_ids == {b.id: a.id}
    assert r.dropped_ids == []


def test_survivor_is_the_higher_scored_item_regardless_of_input_order():
    low = _item(["src/a.py:10"], symbol="alpha", score=0.5)
    high = _item(["src/a.py:10"], symbol="Alpha", score=0.9)
    r1 = render_brief(_packet([low, high]))
    r2 = render_brief(_packet([high, low]))
    assert _body(r1.text) == _body(r2.text)
    assert r1.merged_ids == {low.id: high.id}


def test_windows_and_posix_separators_are_the_same_reference():
    a = _item(["src\\a.py:10"], symbol="alpha", score=0.9)
    b = _item(["src/a.py:10"], symbol="beta", score=0.8)
    assert duplicate_reference_key(a) == duplicate_reference_key(b)


# -- distinct references stay distinct -------------------------------------


def test_same_file_different_line_is_not_merged():
    a = _item(["src/a.py:10"], symbol="alpha", score=0.9)
    b = _item(["src/a.py:11"], symbol="alpha", score=0.8)
    r = render_brief(_packet([a, b]))
    assert len(_brief_lines(r.text)) == 2
    assert r.merged_ids == {}


def test_same_file_and_line_different_column_is_not_merged():
    a = _item(["src/a.py:10"], symbol="alpha", score=0.9)
    b = _item(["src/a.py:10:5"], symbol="alpha", score=0.8)
    # refs.py folds both to the same (path, line) sort key ...
    assert split_line_suffix("src/a.py:10")[0] == split_line_suffix("src/a.py:10:5")[0]
    # ... but rendering keeps the verbatim reference identity.
    assert duplicate_reference_key(a) != duplicate_reference_key(b)
    assert render_brief(_packet([a, b])).merged_ids == {}


def test_cross_collector_or_cross_kind_duplicates_are_not_merged():
    rg = _item(["src/a.py:10"], symbol="alpha", collector="rg", score=0.9)
    gf = _item(["src/a.py:10"], symbol="alpha", collector="graphify", kind="graph_neighbor", score=0.8)
    other_kind = _item(["src/a.py:10"], symbol="alpha", collector="rg", kind="lexical_def", score=0.7)
    r = render_brief(_packet([rg, gf, other_kind]))
    assert len(_brief_lines(r.text)) == 3
    assert r.merged_ids == {}


def test_items_without_references_are_never_merged():
    a = _item([], symbol="", collector="git", kind="git_meta", statement="HEAD abc on main", score=0.9)
    b = _item([], symbol="", collector="git", kind="git_meta", statement="worktree clean", score=0.8)
    assert duplicate_reference_key(a) is None
    unique, merged, also = fold_duplicate_references([a, b])
    assert [i.id for i in unique] == [a.id, b.id] and merged == {} and also == {}


def test_malformed_references_match_only_themselves():
    bad1 = _item(["src/a.py:1:2:3"], symbol="alpha", score=0.9)
    bad1_again = _item(["src/a.py:1:2:3"], symbol="beta", score=0.8)
    bad2 = _item(["src/a.py:x"], symbol="alpha", score=0.7)
    # refs.py returns malformed references whole with no line ...
    assert split_line_suffix("src/a.py:1:2:3")[2] is None and split_line_suffix("src/a.py:x")[2] is None
    r = render_brief(_packet([bad1, bad1_again, bad2]))
    assert r.merged_ids == {bad1_again.id: bad1.id}
    assert len(_brief_lines(r.text)) == 2


# -- ordering, budget and packet consistency -------------------------------


def test_fold_order_and_also_list_are_deterministic():
    keep = _item(["src/a.py:10"], symbol="alpha", score=0.9)
    dups = [_item(["src/a.py:10"], symbol=s, score=0.5) for s in ("gamma", "beta", "delta")]
    texts = {_body(render_brief(_packet([keep] + perm)).text) for perm in (dups, dups[::-1], dups[1:] + dups[:1])}
    assert len(texts) == 1
    # equal scores → canonical (content) order, so the also-list is stable too
    assert "also matches beta, delta, gamma" in texts.pop()


def test_folded_item_is_dropped_with_its_survivor_under_budget():
    keep = _item(["src/a.py:10"], symbol="alpha", score=0.9)
    dup = _item(["src/a.py:10"], symbol="beta", score=0.8)
    r = render_brief(_packet([keep, dup], max_tokens=20))  # nothing fits
    assert r.text == ""
    assert set(r.dropped_ids) == {keep.id, dup.id}
    assert r.merged_ids == {}


def test_compile_records_fold_in_packet_and_keeps_items_selected(golden_repo):
    claims = [
        RawClaim(kind="lexical_ref", statement="pyproject.toml at pyproject.toml:1  |  [project]",
                 references=["pyproject.toml:1"], authority="inferred", freshness="current",
                 confidence=0.7, command="rg", extra={"symbol": "pyproject.toml"}),
        RawClaim(kind="lexical_ref", statement="toml at pyproject.toml:1  |  [project]",
                 references=["pyproject.toml:1"], authority="inferred", freshness="current",
                 confidence=0.7, command="rg", extra={"symbol": "toml"}),
    ]
    result = compiler_mod.compile_packet(
        "fix pyproject.toml", golden_repo, collectors=[StaticCollector(claims)], persist=False
    )
    assert len(_brief_lines(result.brief)) == 1
    assert "also matches toml" in result.brief
    (folded_id, into) = next(iter(result.render.merged_ids.items()))
    folded = next(i for i in result.packet.evidence if i.id == folded_id)
    assert folded.compiler_assessment.selected is True
    assert f"same reference as {into}; rendered once" in folded.compiler_assessment.selected_because
    assert folded_id not in result.packet.budget.omitted_evidence_ids
