"""Deterministic ranking (packet spec §7, build brief §3).

No ML, no LLM, no clock, no hidden state: ranking is a pure function of the
packet's own contents. Every item gets a full component breakdown and a
human-readable ``selected_because`` / ``omitted_because`` — never an opaque
single score.

``rank(packet)`` mutates the packet's evidence in place and fills the budget
selection fields, then returns the same packet for convenience.
"""

from __future__ import annotations

import os

from .packet import EvidenceItem, EvidencePacket
from .scoping import estimate_tokens

# --- component weights (tune with golden fixtures, not a model) -------------
W_DIRECT_SYMBOL = 3.0
W_ACTIVE_FILE = 2.0
W_DIRECT_DEPENDENCY = 2.0
W_SAME_MODULE = 0.5
W_LEXICAL = 1.0
W_CONVENTION = 0.5
FRESHNESS_BONUS_CURRENT = 0.5
AUTHORITY_BONUS = 1.0
PROVISIONAL_PENALTY = 1.0
DUPLICATION_PENALTY = 0.75

# relevance thresholds on final_score
_REL_HIGH = 3.0
_REL_MEDIUM = 1.5
_REL_LOW = 0.0


def rank(packet: EvidencePacket) -> EvidencePacket:
    symbols = [s.lower() for s in packet.task.extracted_symbols]
    active_file = _norm(packet.task.active_file)
    active_dir = os.path.dirname(active_file) if active_file else ""

    seen_refs: set[str] = set()

    for item in packet.evidence:
        _score_item(item, symbols, active_file, active_dir, seen_refs)

    _select_under_budget(packet)
    return packet


def _score_item(
    item: EvidenceItem,
    symbols: list[str],
    active_file: str,
    active_dir: str,
    seen_refs: set[str],
) -> None:
    comp = item.compiler_assessment.components
    reasons: list[str] = []
    refs = [_norm(r) for r in item.source_claim.references]
    ref_paths = [r.split(":", 1)[0] for r in refs]
    statement_low = item.source_claim.statement.lower()
    claimed_symbol = str(item.provenance.extra.get("symbol", "")).lower()

    # direct symbol
    matched_symbol = None
    for sym in symbols:
        if sym and (sym == claimed_symbol or sym in statement_low):
            matched_symbol = sym
            break
    if matched_symbol:
        comp.direct_symbol = W_DIRECT_SYMBOL
        reasons.append(f"references prompt symbol '{matched_symbol}'")

    # active file / same module
    if active_file and active_file in ref_paths:
        comp.active_file = W_ACTIVE_FILE
        reasons.append("touches the active file")
    elif active_dir and any(os.path.dirname(p) == active_dir for p in ref_paths):
        comp.same_module = W_SAME_MODULE
        reasons.append("same module as active file")

    # lexical lane
    if item.source_claim.kind in ("lexical_match", "lexical_def"):
        comp.lexical_reference = W_LEXICAL
        if item.source_claim.kind == "lexical_def":
            reasons.append("exact symbol definition (lexical)")
        else:
            reasons.append("exact lexical match")

    # convention
    if item.authority == "convention":
        comp.convention = W_CONVENTION
        reasons.append("project convention")

    # freshness / authority bonuses
    if item.freshness == "current":
        comp.freshness_bonus = FRESHNESS_BONUS_CURRENT
    if item.authority == "authoritative":
        comp.authority_bonus = AUTHORITY_BONUS
        reasons.append("authoritative source")

    # provisional penalty: dirty overlay or stale never counts as verified
    provisional = item.freshness in ("dirty_overlay", "stale")
    if provisional:
        comp.provisional_penalty = PROVISIONAL_PENALTY

    # duplication penalty against earlier-seen references (order-stable)
    ref_key = "|".join(sorted(refs))
    if ref_key and ref_key in seen_refs:
        comp.duplication_penalty = DUPLICATION_PENALTY
    elif ref_key:
        seen_refs.add(ref_key)

    final = round(comp.total(), 4)
    item.compiler_assessment.final_score = final
    item.compiler_assessment.relevance = _relevance(final)

    # status: provisional items are flagged as such regardless of selection
    if provisional:
        item.status = "provisional"

    # Provisional: holds "why this item scored the way it did," not yet a
    # selection verdict. `_select_under_budget` is the sole place that
    # decides selection; it overwrites this with `omitted_because` (leaving
    # `selected_because` as scoring context) whenever the item is not
    # selected. Rendering/replay only read `selected_because` for items with
    # `selected == True`, so this never surfaces as a false selection claim.
    if not reasons:
        reasons.append("no scope relationship found")
    item.compiler_assessment.selected_because = list(reasons)


def _select_under_budget(packet: EvidencePacket) -> None:
    target = packet.budget.default_tokens

    # candidates: anything with relevance above none. Stable order: score desc,
    # then original index for full determinism.
    indexed = list(enumerate(packet.evidence))
    candidates = [
        (idx, item)
        for idx, item in indexed
        if item.compiler_assessment.relevance != "none"
    ]
    candidates.sort(key=lambda pair: (-pair[1].compiler_assessment.final_score, pair[0]))

    candidate_tokens = sum(_item_tokens(item) for _, item in candidates)
    injected = 0
    selected_ids: list[str] = []
    omitted_ids: list[str] = []

    for _, item in candidates:
        cost = _item_tokens(item)
        if injected + cost <= target:
            item.compiler_assessment.selected = True
            injected += cost
            selected_ids.append(item.id)
            if item.status != "provisional":
                item.status = "usable"
        else:
            item.compiler_assessment.selected = False
            item.compiler_assessment.omitted_because = ["exceeds token budget"]
            if item.status != "provisional":
                item.status = "omitted"
            omitted_ids.append(item.id)

    # items that never qualified as candidates
    for item in packet.evidence:
        if item.compiler_assessment.relevance == "none":
            item.compiler_assessment.selected = False
            item.compiler_assessment.omitted_because = ["no scope relationship found"]
            if item.status != "provisional":  # keep provisional flag visible
                item.status = "omitted"
            omitted_ids.append(item.id)

    packet.budget.candidate_tokens = candidate_tokens
    packet.budget.injected_tokens = injected
    packet.budget.omitted_evidence_ids = omitted_ids


def _item_tokens(item: EvidenceItem) -> int:
    reason = "; ".join(item.compiler_assessment.selected_because)
    text = f"- [{item.provenance.collector}] {item.source_claim.statement}  why: {reason}"
    return estimate_tokens(text)


def _relevance(score: float) -> str:
    if score >= _REL_HIGH:
        return "high"
    if score >= _REL_MEDIUM:
        return "medium"
    if score > _REL_LOW:
        return "low"
    return "none"


def _norm(path: str | None) -> str:
    if not path:
        return ""
    return path.replace("\\", "/")
