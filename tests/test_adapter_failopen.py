"""Claude Code adapter fail-open guarantees (build brief §6).

The hook must never block or fail the parent session: it exits 0 and injects
nothing when every collector throws, and when a collector hangs past the
end-to-end deadline.
"""

from __future__ import annotations

import io
import json

import pytest

from evidence_compiler import compiler as compiler_mod
from evidence_compiler.config import Config
from evidence_compiler.integrations import claude_code
from tests.support import HangingCollector, ThrowingCollector


def _feed_stdin(monkeypatch, payload: dict) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))


def test_all_collectors_throw_still_exits_zero_no_injection(monkeypatch, capsys, golden_repo):
    monkeypatch.setattr(
        compiler_mod,
        "_default_collectors",
        lambda: [ThrowingCollector(), ThrowingCollector(), ThrowingCollector()],
    )
    _feed_stdin(monkeypatch, {"prompt": "look at AlphaService", "cwd": golden_repo})

    rc = claude_code.main()
    out = capsys.readouterr().out

    assert rc == 0
    assert out.strip() == ""  # nothing injected


def test_hanging_collector_deadline_fires_exits_zero(monkeypatch, capsys, golden_repo):
    monkeypatch.setattr(compiler_mod, "_default_collectors", lambda: [HangingCollector(seconds=30)])
    # tiny deadline so the test is fast
    monkeypatch.setattr(
        claude_code, "_load_deadline_ms", lambda repo: 400
    )
    _feed_stdin(monkeypatch, {"prompt": "look at AlphaService", "cwd": golden_repo})

    rc = claude_code.main()
    out = capsys.readouterr().out

    assert rc == 0
    assert out.strip() == ""


def test_malformed_stdin_exits_zero(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("this is not json {"))
    rc = claude_code.main()
    assert rc == 0
    assert capsys.readouterr().out.strip() == ""


def test_empty_prompt_exits_zero(monkeypatch, capsys, golden_repo):
    _feed_stdin(monkeypatch, {"prompt": "   ", "cwd": golden_repo})
    rc = claude_code.main()
    assert rc == 0
    assert capsys.readouterr().out.strip() == ""


def test_successful_injection_shape(monkeypatch, capsys, golden_repo):
    from evidence_compiler.collectors.base import RawClaim
    from tests.support import StaticCollector

    claim = RawClaim(
        kind="lexical_def",
        statement="AlphaService at src/alpha.py:3",
        references=["src/alpha.py:3"],
        authority="inferred",
        freshness="current",
        confidence=0.7,
        command="rg AlphaService",
        extra={"symbol": "AlphaService"},
    )
    monkeypatch.setattr(compiler_mod, "_default_collectors", lambda: [StaticCollector([claim])])
    _feed_stdin(monkeypatch, {"prompt": "explain AlphaService", "cwd": golden_repo})

    rc = claude_code.main()
    out = capsys.readouterr().out
    assert rc == 0
    payload = json.loads(out)
    assert payload["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    assert "AlphaService" in payload["hookSpecificOutput"]["additionalContext"]
