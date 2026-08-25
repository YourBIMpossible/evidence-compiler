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

# The shape ``packet_filename`` produces: sanitized timestamp, underscore,
# hex/uuid packet id, ``.json``. Retention deletes nothing that deviates.
_PACKET_NAME = re.compile(r"^[0-9][A-Za-z0-9._-]*_[0-9a-fA-F-]{8,}\.json$")


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


def prune_packets(storage_dir: str, max_packets: int) -> int:
    """Delete the oldest packet files beyond ``max_packets``; return the count
    actually deleted. ``max_packets <= 0`` disables retention entirely.

    Deliberately narrow: only regular files in ``storage_dir`` itself (no
    recursion) whose names match the ``packet_filename`` contract are eligible.
    Symlinks are never followed or deleted; directories, config, READMEs,
    logs, and ``.tmp`` in-flight writes never match. Packet names start with
    the RFC 3339 creation timestamp, so a lexicographic sort is chronological.
    Individual delete failures are skipped, never raised.
    """
    if max_packets is None or max_packets <= 0:
        return 0
    if not os.path.isdir(storage_dir):
        return 0
    names: list[str] = []
    with os.scandir(storage_dir) as entries:
        for entry in entries:
            if not _PACKET_NAME.match(entry.name):
                continue
            if entry.is_symlink() or not entry.is_file(follow_symlinks=False):
                continue
            names.append(entry.name)
    names.sort()
    deleted = 0
    for name in names[: max(0, len(names) - max_packets)]:
        try:
            os.unlink(os.path.join(storage_dir, name))
            deleted += 1
        except OSError:
            pass
    return deleted


def load_packet(path: str) -> EvidencePacket:
    """Load a packet from ``path``; raises SchemaVersionError on bad version."""
    with open(path, "r", encoding="utf-8") as fh:
        return EvidencePacket.from_json(fh.read())
