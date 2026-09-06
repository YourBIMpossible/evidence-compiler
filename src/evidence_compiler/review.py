"""Local, durable packet-review workflow (``evidence review ...``).

Dogfooding needs a fair way to answer "did the brief help?" without reading
raw prompts into a chat window. This module reads persisted packets from a
repo's storage dir, classifies traffic, draws a reproducible stratified
sample, records reviewer labels, and aggregates them — all on disk, all
local, never touching the packets themselves.

Artifacts live beside the packets in ``.evidence-compiler/logs/review/``
(already covered by the ``logs/`` gitignore pattern downstream):

- ``labels.jsonl``  append-only label records
  ``{ts, packet_id, prompt_hash, label, note}``
- ``window.json``   the active review window
  ``{name, started_at, version, baseline: {...}, note}``

Nothing here stores prompt text, collector stdout, or environment data —
only packet ids, hashes, counts, statuses, and short reviewer notes.
"""

from __future__ import annotations

import json
import os
import random
import statistics
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable

from . import __version__
from .config import Config, load_config
from .packet import EvidencePacket, utcnow_iso
from .storage import _PACKET_NAME, load_packet

LABELS = ("helped", "neutral", "hurt-noise", "insufficient")
TRAFFIC_CLASSES = ("candidate", "nosym", "harness", "probe")
REVIEW_RELDIR = os.path.join(".evidence-compiler", "logs", "review")
LABELS_FILE = "labels.jsonl"
WINDOW_FILE = "window.json"
MAX_NOTE_CHARS = 200

# Packets written before ``task.source_kind`` existed carry harness text
# only in the shape of their symbols. Three or more of these generic
# notification/path words in one packet identifies that legacy traffic.
_LEGACY_HARNESS_WORDS = frozenset(
    {"Users", "AppData", "Local", "Temp", "output", "Background", "completed",
     "Status", "Result", "Summary", "Task", "Agent"}
)


@dataclass
class PacketSummary:
    packet_id: str
    created_at: str
    path: str
    prompt_hash: str
    source_kind: str
    traffic: str
    symbol_count: int
    total_ms: float
    collector_status: dict[str, str] = field(default_factory=dict)
    degraded: bool = False
    rg_outcome: str | None = None
    head_state: str | None = None
    session_id: str | None = None
    label: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


# --------------------------------------------------------------------------
# Scanning + classification
# --------------------------------------------------------------------------


def review_dir(repository_root: str) -> str:
    return os.path.join(repository_root, REVIEW_RELDIR)


def classify_traffic(packet: EvidencePacket) -> str:
    sid = packet.identity.session_id or ""
    if sid.startswith("probe"):
        return "probe"
    if packet.task.source_kind == "harness":
        return "harness"
    symbols = packet.task.extracted_symbols
    if len(_LEGACY_HARNESS_WORDS.intersection(symbols)) >= 3:
        return "harness"
    if not symbols:
        return "nosym"
    return "candidate"


def summarize(packet: EvidencePacket, path: str) -> PacketSummary:
    status = {run.name: run.status for run in packet.collectors_run}
    degraded = any(s in ("error", "timeout") for s in status.values())
    rg_outcome = None
    for run in packet.collectors_run:
        if run.name == "ripgrep" and isinstance(run.diagnostic, dict):
            rg_outcome = run.diagnostic.get("outcome") or run.status
    return PacketSummary(
        packet_id=packet.packet_id,
        created_at=packet.created_at,
        path=path,
        prompt_hash=packet.correlation.prompt_hash,
        source_kind=packet.task.source_kind,
        traffic=classify_traffic(packet),
        symbol_count=len(packet.task.extracted_symbols),
        total_ms=float(packet.timing.total_ms),
        collector_status=status,
        degraded=degraded,
        rg_outcome=rg_outcome,
        head_state=packet.identity.head_state,
        session_id=packet.identity.session_id,
    )


@dataclass
class Inventory:
    repository_root: str
    storage_dir: str
    summaries: list[PacketSummary]
    unreadable: int = 0

    def by_traffic(self) -> dict[str, int]:
        counts = {t: 0 for t in TRAFFIC_CLASSES}
        for s in self.summaries:
            counts[s.traffic] = counts.get(s.traffic, 0) + 1
        return counts


def scan(repository_root: str, config: Config | None = None) -> Inventory:
    """Read every packet in the repo's storage dir, oldest first. Unreadable
    files are counted, never raised."""
    cfg = config or load_config(repository_root)
    storage = cfg.storage_dir(repository_root)
    summaries: list[PacketSummary] = []
    unreadable = 0
    if os.path.isdir(storage):
        names = sorted(n for n in os.listdir(storage) if _PACKET_NAME.match(n))
        for name in names:
            path = os.path.join(storage, name)
            try:
                summaries.append(summarize(load_packet(path), path))
            except Exception:  # noqa: BLE001 - one bad file must not stop review
                unreadable += 1
    labels = load_labels(review_dir(repository_root))
    for s in summaries:
        rec = labels.get(s.packet_id)
        if rec:
            s.label = rec.get("label")
    return Inventory(repository_root, storage, summaries, unreadable)


# --------------------------------------------------------------------------
# Labels
# --------------------------------------------------------------------------


def load_labels(directory: str) -> dict[str, dict[str, Any]]:
    """Latest label record per packet id (later lines override earlier)."""
    path = os.path.join(directory, LABELS_FILE)
    out: dict[str, dict[str, Any]] = {}
    if not os.path.isfile(path):
        return out
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            pid = rec.get("packet_id")
            if isinstance(pid, str) and rec.get("label") in LABELS:
                out[pid] = rec
    return out


def append_label(
    directory: str, packet: PacketSummary, label: str, note: str | None = None
) -> dict[str, Any]:
    if label not in LABELS:
        raise ValueError(f"label must be one of {LABELS}, got {label!r}")
    record = {
        "ts": utcnow_iso(),
        "packet_id": packet.packet_id,
        "prompt_hash": packet.prompt_hash,
        "label": label,
        "note": (note or "").strip()[:MAX_NOTE_CHARS],
    }
    os.makedirs(directory, exist_ok=True)
    with open(os.path.join(directory, LABELS_FILE), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


# --------------------------------------------------------------------------
# Windows
# --------------------------------------------------------------------------


def load_window(directory: str) -> dict[str, Any] | None:
    path = os.path.join(directory, WINDOW_FILE)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def start_window(
    directory: str, name: str, inventory: Inventory, note: str | None = None
) -> dict[str, Any]:
    """Record a new window: a timestamp plus the packet baseline it starts
    after. Historical packets are never moved or altered; the window is a
    cut line used by ``status`` to count only what arrives afterwards."""
    previous = load_window(directory)
    window = {
        "name": name,
        "started_at": utcnow_iso(),
        "version": __version__,
        "baseline": {
            "packets": len(inventory.summaries),
            "by_traffic": inventory.by_traffic(),
            "last_packet_id": inventory.summaries[-1].packet_id if inventory.summaries else None,
        },
        "note": (note or "").strip()[:MAX_NOTE_CHARS],
        "previous": {"name": previous.get("name"), "started_at": previous.get("started_at")}
        if previous
        else None,
    }
    os.makedirs(directory, exist_ok=True)
    tmp = os.path.join(directory, WINDOW_FILE + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(window, fh, indent=2)
    os.replace(tmp, os.path.join(directory, WINDOW_FILE))
    return window


def in_window(summary: PacketSummary, window: dict[str, Any] | None) -> bool:
    if not window:
        return True
    started = window.get("started_at")
    return not isinstance(started, str) or summary.created_at >= started


# --------------------------------------------------------------------------
# Sampling + aggregates
# --------------------------------------------------------------------------


def sample(
    summaries: Iterable[PacketSummary],
    *,
    seed: int,
    size: int,
    include_labeled: bool = False,
) -> list[PacketSummary]:
    """Reproducible stratified sample: candidates fill ~80 % of the slots,
    no-symbol packets the rest (spill-over in either direction). Order within
    a stratum is by ``random.Random(seed)`` over ids sorted lexically, so the
    same corpus and seed always yield the same sample. Harness/probe traffic
    is never sampled."""
    pool = [s for s in summaries if s.traffic in ("candidate", "nosym")]
    if not include_labeled:
        pool = [s for s in pool if s.label is None]
    if size <= 0 or not pool:
        return []
    rng = random.Random(seed)
    strata = {
        "candidate": sorted((s for s in pool if s.traffic == "candidate"), key=lambda s: s.packet_id),
        "nosym": sorted((s for s in pool if s.traffic == "nosym"), key=lambda s: s.packet_id),
    }
    for items in strata.values():
        rng.shuffle(items)
    want_candidate = min(len(strata["candidate"]), max(1, round(size * 0.8)) if strata["nosym"] else size)
    chosen = strata["candidate"][:want_candidate]
    chosen += strata["nosym"][: size - len(chosen)]
    if len(chosen) < size:  # spill back into candidates
        chosen += strata["candidate"][want_candidate : want_candidate + (size - len(chosen))]
    return sorted(chosen, key=lambda s: s.created_at)


@dataclass
class Aggregates:
    packets: int
    by_traffic: dict[str, int]
    degraded: int
    collector_status: dict[str, dict[str, int]]
    rg_outcomes: dict[str, int]
    head_states: dict[str, int]
    latency_ms: dict[str, float]
    labels: dict[str, int]
    labeled: int
    unlabeled_candidates: int


def aggregate(summaries: list[PacketSummary]) -> Aggregates:
    by_traffic = {t: 0 for t in TRAFFIC_CLASSES}
    collector_status: dict[str, dict[str, int]] = {}
    rg_outcomes: dict[str, int] = {}
    head_states: dict[str, int] = {}
    labels = {label: 0 for label in LABELS}
    degraded = 0
    latencies: list[float] = []
    for s in summaries:
        by_traffic[s.traffic] = by_traffic.get(s.traffic, 0) + 1
        degraded += int(s.degraded)
        latencies.append(s.total_ms)
        for name, status in s.collector_status.items():
            collector_status.setdefault(name, {})
            collector_status[name][status] = collector_status[name].get(status, 0) + 1
        if s.rg_outcome:
            rg_outcomes[s.rg_outcome] = rg_outcomes.get(s.rg_outcome, 0) + 1
        hs = s.head_state or "(unset)"
        head_states[hs] = head_states.get(hs, 0) + 1
        if s.label:
            labels[s.label] = labels.get(s.label, 0) + 1
    return Aggregates(
        packets=len(summaries),
        by_traffic=by_traffic,
        degraded=degraded,
        collector_status=collector_status,
        rg_outcomes=rg_outcomes,
        head_states=head_states,
        latency_ms=_latency(latencies),
        labels=labels,
        labeled=sum(labels.values()),
        unlabeled_candidates=sum(1 for s in summaries if s.traffic == "candidate" and s.label is None),
    )


def _latency(values: list[float]) -> dict[str, float]:
    if not values:
        return {"p50": 0.0, "p95": 0.0, "max": 0.0}
    ordered = sorted(values)
    p95_index = min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))
    return {
        "p50": round(statistics.median(ordered), 1),
        "p95": round(ordered[p95_index], 1),
        "max": round(ordered[-1], 1),
    }


def window_due(
    window: dict[str, Any] | None, aggregates: Aggregates, cfg: Config, *, now: datetime | None = None
) -> list[str]:
    """Reasons a review is due (empty when it is not)."""
    reasons: list[str] = []
    if window is None:
        return ["no review window started (run `evidence review window start --name <W>`)"]
    days = cfg.review_threshold("window_days")
    cands = cfg.review_threshold("window_candidates")
    started = _parse_ts(window.get("started_at"))
    current = now or datetime.now(timezone.utc)
    if days and started is not None:
        elapsed = (current - started).days
        if elapsed >= days:
            reasons.append(f"window open {elapsed} days (threshold {days})")
    if cands and aggregates.unlabeled_candidates >= cands:
        reasons.append(
            f"{aggregates.unlabeled_candidates} unlabeled candidate packets (threshold {cands})"
        )
    return reasons


def _parse_ts(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


# --------------------------------------------------------------------------
# Text rendering (pure functions; the CLI just prints these)
# --------------------------------------------------------------------------


def render_inventory(inv: Inventory, window: dict[str, Any] | None, *, only_window: bool) -> str:
    rows = [s for s in inv.summaries if not only_window or in_window(s, window)]
    lines = [
        f"repository  {inv.repository_root}",
        f"packets     {len(rows)} shown / {len(inv.summaries)} on disk"
        + (f"  ({inv.unreadable} unreadable)" if inv.unreadable else ""),
        f"window      {window.get('name') if window else '(none)'}"
        + (f" since {window.get('started_at')}" if window else ""),
        "",
        f"{'packet_id':<14} {'created_at':<20} {'traffic':<9} {'sym':>3} {'rg':<15} {'git':<8} {'ms':>7}  label",
    ]
    for s in rows:
        lines.append(
            f"{s.packet_id[:14]:<14} {s.created_at[:19]:<20} {s.traffic:<9} {s.symbol_count:>3} "
            f"{(s.rg_outcome or s.collector_status.get('ripgrep', '-')):<15} "
            f"{s.collector_status.get('git', '-'):<8} {s.total_ms:>7.0f}  {s.label or ''}"
        )
    return "\n".join(lines) + "\n"


def render_sample(chosen: list[PacketSummary], *, seed: int) -> str:
    lines = [f"sample      {len(chosen)} packet(s), seed {seed}", ""]
    for s in chosen:
        lines.append(
            f"{s.packet_id}  {s.created_at[:19]}  {s.traffic:<9} sym={s.symbol_count} "
            f"rg={s.rg_outcome or '-'}  {_display_path(s.path)}"
        )
    if chosen:
        lines += ["", "review with:  evidence replay <path>",
                  "label with:   evidence review label <packet_id> <helped|neutral|hurt-noise|insufficient> [--note ...]"]
    return "\n".join(lines) + "\n"


def _display_path(path: str) -> str:
    try:
        rel = os.path.relpath(path)
    except ValueError:  # different drive on Windows
        return path
    return rel if not rel.startswith("..") else path


def render_status(
    inv: Inventory, window: dict[str, Any] | None, cfg: Config, *, now: datetime | None = None
) -> str:
    rows = [s for s in inv.summaries if in_window(s, window)]
    agg = aggregate(rows)
    all_agg = aggregate(inv.summaries)
    due = window_due(window, agg, cfg, now=now)
    lines = [
        f"repository  {inv.repository_root}",
        f"window      {window.get('name') if window else '(none)'}"
        + (f" since {window.get('started_at')} (v{window.get('version')})" if window else ""),
        f"packets     {agg.packets} in window / {all_agg.packets} on disk",
        "",
        "traffic     " + "  ".join(f"{k}={v}" for k, v in agg.by_traffic.items()),
        "",
        "operational health (in window):",
        f"  degraded   {agg.degraded} packet(s) with a collector error/timeout",
    ]
    for name, statuses in sorted(agg.collector_status.items()):
        lines.append(f"  {name:<9}  " + "  ".join(f"{k}={v}" for k, v in sorted(statuses.items())))
    if agg.rg_outcomes:
        lines.append("  rg outcome " + "  ".join(f"{k}={v}" for k, v in sorted(agg.rg_outcomes.items())))
    lines.append("  head_state " + "  ".join(f"{k}={v}" for k, v in sorted(agg.head_states.items())))
    lat = agg.latency_ms
    lines.append(f"  latency    p50 {lat['p50']} ms  p95 {lat['p95']} ms  max {lat['max']} ms")
    lines += [
        "",
        "usefulness (labels in window):",
        "  " + "  ".join(f"{k}={v}" for k, v in agg.labels.items()) + f"  (labeled {agg.labeled})",
        f"  unlabeled candidates: {agg.unlabeled_candidates}",
        "",
    ]
    if due:
        lines.append("REVIEW DUE: " + "; ".join(due))
    else:
        lines.append("review not yet due")
    return "\n".join(lines) + "\n"
