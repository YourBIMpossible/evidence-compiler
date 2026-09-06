"""Identity probe: HEAD resolution states and their budgets (W3 pass).

Window 2 produced packets with ``head: null`` on healthy repos because the
git *collector's* 250 ms budget was split per call (62 ms for ``rev-parse
HEAD``). The identity probe now has its own 1000 ms budget with a 100 ms
per-call floor, and reports *why* HEAD is missing.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

from evidence_compiler import gitprobe
from evidence_compiler.collectors.git import GitCollector
from tests.support import make_context

git_required = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


@git_required
def test_healthy_repo_resolves_head(golden_repo):
    info = gitprobe.probe(golden_repo)
    assert info.is_repo
    assert info.head_state == "resolved"
    assert info.head and len(info.head) == 40
    assert info.detached is False


@git_required
def test_head_probe_timeout_is_reported_not_silent(golden_repo, monkeypatch):
    real_run = gitprobe._run

    def run_with_slow_head(args, cwd, timeout_ms):
        if args == ["rev-parse", "HEAD"]:
            return None  # what _run returns on TimeoutExpired
        return real_run(args, cwd, timeout_ms)

    monkeypatch.setattr(gitprobe, "_run", run_with_slow_head)
    info = gitprobe.probe(golden_repo)
    assert info.is_repo
    assert info.head is None
    assert info.head_state == "probe_timeout"
    assert "within budget" in (info.reason or "")


@git_required
def test_unborn_branch_is_unresolved(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    info = gitprobe.probe(str(tmp_path))
    assert info.is_repo
    assert info.head is None
    assert info.head_state == "unresolved"


@git_required
def test_detached_head_is_flagged(golden_repo):
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=golden_repo, capture_output=True, text=True, check=True
    ).stdout.strip()
    subprocess.run(["git", "checkout", "-q", "--detach", head], cwd=golden_repo, check=True)
    info = gitprobe.probe(golden_repo)
    assert info.head == head
    assert info.branch is None
    assert info.detached is True


def test_budget_floor_and_ceiling():
    b = gitprobe._Budget(total_ms=1000, calls=6)
    first = b.next_ms()
    assert 100 <= first <= 1000
    tight = gitprobe._Budget(total_ms=50, calls=6)
    assert tight.next_ms() >= 1


@git_required
def test_git_collector_falls_back_to_context_head_on_probe_timeout(golden_repo, monkeypatch):
    real_run = gitprobe._run

    def run_with_slow_head(args, cwd, timeout_ms):
        if args == ["rev-parse", "HEAD"]:
            return None
        return real_run(args, cwd, timeout_ms)

    monkeypatch.setattr(gitprobe, "_run", run_with_slow_head)
    ctx = make_context(golden_repo, "x", head="a" * 40)
    result = GitCollector().collect(ctx)
    meta = [c for c in result.items if c.kind == "git_meta"][0]
    assert meta.source_revision == "a" * 40
    assert meta.extra["head_state"] == "resolved"
    assert "timed out" not in meta.statement


# -- dirty overlay: a status timeout must be observable, never "clean" ------


@git_required
def test_dirty_state_resolved_lists_dirty_paths(dirty_golden_repo):
    info = gitprobe.probe(dirty_golden_repo)
    assert info.dirty_state == "resolved"
    assert info.dirty_paths  # the fixture dirties src/beta.py


@git_required
def test_status_timeout_is_reported_not_silently_clean(dirty_golden_repo, monkeypatch):
    real_run = gitprobe._run

    def run_with_slow_status(args, cwd, timeout_ms):
        if args[:2] == ["status", "--porcelain"]:
            return None
        return real_run(args, cwd, timeout_ms)

    monkeypatch.setattr(gitprobe, "_run", run_with_slow_status)
    info = gitprobe.probe(dirty_golden_repo)
    assert info.dirty_state == "probe_timeout"
    assert info.dirty_paths == []

    result = GitCollector().collect(make_context(dirty_golden_repo, "x"))
    assert result.status == "ok"
    assert result.diagnostic["dirty_state"] == "probe_timeout"
    assert "dirty overlay unknown" in result.diagnostic["reason"]
    meta = [c for c in result.items if c.kind == "git_meta"][0]
    assert meta.extra["dirty_state"] == "probe_timeout"
    assert "dirty overlay unknown" in meta.statement
    assert not [c for c in result.items if c.kind == "git_dirty"]


@git_required
def test_default_git_budget_covers_six_calls_with_floor():
    from evidence_compiler.config import Config

    # six calls x 100 ms floor must fit the default budget, otherwise the
    # last call (git status) is starved on a cold Windows spawn.
    assert Config().collector_timeout_ms("git") >= 6 * gitprobe._MIN_CALL_MS
