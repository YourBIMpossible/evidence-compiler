# ContextBrief v1 — Specification

**Status:** Frozen for Phase 1A  
**Relationship:** Rendered view of an EvidencePacket for an AI agent. Not a second source of truth.  
**Last updated:** 2026-08-21

---

## 1. Purpose

```text
EvidencePacket  = what was collected and assessed (complete)
ContextBrief    = what the agent is shown (budgeted presentation)
```

Changing ranking or budget regenerates briefs from packets without losing history.

---

## 2. Content requirements

A ContextBrief MUST:

- Identify the packet (`packet_id`) and repository head when known  
- List only **selected** evidence items  
- Include `selected_because` (or equivalent short reasons) per item or group  
- Preserve references (`file:line` / paths)  
- Stay within the configured token/character budget  
- Be safe to inject as plain text or structured `additionalContext`  

A ContextBrief MUST NOT:

- Invent claims absent from the packet  
- Present provisional/stale items as verified structure  
- Include full omitted-item dumps (optional one-line “N items omitted” is fine)  

---

## 3. Suggested text shape (Claude-facing)

```text
<context_brief packet_id="ep_..." head="abc123">
Scope confidence: high
Sources: active_file, prompt_symbol

## Structural
- [graphify] A → B (src/A.cs:10 → src/B.cs:20)
  why: direct caller of symbol X; active-file dependency

## Lexical
- [rg] def X at src/X.py:42
  why: exact symbol match in prompt

## Repository
- dirty: src/A.cs
  graph edges touching dirty paths are provisional

## Absence
- no references to OriginSystem under src/, tests/
</context_brief>
```

Exact markup may vary by adapter; semantic content must match the packet’s selected set.

---

## 4. Empty brief

If nothing useful is selected, adapters inject **nothing** (or a minimal “no structural evidence” line only if empirically helpful). Packet is still persisted.

---

## 5. Adapter notes (Claude Code Desktop)

- Prefer fail-open injection via stdout / `additionalContext`  
- Do not rely on Desktop rendering of block reasons  
- Respect UserPromptSubmit timeouts (operational p95 &lt; 1s; safety ≤ 25s)  
