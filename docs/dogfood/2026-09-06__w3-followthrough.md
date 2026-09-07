# Window 3 follow-through pass — final report (2026-09-06 / 07)

Mandate: close genuine residual defects from the W3 activation pass, convert
observed-but-unconfirmed signals into verified fixes or documented watch
items, sync downstream checkouts without disturbing foreign work, propose the
human-owned `NORTHSTAR.md` update as a patch, and leave Window 3 with an
enforceable review rhythm. No new scope.

Frozen and **not reopened**: capped-ripgrep determinism redesign, broad
match-cap redesign, Phase 1B compound-symbol work, PyPI release, Dashboard
changes, downstream hook/config redesign.

Companion documents: [W3 activation pass](2026-09-06__w3-activation-pass.md),
[W3 improvement pass](2026-09-06__w3-improvement-pass.md),
[dogfood review guide](../dogfood-review.md) (§2.1 cap, §2.2 stall, §6.1 cadence).

## Done

### Core (PR #14, merged `358ea45`, v0.3.1)

Branch `claude/w3-followthrough`, core commit `ceff91b`, merge commit
`358ea454d6a00d6ac04846751bd671e3ebe842ca`. CI 3.10/3.11/3.12 green; ruff
24 pre-existing findings (baseline unchanged); full suite green in a
worktree-local venv.

| Area | Change |
|---|---|
| `review.py` | `PacketSummary.rg_truncated` / `rg_stall`, `rg_display` (`matches+capped`, `timeout+stall`), `incidents` (`degraded:<collector>`, `cap_hit`, `rg_stall`, `hurt-noise`; candidate traffic only), aggregates and `status` lines `rg capped`, `rg stall`, `incidents`; `window_due` immediate trigger at `review.incident_threshold` (default 3). |
| `config.py`, template | `review.incident_threshold: 3`. |
| `gitprobe.py`, `compiler.py` | First probe (`rev-parse --is-inside-work-tree`) timing out now yields `head_state = dirty_state = "probe_timeout"` instead of a bare `head: null` with no state. |
| `test_determinism.py` | Widened deadline/collector budgets, compares a collector signature across 3 runs, skips (not fails) when collectors themselves changed outcome under load. |
| `test_review_telemetry.py` (new, 7 tests) | Cap labeled in queue/sample/inventory/status; deterministic across scans; stall predicate; incident trigger; probe/harness/mixed/zero-threshold exclusions; `hurt-noise` counts. |
| `test_gitprobe_head_state.py` | `probe_timeout` on first-probe timeout; `None` only outside a work tree. |
| `docs/dogfood-review.md` | §2.1 cap and ranking order, §2.2 stall watch, §6 triggers, §6.1 cadence. |

Numeric cap (`_MAX_TOTAL_MATCHES = 100`, 25 per symbol) **unchanged**.

### Live install

Non-editable `pip install git+…@358ea45` into `pythoncore-3.14-64`;
`evidence_compiler.__version__ == "0.3.1"`, `direct_url.json` commit
`358ea454…`. Live smokes on v0.3.1: root and nested hook in BIMpossible and
Workspace, 6/6 exit 0, brief injected, head and dirty state resolved, no rg
timeouts, 807–982 ms. Packet and log artifacts land only in ignored paths.

### Worktree cleanup

`w3a`/`w3-improvement` lanes removed earlier in the pass (branches merged).
`w3b` (merged) removed at the end of this pass; `w3c` is removed after the
docs PR merges. Main checkout `master` fast-forwarded to `origin/master`.

### Safe-sync of downstream checkouts

Rule applied: no stash, reset, clean, or checkout-overwrite of foreign work.

| Checkout | Result |
|---|---|
| BIMpossible | 0 staged; `.evidence-compiler/` tracked files (README, config) match origin/main; packets/logs ignored. |
| BIMpossible_Workspace | 0 staged; `config.yaml` differs from local HEAD but is identical to `origin/main`; local `main` is behind and not fast-forwardable from here — left unchanged. |
| AddIns | 0 staged; same `config.yaml` situation as Workspace — left unchanged. |
| Families | 0 staged; nothing to sync. |

## Investigations

### Ripgrep timeout streak (10/10 symbols timing out, 0 matches)

Not reproducible: 0 of 14 attempts (10 hook smokes, 4 post-load runs) with rg
answering in < 100 ms. No collector change. Converted to a **watch item** with
telemetry: `rg_stall` (rg `timeout` and `symbols_timeout == symbols_searched
>= 2`) shown as `rg=timeout+stall` and counted in `status`. Live count after
the pass: BIMpossible 2, Workspace 4, all from the 2026-09-06 23:35 probe
streak; none on human-task packets.

### Determinism flake — confirmed and fixed (test-side)

- Test: `tests/unit/test_determinism.py::test_repeated_compile_produces_identical_brief`.
- Reproduction before fix: 20 serial runs → 1 failure; 20 runs under 4
  concurrent full suites → 12 failures.
- Cause: collector wall-clock timeouts under load (git identity/dirty probe,
  git collector skipped) change the evidence, so the brief legitimately
  differs. Ordering is deterministic; the flake was environmental input drift
  misread as non-determinism.
- Fix: budgets widened (`deadline_ms` 60 s, collector `timeout_ms` 20 s), a
  collector signature (head, head_state, statuses, dirty outcome) compared
  across the 3 runs, `pytest.skip` when it differs, identical briefs asserted
  otherwise.
- After fix: 20 serial → 0 failures; 20 under load → 12 passed / 8 skipped /
  0 failed (logs: scratch `determinism.log`, `determinism2.log`).
- Decision: the capped-ripgrep determinism redesign stays **frozen**; the
  observed flake was not cap-related.

### `head: null` / dirty observation

Historical for field packets: every v0.2+ packet on disk resolves head and
dirty state. The load reproduction exposed a real gap: when the very first
git probe timed out the packet carried `head: null` with `head_state: null`,
indistinguishable from "not a repository". Fixed (`probe_timeout`), tested,
shipped in v0.3.1.

### AddIns cap-hit

- Order of operations: the cap is applied at **collection time in symbol rank
  order, before ranking and the token budget**; once 100 matches are in, the
  remaining lower-ranked symbols are never searched (`not_searched`,
  `total match cap reached`). Ranking then selects among the ≤100 collected
  items. What a cap hit hides is therefore the tail of the symbol ranking,
  not a random subset.
- Metadata: `diagnostic.truncated: true`, `diagnostic.cap: 100`, status `ok`,
  outcome `matches` (a cap hit is not a timeout). Review views now show
  `rg=matches+capped`; `status` shows `rg capped N` and `incidents cap_hit=N`.
- Live: BIMpossible human packet `ep_09b7ec66b73c43f4` is `matches+capped`;
  `incidents cap_hit=1`. AddIns has no W3 window yet (no packets since v0.3).
- **Reopening trigger (recorded in WORKLOG Roadmap):** reopen the cap or its
  ordering only after at least three distinct, reviewed human-task packets
  show that cap truncation hid needed evidence or caused degraded output.
  Numeric cap unchanged.

## Window 3 live status (v0.3.1, 2026-09-07 ~00:28 UTC)

| Repo | Window / on disk (baseline) | Candidate | nosym | probe | degraded | rg capped | rg stall | head unbound | latency p50 / p95 / max ms | labels | queue | remind |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| BIMpossible | 23 / 250 (250) | 2 | 6 | 15 | 5 (22 %) | 1 | 2 | 0 | 871.7 / 1191.6 / 1829.9 | 0 | 8 | silent |
| BIMpossible_Workspace | 15 / 94 (79) | 0 | 0 | 15 | 4 (27 %) | 0 | 4 | 0 | — | 0 | 0 | silent |

- W3 started 2026-09-06T21:39Z. Triggers: 10 unlabeled candidates (now 2),
  or 2026-09-20 (14 days), or ≥3 candidate packets sharing one incident
  category (now `cap_hit=1`).
- Harness, probe, and smoke packets are excluded from candidacy and from
  incident counting; they still appear in operational counters (degraded,
  stall) — the 4 Workspace stalls are all probe traffic.
- **Labels written: 0.** The two candidates were produced by another session;
  labeling their usefulness from here would be inference, which the cadence
  forbids. Local `DOGFOOD_LOG.md` updated (untracked, not committed).

## Proposed `NORTHSTAR.md` patch (human-owned; not applied)

Verified with `git apply --check` against `master`. Updates only stale
items: W2 closed, W3 started, cadence and usefulness criteria, launcher and
retention and review command shipped, determinism redesign and release
frozen. No prompt or evidence content.

```diff
--- a/NORTHSTAR.md
+++ b/NORTHSTAR.md
@@ -27,6 +27,8 @@
 - A fail-open Claude Code Desktop adapter.
 - Contract, fixture, and regression tests with CI coverage.
 - Repository/worktree/HEAD identity binding and replay mismatch warnings.
+- A Python-native, fail-open hook launcher and bounded packet retention.
+- A local `evidence review` command (inventory, queue, label, status, remind).
 
 Phase 1A does not obligate a linear sequence of future phases. It is the
 stable foundation from which future work must be earned by demonstrated use.
@@ -88,6 +90,26 @@
 If no repeated high-cost gap appears, freeze at Phase 1A. That is successful
 validation, not stagnation.
 
+### Review windows
+
+- **Window 2 — closed 2026-09-06 (reviewed).** Labels: helped 0, neutral 18,
+  hurt/noise 4, insufficient 1. Interpretation is limited: a Windows ripgrep
+  decode defect (since fixed) removed the lexical pass from a large share of
+  the sampled packets, so the window measured breakage more than usefulness.
+- **Window 3 — started 2026-09-06 on v0.3.0** after the collector, timeout,
+  noise, Unicode, duplicate-reference, and review-tooling improvements.
+  Cadence: first review at 10 eligible human-task packets or 14 days,
+  whichever first; then every further 10 or 14 days; immediately when three
+  or more human-task packets share one incident category (degraded
+  collector, match-cap hit, ripgrep stall, or `hurt/noise`). Only packets
+  from genuine human prompts are labeled; harness, probe, and smoke traffic
+  is system traffic. Demonstrated usefulness means labeled `helped` packets
+  with a stated reason, not packet volume or collector health.
+- Frozen pending Window 3 evidence and an owner decision: capped-ripgrep
+  determinism redesign (reopens only after three distinct reviewed human-task
+  packets show cap truncation hid needed evidence), and any public release or
+  PyPI publication.
+
 ## Candidate directions
 
 These are decision branches, not precommitted phases or a promised roadmap:
```

## Commit separation

- `ceff91b` — core + tests + `docs/dogfood-review.md` + template (PR #14).
- Docs-only follow-up commit on the same branch: this report + `WORKLOG.md`.
- Untracked and **not committed**: `DOGFOOD_LOG.md`, `RG-CAP-DETERMINISM.draft.md`,
  `PHASE-1B-EVIDENCE-QUALITY.draft.md`, `RELEASE-READINESS.draft.md`.

## Confirmations

- No frozen workstream reopened; numeric cap unchanged; no collector redesign.
- No PyPI or other release action.
- No foreign WIP changed in any downstream checkout; zero staged files there.
- No local-only dogfood or draft file committed.
- `NORTHSTAR.md` untouched; patch proposed above only.

## Assumed

- Skipping (not failing) the determinism test when collectors time out under
  load is the correct contract: the test asserts ranking/rendering
  determinism, not machine load. Say the word to make it fail-loud instead.
- `incident_threshold` default 3 mirrors the cadence rule; configurable per repo.
- The two W3 candidates are left unlabeled for the owner or the session that
  produced them.

## Left-Flags (owner decisions)

1. Apply the `NORTHSTAR.md` patch above (human-only file).
2. Workspace and AddIns local `main` branches are behind their remotes and
   not fast-forwardable from here; pull them from an owning session.
3. Release / PyPI stays deferred until W3 shows labeled `helped` packets.
4. Whether the stall watch (`rg_stall`) should ever gate anything; today it is
   a counter and an incident category only.
