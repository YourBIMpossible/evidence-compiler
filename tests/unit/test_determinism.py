"""F-D1 regression: the brief is a pure function of evidence *content*, never
of the order collectors happened to emit it in.

The dogfood window surfaced that identical inputs (same install, same repo
HEAD, same prompt/active-file) produced briefs whose item ordering — and the
number of items admitted under the token budget — varied run to run, because
ripgrep emits matches across files in a non-deterministic parallel order and
that arrival order leaked into (a) the duplication penalty, (b) the budget
selection tiebreak, and (c) the render tiebreak. These tests lock the fix:
ranking and rendering canonicalize evidence order by content first.
"""

from __future__ import annotations

import copy
import re
import shutil

import pytest

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
from evidence_compiler.rendering import render_brief

HAS_RG = shutil.which("rg") is not None
HAS_GIT = shutil.which("git") is not None


def _item(kind, statement, refs, symbol=None, authority="inferred", freshness="current"):
    return EvidenceItem(
        source_claim=SourceClaim(kind=kind, statement=statement, references=refs),
        provenance=Provenance(collector="rg", extra={"symbol": symbol} if symbol else {}),
        authority=authority,
        freshness=freshness,
        confidence=0.6,
    )


def _packet(items, *, symbols, active_file, packet_id, budget_default=1000, max_tokens=1200):
    p = EvidencePacket(
        identity=Identity(repository_root="/repo", head="h"),
        correlation=Correlation(prompt_hash="ph"),
        task=Task(raw_prompt_hash="ph", extracted_symbols=symbols, active_file=active_file),
    )
    p.packet_id = packet_id
    p.budget.default_tokens = budget_default
    p.budget.max_tokens = max_tokens
    p.evidence.extend(items)
    return p


def _content_view(packet):
    """A content-only projection of the ranked packet — no random ids."""
    return [
        (
            e.source_claim.kind,
            e.source_claim.statement,
            tuple(e.source_claim.references),
            e.compiler_assessment.final_score,
            e.compiler_assessment.selected,
        )
        for e in packet.evidence
    ]


def _tied_items():
    # A mix that exercises every order-sensitive path: two lexical matches that
    # share a reference (so the duplication penalty depends on which is seen
    # first) plus several equally-scored siblings whose brief order is decided
    # purely by the tiebreak.
    return [
        _item("lexical_def", "AlphaService def at src/alpha.py:3", ["src/alpha.py:3"], symbol="AlphaService"),
        _item("lexical_match", "AlphaService use at src/alpha.py:12", ["src/alpha.py:12"], symbol="AlphaService"),
        _item("lexical_match", "AlphaService use at src/beta.py:7", ["src/beta.py:7"], symbol="AlphaService"),
        _item("lexical_match", "AlphaService dup ref A", ["src/gamma.py:4"], symbol="AlphaService"),
        _item("lexical_match", "AlphaService dup ref B", ["src/gamma.py:4"], symbol="AlphaService"),
        _item("lexical_match", "AlphaService use at src/delta.py:9", ["src/delta.py:9"], symbol="AlphaService"),
    ]


def test_rank_is_pure_function_of_content_not_order():
    """Scores and selection must not depend on the input list order."""
    items = _tied_items()
    forward = _packet(copy.deepcopy(items), symbols=["AlphaService"], active_file="src/alpha.py", packet_id="ep_fixed")
    reverse = _packet(list(reversed(copy.deepcopy(items))), symbols=["AlphaService"], active_file="src/alpha.py", packet_id="ep_fixed")

    rank(forward)
    rank(reverse)

    assert _content_view(forward) == _content_view(reverse)
    assert forward.budget.injected_tokens == reverse.budget.injected_tokens
    assert forward.budget.candidate_tokens == reverse.budget.candidate_tokens


def test_brief_is_byte_identical_under_input_permutation():
    """The rendered brief must be byte-for-byte identical regardless of the
    order evidence was assembled in — the exact property F-D1 violated."""
    items = _tied_items()
    forward = _packet(copy.deepcopy(items), symbols=["AlphaService"], active_file="src/alpha.py", packet_id="ep_fixed")
    reverse = _packet(list(reversed(copy.deepcopy(items))), symbols=["AlphaService"], active_file="src/alpha.py", packet_id="ep_fixed")

    rank(forward)
    rank(reverse)

    assert render_brief(forward).text == render_brief(reverse).text


def test_brief_stable_under_tight_budget():
    """A tight budget makes selection count itself order-sensitive (greedy fill
    admits a different number depending on arrival order). Canonical ordering
    must make the admitted set — not just its order — reproducible."""
    items = _tied_items()
    forward = _packet(copy.deepcopy(items), symbols=["AlphaService"], active_file="src/alpha.py", packet_id="ep_fixed", budget_default=45, max_tokens=45)
    reverse = _packet(list(reversed(copy.deepcopy(items))), symbols=["AlphaService"], active_file="src/alpha.py", packet_id="ep_fixed", budget_default=45, max_tokens=45)

    rank(forward)
    rank(reverse)

    fwd_selected = sorted(e.source_claim.statement for e in forward.evidence if e.compiler_assessment.selected)
    rev_selected = sorted(e.source_claim.statement for e in reverse.evidence if e.compiler_assessment.selected)
    assert fwd_selected == rev_selected
    assert render_brief(forward).text == render_brief(reverse).text


@pytest.mark.skipif(not (HAS_RG and HAS_GIT), reason="ripgrep + git required for the real-pipeline reproducibility check")
def test_repeated_compile_produces_identical_brief(dirty_golden_repo):
    """End-to-end mirror of the dogfood reproduction: compiling the same repo
    HEAD with the same prompt twice must yield an identical brief once the only
    volatile identity fields (packet_id) are normalized."""
    from evidence_compiler.compiler import compile_packet

    def brief_of():
        r = compile_packet(
            prompt="Why does AlphaService.run break, and is OriginSystem referenced anywhere?",
            repository_root=dirty_golden_repo,
            active_file="src/alpha.py",
            persist=False,
        )
        return re.sub(r'packet_id="ep_[0-9a-f]+"', 'packet_id="ep_norm"', r.brief)

    first = brief_of()
    second = brief_of()
    third = brief_of()
    assert first == second == third
