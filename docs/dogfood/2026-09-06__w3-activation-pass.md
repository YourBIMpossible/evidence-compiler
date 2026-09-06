# 2026-09-06 — Window 3 activation pass (final report)

Mandate: one continuous improvement-and-activation pass — core fixes
(Unicode symbols, duplicate-reference folding, review queue/remind), live
install upgrade, downstream timeout configuration, real smoke tests, live
Window 3 measurement. Predecessor: [2026-09-06__w3-improvement-pass.md](2026-09-06__w3-improvement-pass.md).

## Done

### Core (Evidence Compiler, v0.2.1 → v0.3.0)

| Item | Where |
|---|---|
| PR #12 merged to `master` | `92b4e33` (merge), lane `claude/w3b-unicode-dedup-review` |
| Core commit | `f1f5bdd` — Unicode symbols, duplicate-reference folding, review queue/remind |
| Docs-only commit | `68a75c9` — WORKLOG, head-null closure, review-all report |
| Tests | 167 → 200 passing; ruff at pre-PR baseline |
| Live install | `pythoncore-3.14-64` interpreter reports `evidence_compiler.__version__ == 0.3.0`, `direct_url.json` commit `92b4e33f…` (non-editable install from the merged SHA) |

**Unicode symbols** ([src/evidence_compiler/scoping.py](../../src/evidence_compiler/scoping.py)).
Identifier shape is decided by Unicode word class instead of `[A-Za-z]`;
prompt text is NFC-normalised before tokenising. `fenster_größe`,
`Fenster.größe_berechnen()`, `señal_activa`, `fensterGröße`, `` `größe` ``
are recognised with the same categories and ranks as ASCII, and reach the
brief through ripgrep (`-w -F` is already Unicode-aware). Limits, pinned by
[tests/unit/test_unicode_symbols.py](../../tests/unit/test_unicode_symbols.py):
capitalised German nouns enter at rank 30 like English mid-sentence capitals;
NFD-encoded source files are not matched by an NFC query; NFKC and case
folding are deliberately not applied; lowercase hyphenated Unicode spans split
like any lowercase span.

**Duplicate references** ([src/evidence_compiler/render.py](../../src/evidence_compiler/render.py)).
Selected items with identical `(collector, kind, sorted references)` render
once; the survivor's `why` line gains `; also matches <symbol>`. Folded items
stay `selected: true` in the packet with a `same reference as <id>; rendered
once` note and are *not* added to `omitted_evidence_ids`. `RenderResult.merged_ids`
maps folded → survivor. Presentation only; ranking unchanged; the packet
remains the single source of truth.

**Review workflow** ([src/evidence_compiler/review.py](../../src/evidence_compiler/review.py),
[docs/dogfood-review.md](../dogfood-review.md) §6.1).
`evidence review queue` — unlabeled candidates, then nosym, ordered by
`sha256(window:packet_id)`, so labeling never reshuffles. `evidence review
remind` — one line when `window_days`/`window_candidates` trips, else silent.
`label` requires `--note` (whitespace-collapsed, ≤200 chars; exit 2 without).
Legacy harness-word heuristic applies only to packets without
`symbol_details`. `status` adds baseline, degraded rate, reviewed/unreviewed,
`head` watch metric, and the rule "raw packet count is activity, not
usefulness". Eleven tests in [tests/unit/test_review_queue.py](../../tests/unit/test_review_queue.py).

**`identity.head: null`** — closed as historical. Every null-head packet in
BIMpossible predates v0.2.0 (old shared 62 ms probe budget). All v0.2+
packets are `resolved`; `status` now watches the count (expect 0). No
gitprobe change.

### Downstream configuration (`.evidence-compiler/config.yaml`)

Change in every repo: `collectors.git.timeout_ms 250 → 600`,
`collectors.ripgrep.timeout_ms 500 → 1500`. Storage, retention (250),
graphify (1250) untouched. Validated with `yaml.safe_load` and `load_config`.

| Repo | PR | Merge | Method |
|---|---|---|---|
| BIMpossible | #601 | `2236cbf` | squash (repo policy: squash-only) |
| BIMpossible-Workspace | #123 | `25ac819` | merge commit |
| BIMpossible-AddIns | #118 | `945c195` | merge commit (required checks: firm-literals, test, gitleaks, nuget-vulns) |
| Families-by-BIMpossible | #14 | `57b63e6` | merge commit |

AddIns and Families were inspected first (identical 250/500 overrides) and
changed only after a live measurement demonstrated harm (below). Live
checkouts received the same two-line edit in the working tree so the hook
uses the new budgets immediately; nothing else was staged or touched.

### Live measurement — before / after (0.3.0 installed, 9–10 symbol prompt)

| Repo | Before: rg | Before: git dirty probe | After: rg | After: git | Hook wall |
|---|---|---|---|---|---|
| BIMpossible | 4/10 searched, 0 matches, `timeout` | `probe_timeout` | 10/10, 25 matches, `ok` | `resolved` | 1016 ms |
| Workspace | 4/10 searched, 0 matches, `timeout` | `probe_timeout` | 10/10, 25 matches, `ok` | `resolved` | 1090 ms |
| AddIns | 4/9 searched, 0 matches, `timeout` (2 runs) | `probe_timeout` | 6–7/9 searched, 5 matched, 100 matches (cap), `ok` | `resolved` | 861–1256 ms |
| Families | 6/9 then 9/9, `partial_timeout` then `ok` | `probe_timeout` | 9/9, 5 matched, 43 matches, `ok` | `resolved` | 947–1096 ms |

All smokes: exit 0, `additionalContext` injected, packets and logs
git-ignored in every repo (`git check-ignore`), nothing evidence-related
staged.

### Window 3 live status (after this pass; probes counted as system traffic)

| | BIMpossible | Workspace |
|---|---|---|
| Window | W3 since 2026-09-06T21:39Z | W3 since 2026-09-06T21:39Z |
| Packets in window / on disk (baseline) | 14 / 250 (250) | 8 / 87 (79) |
| Traffic | candidate 1, nosym 5, probe 8 | probe 8 |
| Degraded | 5 (36 %) — rg timeouts, all before the config change | 4 (50 %) — all before the config change |
| head without commit | 0 | 0 |
| Latency p50 / p95 | 789 / 1192 ms | 1036 / 1785 ms |
| Labels | 0 (1 candidate unreviewed) | 0 |
| Queue | 6 unlabeled (1 candidate + 5 nosym) | empty |
| `remind` | silent (not due) | silent (not due) |

Next review threshold: 10 unlabeled candidates or 2026-09-20, whichever
first. No labels were written this pass — reviewing is the human's job.

### Commit separation

- Core code: `f1f5bdd` (one lane commit). Docs-only: `68a75c9`. Merge `92b4e33`.
- This report + WORKLOG: one docs-only commit on `claude/w3-activation-report`.
- Downstream: one config-only commit per repo (`6fc022c` AddIns, `f5cab88`
  Families; BIMpossible/Workspace lane commits landed via #601/#123).

### Confirmations

Not published to PyPI. Dashboard untouched. No foreign work modified or
staged in BIMpossible, Workspace, AddIns, or Families (each lane worktree
held exactly one changed file). No force-push, no history rewrite, no
branch-protection change. `DOGFOOD_LOG.md`, `*.draft.md`, local archive left
untracked. Capped-ripgrep determinism and Phase 1B compound-symbol work not
reopened (no new field evidence). No raw prompts, secrets, or evidence bodies
in any review record. Remote lane branches left in place. `NORTHSTAR.md` not
edited.

## Assumed

- Downstream Workspace local `main` carries a foreign unpushed commit and is
  behind origin; the config edit was applied to the working tree, not merged
  locally. Say the word to `git pull --ff-only` there (may conflict with the
  foreign commit — not attempted).
- AddIns local `main` is behind origin by 12 and dirty with foreign work; same
  treatment (working-tree edit only).

## Left-Flags

- **Transient rg timeout streak** right after the Workspace/BIMpossible config
  edit: every symbol timed out at 1500 ms for a few minutes while raw `rg` took
  70–150 ms. Not reproduced afterwards; not caused by stdin handling. Watch the
  W3 degraded rate; if it recurs, capture `rg` wall time alongside the packet.
- **Determinism test flake** (`test_repeated_compile_produces_identical_brief`)
  failed once under concurrent load, passed 3× individually and in 3 full runs.
- **AddIns hits the 100-match cap** with a 9-symbol Revit prompt (3 symbols
  `not_searched` because the cap stopped the run, not a timeout). This is the
  frozen capped-ripgrep behaviour working as designed; recorded only as the
  first field observation of the cap on a real repo.
- **Window 3 has one candidate packet and zero labels.** The measurement
  automation is in place; usefulness evidence still depends on the human
  labeling when `remind` fires.

## Proposed `NORTHSTAR.md` patch (human-only file; not applied)

Insert after the "Dogfood signals and phase selection" bullet list ending
"…Whether the brief helped, was neutral, or created noise." and before the
"A future local review command…" paragraph:

```markdown
### Review windows

- **Window 2** (v0.1.0 → v0.2.0, closed 2026-09-06): 343 packets;
  labeled helped 0 / neutral 18 / hurt-noise 4 / insufficient 1. Dominated by
  the ripgrep cp1252 decode defect and harness notifications compiled as
  prompts; both fixed in v0.2.0. No repeated high-cost gap → no new phase.
- **Window 3** (v0.2.1+, opened 2026-09-06 in BIMpossible and
  BIMpossible-Workspace via `evidence review window start --name W3`;
  baselines 250 / 79 packets). Review when `evidence review remind` fires
  (10 unlabeled candidates or 14 days). Measurement: `evidence review
  status|queue`. Labels require a note.
```

And amend the sentence "A future local review command may summarize these
factual signals" to "The local `evidence review` command summarizes these
factual signals" (shipped in v0.2.0/v0.3.0). No change to `status:` or to
mission, boundaries, or phase requirements.
