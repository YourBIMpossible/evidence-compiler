# Evidence Compiler — Claude Code Operating Brief

This file is read automatically at session start. It sets the boundary for
this build. The Phase 1A specifications are frozen for implementation.
Changes require an explicit decision and coordinated update to the
affected specification, fixtures, and contract tests; do not reinterpret
them ad hoc during a build. If a spec is ambiguous, ask before
improvising; do not silently expand scope to resolve ambiguity.

## What this project is

A local, deterministic control plane that collects evidence via pluggable
Collectors, normalizes it into an immutable `EvidencePacket`, and renders a
token-budgeted `ContextBrief` for an AI coding agent. Claude Code Desktop is
the first integration adapter — not the core. Graphify is the first optional
structural collector — not a dependency.

Full specs (read these before writing code that touches their area):

| Doc | Covers |
|---|---|
| `01-architecture.md` | Product boundary, components, critical path, repo layout |
| `02-evidence-packet-v1.md` | EvidencePacket schema — the system of record |
| `03-context-brief-v1.md` | ContextBrief schema — the agent-facing render |
| `04-collector-interface-v1.md` | Collector plugin boundary + contract tests |
| `05-graphify-evaluation.md` | Graphify's role, evaluation tiers, guardrails |
| `06-roadmap.md` | Phased delivery, v0.1 → v1.0, explicit non-goals |
| `BUILD_BRIEF.md` | Ordered task list + acceptance criteria for this build |

## Non-negotiable invariants

1. Collectors collect; compiler evaluates; agent reasons. A collector must
   never set `selected`, `final_score`, or relevance judgments.
2. The compiler must remain functional if any collector is missing, times
   out, or errors. No collector failure may propagate to a crash.
3. `EvidencePacket` is truth (full fidelity, persisted, immutable).
   `ContextBrief` is a budgeted presentation derived from it — never a
   second source of truth.
4. Provisional/stale evidence never satisfies verification, when
   verification exists. Authority and freshness are orthogonal — don't
   collapse them into one score without the `components` breakdown.
5. The critical path (prompt → adapter → compiler → packet → brief →
   agent) is deterministic and fail-open: on any error, inject nothing,
   log, exit success. Never block the agent.
6. Product-specific policy (BIMpossible/Revit/APS conventions, project
   rules) lives in per-repo `.evidence-compiler/config.yaml`, never in
   core package code.

## Phase 1A scope discipline

**In scope (build this):** Python package + CLI, git + ripgrep collectors,
Graphify as an optional collector, EvidencePacket v1 + ContextBrief v1,
deterministic ranking with `selected_because`/`omitted_because`, packet
persistence, Claude Code Desktop adapter (fail-open), minimal per-repo
config, golden fixture repo + collector contract tests, `evidence replay
<packet>` CLI.

**Out of scope — do not build, even if it seems easy or "while I'm in
there":** verification hooks / hard Stop, change contracts, a resident
graph daemon, GPU compression, LLM-based ranking, adaptive budgets (schema
may leave room, behavior stays fixed), a second agent adapter beyond
Claude Code Desktop, a collector plugin marketplace, any BIMpossible-
specific rule inside `src/evidence_compiler/`.

If a task seems to require stepping outside this list, stop and flag it
rather than proceeding — scope creep here is the main risk to this
project, not technical difficulty.

## Licensing and release posture

- License: Apache-2.0 (patent grant matters given the AEC/Autodesk
  ecosystem this will eventually touch). Add `LICENSE` at repo root as
  part of initial scaffolding.
- Release posture: docs may already be public. Code development happens
  before any "v0.1 launch" is announced — the exit bar for calling this
  publicly usable is golden-fixture + contract tests passing end-to-end,
  plus real dogfooding against the maintainer's own Revit/BIMpossible
  repos through the Claude Code Desktop adapter. Don't treat pushing code
  as equivalent to shipping v0.1.

## Working rules for this session

- Prefer the solid, spec-compliant implementation over a shortcut. If a
  quick hack would violate an invariant above, do not take it — say so
  and implement the correct version.
- Every collector implementation must pass the contract tests in
  `04-collector-interface-v1.md` §7 before being considered done.
- No unexplained TODOs. If something is deliberately deferred, say why
  and which roadmap version (`06-roadmap.md`) it belongs to.
- When in doubt about whether something belongs in core vs. per-repo
  config, default to per-repo config.
