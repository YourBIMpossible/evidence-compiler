"""ContextBrief v1 renderer (`docs/specifications/context-brief-v1.md`).

Renders only *selected* evidence, preserves ``file:line`` references, stays
within ``budget.max_tokens``, and never presents provisional/stale items as
verified structure. The brief is a derived view — it invents nothing that is
not already in the packet.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .packet import EvidenceItem, EvidencePacket
from .scoping import estimate_tokens

# lane grouping by source_claim.kind
_LANES: list[tuple[str, tuple[str, ...]]] = [
    ("Structural", ("graph_edge", "graph_path")),
    ("Lexical", ("lexical_def", "lexical_match")),
    ("Repository", ("git_meta", "git_dirty")),
]
_OTHER_LANE = "Other"


@dataclass
class RenderResult:
    text: str
    tokens: int
    rendered_ids: list[str] = field(default_factory=list)
    dropped_ids: list[str] = field(default_factory=list)


def render_brief(packet: EvidencePacket) -> RenderResult:
    """Render the ContextBrief text for ``packet`` within its max-token budget.

    Items are admitted highest-score-first, and the *whole assembled document*
    is re-measured on each admission — so the returned text is guaranteed to
    stay within ``budget.max_tokens`` including all framing, lane headers, and
    the omitted-count line. Empty selection renders nothing (spec §4).
    """
    max_tokens = packet.budget.max_tokens

    selected = [item for item in packet.evidence if item.compiler_assessment.selected]
    selected.sort(key=lambda it: (-it.compiler_assessment.final_score, it.id))
    negatives = [n for n in packet.negative_evidence if n.outcome == "no_existing_reference"]

    chosen: list[EvidenceItem] = []
    dropped_ids: list[str] = []
    for item in selected:
        trial = chosen + [item]
        if estimate_tokens(_assemble(packet, trial, [], reserve_omitted=True)) <= max_tokens:
            chosen.append(item)
        else:
            dropped_ids.append(item.id)

    chosen_neg: list = []
    for neg in negatives:
        trial_neg = chosen_neg + [neg]
        if estimate_tokens(_assemble(packet, chosen, trial_neg, reserve_omitted=True)) <= max_tokens:
            chosen_neg.append(neg)

    if not chosen and not chosen_neg:
        return RenderResult(text="", tokens=0, rendered_ids=[], dropped_ids=dropped_ids)

    omitted_count = len(packet.budget.omitted_evidence_ids) + len(dropped_ids)
    text = _assemble(packet, chosen, chosen_neg, omitted_count=omitted_count)
    return RenderResult(
        text=text,
        tokens=estimate_tokens(text),
        rendered_ids=[i.id for i in chosen],
        dropped_ids=dropped_ids,
    )


def _assemble(
    packet: EvidencePacket,
    items: list[EvidenceItem],
    negatives: list,
    *,
    reserve_omitted: bool = False,
    omitted_count: int | None = None,
) -> str:
    """Build the brief text. ``reserve_omitted`` includes a worst-case
    omitted-count line so budget checks during admission never underestimate."""
    lane_lines: dict[str, list[str]] = {}
    for item in items:
        lane_lines.setdefault(_lane_for(item.source_claim.kind), []).append(_item_line(item))

    parts = [_header(packet), ""]
    for lane_title, _ in _LANES:
        if lane_lines.get(lane_title):
            parts.append(f"## {lane_title}")
            parts.extend(lane_lines[lane_title])
            parts.append("")
    if lane_lines.get(_OTHER_LANE):
        parts.append(f"## {_OTHER_LANE}")
        parts.extend(lane_lines[_OTHER_LANE])
        parts.append("")
    if negatives:
        parts.append("## Absence")
        for neg in negatives:
            roots = ", ".join(neg.searched_roots) or "."
            parts.append(f"- no references to {neg.query} under {roots}")
        parts.append("")

    if reserve_omitted:
        # worst-case width: every evidence item could be the omitted count
        parts.append(
            f"({len(packet.evidence)} additional item(s) omitted for budget/relevance)"
        )
    elif omitted_count:
        parts.append(f"({omitted_count} additional item(s) omitted for budget/relevance)")

    parts.append("</context_brief>")
    return "\n".join(parts).rstrip() + "\n"


def _header(packet: EvidencePacket) -> str:
    head = packet.identity.head or "unknown"
    lines = [f'<context_brief packet_id="{packet.packet_id}" head="{head}">']
    lines.append(f"Scope confidence: {packet.scope.confidence}")
    if packet.scope.sources:
        lines.append(f"Sources: {', '.join(packet.scope.sources)}")
    return "\n".join(lines)


def _item_line(item: EvidenceItem) -> str:
    reason = "; ".join(item.compiler_assessment.selected_because) or "in scope"
    prefix = f"- [{item.provenance.collector}] {item.source_claim.statement}"
    provisional = " (provisional — dirty/stale, not verified)" if item.status == "provisional" else ""
    return f"{prefix}{provisional}\n  why: {reason}"


def _lane_for(kind: str) -> str:
    for lane_title, kinds in _LANES:
        if kind in kinds:
            return lane_title
    return _OTHER_LANE
