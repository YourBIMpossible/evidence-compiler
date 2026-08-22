# Evidence Compiler — Phase 1A Build Brief

Ordered task list for the initial implementation. Each step names its
spec, its acceptance criterion, and what NOT to do. Work top to bottom —
later steps depend on earlier ones being contract-correct, not just
"working."

---

## 0. Repo scaffolding

Create the layout from `01-architecture.md` §7:

```text
evidence-compiler/
├── README.md            (already exists — update Documents table if paths change)
├── LICENSE              (Apache-2.0 — new)
├── pyproject.toml       (new)
├── docs/
│   ├── architecture/architecture.md
│   ├── specifications/{evidence-packet-v1,context-brief-v1,collector-interface-v1}.md
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

Move the six existing `0N-*.md` files into `docs/` per the mapping above.

**Acceptance:** `pip install -e .` succeeds; `evidence --help` runs (stub
CLI is fine at this stage).

---

## 1. Collectors — git, ripgrep

Implement `Collector.collect(context) → EvidenceResult` per
`04-collector-interface-v1.md` §2–4.

- Git collector: HEAD, branch, dirty paths, basic meta. Enabled by
  default when a Git worktree is detected; otherwise returns
  `status: skipped` with an explicit diagnostic.
- Ripgrep collector: exact symbol defs/refs. Enabled by default when `rg`
  is available; otherwise returns `status: skipped` with an explicit
  diagnostic.
- Graphify: stub only — a collector that returns `status: skipped` with
  `diagnostic.reason: "not implemented"` is correct for Phase 1A. Do not
  build real Graphify integration yet unless explicitly asked.

**Acceptance:** each collector passes the contract test list in
`04-collector-interface-v1.md` §7 (timeout behavior, malformed/empty
output, provenance present, path normalization including Windows inputs,
failure isolation, no crash on duplicate-heavy input).

---

## 2. EvidencePacket v1

Implement the schema in `02-evidence-packet-v1.md` §2–3 as the internal
model (Python side may use dataclasses/pydantic; JSON serialization must
match the logical schema, `schema_version: 1` required on read/write).

- Include `EvidenceItem` with both `source_claim` and `compiler_assessment`
  layers — do not collapse them into one flat object.
- Include `NegativeEvidenceItem` — absence-after-search is a first-class
  citizen, not an afterthought.
- Identity binding (`repository_root`, `worktree_id`, `head`, `session_id`,
  `turn_id`, `packet_id`) is mandatory on every packet.

**Acceptance:** a packet round-trips through JSON serialize/deserialize
with no data loss; unknown major `schema_version` on read raises a clear
error rather than silently coercing.

---

## 3. Ranking (deterministic)

Implement the component-score model from `02-evidence-packet-v1.md` §7.
No ML/LLM ranking. Every selected or omitted item must carry
`selected_because` / `omitted_because` — no opaque single score.

**Acceptance:** given the same packet input, ranking output is identical
across runs (pure function of packet contents, no hidden state/clock
dependence beyond what's in the packet).

---

## 4. ContextBrief v1 rendering

Implement per `03-context-brief-v1.md` §2–4: render only selected
evidence, preserve `file:line` references, stay within budget, never
invent claims not present in the packet, never present provisional/stale
items as verified.

**Acceptance:** brief token/char count stays within
`budget.max_tokens` from the source packet; an empty selection renders
nothing (or a single-line "no structural evidence" note, not a stub
block).

---

## 5. Storage

Persist one JSON file per packet (`02-evidence-packet-v1.md` §6). Storage
dir configurable; default under `.evidence-compiler/packets/`.

**Acceptance:** `evidence replay <packet.json>` (see §8 below) can load
any persisted packet back.

---

## 6. Claude Code Desktop adapter

Implement `integrations/claude_code.py` per `01-architecture.md` §4 and
`03-context-brief-v1.md` §5: `UserPromptSubmit` hook → run compiler → on
success inject brief via `additionalContext`/stdout; on any error, inject
nothing, log, exit 0. Respect operational p95 < 1s, hard safety ceiling
25s.

The adapter must enforce a bounded end-to-end deadline, not just
per-collector timeouts. On deadline expiry: cancel or abandon outstanding
collection, persist any safe diagnostics when possible, inject nothing,
log, and exit 0. This is what makes the fail-open rule real under a
stalled subprocess — it is not scope expansion.

**Acceptance:** hook never blocks or fails the parent Claude Code session,
even with all collectors erroring simultaneously (test this explicitly —
force every collector to throw and confirm exit 0 + no injection), and
even when a collector hangs past its individual timeout (confirm the
end-to-end deadline still fires and the hook exits 0).

---

## 7. Per-repo config

Implement config loading from `.evidence-compiler/config.yaml` per
`01-architecture.md` §8 and the collector config slice in
`04-collector-interface-v1.md` §8. Core package must run with defaults
(git + rg only, no config file present) on any git repo.

**Acceptance:** deleting the config file entirely does not break the
compiler — defaults apply.

---

## 8. Golden fixture repo + contract tests

Build `tests/fixtures/golden-repo/` — a small synthetic repo exercising:
a clean symbol match, a dirty/uncommitted file, a missing-symbol (negative
evidence) case, and a collector timeout/error simulation.

Add `evidence replay <packet.json>` as a minimal text report (packet id,
head, selected vs. omitted counts, collector statuses, timings).

**Acceptance:** golden-repo integration test asserts full packet shape
end-to-end (not just unit-level collector mocks) and passes in CI.

---

## Exit criteria for "Phase 1A done" (do not skip to v0.2 work before this)

- All acceptance criteria above pass in CI on a clean checkout.
- Maintainer has run this against at least one real Revit/BIMpossible repo
  through Claude Code Desktop and confirmed the injected brief was useful
  at least once (this is the actual product validation — CI passing is
  necessary but not sufficient).
- No open TODOs in `src/evidence_compiler/` without a roadmap version
  reference.

## Explicitly deferred (see `06-roadmap.md` — do not pull forward)

v0.2: richer replay output, collector health metrics, hardened empty-result
diagnostics. v0.3+: change contracts, verification ledger, overrides.yaml
behavior. v0.4+: post-edit impact packets, async freshness, GPU
compression, human-approved usefulness recommendations. None of these
belong in this build pass.
