# Evidence Compiler — Worklog

Routing per `NORTHSTAR.md`: small-and-on-mission → Done; worth-doing branch-off
→ Roadmap; would-change-the-mission → Needs your call.

## Done

- 2026-09-06 — **Window 3 activation pass** (lane `claude/w3b-unicode-dedup-review`,
  v0.2.1 → v0.3.0, commit `f1f5bdd`). Tests 167 → 200; lint at baseline.
  - Unicode-aware symbol extraction: identifier shape by Unicode word class,
    NFC normalisation only. Field trigger: `größe` dropped in W3. Limitation
    pinned: capitalised German nouns enter at rank 30 (prose rule), NFD source
    files are not matched. ripgrep collector unchanged (`-w -F` already
    Unicode-aware).
  - Duplicate rendered references fold into one line (`; also matches …`);
    packet keeps folded items `selected` with a `rendered once` note;
    `RenderResult.merged_ids`. Presentation only; ranking untouched.
  - `evidence review queue|remind`: hash-ordered unlabeled queue that labeling
    never reshuffles; one-line reminder when due; `label` requires `--note`
    (exit 2 otherwise); legacy harness-word heuristic now only for packets
    without `symbol_details` (review-all finding 5); `status` gains baseline,
    degraded rate, reviewed/unreviewed, `head` watch metric, and the
    "packet count is activity, not usefulness" rule. Cadence documented in
    [docs/dogfood-review.md](docs/dogfood-review.md) §6.1.
  - `head: null` investigation closed: all 16 BIMpossible packets with a null
    head predate v0.2.0 (no `head_state`, mostly no `branch`) — identity probe
    timeouts under the old shared 62 ms budget, not detached HEAD. Every v0.2+
    packet is `resolved`. No gitprobe change; watch metric only.

- 2026-09-06 — **Window 3 improvement pass** (lane `claude/w3-evidence-quality`,
  anchor [docs/dogfood/2026-09-06__w3-improvement-pass.md](docs/dogfood/2026-09-06__w3-improvement-pass.md),
  v0.1.0 → v0.2.0). Resolves the five queued 2026-09-06 items below.
  - ripgrep: explicit UTF-8 decode + `None`-stdout guard; per-symbol outcome
    categories (`matches/no_matches/timeout/not_searched/decode_error/process_error/launch_error`)
    with counts in the diagnostic; dynamic per-symbol budget; unsearched symbols
    recorded as `not_searched`; logical `rg` in provenance; core default
    `timeout_ms` 500 → 1500.
  - Identity probe: own 1000 ms shared budget, `identity.head_state`
    (`resolved/probe_timeout/unresolved`), detached-HEAD flag.
  - Scoping: ranked, bounded, explainable selection (`task.symbol_details`);
    sentence-initial prose rejected; repo self-name and `scoping.ignore_symbols`
    rejected; harness/system-notification text → `task.source_kind: harness`,
    no symbols. Compound (Phase 1B) behaviour unchanged.
  - `evidence review inventory|sample|label|status|window` — local packet review
    with stable ids, seeded stratified sampling, labels under
    `.evidence-compiler/logs/review/`. Validated read-only on both Window 2
    corpora (BIMpossible 250 packets, Workspace 77).
  - Docs: [docs/dogfood-review.md](docs/dogfood-review.md), README, quickstart,
    packet-spec 1.x additions. Tests 131 → 163.
- 2026-09-06 — **Maintenance + Window 2 review pass** (bounded; no commits,
  pushes, releases, or downstream-repo changes).
  - Local-only knowledge preserved, hash-verified, to
    `C:/Users/Zeria/.claude/projects/F--Evidence-Compiler/local-archive/2026-09-06_pre-sync/`
    (`MANIFEST.txt` has SHA-256 + sizes). The 21.5 KB pre-tracking local
    `WORKLOG.md` (2026-08-24, SHA-256 `b4b0d8db…`) lives there as
    `WORKLOG.local-2026-08-24.md`; it was **moved, not merged** — this tracked
    file supersedes the old untracked convention. Safety branch
    `safety/pre-sync-2026-09-06` = `874bd7f`.
  - Worktree moved `claude/hook-safe-launcher`@`874bd7f` → `master` fast-forwarded
    to `origin/master`@`36e83ac` (PR #6 audit fixes, PR #7 ruff, review profile).
    `DOGFOOD_LOG.md` + 3 drafts remain local, untracked, hashes unchanged.
  - Live hook install upgraded non-editably: `pip install git+…@36e83ac` into
    `pythoncore-3.14-64` (was VCS-pinned `0ef747e`, 8 commits stale). Runtime
    matrix 8/8 pass (root+nested BIMpossible/Workspace inject; outside-root cwd
    refused; empty stdin logged; both off switches silent; `hook`/`hook-safe --help`).
  - Window 2 review recorded in local `DOGFOOD_LOG.md`: 343 packets, n=23 sample,
    **helped 0 / neutral 18 / hurt-noise 4 / insufficient 1**. Result dominated by
    the collector defect below.

## Roadmap / queued

- 2026-09-06 — **/review-all on the W3 pass** (read-only, 13 retained, 0 dropped):
  [docs/reviews/2026-09-06__review-all__w3-pass.md](docs/reviews/2026-09-06__review-all__w3-pass.md).
  Top items: temp-path regex alone marks human prompts `harness`; `word (`
  ranked as a call; sentence-initial rejection is per token not per occurrence;
  PascalCase filenames leak their extension as a symbol; review's legacy
  harness-word heuristic overrides `source_kind`. Same Phase 1A scope as W3;
  not started.
- (resolved 2026-09-06, W3 pass) The next five items — rg decode defect, rg
  12-symbol timeout, harness notifications, absolute rg path, `head: null` —
  are fixed on `claude/w3-evidence-quality`; kept for the record.
- **2026-09-06 — DEFECT (Phase 1A scope, not a new phase): ripgrep collector
  drops its whole pass on Windows.** `collectors/ripgrep.py:79-86` uses
  `subprocess.run(text=True)` without `encoding=`; cp1252 decode of rg stdout
  fails on any non-cp1252 byte, the reader thread dies, `proc.stdout` is `None`,
  `_parse_rg_json` raises `AttributeError` → status `error`. 119/343 dogfood
  packets (35 %); reproduced on `36e83ac` with the single symbol `BIMpossible`.
  Fix: `encoding="utf-8", errors="replace"` (rg emits UTF-8 JSON; `--json`
  already base64-encodes non-UTF-8 text as `bytes`), plus a regression test with
  a fixture line containing `\x90`/`\x9d`. Also audit `git.py` for the same
  pattern. Not started — this pass was no-commit.
- 2026-09-06 — rg `timeout` at the 12-symbol maximum (31×): `per_symbol_ms =
  max(500//12, 100)` = 100 ms, so only ~5 searches fit the 500 ms collector
  deadline; symbols 6–12 never run. Decision needed: raise `timeout_ms`, lower
  `_MAX_SYMBOLS`, or search in one rg invocation (`-e` per symbol). Design
  question; queue for the phase proposal.
- 2026-09-06 — Harness task-notification text ("Background Agent completed …
  `C:\Users\…\Temp\…\output`") reaches `UserPromptSubmit` and is compiled as a
  prompt: 77/343 packets (22 %); symbols `Users`/`Zeria`/`AppData`/`Temp` 77–82×.
  Whether/how to detect non-human prompts is a product decision (could be
  per-repo config, could be core). Not started.
- 2026-09-06 — `provenance.command` stores the absolute rg executable path
  (`C:\Users\<user>\…\rg.EXE`) in every lexical item. Packets are ignored/local,
  but the existing replay redaction should cover it or the collector should
  record `rg` by basename.
- (resolved 2026-09-06, W3 activation pass) 15 BIMpossible packets on 2026-09-06
  carry `identity.head: null` while `git` reported `ok`. Root cause: pre-v0.2.0
  identity-probe timeout; not detached HEAD. `status` now carries a `head`
  watch metric.
- (resolved 2026-09-02) Pre-existing ruff `F401` in
  `tests/contract/test_collector_contract.py:18` (`RawClaim` imported but
  unused) — dropped the unused import on lane `claude/ruff-f401-cleanup`.

## Needs your call

- (resolved 2026-09-06) **Window 2 disposition** — closed as reviewed
  (helped 0 / neutral 18 / hurt-noise 4 / insufficient 1, dominated by the rg
  defect); Window 3 starts on v0.2.0 via `evidence review window start`.
  `NORTHSTAR.md` untouched — record the W2 → W3 transition there yourself.
- (resolved 2026-09-06) **ripgrep encoding fix** — shipped in the W3 pass.
- 2026-09-06 — **WORKLOG collision disposition.** Chosen: archive the old local
  21.5 KB file, adopt the tracked upstream file (this one). Alternative: merge
  its historical sections in under a `## Archive` heading — say the word.
- (resolved 2026-09-06) WORKLOG edits committed in a docs-only commit on
  `claude/w3-evidence-quality`.
- 2026-09-06 — **Post-deploy follow-up shipped**: PR #10 (`ab6dc90`, v0.2.1) —
  git `dirty_state` observability + default git budget 600 ms; fixes the
  determinism flake found in post-deploy verification. Window 3 started on
  v0.2.1 in both downstream repos (`evidence review window start --name W3`).
- 2026-09-06 — **Downstream configs still pin `ripgrep.timeout_ms: 500`** (and `git.timeout_ms: 250`)
  (BIMpossible, Workspace). Core default is now 1500; raising them is a
  downstream edit this pass did not make. Say the word.
- (resolved 2026-09-02) Pushed lane `claude/evidence-compiler-audit-81162b` to
  `origin` and opened PR #6 against `master` for the audit + code-review fixes.
