"""Evidence Compiler — local, deterministic evidence compilation for AI agents.

Public entry points:

- :func:`~evidence_compiler.compiler.compile_packet` — run the critical path.
- :class:`~evidence_compiler.packet.EvidencePacket` — the system of record.
- :func:`~evidence_compiler.rendering.render_brief` — derive a ContextBrief.
"""

from __future__ import annotations

from .compiler import CompileResult, compile_packet
from .packet import EvidencePacket, SchemaVersionError
from .rendering import render_brief

__version__ = "0.1.0"

__all__ = [
    "compile_packet",
    "CompileResult",
    "EvidencePacket",
    "SchemaVersionError",
    "render_brief",
    "__version__",
]
