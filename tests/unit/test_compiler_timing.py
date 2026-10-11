"""Compiler deadline is end-to-end from compile start; persistence failures
are reported by class name without breaking the result."""

from __future__ import annotations

import time

from evidence_compiler import compiler as compiler_mod
from evidence_compiler import gitprobe
from evidence_compiler.compiler import compile_packet
from evidence_compiler.config import Config

from tests.support import HangingCollector


def test_collection_gets_only_the_remaining_deadline(golden_repo, monkeypatch) -> None:
    real_probe = gitprobe.probe

    def slow_probe(cwd, timeout_ms):
        time.sleep(0.3)
        return real_probe(cwd, timeout_ms=timeout_ms)

    seen: list[int] = []
    real_run = compiler_mod._run_collectors

    def spy(jobs, cfg, deadline_ms, **kw):
        seen.append(deadline_ms)
        return real_run(jobs, cfg, deadline_ms, **kw)

    monkeypatch.setattr(compiler_mod.gitprobe, "probe", slow_probe)
    monkeypatch.setattr(compiler_mod, "_run_collectors", spy)
    compile_packet("fix AlphaService", golden_repo, config=Config(), collectors=[HangingCollector(5.0)],
                   deadline_ms=1000, persist=False)
    assert seen and 1 <= seen[0] <= 700


def test_deadline_already_spent_still_fails_open(golden_repo, monkeypatch) -> None:
    real_probe = gitprobe.probe

    def slow_probe(cwd, timeout_ms):
        time.sleep(0.2)
        return real_probe(cwd, timeout_ms=timeout_ms)

    monkeypatch.setattr(compiler_mod.gitprobe, "probe", slow_probe)
    t0 = time.perf_counter()
    res = compile_packet("fix AlphaService", golden_repo, config=Config(), collectors=[HangingCollector(5.0)],
                         deadline_ms=50, persist=False)
    assert time.perf_counter() - t0 < 2.0
    assert [r.status for r in res.packet.collectors_run] == ["timeout"]


def test_persist_failure_reported_by_class_name(golden_repo, monkeypatch) -> None:
    import evidence_compiler.storage as storage_mod

    def broken_save(packet, storage_dir):
        raise OSError("disk full at a path that may carry prompt text")

    monkeypatch.setattr(storage_mod, "save_packet", broken_save)
    res = compile_packet("fix AlphaService", golden_repo, config=Config(), persist=True)
    assert res.storage_path is None and res.persist_error == "OSError"
    assert res.brief


def test_persist_success_has_no_error(golden_repo, tmp_path) -> None:
    cfg = Config(data={"storage": {"dir": str(tmp_path / "packets")}})
    res = compile_packet("fix AlphaService", golden_repo, config=cfg, persist=True)
    assert res.storage_path and res.persist_error is None
