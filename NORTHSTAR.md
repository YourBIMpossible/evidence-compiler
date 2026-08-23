---
status: active
---

# Evidence Compiler — North Star

## Mission

Give an AI coding agent—Claude Code Desktop first—a small, deterministic,
trustworthy brief of real evidence about a repository: what is true, what is
absent, and where each claim came from. The agent should reason from facts
instead of guesses, without Evidence Compiler blocking the agent or inventing
claims.

## Phase 1A outcome

Phase 1A is the complete currently committed implementation scope.

It provides:

- Package and CLI.
- Git and ripgrep collectors.
- Graphify as an intentional optional stub.
- EvidencePacket v1 and ContextBrief v1.
- Deterministic ranking and bounded selection.
- Packet persistence and replay.
- A fail-open Claude Code Desktop adapter.
- Contract, fixture, and regression tests with CI coverage.
- Repository/worktree/HEAD identity binding and replay mismatch warnings.

Phase 1A does not obligate a linear sequence of future phases. It is the
stable foundation from which future work must be earned by demonstrated use.

## Current boundaries

The following are out of scope unless this North Star is explicitly revised
or a separately approved phase proposal authorizes them:

- Verification hooks, hard-stop gates, change contracts, or validation ledgers.
- A resident daemon, background graph watcher, or AST daemon.
- LLM or local-AI work in the prompt-critical path.
- GPU workloads, vector databases, embeddings, RAG, or an MCP server.
- LLM-based ranking, autonomous tool loops, or policy mutation.
- A second agent adapter, plugin marketplace, IDE extension, HTTP service, or
  CI/PR integration.
- BIMpossible, Revit, APS, Autodesk, or other product-specific policy inside
  `src/evidence_compiler/` core.
- Telemetry upload, cloud analytics, dashboards, autonomous roadmap selection,
  or automatic phase creation.

These capabilities must never be pulled in incidentally while working on an
unrelated task.

## Dogfood signals and phase selection

Evidence Compiler earns a new phase only when repeated real work shows that
deterministic, provenance-preserving evidence cannot answer a recurring
high-cost question within the interaction budget.

Review dogfood evidence at whichever happens first:

- 10 meaningful real-repository prompts processed during normal work.
- Two weeks of normal dogfooding after Phase 1A activation.

At that review point, inspect only packets that mattered to real work. Label
each manually:

- `helped`
- `neutral`
- `hurt/noise`

For every meaningful packet, record one short reason. Group repeated reasons.
A new phase is considered only when the same high-cost gap appears at least
three times.

The initial review remains manual and local. It should consider factual packet
signals alongside the human usefulness label:

- Collector health: `ok`, `empty`, `skipped`, `timeout`, and error outcomes.
- Hook and collector latency.
- Presence and relevance of selected `file:line` citations.
- Token-budget utilization, truncation, and omitted evidence.
- Whether the brief helped, was neutral, or created noise.

A future local review command may summarize these factual signals, but Evidence
Compiler must not autonomously select, create, begin, or implement a phase.

If no repeated high-cost gap appears, freeze at Phase 1A. That is successful
validation, not stagnation.

## Candidate directions

These are decision branches, not precommitted phases or a promised roadmap:

- **Evidence quality:** retrieval, symbol extraction, ranking, or selection is
  repeatedly noisy, incomplete, or irrelevant.
- **Structural evidence:** recurring questions require callers, dependencies,
  ownership, dataflow, or relationships beyond lexical search.
- **Verification evidence:** the recurring problem is proving a change is safe
  or validated rather than finding relevant context.
- **Interoperability:** another agent or interface becomes a demonstrated need
  beyond Claude Code Desktop.
- **Optional inference:** deterministic evidence is repeatedly sufficient, but
  interpretation or synthesis remains the demonstrated bottleneck.

Local-AI, if ever considered, must be opt-in, outside the prompt-critical
path, explicitly provenance-labeled, and unable to satisfy verification by
itself.

## Requirements for a new phase

Before implementation, create a one-page phase proposal containing:

1. The problem demonstrated by real packets.
2. At least three concrete examples from normal use.
3. Explicit non-goals.
4. A measurable success metric.
5. The smallest experiment or implementation slice that can test the claim.

No new phase begins merely because a capability sounds useful or is available.