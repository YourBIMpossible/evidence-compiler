# EvidencePacket v1 — Specification

**Status:** Logical contract for Phase 1A  
**Note:** v1 is a **logical schema**. Storage is a versioned serialization of this model (JSON initially). Internal Python models may evolve behind serializers without breaking the logical contract’s intent.  
**Last updated:** 2026-08-21

---

## 1. Purpose

The EvidencePacket is the **complete, immutable record** of:

- What was collected  
- Under which repository / worktree / revision  
- How the compiler assessed relevance  
- What was selected vs omitted for the agent  
- Timing and diagnostics  

It is **not** what is necessarily injected into the model. That is the **ContextBrief**.

```text
Collectors → raw results
     ↓
Compiler normalize + assess
     ↓
EvidencePacket  (full fidelity, persisted)
     ↓
render / budget
     ↓
ContextBrief    (agent-facing)
```

---

## 2. Top-level fields

```yaml
schema_version: 1
packet_id: ep_...                 # unique
created_at: ISO-8601

identity:
  session_id: string | null
  turn_id: string | null
  repository_root: string         # absolute, normalized
  worktree_id: string | null
  head: string | null
  branch: string | null

correlation:
  prompt_hash: string
  parent_packet_id: string | null

task:
  raw_prompt_hash: string
  intent: debugging | implementation | refactor | discovery | unknown
  active_file: string | null
  selection_range: object | null
  extracted_symbols: [string]

scope:
  confidence: high | medium | low
  sources: [active_file | prompt_symbol | git_diff | ...]

collectors_run:
  - name: git | ripgrep | graphify | ...
    status: ok | empty | timeout | error | skipped
    duration_ms: number
    diagnostic: object            # collector-specific

evidence: [EvidenceItem]
negative_evidence: [NegativeEvidenceItem]

budget:
  min_tokens: 600
  default_tokens: 1000
  max_tokens: 1200
  candidate_tokens: number
  injected_tokens: number
  omitted_evidence_ids: [string]

validation:                       # placeholder Phase 1A
  execution: []
  evidence_state: UNVERIFIED

timing:
  total_ms: number
  stages: object
```

---

## 3. EvidenceItem

Two layers of claim:

1. **source_claim** — what the collector reported (fact)  
2. **compiler_assessment** — relevance / selection (judgment)

```yaml
- id: ev_...

  source_claim:
    kind: graph_edge | lexical_match | convention | git_meta | ...
    statement: string             # e.g. "A calls B"
    references: [string]          # file:line or path

  provenance:
    collector: string
    command: string | null
    captured_at: ISO-8601
    source_revision: string | null
    graph_hash: string | null

  authority: authoritative | convention | inferred
  freshness: current | dirty_overlay | stale | unknown
  confidence: number              # 0–1, claim quality; orthogonal to authority

  compiler_assessment:
    relevance: high | medium | low | none
    selected: boolean
    final_score: number
    components:                   # deterministic in Phase 1A
      direct_symbol: number
      active_file: number
      direct_dependency: number
      same_module: number
      lexical_reference: number
      convention: number
      freshness_bonus: number
      authority_bonus: number
      provisional_penalty: number
      duplication_penalty: number
    selected_because: [string]    # human-readable reasons if selected
    omitted_because: [string]     # if not selected

  status: usable | omitted | provisional
```

### Authority × freshness × use

| | Reasoning | Planning | Verification (later) |
|--|-----------|----------|----------------------|
| authoritative + current | ✅ | ✅ | ✅ |
| inferred + current | ✅ | ✅ | ❌ |
| provisional / stale | ⚠️ lead | ⚠️ | ❌ |

---

## 4. NegativeEvidenceItem

```yaml
- id: ev_abs_...
  query: string
  collector: string
  searched_roots: [string]
  outcome: no_existing_reference | no_graph_node | ...
  captured_at: ISO-8601
  diagnostic: object
```

Absence **after search** is evidence. Distinguish “not looked” from “looked, found none.”

---

## 5. Isolation rule

Packets are valid only for matching `identity.repository_root` and `identity.worktree_id`.  
Adapters must not inject a packet from another worktree/session identity.

---

## 6. Serialization

- Phase 1A: one JSON file per packet under configured storage dir  
- Filename recommendation: `{packet_id}.json` or `{timestamp}_{packet_id}.json`  
- `schema_version` required on read; unknown major version → reject with clear error  
- Logical v1 may gain optional fields in minor revisions; required fields stay stable for 1.x replay tools  

---

## 7. Ranking (Phase 1A)

Deterministic only. Example component weights (tune with golden fixtures, not LLM):

```text
final_score ≈
  relationship/scope components
  + freshness_bonus
  + authority_bonus
  − provisional_penalty
  − duplication_penalty
```

No opaque single magic score without `components` and `selected_because` / `omitted_because`.
