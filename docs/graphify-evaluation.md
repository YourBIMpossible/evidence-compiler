# Graphify Evaluation & Improvement Plan

**Status:** Companion to Evidence Compiler — optional structural collector  
**Not:** A Graphify fork, second control plane, or required dependency  
**Guardrail:** Evidence Compiler must function when Graphify is absent, skipped, or failing  
**Last updated:** 2026-08-21

---

## 1. Real question

Not “how do we make Graphify maximally sophisticated?”

**Is Graphify good enough for the Evidence Compiler, and if not, where does it fail?**

Decision outcomes: **keep · improve · supplement · replace** (collector swap only).

---

## 2. Division of labor

| Layer | Responsibility |
|-------|----------------|
| Graphify | What code is connected to (structural facts) |
| Evidence Compiler | Why that matters to the task (scope, rank, brief, later verification) |

Project boundaries (public contract, host, API, web) live as **compiler/policy reachability**, not new Graphify edge types in core.

---

## 3. Tier 0 — Measure first

Baseline on real repos **and** a golden fixture repo before optimizing.

| Metric | Meaning |
|--------|---------|
| Latency p50/p95 | Lane budget fit |
| Hit rate | Seeds → useful nodes |
| Empty rate | Needs diagnostics |
| Timeout rate | Hard limit pressure |
| EXTRACTED / INFERRED ratio | Authority mix |
| **Precision** | Of reported relationships, how many are correct/relevant? |
| **Recall** | Of known-needed relationships, how many found? |
| Useful-evidence rate | Share that survives into ContextBrief / later edits |
| Index age / coverage | Freshness and language gaps |

**Promotion rule:** No Tier 2+ work without a Tier 0/1 measured failure mode.

---

## 4. Tier 1 — Operational hardening

- Freshness: prefer update-on-relevant-dirty and/or on-demand before query; continuous `watch` only after benchmark  
- Dirty paths → provisional / dirty_overlay on related edges  
- Scoped seeds (active file + symbols)  
- Query discipline (path/explain/budgeted query)  
- Authority ≠ confidence  
- EXTRACTED: reason/plan/verify; INFERRED: reason/plan only; provisional: never verify  
- Provenance on every item  
- Timeouts: initial 250–750 ms target, ~1.25 s hard — **tune after measurement**  
- Omit lane on timeout/error  

---

## 5. Tier 1b — Conditional fallback ladder

```text
Graphify query/path
  → good → done
  → empty → diagnostic + optional narrow explain
  → timeout/error → rg (already parallel) / optional LSP → omit structural
```

Do not always run every step. Empty diagnostics distinguish wrong seed, stale index, parser gap, and true absence.

---

## 6. Tier 2 — Capability expansion (metrics-gated)

- Boundary layer outside Graphify  
- Small language gap collectors (DI, generated, partials) as separate collectors  
- Incremental/scoped index for huge monorepos  
- Better seed extraction (Tree-sitter on active file)  

---

## 7. Tier 3–4 — Supplement / replace

- Tier 3: LSP and specialized lexical lanes  
- Tier 4: replace Graphify collector only if measured latency, coverage, or maintenance failure persists  

---

## 8. Out of scope

Vector-default retrieval, mandatory daemon, LLM graph reasoner on critical path, preemptive “more efficient graph product,” OSS ownership of Graphify upstream.

---

## 9. Bottom line

Graphify is a **high-value optional collector**. Evaluate scientifically; improve operationally; never couple the compiler’s availability to Graphify’s.
