"""Regression tests for the Window 2 ripgrep defects (W3 improvement pass).

Root cause on Windows: ``subprocess`` decoded rg's stdout with the console
code page (cp1252); bytes such as ``0x90``/``0x9d`` have no cp1252 mapping,
the reader thread died with ``UnicodeDecodeError``, ``proc.stdout`` came back
``None`` and the collector crashed with ``AttributeError``. The collector
now decodes as UTF-8 with replacement and guards the ``None`` case.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import types

import pytest

from evidence_compiler.collectors import ripgrep as rgmod
from evidence_compiler.collectors.ripgrep import OUTCOMES, RipgrepCollector
from tests.support import make_context

rg_required = pytest.mark.skipif(shutil.which("rg") is None, reason="ripgrep not installed")


def _write_bytes(root: str, rel: str, data: bytes) -> None:
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data)


@rg_required
def test_non_cp1252_bytes_in_matching_line_do_not_crash(golden_repo):
    # 0x90 and 0x9d are undefined in cp1252 -> exactly the Window 2 crash input.
    _write_bytes(
        golden_repo,
        os.path.join("src", "odd_bytes.py"),
        b"# \x90\x9d \xe2\x82\xac euro sign\ndef weird_symbol():\n    return 1  # \x90\n",
    )
    ctx = make_context(golden_repo, "x", extracted_symbols=["weird_symbol"])
    result = RipgrepCollector().collect(ctx)
    assert result.status == "ok"
    assert result.diagnostic["symbols_error"] == 0
    assert any("odd_bytes.py" in ref for c in result.items for ref in c.references)


@rg_required
def test_utf8_symbol_and_path_search(golden_repo):
    _write_bytes(
        golden_repo,
        os.path.join("src", "übersicht.py"),
        "def größe_berechnen():\n    return 'größe'\n".encode("utf-8"),
    )
    ctx = make_context(golden_repo, "x", extracted_symbols=["größe_berechnen"])
    result = RipgrepCollector().collect(ctx)
    assert result.status == "ok"
    assert any("bersicht.py" in ref for c in result.items for ref in c.references)


@rg_required
def test_none_stdout_is_a_decode_error_not_a_crash(golden_repo, monkeypatch):
    def fake_run(*args, **kwargs):
        return types.SimpleNamespace(stdout=None, stderr="", returncode=0)

    monkeypatch.setattr(rgmod.subprocess, "run", fake_run)
    ctx = make_context(golden_repo, "x", extracted_symbols=["AlphaService"])
    result = RipgrepCollector().collect(ctx)
    assert result.status == "error"
    assert result.diagnostic["outcome"] == "error"
    assert result.diagnostic["error_categories"] == ["decode_error"]
    assert result.diagnostic["symbols_error"] == 1
    assert [n.outcome for n in result.negative_items] == ["search_error"]


@rg_required
def test_process_error_isolated_per_symbol(golden_repo, monkeypatch):
    real_run = rgmod.subprocess.run

    def flaky_run(cmd, **kwargs):
        if "BetaService" in cmd:
            return types.SimpleNamespace(stdout="", stderr="regex parse error", returncode=2)
        return real_run(cmd, **kwargs)

    monkeypatch.setattr(rgmod.subprocess, "run", flaky_run)
    ctx = make_context(golden_repo, "x", extracted_symbols=["AlphaService", "BetaService"])
    result = RipgrepCollector().collect(ctx)
    assert result.status == "ok"  # AlphaService matched; one failure does not poison the run
    assert result.diagnostic["symbols_matched"] == 1
    assert result.diagnostic["symbols_error"] == 1
    assert result.diagnostic["error_categories"] == ["process_error"]
    beta = [n for n in result.negative_items if n.query == "BetaService"]
    assert beta and beta[0].outcome == "search_error"
    assert beta[0].diagnostic["rg_returncode"] == 2


@rg_required
def test_timeout_outcomes_are_accounted_per_symbol(golden_repo, monkeypatch):
    def slow_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout", 0))

    monkeypatch.setattr(rgmod.subprocess, "run", slow_run)
    ctx = make_context(golden_repo, "x", extracted_symbols=["AlphaService", "BetaService"], timeout_ms=300)
    result = RipgrepCollector().collect(ctx)
    assert result.status == "timeout"
    assert result.diagnostic["outcome"] == "timeout"
    assert result.diagnostic["symbols_timeout"] + result.diagnostic["symbols_not_searched"] == 2
    assert all(n.outcome in ("search_timeout", "not_searched") for n in result.negative_items)


@rg_required
def test_provenance_command_uses_logical_rg_not_absolute_path(golden_repo):
    ctx = make_context(golden_repo, "x", extracted_symbols=["AlphaService"])
    result = RipgrepCollector().collect(ctx)
    assert result.items
    for claim in result.items:
        assert claim.command.startswith("rg ")
        assert ":\\" not in claim.command and "/usr/" not in claim.command


@rg_required
def test_diagnostic_counts_are_complete_and_consistent(golden_repo):
    ctx = make_context(golden_repo, "x", extracted_symbols=["AlphaService", "definitely_absent_zzz"])
    result = RipgrepCollector().collect(ctx)
    d = result.diagnostic
    assert d["symbols_total"] == 2
    assert d["symbols_searched"] == 2
    assert d["symbols_matched"] == 1
    assert d["symbols_no_match"] == 1
    assert d["symbols_timeout"] == d["symbols_error"] == d["symbols_not_searched"] == 0
    assert d["outcome"] == "matches"
    absent = [n for n in result.negative_items if n.query == "definitely_absent_zzz"]
    assert absent and absent[0].outcome == "no_existing_reference"


def test_outcome_vocabulary_is_frozen():
    assert OUTCOMES == (
        "matches", "no_matches", "timeout", "not_searched",
        "decode_error", "process_error", "launch_error", "unavailable",
    )
