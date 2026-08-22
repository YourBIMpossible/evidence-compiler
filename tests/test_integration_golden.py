"""End-to-end golden-repo integration (build brief §8).

Asserts full packet shape through the real compiler + collectors, not unit
mocks: identity, collector statuses, evidence selection, negative evidence,
dirty overlay, brief budget, persistence, and replay.
"""

from __future__ import annotations

import os
import shutil

import pytest

from evidence_compiler.cli import render_replay_report
from evidence_compiler.compiler import compile_packet
from evidence_compiler.packet import EvidencePacket
from evidence_compiler.scoping import estimate_tokens
from evidence_compiler.storage import load_packet

HAS_GIT = shutil.which("git") is not None
HAS_RG = shutil.which("rg") is not None
PROMPT = "Why does AlphaService.run break, and is OriginSystem referenced anywhere?"


def _compile(repo):
    return compile_packet(
        prompt=PROMPT,
        repository_root=repo,
        active_file="src/alpha.py",
        session_id="sess-1",
        turn_id="turn-1",
    )


def test_end_to_end_packet_shape(dirty_golden_repo):
    result = _compile(dirty_golden_repo)
    p = result.packet

    # identity binding
    assert p.schema_version == 1
    assert p.identity.repository_root == os.path.abspath(dirty_golden_repo).replace("\\", "/")
    assert p.identity.session_id == "sess-1"
    assert p.task.intent == "debugging"
    assert "AlphaService.run" in p.task.extracted_symbols or "AlphaService" in p.task.extracted_symbols

    # all three built-in collectors recorded, in registration order
    names = [c.name for c in p.collectors_run]
    assert names == ["git", "ripgrep", "graphify"]
    statuses = {c.name: c.status for c in p.collectors_run}
    assert statuses["graphify"] == "skipped"

    if HAS_GIT:
        assert p.identity.head, "git head should be bound"
        # dirty overlay for the mutated file
        dirty = [e for e in p.evidence if e.source_claim.kind == "git_dirty"]
        assert any("beta.py" in e.source_claim.statement for e in dirty)

    if HAS_RG:
        assert statuses["ripgrep"] in {"ok", "empty", "timeout"}
        # negative evidence for the absent symbol
        assert any(n.query == "OriginSystem" and n.outcome == "no_existing_reference"
                   for n in p.negative_evidence)


@pytest.mark.skipif(not HAS_RG, reason="ripgrep required for selection assertions")
def test_end_to_end_selection_and_brief(dirty_golden_repo):
    result = _compile(dirty_golden_repo)
    p = result.packet

    selected = [e for e in p.evidence if e.compiler_assessment.selected]
    assert selected, "at least one evidence item should be selected"
    for e in selected:
        assert e.compiler_assessment.selected_because

    # brief is within budget and references are preserved
    assert estimate_tokens(result.brief) <= p.budget.max_tokens
    if result.brief:
        assert f'packet_id="{p.packet_id}"' in result.brief


def test_packet_persisted_and_replayable(dirty_golden_repo):
    result = _compile(dirty_golden_repo)
    assert result.storage_path and os.path.isfile(result.storage_path)

    reloaded = load_packet(result.storage_path)
    assert isinstance(reloaded, EvidencePacket)
    assert reloaded.packet_id == result.packet.packet_id
    assert reloaded.to_dict() == result.packet.to_dict()

    report = render_replay_report(reloaded)
    assert result.packet.packet_id in report
    assert "collectors:" in report
    assert "selected" in report


def test_clean_repo_symbol_match(golden_repo):
    # clean (all committed) repo → no git_dirty, but symbol still matches
    result = _compile(golden_repo)
    kinds = {e.source_claim.kind for e in result.packet.evidence}
    if HAS_GIT:
        assert not any(e.source_claim.kind == "git_dirty" for e in result.packet.evidence)
    if HAS_RG:
        assert "lexical_def" in kinds or "lexical_match" in kinds


def test_packet_immutable_after_compile_and_render(dirty_golden_repo):
    """F-1 regression: the packet returned by compile_packet must not be
    further mutated by any subsequent render_brief call — reconciliation
    happens before the returned render, never after (packet spec §1)."""
    from evidence_compiler.rendering import render_brief

    result = _compile(dirty_golden_repo)
    before = result.packet.to_dict()
    again = render_brief(result.packet)
    after = result.packet.to_dict()
    assert after == before, "render_brief must not mutate the packet"
    assert again.text == result.brief


@pytest.mark.skipif(not HAS_RG, reason="ripgrep required to produce enough evidence to overflow a tiny budget")
def test_packet_consistent_with_brief_under_hard_budget_reconciliation(dirty_golden_repo):
    """F-1 regression: when the renderer's precise token accounting drops an
    item ranking had selected, the returned packet must already reflect that
    (omitted) before compile_packet returns — not via a later mutation."""
    from evidence_compiler.config import Config

    cfg = Config()
    cfg.data["budget"] = {"min_tokens": 10, "default_tokens": 5000, "max_tokens": 40}
    result = compile_packet(
        prompt=PROMPT,
        repository_root=dirty_golden_repo,
        active_file="src/alpha.py",
        config=cfg,
    )
    selected_ids = {e.id for e in result.packet.evidence if e.compiler_assessment.selected}
    assert selected_ids == set(result.render.rendered_ids)
    for e in result.packet.evidence:
        if e.id not in selected_ids:
            assert e.compiler_assessment.selected is False


def test_missing_symbol_is_negative_only(golden_repo):
    if not HAS_RG:
        pytest.skip("ripgrep required")
    result = compile_packet(
        prompt="Where is OriginSystem defined?",
        repository_root=golden_repo,
    )
    # OriginSystem exists nowhere → recorded as absence, not invented evidence
    assert any(n.query == "OriginSystem" for n in result.packet.negative_evidence)
    assert not any("OriginSystem" in e.source_claim.statement for e in result.packet.evidence)
