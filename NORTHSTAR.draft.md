status: draft

# Evidence Compiler — North Star (DRAFT — needs your review)

This is a draft only. Rename to `NORTHSTAR.md` (dropping `.draft`) to lock
and activate it. Until then it is not authoritative and I will not treat it
as a mandate.

## Mission

Give an AI coding agent (Claude Code Desktop first) a small, deterministic,
trustworthy brief of real evidence about a repository — what's true, what's
absent, and where it came from — so the agent reasons from facts instead of
guessing, without ever blocking the agent or inventing claims.

## What "done" looks like for the current phase (Phase 1A)

- Package + CLI, git + ripgrep collectors, Graphify as an optional stub,
  EvidencePacket v1 + ContextBrief v1, deterministic ranking, packet
  persistence + replay, Claude Code Desktop adapter (fail-open), golden
  fixture + contract tests — all shipped and CI-green. (Done as of this
  status.)
- Real dogfood: run it against a real BIMpossible/Revit repo through Claude
  Code Desktop and confirm the injected brief was useful at least once.
  (Not done yet — waiting on BIMpossible's local path to settle.)

## What's off-limits right now

- No verification hooks, hard Stop gates, or change contracts.
- No resident daemon or background graph watcher.
- No LLM/local-AI in the prompt-critical path.
- No GPU, vector DB, embeddings, RAG, or MCP server.
- No second agent adapter, plugin marketplace, or BIMpossible/Revit/APS
  policy inside `src/evidence_compiler/` core.
- These stay out until this file (once locked) or an explicit new decision
  says otherwise — never pulled in "while we're in there" on an unrelated
  task.

## Dogfood Signals and Phase Selection

Phase 1A is the complete, currently committed implementation scope. Nothing
past it is pre-committed as a linear roadmap — what comes next (if anything)
is decided from real evidence, not planned in advance.

**Review trigger** — whichever comes first, after Phase 1A activation:
- 10 meaningful real-repository prompts processed during normal work, or
- two weeks of normal dogfooding.

**How the review works:**
1. Inspect only the packets that mattered to real work. Classify each by
   hand as `helped` / `neutral` / `hurt-noise`.
2. For each meaningful packet, record one short reason. Group repeated
   reasons across packets.
3. A new phase is only considered when the same high-cost gap recurs at
   least three times.
4. If no repeated high-cost gap appears, freeze at Phase 1A. That is
   successful validation, not stagnation.

Evidence Compiler may expose factual signals in a future local review
command, but must never autonomously select, create, or begin a phase.
The initial review is deliberately manual and local, drawing only on:
- collector health/status
- latency / timeout behavior
- presence of selected `file:line` citations
- token-budget utilization
- the human usefulness label from step 1 above

**If a new phase is warranted**, write a one-page phase proposal before any
implementation, containing:
- the problem, demonstrated by real packets
- at least three concrete examples
- explicit non-goals
- a success metric
- the smallest experiment or implementation slice

**Candidate directions are decision branches, not promises** — each is
justified only by its own recurring signal, not chosen in advance:
- *evidence quality* — if retrieval/ranking is consistently noisy or
  incomplete
- *structural evidence* — if recurring questions need callers,
  dependencies, or dataflow beyond lexical search
- *verification evidence* — if the recurring gap is proving change safety
  rather than finding context
- *interoperability* — if a non-Claude Code integration becomes a
  demonstrated need
- *optional inference* — only when deterministic evidence is repeatedly
  sufficient but interpretation/synthesis is the recurring bottleneck

Governing selection principle, to be applied verbatim at every review:

> "Evidence Compiler earns a new phase only when repeated real work shows
> that deterministic, provenance-preserving evidence cannot answer a
> recurring high-cost question within the interaction budget."

**Deferred boundaries — this document introduces none of the following:**
no telemetry upload, no cloud analytics, no resident daemon, no dashboard,
no autonomous roadmap selection, no local-AI in the critical path, and no
implementation of a review command. This section is policy only.
</content>
