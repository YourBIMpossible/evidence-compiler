# Evidence Compiler — Roadmap

**Last updated:** 2026-11-01 (N6/N7 accepted) · **Installed runtime:** 0.3.1,
dist-info commit `1cdc625c` (same runtime content as the last runtime change on
`master`, `92a9b0088291ae14bc85a296d4b8cc22ebfc2527`). Later documentation-only
commits on `master` change the published head, not the installed runtime.

This is a navigation and status document. It grants no execution authority.
Work operates under [`NORTHSTAR.md`](../NORTHSTAR.md), applicable owner
decisions ([`docs/decisions/`](decisions/)), and the accepted specifications.

## Where each kind of information lives

| Document | Role |
|---|---|
| [`NORTHSTAR.md`](../NORTHSTAR.md) | Mission, boundaries, and the evidence required to earn a new phase (human-only). |
| `docs/roadmap.md` (this file) | Reader-facing track: shipped, active, queued, frozen, and candidate directions. |
| [`WORKLOG.md`](../WORKLOG.md) | Detailed outcomes, findings, decisions, and reopening conditions. |
| `CURRENT-STATE.md` (maintainer handoff, outside the repo) | Sole operational resume anchor: exact revisions, grants, checks, the current action, and the checkpoint. |

A proposed EC-specific `PROJECT-INSTRUCTIONS.md` in the maintainer handoff
grants no authority by itself.

## How a new phase is earned

There is no precommitted sequence of capabilities. A new phase requires both:

1. The same **high-cost** gap, appearing in at least three reviewed packets.
   Recurrence alone is not enough.
2. A one-page phase proposal giving examples, non-goals, a success metric,
   and the smallest experiment.

If no such gap appears, freezing at Phase 1A is successful validation (see
`NORTHSTAR.md` → *Requirements for a new phase*).

The original 2026-08-21 version plan is **superseded**. It is kept at the end
for the record.

---

## Shipped

| When | What | Ref |
|---|---|---|
| 2026-08-22 | **Phase 1A**: package + CLI, git/ripgrep collectors, Graphify stub, EvidencePacket v1, ContextBrief v1, deterministic ranking, persistence/replay, fail-open Claude Code Desktop adapter, contract + golden tests, CI | `237d115` |
| 2026-08-24 | Brief determinism (F-D1); **Phase 1B** compound technical terms (narrow, Option A only); single-source version; Python hook launcher | PR #2–#5 |
| 2026-09-02 | Independent audit; F-1…F-5 fixed | PR #6, [`docs/audit/`](audit/) |
| 2026-09-06 | **Window 3 evidence-quality pass** (v0.2.0 → v0.3.0): rg UTF-8 decode fix, timeouts, harness-notification detection, Unicode/dedup, git dirty-state observability, `evidence review` workflow | PR #9–#16 |
| 2026-09-16/21 | Batched rg search, exact filename-stem evidence, equal-score tie-break, stem lookup respects the deadline | PR #18–#20 |
| 2026-10-06/10 | Markup-tag stripping; allow-listed secondary repository scope ([decision](decisions/2026-10-06__secondary-repository-scope.md)); review-repair pass | `0646e8d`, PR #21–#22 |
| 2026-10-11 | **N6**: peer-session messages and cross-session idle notices classified `harness`. **Merged and installed; accepted 2026-11-01 on natural traffic.** | PR #23 |

### Shipped vs accepted

These are different states:

| State | Revision |
|---|---|
| Last runtime change on `master` | `92a9b0088291ae14bc85a296d4b8cc22ebfc2527` |
| Installed runtime (dist-info `direct_url.json`; same content) | `1cdc625c` |
| Published `master` head | Moves with documentation-only commits; does not imply a reinstall |
| Last accepted runtime (rollback target) | `92a9b0088291ae14bc85a296d4b8cc22ebfc2527` (accepted 2026-11-01; previous `4df93f2ab255a9470f51c5580f52330e17ac7e7b`) |

N6 and N7 were accepted on 2026-11-01 (owner, in chat) on the passive
natural-traffic re-check receipt of 2026-11-01 (packets 2026-10-16 to
2026-11-01, 1233 inspected). Criterion, per the owner's 2026-10-31
clarification: envelope prompts classified `harness`, 0 extracted symbols, no
evidence search; a git-status-only brief is permitted. Observed: PEER 172/172,
IDLE 24/24, AGENT-MSG 116/116, genuine prompts `human` 521/521,
`persist_failed` 0. Limits carried: AGENT-MSG and PEER origin verified from
queue entries only; 100 empty-brief packets have no hook.log line (early
return in `hook_safe.py`, packets persisted).

### Phase 1B status note

The implementation shipped in PR #3. The proposal's closure gate (five
labelled post-implementation dogfood prompts) has no recorded outcome. This is
an open historical evidence gap, not a closure.

## Now — one active milestone

None active. **Passive natural-traffic acceptance of N6** completed and was
accepted 2026-11-01 (see *Shipped vs accepted*). Done-means, as met:

- A natural peer message or idle notice is classified `harness` with 0 symbols.
- Genuine prompts stay `human`.
- There is no `persist_failed`.

Phase 1A remains frozen; no publish, install or release. The next milestone
needs an owner grant.

**Window 3 usefulness review — closed 2026-10-12.**

- 12 agent-proposed judgments (ten original W3 packets, one proposed
  replacement, and one runner-up) were **owner-ratified on 2026-10-11**: all
  12 `neutral`, with their recorded reasons and the review's sampling and
  attribution limits intact. This means no observable contribution or harm
  in the inspected evidence, not proof of zero internal effect.
- **W3 closed 2026-10-12** (owner-granted): 7 labels via `evidence review
  label`; the 5 archive-only judgments in a local sidecar bound to verified
  archive hashes (not CLI labels). Window membership unchanged.
- Ratification does not authorize a phase. The review reports recurring
  noise, not demonstrated high-cost harm.

## Queued — current-scope maintenance, not a phase

None of these is evidence that a new phase has been earned. Each needs its own
grant. Details are in [`WORKLOG.md`](../WORKLOG.md) → *Roadmap / queued*.

| ID | Item | Status |
|---|---|---|
| N1 | `filenames` cache keyed by (root, HEAD) goes stale on staging changes | Queued, ungranted |
| N2 | Dirty paths are relative to the git toplevel when the root sits below it | Queued, ungranted |
| N3 | `save_packet` leaves a `.tmp` file on write failure | Queued, ungranted |
| N4 | Packet vocabulary constants are not validated on load | Queued, ungranted |
| N5 | `load_labels` raises on an unreadable labels file | Queued, ungranted |
| N7 | `<agent-message from=…>` envelopes classify `human` and inject; N6 does not cover this shape | Owner-granted 2026-10-12; delivered via PR; **accepted 2026-11-01** on the N6 criterion (116/116) |
| — | `/review-all` W3-pass findings ([report](reviews/2026-09-06__review-all__w3-pass.md)) | Queued, ungranted |
| — | W3 label route for archive-only packets | Resolved 2026-10-12: hash-bound local sidecar |

## Frozen — reopens only on the stated evidence

| Item | Reopen condition |
|---|---|
| Capped-ripgrep determinism redesign (`EC-RG-CAP-DET`) and the total match cap | At least 3 distinct reviewed human-task packets where cap truncation hid needed evidence |
| rg stall | Recurs on human-task packets (0/14 reproductions so far) |
| F2: hyphenated lowercase names dropped by extraction | Owner call, because it is an evidence-quality change |
| Public v0.1 launch / PyPI | Golden + contract tests green end-to-end, real dogfooding, and an owner decision after Window 3 |

## Candidate directions — not phases

These come from `NORTHSTAR.md`:

- Evidence quality
- Structural evidence
- Verification evidence
- Interoperability
- Optional inference

Each requires the phase proposal described above before any work starts.

## Out of scope

`NORTHSTAR.md` is authoritative; in summary:

- Verification hooks or a hard Stop
- Change contracts
- A daemon
- GPU, embeddings, or RAG
- LLM ranking
- A second adapter
- A plugin marketplace
- Product-specific policy in core
- Telemetry upload

---

## Superseded: original version plan (2026-08-21)

Kept for the record only. It no longer describes intended work.

| Version | Original plan | Outcome |
|---|---|---|
| v0.1 | Phase 1A | Shipped. |
| v0.2 | Richer replay and diagnostics; collector health metrics; expanded golden corpus | Partly absorbed into the Window 3 pass and `evidence review`. |
| v0.3 | Change contracts; path policy; soft verification ledger | Out of scope per the North Star. |
| v0.4+ | Post-edit impact packets; async freshness; GPU compression; offline usefulness recommendations | Out of scope or unearned. |
| v1.0 | Schema stability and migration policy after multi-repo production use | Long-range bar; not scheduled. |
