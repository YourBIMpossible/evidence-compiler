"""CLI replay identity-mismatch warning (audit F-2, packet spec §5)."""

from __future__ import annotations

from evidence_compiler.cli import render_replay_report
from evidence_compiler.packet import Correlation, EvidencePacket, Identity, Task


def _packet(repository_root):
    return EvidencePacket(
        identity=Identity(repository_root=str(repository_root), head="abc123"),
        correlation=Correlation(prompt_hash="ph"),
        task=Task(raw_prompt_hash="ph"),
    )


def test_replay_warns_on_repository_mismatch(tmp_path):
    repo_a = tmp_path / "a"
    repo_b = tmp_path / "b"
    repo_a.mkdir()
    repo_b.mkdir()
    report = render_replay_report(_packet(repo_a), cwd=str(repo_b))
    assert report.startswith("WARNING:")
    assert str(repo_a).replace("\\", "/") in report
    assert str(repo_b).replace("\\", "/") in report


def test_replay_silent_when_repository_matches(tmp_path):
    repo = tmp_path / "a"
    repo.mkdir()
    report = render_replay_report(_packet(repo), cwd=str(repo))
    assert not report.startswith("WARNING:")


def test_replay_silent_when_cwd_inside_repository_root(tmp_path):
    repo = tmp_path / "a"
    (repo / "src").mkdir(parents=True)
    report = render_replay_report(_packet(repo), cwd=str(repo / "src"))
    assert not report.startswith("WARNING:")


def test_replay_silent_when_cwd_not_supplied(tmp_path):
    repo = tmp_path / "a"
    repo.mkdir()
    report = render_replay_report(_packet(repo))
    assert not report.startswith("WARNING:")
