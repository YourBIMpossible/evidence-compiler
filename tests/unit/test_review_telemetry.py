"""Window 3 follow-through: capped and stalled ripgrep passes must be
unmistakable in every review view, and repeated same-category incidents on
human-task packets trigger a review immediately. Synthetic corpus only.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

from evidence_compiler import review
from evidence_compiler.config import Config
from evidence_compiler.packet import CollectorRun
from evidence_compiler.storage import save_packet
from tests.unit.test_review import _packet


def _rg_diag(**overrides):
    diag = {
        "symbols_total": 9,
        "symbols_searched": 7,
        "symbols_matched": 5,
        "symbols_no_match": 2,
        "symbols_timeout": 0,
        "symbols_error": 0,
        "symbols_not_searched": 2,
        "matches": 100,
        "budget_ms": 1500,
        "outcome": "matches",
    }
    diag.update(overrides)
    return diag


def _with_rg(packet, status, diag):
    packet.collectors_run = [
        CollectorRun(name="git", status="ok", duration_ms=5.0),
        CollectorRun(name="ripgrep", status=status, duration_ms=900.0, diagnostic=diag),
    ]
    return packet


def _capped(repo, created, **kw):
    return _with_rg(
        _packet(repo, symbols=["A", "B", "C"], created=created, **kw), "ok", _rg_diag(truncated=True, cap=100)
    )


def _stalled(repo, created, **kw):
    diag = _rg_diag(
        symbols_searched=10,
        symbols_matched=0,
        symbols_no_match=0,
        symbols_timeout=10,
        symbols_not_searched=0,
        matches=0,
        outcome="timeout",
    )
    return _with_rg(_packet(repo, symbols=["A", "B"], created=created, **kw), "timeout", diag)


def _save(repo, packets):
    storage = os.path.join(repo, ".evidence-compiler", "packets")
    for p in packets:
        save_packet(p, storage)
    return review.scan(repo, Config())


# -- cap visibility -----------------------------------------------------------


def test_capped_packet_is_labeled_truncated_in_every_view(tmp_path):
    repo = str(tmp_path)
    inv = _save(
        repo,
        [
            _capped(repo, "2026-09-06T10:00:00Z"),
            _with_rg(
                _packet(repo, symbols=["D"], created="2026-09-06T11:00:00Z"),
                "ok",
                _rg_diag(matches=12, symbols_not_searched=0),
            ),
        ],
    )
    capped = next(s for s in inv.summaries if s.rg_truncated)
    plain = next(s for s in inv.summaries if not s.rg_truncated)
    assert capped.rg_outcome == "matches" and capped.rg_display == "matches+capped"
    assert capped.collector_status["ripgrep"] == "ok"  # the cap is not a timeout
    assert plain.rg_display == "matches"
    assert capped.as_dict()["rg_display"] == "matches+capped"
    assert capped.incidents == ["cap_hit"]

    q = review.queue(inv.summaries, size=10, window_name="W3")
    text = review.render_queue(q, window_name="W3")
    assert capped.packet_id in text and "rg=matches+capped" in text
    assert text.count("+capped") == 1
    assert "+capped" in review.render_sample(review.sample(inv.summaries, size=10, seed=1), seed=1)
    assert "matches+capped" in review.render_inventory(inv, None, only_window=False)
    status = review.render_status(inv, None, Config())
    assert "rg capped  1 packet(s) truncated by the total match cap" in status


def test_cap_flag_is_deterministic_across_scans(tmp_path):
    repo = str(tmp_path)
    _save(repo, [_capped(repo, "2026-09-06T10:00:00Z")])
    views = {review.render_inventory(review.scan(repo, Config()), None, only_window=False) for _ in range(5)}
    assert len(views) == 1


# -- stall watch --------------------------------------------------------------


def test_rg_stall_requires_every_searched_symbol_to_time_out():
    assert review._is_rg_stall("timeout", {"symbols_searched": 10, "symbols_timeout": 10})
    assert not review._is_rg_stall("timeout", {"symbols_searched": 10, "symbols_timeout": 4})  # partial
    assert not review._is_rg_stall("timeout", {"symbols_searched": 1, "symbols_timeout": 1})  # one slow symbol
    assert not review._is_rg_stall("ok", {"symbols_searched": 5, "symbols_timeout": 5})
    assert not review._is_rg_stall("timeout", {"symbols_searched": "x"})


def test_stall_is_surfaced_and_counted(tmp_path):
    repo = str(tmp_path)
    inv = _save(repo, [_stalled(repo, "2026-09-06T10:00:00Z")])
    s = inv.summaries[0]
    assert s.rg_stall and s.rg_display == "timeout+stall"
    assert s.incidents == ["degraded:ripgrep", "rg_stall"]
    status = review.render_status(inv, None, Config())
    assert "rg stall   1 packet(s) where every searched symbol timed out" in status
    assert "incidents  degraded:ripgrep=1  rg_stall=1" in status


# -- immediate incident trigger -----------------------------------------------


def test_three_same_category_candidate_incidents_trigger_review(tmp_path):
    repo = str(tmp_path)
    inv = _save(repo, [_capped(repo, f"2026-09-06T1{i}:00:00Z") for i in range(3)])
    now = datetime(2026, 9, 7, tzinfo=timezone.utc)
    window = {"name": "W3", "started_at": "2026-09-06T00:00:00Z"}
    due = review.window_due(window, review.aggregate(inv.summaries), Config(), now=now)
    assert due == ["3 candidate packets with cap_hit incidents (threshold 3)"]
    assert review.remind(inv, window, Config(), now=now).startswith(
        "evidence review due (W3): 3 candidate packets with cap_hit"
    )


def test_incident_trigger_ignores_probes_mixed_categories_and_zero_threshold(tmp_path):
    repo = str(tmp_path)
    packets = [
        _capped(repo, "2026-09-06T10:00:00Z", session="probe-1"),  # system traffic never counts
        _capped(repo, "2026-09-06T11:00:00Z", source_kind="harness"),
        _capped(repo, "2026-09-06T12:00:00Z"),
        _capped(repo, "2026-09-06T13:00:00Z"),
        _stalled(repo, "2026-09-06T14:00:00Z"),
    ]
    inv = _save(repo, packets)
    agg = review.aggregate(inv.summaries)
    assert agg.incidents == {"cap_hit": 2, "degraded:ripgrep": 1, "rg_stall": 1}
    assert agg.rg_truncated == 4  # operational counts still include system traffic
    now = datetime(2026, 9, 7, tzinfo=timezone.utc)
    window = {"name": "W3", "started_at": "2026-09-06T00:00:00Z"}
    assert review.window_due(window, agg, Config(), now=now) == []
    cfg = Config()
    cfg.data["review"]["incident_threshold"] = 2
    assert review.window_due(window, agg, cfg, now=now) == [
        "2 candidate packets with cap_hit incidents (threshold 2)"
    ]
    cfg.data["review"]["incident_threshold"] = 0
    cfg.data["review"]["window_days"] = 0
    assert review.window_due(window, agg, cfg, now=now) == []


def test_hurt_noise_labels_count_as_incidents(tmp_path):
    repo = str(tmp_path)
    inv = _save(repo, [_packet(repo, symbols=["A"], created=f"2026-09-06T1{i}:00:00Z") for i in range(3)])
    rdir = review.review_dir(repo)
    for s in inv.summaries:
        review.append_label(rdir, s, "hurt-noise", note="synthetic")
    agg = review.aggregate(review.scan(repo, Config()).summaries)
    assert agg.incidents == {"hurt-noise": 3}
    window = {"name": "W3", "started_at": "2026-09-06T00:00:00Z"}
    due = review.window_due(window, agg, Config(), now=datetime(2026, 9, 7, tzinfo=timezone.utc))
    assert "3 candidate packets with hurt-noise incidents (threshold 3)" in due
