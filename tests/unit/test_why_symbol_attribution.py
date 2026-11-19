"""The why-line names the prompt symbol an item was actually collected for.

Regression for a defect seen in real packets (2026-09 to 2026-11): the direct
symbol reason was credited to the first prompt symbol that appeared anywhere
in the statement text, so a match collected for ``Foreman`` on a line that
also mentioned ``MyBuddy`` was explained as "references prompt symbol
'mybuddy'". 232 of 1394 selected ripgrep items in 47 of 92 real briefs
carried the wrong symbol. Attribution only: no score may change.
"""

from __future__ import annotations

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
from evidence_compiler.ranking import W_DIRECT_SYMBOL, rank


def _item(kind, statement, refs, authority="inferred", symbol=None):
    return EvidenceItem(
        source_claim=SourceClaim(kind=kind, statement=statement, references=refs),
        provenance=Provenance(collector="test", extra={"symbol": symbol} if symbol else {}),
        authority=authority,
        freshness="current",
        confidence=0.5,
    )


def _packet(items, symbols):
    packet = EvidencePacket(
        identity=Identity(repository_root="/repo", head="h"),
        correlation=Correlation(prompt_hash="ph"),
        task=Task(raw_prompt_hash="ph", extracted_symbols=symbols),
    )
    packet.evidence.extend(items)
    return packet


def _direct_reason(item) -> str:
    reasons = [r for r in item.compiler_assessment.selected_because if "prompt symbol" in r]
    assert len(reasons) == 1, item.compiler_assessment.selected_because
    return reasons[0]


@pytest.mark.parametrize(
    ("symbols", "claimed", "statement", "ref"),
    [
        # Another prompt symbol appears earlier in the prompt and on the line.
        (
            ["MyBuddy", "Foreman"],
            "Foreman",
            "Foreman at docs/register.md:207  |  | OD-250 | MyBuddy Foreman env edits",
            "docs/register.md:207",
        ),
        # An earlier prompt symbol is a substring of the collected one.
        (
            ["Super", "Superintendent"],
            "Superintendent",
            "Superintendent at docs/register.md:7  |  Superintendent CHECKIN log",
            "docs/register.md:7",
        ),
        # A path-like prompt token matches the reference path, not the claim.
        (
            ["geometry.py", "compute_window_area"],
            "compute_window_area",
            "compute_window_area at pkg/geometry.py:3  |  def compute_window_area(w, h):",
            "pkg/geometry.py:3",
        ),
    ],
)
def test_reason_names_the_symbol_the_item_was_collected_for(symbols, claimed, statement, ref):
    item = _item("lexical_match", statement, [ref], symbol=claimed)
    rank(_packet([item], symbols=symbols))
    assert _direct_reason(item) == f"references prompt symbol '{claimed.lower()}'"
    assert item.compiler_assessment.components.direct_symbol == W_DIRECT_SYMBOL


def test_item_without_a_claimed_symbol_still_credits_a_statement_match():
    # git-style evidence carries no collected-for symbol; the statement test
    # remains the only signal and must keep working.
    item = _item("repo_state", "HEAD abc123 on branch main", [], authority="authoritative")
    rank(_packet([item], symbols=["Main"]))
    assert _direct_reason(item) == "references prompt symbol 'main'"


def test_claimed_symbol_outside_the_prompt_falls_back_to_statement_match():
    item = _item(
        "lexical_match",
        "helper at src/a.py:1  |  parse_cfg(helper)",
        ["src/a.py:1"],
        symbol="helper",
    )
    rank(_packet([item], symbols=["parse_cfg"]))
    assert _direct_reason(item) == "references prompt symbol 'parse_cfg'"


def test_attribution_does_not_change_scores():
    def build():
        return [
            _item("lexical_match", "Foreman at d.md:2  |  MyBuddy Foreman", ["d.md:2"], symbol="Foreman"),
            _item("lexical_def", "MyBuddy at e.py:9  |  class MyBuddy:", ["e.py:9"], symbol="MyBuddy"),
        ]

    items = build()
    rank(_packet(items, symbols=["MyBuddy", "Foreman"]))
    assert [i.compiler_assessment.final_score for i in items] == [4.5, 4.5]
