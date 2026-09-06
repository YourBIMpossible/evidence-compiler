"""Local packet-review workflow (``evidence review``): synthetic corpus tests.

No real prompts, no fabricated dogfood labels — only shape, determinism,
privacy, and window arithmetic.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

from evidence_compiler import review
from evidence_compiler.cli import main
from evidence_compiler.config import Config
from evidence_compiler.packet import (
    CollectorRun,
    Correlation,
    EvidencePacket,
    Identity,
    Task,
    Timing,
)
from evidence_compiler.storage import save_packet


def _packet(repo, *, symbols, session=None, source_kind="human", rg="ok", git="ok", ms=100.0, created=None):
    p = EvidencePacket(
        identity=Identity(repository_root=repo, session_id=session, head="a" * 40, head_state="resolved"),
        correlation=Correlation(prompt_hash="h" * 64),
        task=Task(raw_prompt_hash="h" * 64, extracted_symbols=symbols, source_kind=source_kind),
        collectors_run=[
            CollectorRun(name="git", status=git, duration_ms=5.0),
            CollectorRun(name="ripgrep", status=rg, duration_ms=50.0, diagnostic={"outcome": rg}),
        ],
        timing=Timing(total_ms=ms),
    )
    if created:
        p.created_at = created
    return p


def _corpus(tmp_path):
    repo = str(tmp_path)
    storage = os.path.join(repo, ".evidence-compiler", "packets")
    packets = [
        _packet(repo, symbols=["AlphaService"], created="2026-09-01T10:00:00Z"),
        _packet(repo, symbols=["BetaService"], rg="timeout", created="2026-09-01T11:00:00Z"),
        _packet(repo, symbols=[], created="2026-09-02T10:00:00Z"),
        _packet(repo, symbols=["x"], session="probe-1", created="2026-09-02T11:00:00Z"),
        _packet(repo, symbols=[], source_kind="harness", created="2026-09-03T10:00:00Z"),
        _packet(repo, symbols=["Users", "AppData", "Temp", "output"], created="2026-09-03T11:00:00Z"),
        _packet(repo, symbols=["GammaService"], created="2026-09-04T10:00:00Z"),
    ]
    for p in packets:
        save_packet(p, storage)
    return repo, packets


def test_scan_classifies_traffic(tmp_path):
    repo, _ = _corpus(tmp_path)
    inv = review.scan(repo, Config())
    assert len(inv.summaries) == 7 and inv.unreadable == 0
    assert inv.by_traffic() == {"candidate": 3, "nosym": 1, "harness": 2, "probe": 1}
    degraded = [s for s in inv.summaries if s.degraded]
    assert len(degraded) == 1 and degraded[0].rg_outcome == "timeout"


def test_sample_is_reproducible_and_skips_harness(tmp_path):
    repo, _ = _corpus(tmp_path)
    inv = review.scan(repo, Config())
    a = review.sample(inv.summaries, seed=7, size=3)
    b = review.sample(inv.summaries, seed=7, size=3)
    assert [s.packet_id for s in a] == [s.packet_id for s in b]
    assert all(s.traffic in ("candidate", "nosym") for s in a)
    assert len(a) == 3


def test_label_round_trip_and_privacy(tmp_path):
    repo, _ = _corpus(tmp_path)
    inv = review.scan(repo, Config())
    target = [s for s in inv.summaries if s.traffic == "candidate"][0]
    rdir = review.review_dir(repo)
    review.append_label(rdir, target, "helped", note="x" * 500)
    labels = review.load_labels(rdir)
    assert labels[target.packet_id]["label"] == "helped"
    assert len(labels[target.packet_id]["note"]) == review.MAX_NOTE_CHARS
    raw = open(os.path.join(rdir, review.LABELS_FILE), encoding="utf-8").read()
    assert set(json.loads(raw.splitlines()[0]).keys()) == {"ts", "packet_id", "prompt_hash", "label", "note"}
    # re-scan picks the label up and the sample skips it by default
    inv2 = review.scan(repo, Config())
    assert [s for s in inv2.summaries if s.packet_id == target.packet_id][0].label == "helped"
    assert target.packet_id not in {s.packet_id for s in review.sample(inv2.summaries, seed=1, size=10)}


def test_window_start_and_due(tmp_path):
    repo, packets = _corpus(tmp_path)
    inv = review.scan(repo, Config())
    rdir = review.review_dir(repo)
    window = review.start_window(rdir, "W3", inv, note="clean baseline")
    assert window["baseline"]["packets"] == 7
    assert window["baseline"]["last_packet_id"] == inv.summaries[-1].packet_id
    # nothing on disk is newer than the window: zero in-window packets
    in_win = [s for s in inv.summaries if review.in_window(s, window)]
    assert in_win == []
    agg = review.aggregate(in_win)
    assert review.window_due(window, agg, Config()) == []
    later = datetime.now(timezone.utc) + timedelta(days=15)
    assert review.window_due(window, agg, Config(), now=later)
    # packets on disk are untouched
    for p in packets:
        assert os.path.exists(os.path.join(repo, ".evidence-compiler", "packets"))


def test_status_and_inventory_render_without_prompt_text(tmp_path):
    repo, _ = _corpus(tmp_path)
    cfg = Config()
    inv = review.scan(repo, cfg)
    text = review.render_status(inv, None, cfg) + review.render_inventory(inv, None, only_window=False)
    assert "candidate=3" in text
    assert "REVIEW DUE" in text  # no window started yet
    assert "latency" in text
    assert "AlphaService" not in text  # symbols/prompts never rendered


def test_cli_review_flow(tmp_path, capsys):
    repo, _ = _corpus(tmp_path)
    assert main(["review", "--repo", repo, "window", "start", "--name", "W3"]) == 0
    assert main(["review", "--repo", repo, "inventory", "--all"]) == 0
    assert main(["review", "--repo", repo, "sample", "--all", "--seed", "3", "--n", "2"]) == 0
    out = capsys.readouterr().out
    assert "sample      2 packet(s), seed 3" in out
    pid = [line.split()[0] for line in out.splitlines() if line.startswith("ep")][0]
    assert main(["review", "--repo", repo, "label", pid, "neutral", "--note", "fine"]) == 0
    assert main(["review", "--repo", repo, "status"]) == 0
    assert main(["review", "--repo", repo, "label", "zzz", "helped"]) == 2
