"""Batched ripgrep search: one repository walk per match mode, not per symbol.

Window 3 timeouts came from twelve sequential full-repo rg processes sharing a
1.5 s slice. These pin the batching contract: process count, per-symbol
attribution on shared lines, caps, and outcome vocabulary.
"""

from __future__ import annotations

import os
import shutil

import pytest

from evidence_compiler.collectors import ripgrep as rgmod
from evidence_compiler.collectors.ripgrep import RipgrepCollector
from tests.support import make_context

rg_required = pytest.mark.skipif(shutil.which("rg") is None, reason="ripgrep not installed")


def _write(root: str, rel: str, text: str) -> None:
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def _count_runs(monkeypatch) -> list[list[str]]:
    calls: list[list[str]] = []
    real_run = rgmod.subprocess.run

    def counting_run(cmd, **kwargs):
        calls.append(list(cmd))
        return real_run(cmd, **kwargs)

    monkeypatch.setattr(rgmod.subprocess, "run", counting_run)
    return calls


@rg_required
def test_many_symbols_use_at_most_two_processes(golden_repo, monkeypatch):
    calls = _count_runs(monkeypatch)
    symbols = ["AlphaService", "BetaService", "GammaThing", "nl_filter", "user_agent", "DeltaMissing"]
    result = RipgrepCollector().collect(make_context(golden_repo, "x", extracted_symbols=symbols))
    assert len([c for c in calls if c[0] != "git"]) == 2  # git ls-files is the filename-stem lookup
    assert result.diagnostic["symbols_total"] == len(symbols)
    accounted = (
        result.diagnostic["symbols_matched"]
        + result.diagnostic["symbols_no_match"]
        + result.diagnostic["symbols_timeout"]
        + result.diagnostic["symbols_error"]
        + result.diagnostic["symbols_not_searched"]
    )
    assert accounted == len(symbols)


@rg_required
def test_shared_line_credits_every_matching_symbol(golden_repo):
    _write(golden_repo, "src/shared_line.py", "FooWidget = BarWidget  # both\n")
    ctx = make_context(golden_repo, "x", extracted_symbols=["FooWidget", "BarWidget"])
    result = RipgrepCollector().collect(ctx)
    by_symbol = {c.extra["symbol"] for c in result.items if any("shared_line.py" in r for r in c.references)}
    assert by_symbol == {"FooWidget", "BarWidget"}


@rg_required
def test_word_mode_does_not_credit_embedded_match(golden_repo):
    _write(golden_repo, "src/embedded.py", "FooWidgetFactory = 1\nBarWidget = 2\n")
    ctx = make_context(golden_repo, "x", extracted_symbols=["BarWidget", "FooWidget"])
    result = RipgrepCollector().collect(ctx)
    assert not any(c.extra["symbol"] == "FooWidget" for c in result.items)
    assert [n.query for n in result.negative_items if n.outcome == "no_existing_reference"] == ["FooWidget"]


@rg_required
def test_snake_symbol_matches_inside_longer_identifier(golden_repo):
    _write(golden_repo, "src/agent.py", "default_user_agent = 'x'\n")
    ctx = make_context(golden_repo, "x", extracted_symbols=["user_agent"])
    result = RipgrepCollector().collect(ctx)
    assert any("agent.py" in r for c in result.items for r in c.references)


@rg_required
def test_per_symbol_cap_holds_in_batch(golden_repo):
    body = "".join(f"CapHeavy = {i}\nCapLight = {i}\n" for i in range(40))
    _write(golden_repo, "src/cap_heavy.py", body)
    ctx = make_context(golden_repo, "x", extracted_symbols=["CapHeavy", "CapLight"])
    result = RipgrepCollector().collect(ctx)
    heavy = [c for c in result.items if c.extra["symbol"] == "CapHeavy"]
    light = [c for c in result.items if c.extra["symbol"] == "CapLight"]
    assert len(heavy) == rgmod._MAX_MATCHES_PER_SYMBOL
    assert len(light) == rgmod._MAX_MATCHES_PER_SYMBOL


def test_batches_keep_rank_order_best_group_first():
    assert rgmod._batches(["nl_filter", "Alpha", "user_agent", "Beta"]) == [
        ["nl_filter", "user_agent"],
        ["Alpha", "Beta"],
    ]
