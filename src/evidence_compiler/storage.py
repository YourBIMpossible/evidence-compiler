"""Packet persistence — one JSON file per packet (packet spec §6).

Storage dir is configurable; default ``.evidence-compiler/packets/``. Writes
are best-effort and must never crash the critical path — a failed persist is
logged by the caller, not raised into the agent's session.
"""

from __future__ import annotations

import os
import re

from .packet import EvidencePacket

_SAFE = re.compile(r"[^A-Za-z0-9._-]")


def packet_filename(packet: EvidencePacket) -> str:
    ts = _SAFE.sub("-", packet.created_at)
    return f"{ts}_{packet.packet_id}.json"


def save_packet(packet: EvidencePacket, storage_dir: str) -> str:
    """Serialize ``packet`` to ``storage_dir``; return the written path."""
    os.makedirs(storage_dir, exist_ok=True)
    path = os.path.join(storage_dir, packet_filename(packet))
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(packet.to_json())
    os.replace(tmp, path)  # atomic on same filesystem
    return path


def load_packet(path: str) -> EvidencePacket:
    """Load a packet from ``path``; raises SchemaVersionError on bad version."""
    with open(path, "r", encoding="utf-8") as fh:
        return EvidencePacket.from_json(fh.read())
