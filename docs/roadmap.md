# Evidence Compiler — Roadmap

**Last updated:** 2026-08-21

---

## v0.1 — Phase 1A “Evidence packets, locally”

- Package + CLI  
- Collectors: git, ripgrep, graphify (optional)  
- EvidencePacket v1 persist  
- Deterministic rank + ContextBrief  
- Claude Code Desktop adapter (fail-open)  
- Config template  
- Contract tests (initial) + golden-repo fixtures (seed)  
- `evidence-compiler replay <packet.json>` (minimal text report)  

## v0.2 — Replay & diagnostics

- Richer replay (selected vs omitted, timings, collector statuses)  
- Graph/collector health metrics export  
- Empty-result diagnostics hardened  
- Expand golden corpus  

## v0.3 — Project-aware policy (flagged)

- Change contracts + assumptions  
- Path/change-kind policy  
- Soft verification ledger (no hard Stop until FP known)  
- overrides.yaml stub behavior  

## v0.4+ 

- Post-edit impact packets  
- Async freshness helpers  
- Conditional GPU compression (off critical path)  
- Offline usefulness recommendations (human-approved)  

## v1.0

After multi-repo, multi-worktree production use; declare packet schema stability + migration policy.

---

## Non-goals until proven

- Agent-agnostic marketplace of plugins beyond collector interface  
- Mandatory cloud services  
- Embedding BIMpossible (or any vendor) policy in core  
