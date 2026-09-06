"""Window 3 measurement automation on ``evidence review``: deterministic
queue, validated labels, reminder, status signal. Synthetic corpus only — no
real prompts, no fabricated dogfood labels.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest

from evidence_compiler import review
from evidence_compiler.cli import main
from evidence_compiler.config import Config
from evidence_compiler.packet import Correlation, EvidencePacket, Identity, Task
from tests.unit.test_review import _corpus, _packet


def _ids(rows):
    return [s.packet_id for s in rows]


# -- queue -------------------------------------------------------------------


def test_queue_is_deterministic_and_stable_after_labeling(tmp_path):
    repo, _ = _corpus(tmp_path)
    inv = review.scan(repo, Config())
    q1 = review.queue(inv.summaries, size=10, window_name="W3")
    q2 = review.queue(inv.summaries, size=10, window_name="W3")
    assert _ids(q1) == _ids(q2)
    assert [s.traffic for s in q1] == ["candidate"] * 3 + ["nosym"]
    # labeling the first packet removes it and leaves the rest in the same order
    review.append_label(review.review_dir(repo), q1[0], "neutral", note="synthetic")
    after = review.queue(review.scan(repo, Config()).summaries, size=10, window_name="W3")
    assert _ids(after) == _ids(q1)[1:]


def test_queue_order_depends_on_window_name_only_through_hash(tmp_path):
    repo, _ = _corpus(tmp_path)
    inv = review.scan(repo, Config())
    a = set(_ids(review.queue(inv.summaries, size=10, window_name="W3")))
    b = set(_ids(review.queue(inv.summaries, size=10, window_name="W4")))
    assert a == b  # same membership; ordering per window is a hash, not a sample
    assert review.queue(inv.summaries, size=0, window_name="W3") == []
    assert len(review.queue(inv.summaries, size=2, window_name=None)) == 2


def test_queue_excludes_harness_probe_and_labeled(tmp_path):
    repo, _ = _corpus(tmp_path)
    inv = review.scan(repo, Config())
    q = review.queue(inv.summaries, size=50, window_name="W3")
    assert all(s.traffic in ("candidate", "nosym") for s in q)
    assert all(s.label is None for s in q)
    text = review.render_queue(q, window_name="W3")
    assert "AlphaService" not in text and "GammaService" not in text
    assert "evidence replay" in text
    assert "nothing to review" in review.render_queue([], window_name="W3")


# -- labels ------------------------------------------------------------------


def test_label_requires_a_note_and_a_known_label(tmp_path):
    repo, _ = _corpus(tmp_path)
    inv = review.scan(repo, Config())
    target = next(s for s in inv.summaries if s.traffic == "candidate")
    rdir = review.review_dir(repo)
    with pytest.raises(ValueError, match="note is required"):
        review.append_label(rdir, target, "helped", note="   ")
    with pytest.raises(ValueError, match="label must be one of"):
        review.append_label(rdir, target, "great", note="x")
    assert review.validate_label("helped", "  two\n  lines  ") == "two lines"
    assert len(review.validate_label("helped", "x" * 500)) == review.MAX_NOTE_CHARS


def test_load_labels_skips_non_object_lines(tmp_path):
    repo, _ = _corpus(tmp_path)
    inv = review.scan(repo, Config())
    rdir = review.review_dir(repo)
    target = inv.summaries[0]
    review.append_label(rdir, target, "neutral", note="synthetic")
    with open(os.path.join(rdir, review.LABELS_FILE), "a", encoding="utf-8") as fh:
        fh.write("[1, 2]\n\"str\"\n42\nnot json\n")
    labels = review.load_labels(rdir)
    assert labels[target.packet_id]["label"] == "neutral"
    assert len(labels) == 1


def test_cli_label_without_note_exits_2(tmp_path, capsys):
    repo, _ = _corpus(tmp_path)
    inv = review.scan(repo, Config())
    pid = next(s for s in inv.summaries if s.traffic == "candidate").packet_id
    assert main(["review", "--repo", repo, "label", pid, "helped"]) == 2
    err = capsys.readouterr().err
    assert "note is required" in err
    assert review.load_labels(review.review_dir(repo)) == {}


# -- traffic classification ------------------------------------------------------


def test_legacy_harness_word_rule_applies_only_without_symbol_details():
    words = ["Users", "AppData", "Temp", "output"]
    legacy = EvidencePacket(
        identity=Identity(repository_root="/r"),
        correlation=Correlation(prompt_hash="h"),
        task=Task(raw_prompt_hash="h", extracted_symbols=words),
    )
    assert review.classify_traffic(legacy) == "harness"
    modern = EvidencePacket(
        identity=Identity(repository_root="/r"),
        correlation=Correlation(prompt_hash="h"),
        task=Task(
            raw_prompt_hash="h",
            extracted_symbols=words,
            source_kind="human",
            symbol_details=[{"value": w, "category": "capitalized", "rank": 30} for w in words],
        ),
    )
    assert review.classify_traffic(modern) == "candidate"


# -- reminder + status -----------------------------------------------------------


def test_remind_is_silent_until_due(tmp_path):
    repo, _ = _corpus(tmp_path)
    cfg = Config()
    inv = review.scan(repo, cfg)
    rdir = review.review_dir(repo)
    assert review.remind(inv, None, cfg).startswith("evidence review due ((none))")
    window = review.start_window(rdir, "W3", inv)
    assert review.remind(inv, window, cfg) == ""
    later = datetime.now(timezone.utc) + timedelta(days=14)
    line = review.remind(inv, window, cfg, now=later)
    assert line.startswith("evidence review due (W3)") and line.count("\n") == 1
    assert "evidence review queue" in line


def test_remind_fires_on_unlabeled_candidate_threshold(tmp_path):
    repo, _ = _corpus(tmp_path)
    cfg = Config()
    rdir = review.review_dir(repo)
    window = review.start_window(rdir, "W3", review.scan(repo, cfg))
    storage = os.path.join(repo, ".evidence-compiler", "packets")
    from evidence_compiler.storage import save_packet

    for i in range(cfg.review_threshold("window_candidates")):
        save_packet(_packet(repo, symbols=[f"Svc{i}"]), storage)
    inv = review.scan(repo, cfg)
    line = review.remind(inv, window, cfg)
    assert "unlabeled candidate packets" in line


def test_status_reports_baseline_review_progress_and_head_watch(tmp_path):
    repo, _ = _corpus(tmp_path)
    cfg = Config()
    rdir = review.review_dir(repo)
    inv = review.scan(repo, cfg)
    window = review.start_window(rdir, "W3", inv)
    review.append_label(rdir, inv.summaries[0], "neutral", note="synthetic")
    storage = os.path.join(repo, ".evidence-compiler", "packets")
    from evidence_compiler.storage import save_packet

    save_packet(_packet(repo, symbols=["NewSvc"]), storage)
    unbound = _packet(repo, symbols=["Other"])
    unbound.identity.head = None
    unbound.identity.head_state = None
    save_packet(unbound, storage)
    inv = review.scan(repo, cfg)
    text = review.render_status(inv, window, cfg)
    assert "(baseline 7 at window start)" in text
    assert "2 in window / 9 on disk" in text
    assert "head       1 packet(s) without a head commit" in text
    assert "candidates reviewed 0 / unreviewed 2" in text
    assert "raw packet count is activity, not usefulness" in text
    assert "harness/probe packet(s) are system traffic" in text
    assert "(0% of 2)" in text
    assert "NewSvc" not in text and "Other" not in text
    agg = review.aggregate(inv.summaries)
    assert agg.labeled_candidates == 1 and agg.head_unbound == 1
    assert agg.degraded_rate == pytest.approx(1 / 9)


def test_cli_queue_and_remind(tmp_path, capsys):
    repo, _ = _corpus(tmp_path)
    assert main(["review", "--repo", repo, "remind"]) == 0
    assert "evidence review due" in capsys.readouterr().out
    assert main(["review", "--repo", repo, "window", "start", "--name", "W3"]) == 0
    capsys.readouterr()
    assert main(["review", "--repo", repo, "remind"]) == 0
    assert capsys.readouterr().out == ""
    assert main(["review", "--repo", repo, "queue", "--all", "--n", "2"]) == 0
    out = capsys.readouterr().out
    assert "queue       2 unlabeled packet(s), window W3" in out
    assert len([line for line in out.splitlines() if line.startswith("ep")]) == 2
    assert main(["review", "--repo", repo, "queue"]) == 0
    assert "queue       0 unlabeled" in capsys.readouterr().out
