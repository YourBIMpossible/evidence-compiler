"""Collector contract suite (collector-interface-v1.md §7).

Covers timeout behavior, malformed/empty output, provenance, authority/
freshness, path normalization (incl. Windows inputs), failure isolation, and
duplicate-heavy input for the git and ripgrep collectors.
"""

from __future__ import annotations

import os
import shutil
import subprocess

import pytest

from evidence_compiler.collectors.base import (
    EvidenceResult,
    RawClaim,
    run_collector_safely,
)
from evidence_compiler.collectors.git import GitCollector
from evidence_compiler.collectors.ripgrep import RipgrepCollector, _parse_rg_json
from tests.support import ThrowingCollector, make_context

HAS_RG = shutil.which("rg") is not None
HAS_GIT = shutil.which("git") is not None
rg_required = pytest.mark.skipif(not HAS_RG, reason="ripgrep not installed")
git_required = pytest.mark.skipif(not HAS_GIT, reason="git not installed")

ALLOWED_STATUS = {"ok", "empty", "timeout", "error", "skipped"}


# --------------------------------------------------------------------------
# Failure isolation (applies to every collector via the safety wrapper)
# --------------------------------------------------------------------------


def test_failure_isolation_never_raises(golden_repo):
    ctx = make_context(golden_repo, "anything")
    result = run_collector_safely(ThrowingCollector(), ctx)
    assert isinstance(result, EvidenceResult)
    assert result.status == "error"
    assert result.error_message
    assert result.duration_ms >= 0


# --------------------------------------------------------------------------
# ripgrep collector
# --------------------------------------------------------------------------


@rg_required
def test_rg_empty_when_no_symbols(golden_repo):
    ctx = make_context(golden_repo, "no symbols here", extracted_symbols=[])
    result = RipgrepCollector().collect(ctx)
    assert result.status == "empty"
    assert result.diagnostic.get("reason")


@rg_required
def test_rg_finds_symbol_with_full_provenance(golden_repo):
    ctx = make_context(golden_repo, "AlphaService", extracted_symbols=["AlphaService"])
    result = RipgrepCollector().collect(ctx)
    assert result.status == "ok"
    assert result.items
    for item in result.items:
        assert item.references, "every item must carry references"
        assert item.command, "provenance command required"
        assert item.authority in {"authoritative", "convention", "inferred"}
        assert item.freshness in {"current", "dirty_overlay", "stale", "unknown"}
        for ref in item.references:
            assert "\\" not in ref, "references must be POSIX-normalized"
            assert not os.path.isabs(ref.split(":", 1)[0]), "references must be repo-relative"


@rg_required
def test_rg_negative_evidence_for_absent_symbol(golden_repo):
    ctx = make_context(golden_repo, "OriginSystem", extracted_symbols=["OriginSystem"])
    result = RipgrepCollector().collect(ctx)
    assert any(n.outcome == "no_existing_reference" and n.query == "OriginSystem"
               for n in result.negative_items)


@rg_required
def test_rg_timeout_does_not_crash(golden_repo):
    ctx = make_context(golden_repo, "AlphaService", extracted_symbols=["AlphaService"], timeout_ms=1)
    result = RipgrepCollector().collect(ctx)
    assert result.status in ALLOWED_STATUS  # timeout or (fast) ok, never a crash


@rg_required
def test_rg_duplicate_heavy_input_capped(tmp_path):
    # a file with thousands of matches must not explode the result
    repo = tmp_path / "dup"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "many.py").write_text("Widget\n" * 5000, encoding="utf-8")
    ctx = make_context(str(repo), "Widget", extracted_symbols=["Widget"], timeout_ms=3000)
    result = RipgrepCollector().collect(ctx)
    assert len(result.items) <= 100  # global cap enforced
    if len(result.items) == 100:
        assert result.diagnostic.get("truncated") is True


def test_rg_malformed_json_lines_skipped():
    ctx = make_context("/repo", "X", extracted_symbols=["X"])
    stdout = 'not json\n{"type":"other"}\n{bad json\n'
    claims = _parse_rg_json(stdout, ctx, "X", ["rg", "X"])
    assert claims == []  # nothing usable, but no exception


@rg_required
def test_rg_skipped_when_binary_missing(monkeypatch, golden_repo):
    monkeypatch.setattr("evidence_compiler.collectors.ripgrep.shutil.which", lambda _: None)
    ctx = make_context(golden_repo, "AlphaService", extracted_symbols=["AlphaService"])
    result = RipgrepCollector().collect(ctx)
    assert result.status == "skipped"
    assert result.diagnostic.get("reason")


@rg_required
def test_rg_oserror_on_one_symbol_preserves_prior_matches(monkeypatch, golden_repo):
    # F-5 regression: a launch failure on symbol N must not discard matches
    # already found for symbols 1..N-1 (per-symbol failure isolation).
    import subprocess as subprocess_mod

    real_run = subprocess_mod.run
    calls = {"n": 0}

    def flaky_run(cmd, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("simulated launch failure")
        return real_run(cmd, **kwargs)

    monkeypatch.setattr("evidence_compiler.collectors.ripgrep.subprocess.run", flaky_run)
    ctx = make_context(
        golden_repo, "AlphaService BetaService", extracted_symbols=["AlphaService", "BetaService"]
    )
    result = RipgrepCollector().collect(ctx)
    assert result.status != "error"
    assert any(n.query == "BetaService" and n.outcome == "search_error" for n in result.negative_items)
    assert any(item.extra.get("symbol") == "AlphaService" for item in result.items)


# --------------------------------------------------------------------------
# git collector
# --------------------------------------------------------------------------


@git_required
def test_git_ok_on_repo_with_provenance(golden_repo):
    ctx = make_context(golden_repo, "anything")
    result = GitCollector().collect(ctx)
    assert result.status == "ok"
    meta = [i for i in result.items if i.kind == "git_meta"]
    assert meta, "git_meta claim expected"
    assert meta[0].authority == "authoritative"
    assert meta[0].freshness == "current"
    assert meta[0].command


@git_required
def test_git_dirty_path_is_overlay(dirty_golden_repo):
    ctx = make_context(dirty_golden_repo, "anything")
    result = GitCollector().collect(ctx)
    dirty = [i for i in result.items if i.kind == "git_dirty"]
    assert dirty, "expected a dirty-path claim"
    for item in dirty:
        assert item.freshness == "dirty_overlay"
        assert item.references
        assert "\\" not in item.references[0]


def test_git_skipped_outside_repo(tmp_path):
    non_repo = tmp_path / "plain"
    non_repo.mkdir()
    ctx = make_context(str(non_repo), "anything")
    result = GitCollector().collect(ctx)
    assert result.status == "skipped"
    assert result.diagnostic.get("reason")


@git_required
def test_git_no_commits_reports_ok_with_unknown_head(tmp_path):
    # F-4 regression: a git work tree with zero commits (no HEAD yet) must
    # not crash and must surface an honest "unknown" HEAD rather than
    # inventing a revision. The git collector always emits a git_meta claim
    # once inside a work tree (branch/worktree_id are known even pre-first-
    # commit), so `status` is "ok" here, not "empty" — the "empty" branch in
    # GitCollector.collect is unreachable for this collector by design; this
    # test pins the actual (correct) no-commit behavior instead of asserting
    # an unreachable status.
    repo = tmp_path / "no-commits"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=str(repo), check=True, capture_output=True, text=True)
    ctx = make_context(str(repo), "anything")
    result = GitCollector().collect(ctx)
    assert result.status == "ok"
    meta = [i for i in result.items if i.kind == "git_meta"]
    assert meta and "unknown" in meta[0].statement
    assert meta[0].source_revision is None
