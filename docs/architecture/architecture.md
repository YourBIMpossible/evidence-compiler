# Evidence Compiler — Architecture Specification

**Status:** Frozen for Phase 1A  
**Product:** Evidence Compiler — a local evidence compilation layer for AI coding agents  
**Not the product:** Claude Code tooling, Graphify, or any single agent runtime  
**Last updated:** 2026-08-21

---

## 1. What this is

A **local, deterministic control plane** that:

1. Collects structural, lexical, and repository evidence from pluggable **Collectors**
2. Normalizes it into an immutable **EvidencePacket**
3. Ranks and budgets a **ContextBrief** for an AI coding agent
4. Persists packets for replay, metrics, and later verification

Claude Code Desktop is the **first integration adapter**, not the core.

```text
                    ┌──────────────────────┐
                    │      AI AGENT        │
                    │ Claude / future LLMs │
                    └──────────▲───────────┘
                               │
                         ContextBrief
                               │
                    ┌──────────┴───────────┐
                    │  EVIDENCE COMPILER   │
                    │  Scope · Normalize   │
                    │  Rank · Budget       │
                    │  Provenance · Replay │
                    └──────────▲───────────┘
                               │
                       EvidencePacket
                               │
          ┌────────────────────┼────────────────────┐
          ▼                    ▼                    ▼
      Graphify*               rg                  Git
     (optional)            lexical             repository
          │                    │                    │
          └────────────────────┼────────────────────┘
                               │
                    Optional: LSP, conventions, …
```

\*Graphify improves structural evidence when present. It is **not required**.

---

## 2. What this is not

- Not a Graphify fork or replacement product  
- Not a general autonomous agent framework  
- Not BIMpossible-specific policy, architecture, or private conventions  
- Not dependent on any single agent’s hook mechanism for core logic  
- Not an online LLM ranker or RAG platform on the critical path  

Product-specific knowledge lives in **per-repo config**, not in the package.

---

## 3. Component roles

| Component | Responsibility |
|-----------|----------------|
| **Collector** | Gather raw facts under timeout; emit provenance; never decide task relevance |
| **Evidence Compiler** | Scope, normalize, assess relevance, rank, dedupe, budget, persist, render brief |
| **EvidencePacket** | Full, immutable, identity-scoped record of what was collected and assessed |
| **ContextBrief** | Token-budgeted presentation of selected evidence for the agent |
| **Agent adapter** | e.g. Claude Code `UserPromptSubmit` → inject brief; fail-open |
| **Verification ledger** | Later: observed runs → completion evidence state |

**Invariant:** Collectors collect. Compiler evaluates. Agent reasons.  
**Invariant:** Compiler remains functional if any collector is missing, times out, or fails.

---

## 4. Critical path vs async

**Critical path (every prompt):**

```text
Agent prompt
  → adapter
  → compiler (CPU collectors in parallel)
  → EvidencePacket (persist)
  → ContextBrief (optional inject)
  → agent
```

Fail-open: on error, inject nothing, log, exit success so the agent is not blocked.

**Async / later (not Phase 1A):**

- GPU compression of oversized logs  
- Offline usefulness analysis  
- Impact recomputation after edits  
- Soft verification ledger  

GPU never sits on the prompt critical path in Phase 1A.

---

## 5. Identity and isolation

Every packet binds to:

- `repository_root` (normalized absolute path)  
- `worktree_id` (or null for main tree)  
- `head`, `session_id`, `turn_id`, `packet_id`  

**Rule:** A packet must not be reused across incompatible repository root or worktree identity (Desktop multi-session / worktree safety).

---

## 6. Phase 1A scope (implementation freeze)

In:

- Python package + CLI  
- Collectors: Git, ripgrep, Graphify (optional)  
- EvidencePacket v1 + ContextBrief v1  
- Deterministic ranking (component scores + `selected_because`)  
- Persist packets; selective inject; logs; fail-open  
- Claude Code Desktop adapter  
- Minimal project config  
- Golden fixture repo + collector contract tests (as they land)  
- Basic `evidence replay <packet>` CLI  

Out:

- Verification hooks / hard Stop  
- Change contracts  
- Resident graph daemon  
- GPU  
- LLM ranking  
- Adaptive budgets (schema may allow; behavior fixed)  
- Human overrides execution (schema/config stub only)  
- BIMpossible-specific rules in core  

---

## 7. Repository layout (target)

```text
evidence-compiler/
├── README.md
├── LICENSE
├── pyproject.toml
├── docs/
│   ├── architecture/
│   │   └── architecture.md          # this file
│   ├── specifications/
│   │   ├── evidence-packet-v1.md
│   │   ├── context-brief-v1.md
│   │   └── collector-interface-v1.md
│   ├── graphify-evaluation.md
│   └── roadmap.md
├── src/evidence_compiler/
│   ├── cli.py
│   ├── compiler.py
│   ├── packet.py
│   ├── ranking.py
│   ├── rendering.py
│   ├── storage.py
│   ├── collectors/
│   └── integrations/claude_code.py
├── templates/
│   ├── claude-settings.json
│   └── evidence-compiler.yaml
├── tests/
│   ├── fixtures/golden-repo/
│   ├── unit/
│   └── contract/
└── examples/
```

---

## 8. Per-repo configuration

```text
<project>/
  .evidence-compiler/
    config.yaml
    overrides.yaml          # later
    conventions/            # optional local docs
  .claude/settings.json     # thin adapter only
```

Core package must run with defaults (git + rg only) on any git repo.

---

## 9. Related documents

| Doc | Role |
|-----|------|
| `evidence-packet-v1.md` | Logical packet contract |
| `context-brief-v1.md` | Agent-facing render contract |
| `collector-interface-v1.md` | Plugin boundary + contract tests |
| `graphify-evaluation.md` | Optional structural collector evaluation |
| `roadmap.md` | Phased delivery |

---

## 10. Bottom line

Evidence Compiler is a **portable local tool**.  
Claude Code is the first consumer.  
Graphify is the first optional structural collector.  
Packets are the system of record; briefs are presentations; collectors are replaceable.
