"""ContextBrief v1 renderer (`docs/specifications/context-brief-v1.md`).

Renders only *selected* evidence, preserves ``file:line`` references, stays
within ``budget.max_tokens``, and never presents provisional/stale items as
verified structure. The brief is a derived view — it invents nothing that is
not already in the packet.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .packet import EvidenceItem, EvidencePacket, canonical_item_key
from .scoping import estimate_tokens

# lane grouping by source_claim.kind
_LANES: list[tuple[str, tuple[str, ...]]] = [
    ("Structural", ("graph_edge", "graph_path")),
    ("Lexical", ("lexical_def", "lexical_filename", "lexical_match")),
    ("Repository", ("git_meta", "git_dirty")),
]
_OTHER_LANE = "Other"


@dataclass
class RenderResult:
    text: str
    tokens: int
    rendered_ids: list[str] = field(default_factory=list)
    dropped_ids: list[str] = field(default_factory=list)
    # Selected items whose references are identical to an already-rendered
    # item of the same collector and kind: ``{folded_id: rendered_id}``. The
    # folded item's symbol is shown on the rendered line ("also: ..."), so
    # the evidence is still presented — once, not per matching symbol.
    merged_ids: dict[str, str] = field(default_factory=dict)


def duplicate_reference_key(item: EvidenceItem) -> tuple[str, str, tuple[str, ...]] | None:
    """Identity under which two selected items render as one line.

    Two items are the *same rendered reference* when they come from the same
    collector, carry the same kind, and cite exactly the same reference
    strings (path separators normalised, otherwise verbatim — so ``a.py:10``,
    ``a.py:11`` and ``a.py:10:5`` are three distinct references, and a
    malformed reference only ever matches itself). Items without references
    are never folded: a git-meta statement is not "the same" as another one.
    Ranking's duplication penalty is unchanged — this only affects rendering.
    """
    refs = item.source_claim.references
    if not refs:
        return None
    normalised = tuple(sorted(r.replace("\\", "/") for r in refs))
    return (item.provenance.collector, item.source_claim.kind, normalised)


def _symbol_of(item: EvidenceItem) -> str:
    return str(item.provenance.extra.get("symbol", "") or "")


def fold_duplicate_references(
    ordered: list[EvidenceItem],
) -> tuple[list[EvidenceItem], dict[str, str], dict[str, list[str]]]:
    """Keep the first item per :func:`duplicate_reference_key` (``ordered`` is
    already highest-score-first, so the survivor is the best-scored one).
    Returns ``(unique, merged_ids, also)`` where ``also[rendered_id]`` lists the
    distinct extra symbols of the folded items, in fold order."""
    unique: list[EvidenceItem] = []
    kept: dict[tuple[str, str, tuple[str, ...]], EvidenceItem] = {}
    merged: dict[str, str] = {}
    also: dict[str, list[str]] = {}
    for item in ordered:
        key = duplicate_reference_key(item)
        survivor = kept.get(key) if key is not None else None
        if survivor is None:
            if key is not None:
                kept[key] = item
            unique.append(item)
            continue
        merged[item.id] = survivor.id
        sym = _symbol_of(item)
        extras = also.setdefault(survivor.id, [])
        if sym and sym != _symbol_of(survivor) and sym not in extras:
            extras.append(sym)
    return unique, merged, also


def render_brief(packet: EvidencePacket) -> RenderResult:
    """Render the ContextBrief text for ``packet`` within its max-token budget.

    Items are admitted highest-score-first, and the *whole assembled document*
    is re-measured on each admission — so the returned text is guaranteed to
    stay within ``budget.max_tokens`` including all framing, lane headers, and
    the omitted-count line. Empty selection renders nothing (spec §4).
    """
    max_tokens = packet.budget.max_tokens

    selected = [item for item in packet.evidence if item.compiler_assessment.selected]
    # Tiebreak on content, not the random item id — otherwise equally-scored
    # items render in a different order every run (F-D1).
    selected.sort(key=lambda it: (-it.compiler_assessment.final_score, canonical_item_key(it)))
    negatives = [n for n in packet.negative_evidence if n.outcome == "no_existing_reference"]
    unique, merged, also = fold_duplicate_references(selected)

    chosen: list[EvidenceItem] = []
    dropped_ids: list[str] = []
    for item in unique:
        trial = chosen + [item]
        if estimate_tokens(_assemble(packet, trial, [], reserve_omitted=True, also=also)) <= max_tokens:
            chosen.append(item)
        else:
            dropped_ids.append(item.id)
    # A folded item stands or falls with the line it was folded into.
    chosen_ids = {i.id for i in chosen}
    for folded_id, into in list(merged.items()):
        if into not in chosen_ids:
            dropped_ids.append(folded_id)
            del merged[folded_id]

    chosen_neg: list = []
    for neg in negatives:
        trial_neg = chosen_neg + [neg]
        if estimate_tokens(_assemble(packet, chosen, trial_neg, reserve_omitted=True, also=also)) <= max_tokens:
            chosen_neg.append(neg)

    if not chosen and not chosen_neg:
        return RenderResult(text="", tokens=0, rendered_ids=[], dropped_ids=dropped_ids)

    omitted_count = len(packet.budget.omitted_evidence_ids) + len(dropped_ids)
    text = _assemble(packet, chosen, chosen_neg, omitted_count=omitted_count, also=also)
    return RenderResult(
        text=text,
        tokens=estimate_tokens(text),
        rendered_ids=[i.id for i in chosen],
        dropped_ids=dropped_ids,
        merged_ids=merged,
    )


def _assemble(
    packet: EvidencePacket,
    items: list[EvidenceItem],
    negatives: list,
    *,
    reserve_omitted: bool = False,
    omitted_count: int | None = None,
    also: dict[str, list[str]] | None = None,
) -> str:
    """Build the brief text. ``reserve_omitted`` includes a worst-case
    omitted-count line so budget checks during admission never underestimate."""
    lane_lines: dict[str, list[str]] = {}
    for item in items:
        extras = also.get(item.id, []) if also else []
        lane_lines.setdefault(_lane_for(item.source_claim.kind), []).append(_item_line(item, extras))

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


def _item_line(item: EvidenceItem, also: list[str] | None = None) -> str:
    reason = "; ".join(item.compiler_assessment.selected_because) or "in scope"
    if also:
        reason += "; also matches " + ", ".join(also)
    prefix = f"- [{item.provenance.collector}] {item.source_claim.statement}"
    provisional = " (provisional — dirty/stale, not verified)" if item.status == "provisional" else ""
    return f"{prefix}{provisional}\n  why: {reason}"


def _lane_for(kind: str) -> str:
    for lane_title, kinds in _LANES:
        if kind in kinds:
            return lane_title
    return _OTHER_LANE
