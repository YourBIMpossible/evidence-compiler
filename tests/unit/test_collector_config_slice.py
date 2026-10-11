"""The compiler hands every collector job its own config slice (interface spec §2)."""

from __future__ import annotations

import os

from evidence_compiler.collectors import ripgrep as rgmod
from evidence_compiler.collectors.base import Collector, CollectorContext, EvidenceResult
from evidence_compiler.collectors.ripgrep import RipgrepCollector
from evidence_compiler.compiler import compile_packet
from evidence_compiler.config import Config

from tests.support import make_context


class _ConfigSpy(Collector):
    name = "spy"

    def __init__(self) -> None:
        self.seen: dict[str, dict] = {}

    def collect(self, context: CollectorContext) -> EvidenceResult:
        self.seen[context.repository_root] = dict(context.config)
        return EvidenceResult(collector=self.name, status="empty")


def _repo(path) -> str:
    os.makedirs(path / ".git", exist_ok=True)
    return str(path).replace("\\", "/")


def test_primary_job_receives_collector_slice(tmp_path) -> None:
    session = _repo(tmp_path / "session")
    spy = _ConfigSpy()
    cfg = Config(data={"collectors": {"spy": {"timeout_ms": 400, "extra_args": ["--hidden"], "k": 1}}})
    compile_packet("fix Widget", session, config=cfg, collectors=[spy], persist=False)
    (seen,) = spy.seen.values()
    assert seen == {"enabled": True, "timeout_ms": 400, "extra_args": ["--hidden"], "k": 1}


def test_secondary_job_receives_same_collector_slice(tmp_path) -> None:
    session, other = _repo(tmp_path / "session"), _repo(tmp_path / "other")
    spy = _ConfigSpy()
    cfg = Config(data={"scoping": {"allowed_roots": [other]},
                       "collectors": {"spy": {"timeout_ms": 400, "extra_args": ["--hidden"]}}})
    compile_packet(f"fix Widget like {other}/src/w.py", session, config=cfg, collectors=[spy], persist=False)
    assert len(spy.seen) == 2
    assert all(s["extra_args"] == ["--hidden"] for s in spy.seen.values())


def test_ripgrep_extra_args_reach_rg_through_compiler(golden_repo, monkeypatch) -> None:
    cmds: list[list[str]] = []
    real_run = rgmod.subprocess.run

    def recording_run(cmd, *a, **kw):
        if "--json" in cmd:  # rg calls only; git probes share subprocess
            cmds.append(list(cmd))
        return real_run(cmd, *a, **kw)

    monkeypatch.setattr(rgmod.subprocess, "run", recording_run)
    cfg = Config(data={"collectors": {"ripgrep": {"extra_args": ["--hidden"]}}})
    compile_packet("fix AlphaService", golden_repo, config=cfg, collectors=[RipgrepCollector()], persist=False)
    assert cmds and all("--hidden" in c for c in cmds)


def test_ripgrep_ignores_malformed_extra_args(golden_repo, monkeypatch) -> None:
    cmds: list[list[str]] = []
    real_run = rgmod.subprocess.run

    def recording_run(cmd, *a, **kw):
        if "--json" in cmd:  # rg calls only; git probes share subprocess
            cmds.append(list(cmd))
        return real_run(cmd, *a, **kw)

    monkeypatch.setattr(rgmod.subprocess, "run", recording_run)
    ctx = make_context(golden_repo, "x", extracted_symbols=["AlphaService"], config={"extra_args": "--hidden"})
    result = RipgrepCollector().collect(ctx)
    assert result.status == "ok"
    assert cmds and not any("--hidden" in c for c in cmds)
    assert not any("-" in c or "h" in c for c in cmds)  # string not split into chars
