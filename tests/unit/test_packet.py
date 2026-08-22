"""EvidencePacket round-trip and schema-version guard (build brief §2)."""

from __future__ import annotations

import json

import pytest

from evidence_compiler.packet import (
    CompilerAssessment,
    Correlation,
    EvidenceItem,
    EvidencePacket,
    Identity,
    NegativeEvidenceItem,
    Provenance,
    SchemaVersionError,
    ScoreComponents,
    SourceClaim,
    Task,
)


def _sample_packet() -> EvidencePacket:
    item = EvidenceItem(
        source_claim=SourceClaim(kind="lexical_def", statement="X at a.py:1", references=["a.py:1"]),
        provenance=Provenance(collector="ripgrep", command="rg X"),
        authority="inferred",
        freshness="current",
        confidence=0.7,
        compiler_assessment=CompilerAssessment(
            relevance="high",
            selected=True,
            final_score=4.0,
            components=ScoreComponents(direct_symbol=3.0, lexical_reference=1.0),
            selected_because=["exact symbol"],
        ),
        status="usable",
    )
    neg = NegativeEvidenceItem(
        query="OriginSystem", collector="ripgrep", outcome="no_existing_reference",
        searched_roots=["."],
    )
    packet = EvidencePacket(
        identity=Identity(repository_root="/repo", head="abc123", branch="main"),
        correlation=Correlation(prompt_hash="ph"),
        task=Task(raw_prompt_hash="ph", intent="discovery", extracted_symbols=["X"]),
    )
    packet.evidence.append(item)
    packet.negative_evidence.append(neg)
    return packet


def test_round_trip_no_data_loss():
    packet = _sample_packet()
    text = packet.to_json()
    restored = EvidencePacket.from_json(text)
    # full structural equality via canonical dict form
    assert restored.to_dict() == packet.to_dict()


def test_nested_layers_preserved():
    packet = _sample_packet()
    restored = EvidencePacket.from_json(packet.to_json())
    item = restored.evidence[0]
    # both claim layers survive, not collapsed
    assert item.source_claim.kind == "lexical_def"
    assert item.compiler_assessment.components.direct_symbol == 3.0
    assert item.compiler_assessment.selected is True
    assert restored.negative_evidence[0].outcome == "no_existing_reference"


def test_unknown_major_version_rejected():
    data = _sample_packet().to_dict()
    data["schema_version"] = 2
    with pytest.raises(SchemaVersionError):
        EvidencePacket.from_dict(data)


def test_missing_version_rejected():
    data = _sample_packet().to_dict()
    del data["schema_version"]
    with pytest.raises(SchemaVersionError):
        EvidencePacket.from_dict(data)


def test_unknown_optional_field_ignored_within_1x():
    data = _sample_packet().to_dict()
    data["identity"]["future_optional"] = "ok"  # minor-version additive field
    restored = EvidencePacket.from_dict(data)
    assert restored.identity.repository_root == "/repo"


def test_identity_binding_mandatory_fields_present():
    packet = _sample_packet()
    d = json.loads(packet.to_json())
    for key in ("repository_root", "worktree_id", "head", "session_id", "turn_id"):
        assert key in d["identity"]
    assert "packet_id" in d
