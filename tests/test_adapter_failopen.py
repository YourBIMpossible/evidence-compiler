"""Claude Code adapter fail-open guarantees (build brief §6).

``evidence hook`` (``claude_code.main``) is now a thin deprecated shim over
``evidence hook-safe`` (``hook_safe.main``) — see the module docstring on
``evidence_compiler.integrations.claude_code``. These tests exercise the
shim through its own public entry point so a future re-divergence between
the two would be caught here, but drive it with the same byte-oriented
stdin/stdout contract and ``CLAUDE_PROJECT_DIR``-based repo-root resolution
that ``hook_safe`` actually implements (mirroring ``test_hook_safe.py``).

The hook must never block or fail the parent session: it exits 0 and injects
nothing when every collector throws, and when a collector hangs past the
end-to-end deadline.
"""

from __future__ import annotations

import io
import json
import os
import sys

import pytest

from evidence_compiler import compiler as compiler_mod
from evidence_compiler.integrations import claude_code
from tests.support import HangingCollector, ThrowingCollector


def _feed_stdin(monkeypatch, payload: dict) -> None:
    data = json.dumps(payload).encode("utf-8")
    wrapper = io.TextIOWrapper(io.BytesIO(data), encoding="utf-8")
    monkeypatch.setattr(sys, "stdin", wrapper)


@pytest.fixture(autouse=True)
def _project_dir_unset(monkeypatch):
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.delenv("EVIDENCE_HOOK", raising=False)
    monkeypatch.delenv("BIMP_EVIDENCE_HOOK", raising=False)


def _write_deadline(repo: str, deadline_ms: int) -> None:
    cfg_dir = os.path.join(repo, ".evidence-compiler")
    os.makedirs(cfg_dir, exist_ok=True)
    with open(os.path.join(cfg_dir, "config.yaml"), "w", encoding="utf-8") as fh:
        fh.write(f"deadline_ms: {deadline_ms}\n")


def test_all_collectors_throw_still_exits_zero_no_injection(monkeypatch, capsysbinary, golden_repo):
    monkeypatch.setattr(
        compiler_mod,
        "_default_collectors",
        lambda: [ThrowingCollector(), ThrowingCollector(), ThrowingCollector()],
    )
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", golden_repo)
    _feed_stdin(monkeypatch, {"prompt": "look at AlphaService", "cwd": golden_repo})

    rc = claude_code.main()
    out = capsysbinary.readouterr().out

    assert rc == 0
    assert out == b""  # nothing injected


def test_hanging_collector_deadline_fires_exits_zero(monkeypatch, capsysbinary, golden_repo):
    monkeypatch.setattr(compiler_mod, "_default_collectors", lambda: [HangingCollector(seconds=30)])
    _write_deadline(golden_repo, 400)  # tiny deadline so the test is fast
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", golden_repo)
    _feed_stdin(monkeypatch, {"prompt": "look at AlphaService", "cwd": golden_repo})

    rc = claude_code.main()
    out = capsysbinary.readouterr().out

    assert rc == 0
    assert out == b""


def test_malformed_stdin_exits_zero(monkeypatch, capsysbinary, golden_repo):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", golden_repo)
    wrapper = io.TextIOWrapper(io.BytesIO(b"this is not json {"), encoding="utf-8")
    monkeypatch.setattr(sys, "stdin", wrapper)
    rc = claude_code.main()
    assert rc == 0
    assert capsysbinary.readouterr().out == b""


def test_empty_prompt_exits_zero(monkeypatch, capsysbinary, golden_repo):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", golden_repo)
    _feed_stdin(monkeypatch, {"prompt": "   ", "cwd": golden_repo})
    rc = claude_code.main()
    assert rc == 0
    assert capsysbinary.readouterr().out == b""


def test_successful_injection_shape(monkeypatch, capsysbinary, golden_repo):
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
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", golden_repo)
    _feed_stdin(monkeypatch, {"prompt": "explain AlphaService", "cwd": golden_repo})

    rc = claude_code.main()
    out = capsysbinary.readouterr().out
    assert rc == 0
    payload = json.loads(out.decode("utf-8"))
    assert payload["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    assert "AlphaService" in payload["hookSpecificOutput"]["additionalContext"]
