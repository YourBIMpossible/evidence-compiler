"""EvidencePacket v1 — the immutable system of record.

This module defines the logical schema from
``docs/specifications/evidence-packet-v1.md`` as Python dataclasses plus
lossless JSON serialization with an explicit ``schema_version`` guard.

The packet is *truth*: full fidelity, persisted, immutable. The
:class:`~evidence_compiler.rendering` layer derives a budgeted ContextBrief
from it — never the other way around.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from datetime import datetime, timezone
from typing import Any

# Logical schema major version. Storage encodes this; readers reject an
# unknown *major* version rather than silently coercing (spec §6).
SCHEMA_VERSION = 1

# --- controlled vocabularies (validated on read; stored as plain strings) ---

INTENTS = ("debugging", "implementation", "refactor", "discovery", "unknown")
SCOPE_CONFIDENCE = ("high", "medium", "low")
COLLECTOR_STATUS = ("ok", "empty", "timeout", "error", "skipped")
AUTHORITY = ("authoritative", "convention", "inferred")
FRESHNESS = ("current", "dirty_overlay", "stale", "unknown")
RELEVANCE = ("high", "medium", "low", "none")
ITEM_STATUS = ("usable", "omitted", "provisional")
EVIDENCE_STATE = ("UNVERIFIED", "VERIFIED", "REFUTED")


class SchemaVersionError(ValueError):
    """Raised when a packet on disk carries an incompatible major version."""


def utcnow_iso() -> str:
    """ISO-8601 UTC timestamp with a trailing ``Z``."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


# --------------------------------------------------------------------------
# Identity / correlation / task / scope
# --------------------------------------------------------------------------


@dataclass
class Identity:
    repository_root: str
    session_id: str | None = None
    turn_id: str | None = None
    worktree_id: str | None = None
    head: str | None = None
    branch: str | None = None


@dataclass
class Correlation:
    prompt_hash: str
    parent_packet_id: str | None = None


@dataclass
class Task:
    raw_prompt_hash: str
    intent: str = "unknown"
    active_file: str | None = None
    selection_range: dict[str, Any] | None = None
    extracted_symbols: list[str] = field(default_factory=list)


@dataclass
class Scope:
    confidence: str = "low"
    sources: list[str] = field(default_factory=list)


@dataclass
class CollectorRun:
    name: str
    status: str
    duration_ms: float
    diagnostic: dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------
# Evidence
# --------------------------------------------------------------------------


@dataclass
class SourceClaim:
    """What the collector reported — fact layer."""

    kind: str
    statement: str
    references: list[str] = field(default_factory=list)


@dataclass
class Provenance:
    collector: str
    command: str | None = None
    captured_at: str = field(default_factory=utcnow_iso)
    source_revision: str | None = None
    graph_hash: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class ScoreComponents:
    """Deterministic component breakdown. No opaque single score (spec §7)."""

    direct_symbol: float = 0.0
    active_file: float = 0.0
    direct_dependency: float = 0.0
    same_module: float = 0.0
    lexical_reference: float = 0.0
    convention: float = 0.0
    freshness_bonus: float = 0.0
    authority_bonus: float = 0.0
    provisional_penalty: float = 0.0
    duplication_penalty: float = 0.0

    def total(self) -> float:
        return (
            self.direct_symbol
            + self.active_file
            + self.direct_dependency
            + self.same_module
            + self.lexical_reference
            + self.convention
            + self.freshness_bonus
            + self.authority_bonus
            - self.provisional_penalty
            - self.duplication_penalty
        )


@dataclass
class CompilerAssessment:
    """Compiler judgment — relevance / selection layer."""

    relevance: str = "none"
    selected: bool = False
    final_score: float = 0.0
    components: ScoreComponents = field(default_factory=ScoreComponents)
    selected_because: list[str] = field(default_factory=list)
    omitted_because: list[str] = field(default_factory=list)


@dataclass
class EvidenceItem:
    source_claim: SourceClaim
    provenance: Provenance
    authority: str = "inferred"
    freshness: str = "unknown"
    confidence: float = 0.0
    compiler_assessment: CompilerAssessment = field(default_factory=CompilerAssessment)
    status: str = "omitted"
    id: str = field(default_factory=lambda: new_id("ev"))


def _ref_sort_key(ref: str) -> tuple[str, int]:
    """Order a ``file:line`` reference by (path, numeric line).

    Slashes are normalized so platform path separators never perturb the
    order, and the line is compared numerically so ``:100`` follows ``:9``
    rather than sorting lexically before it.
    """
    norm = ref.replace("\\", "/")
    path, sep, line = norm.partition(":")
    if sep:
        try:
            return (path, int(line))
        except ValueError:
            return (path, -1)
    return (norm, -1)


def canonical_item_key(item: "EvidenceItem") -> tuple:
    """A total order over evidence derived only from item *content*.

    Ranking and rendering must be pure functions of what the evidence *is*,
    never of the order collectors happened to emit it in (which, for parallel
    tools like ripgrep, is not reproducible). This key intentionally excludes
    the random ``id`` and the wall-clock ``captured_at`` so identical evidence
    always sorts identically across runs — the property F-D1 exposed as broken.
    """
    claim = item.source_claim
    refs = tuple(_ref_sort_key(r) for r in sorted(claim.references, key=_ref_sort_key))
    return (
        refs,
        item.provenance.collector,
        claim.kind,
        claim.statement,
        str(item.provenance.extra.get("symbol", "")),
    )


@dataclass
class NegativeEvidenceItem:
    """Absence *after* search is first-class evidence (spec §4)."""

    query: str
    collector: str
    outcome: str
    searched_roots: list[str] = field(default_factory=list)
    captured_at: str = field(default_factory=utcnow_iso)
    diagnostic: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: new_id("ev_abs"))


# --------------------------------------------------------------------------
# Budget / validation / timing / packet
# --------------------------------------------------------------------------


@dataclass
class Budget:
    min_tokens: int = 600
    default_tokens: int = 1000
    max_tokens: int = 1200
    candidate_tokens: int = 0
    injected_tokens: int = 0
    omitted_evidence_ids: list[str] = field(default_factory=list)


@dataclass
class Validation:
    execution: list[Any] = field(default_factory=list)
    evidence_state: str = "UNVERIFIED"


@dataclass
class Timing:
    total_ms: float = 0.0
    stages: dict[str, float] = field(default_factory=dict)


@dataclass
class EvidencePacket:
    identity: Identity
    correlation: Correlation
    task: Task
    scope: Scope = field(default_factory=Scope)
    collectors_run: list[CollectorRun] = field(default_factory=list)
    evidence: list[EvidenceItem] = field(default_factory=list)
    negative_evidence: list[NegativeEvidenceItem] = field(default_factory=list)
    budget: Budget = field(default_factory=Budget)
    validation: Validation = field(default_factory=Validation)
    timing: Timing = field(default_factory=Timing)
    schema_version: int = SCHEMA_VERSION
    packet_id: str = field(default_factory=lambda: new_id("ep"))
    created_at: str = field(default_factory=utcnow_iso)

    # -- serialization ----------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Ordered dict mirroring the logical schema top-level layout."""
        return {
            "schema_version": self.schema_version,
            "packet_id": self.packet_id,
            "created_at": self.created_at,
            "identity": asdict(self.identity),
            "correlation": asdict(self.correlation),
            "task": asdict(self.task),
            "scope": asdict(self.scope),
            "collectors_run": [asdict(c) for c in self.collectors_run],
            "evidence": [asdict(e) for e in self.evidence],
            "negative_evidence": [asdict(n) for n in self.negative_evidence],
            "budget": asdict(self.budget),
            "validation": asdict(self.validation),
            "timing": asdict(self.timing),
        }

    def to_json(self, *, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False, sort_keys=False)

    # -- deserialization --------------------------------------------------

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EvidencePacket":
        raw_version = data.get("schema_version")
        if raw_version is None:
            raise SchemaVersionError("packet is missing required 'schema_version'")
        try:
            major = int(raw_version)
        except (TypeError, ValueError) as exc:
            raise SchemaVersionError(
                f"packet 'schema_version' is not an integer: {raw_version!r}"
            ) from exc
        if major != SCHEMA_VERSION:
            raise SchemaVersionError(
                f"unsupported EvidencePacket schema_version {major}; "
                f"this build reads version {SCHEMA_VERSION}"
            )

        packet = cls(
            identity=_build(Identity, data.get("identity", {})),
            correlation=_build(Correlation, data.get("correlation", {})),
            task=_build(Task, data.get("task", {})),
            scope=_build(Scope, data.get("scope", {})),
            collectors_run=[_build(CollectorRun, c) for c in data.get("collectors_run", [])],
            evidence=[_build_evidence_item(e) for e in data.get("evidence", [])],
            negative_evidence=[
                _build(NegativeEvidenceItem, n) for n in data.get("negative_evidence", [])
            ],
            budget=_build(Budget, data.get("budget", {})),
            validation=_build(Validation, data.get("validation", {})),
            timing=_build(Timing, data.get("timing", {})),
            schema_version=major,
            packet_id=data.get("packet_id", new_id("ep")),
            created_at=data.get("created_at", utcnow_iso()),
        )
        return packet

    @classmethod
    def from_json(cls, text: str) -> "EvidencePacket":
        return cls.from_dict(json.loads(text))


# --------------------------------------------------------------------------
# Construction helpers (tolerant of unknown *optional* keys within 1.x)
# --------------------------------------------------------------------------


def _build(dc_type: type, data: dict[str, Any]):
    """Instantiate a flat dataclass, ignoring keys it does not declare.

    Ignoring unknown keys is deliberate: logical v1 may gain optional fields
    in minor revisions and 1.x replay tools must still load older/newer
    minor packets (spec §6).
    """
    if not is_dataclass(dc_type):  # pragma: no cover - programmer error
        raise TypeError(f"{dc_type!r} is not a dataclass")
    known = {f.name for f in fields(dc_type)}
    kwargs = {k: v for k, v in (data or {}).items() if k in known}
    return dc_type(**kwargs)


def _build_evidence_item(data: dict[str, Any]) -> EvidenceItem:
    source_claim = _build(SourceClaim, data.get("source_claim", {}))
    provenance = _build(Provenance, data.get("provenance", {}))
    assessment_raw = data.get("compiler_assessment", {}) or {}
    components = _build(ScoreComponents, assessment_raw.get("components", {}) or {})
    assessment = _build(CompilerAssessment, assessment_raw)
    assessment.components = components
    return EvidenceItem(
        source_claim=source_claim,
        provenance=provenance,
        authority=data.get("authority", "inferred"),
        freshness=data.get("freshness", "unknown"),
        confidence=float(data.get("confidence", 0.0)),
        compiler_assessment=assessment,
        status=data.get("status", "omitted"),
        id=data.get("id", new_id("ev")),
    )
