# Evidence Compiler — Worklog

Routing per `NORTHSTAR.md`: small-and-on-mission → Done; worth-doing branch-off
→ Roadmap; would-change-the-mission → Needs your call.

## Done

- 2026-10-11 — **N6: cross-session traffic classified as harness.**
  - Peer-session messages (the whole prompt is one
    `<cross-session-message …>` block) and cross-session idle notices (the
    prompt begins `[Cross-session idle notice]`) are now
    `source_kind: harness`: zero symbols, no search. Matching uses anchored
    whole-prompt envelopes, so prose that quotes either marker, a block with
    human text around it, and pasted copies inside `<pasted_content>` stay
    `human`.
  - `cross-session-message` was added to the default `scoping.markup_tags`,
    so wrapper tokens (`uds`, `pipe`, `from-session` ids) are no longer
    candidates in human prompts. Paths inside a peer block are no longer
    secondary `named_paths`.
  - Tests: `tests/unit/test_cross_session_traffic.py` (8).
  - Replay against the live BIMpossible store compared base `37a3726` with
    N6 code. 239 of 250 prompts were recovered by transcript hash.
    - Exactly 13 changed, all human → harness, and each is a real envelope
      (10 peer messages and 3 idle notices, including `9b8e2967` and
      `f2fbae05`).
    - The other 226 kept the same `source_kind` and the same extracted
      symbols, including genuine `9dd1dfe3`, `70fb08c4`, `631d6e94`,
      `f58778e7` and `43ae1b50`.

- 2026-10-11 — **Repair delivered: PR #21 merged as `4df93f2`, installed.**
  - Commit `3749356` (the 2026-10-10 repair below plus its docs). PR
    https://github.com/YourBIMpossible/evidence-compiler/pull/21.
  - CI run 38109704167 on head `3749356`: ubuntu 3.10, 3.11 and 3.12 each
    `297 passed`, no skips; no workflow change. This is the first real POSIX
    run of fix A.
  - Merged 2026-10-11T03:52:47Z as merge commit
    `4df93f2ab255a9470f51c5580f52330e17ac7e7b`. Its tree equals the tested
    head's tree.
  - Installed `@4df93f2ab255a9470f51c5580f52330e17ac7e7b` into
    `pythoncore-3.14-64`, 03:53:21.741Z–03:53:29.262Z (20:53 local).
    `direct_url.json` `commit_id` verified in a fresh `-I` process.
    Hooks, configs and `allowed_roots` unchanged.
  - Last pre-install BIMpossible packet: `ep_9f1f7b534ec24da6` (03:28:48Z).
    Packets in the install window: 0.
  - **Installed; natural-traffic acceptance pending:** 0 post-install
    packets at closeout. Comparison sample for the next check: the 9
    post-`0646e8d` human packets (p50 869, p90 1134, max 1258 ms) and the 40
    human packets before them (p50 798, p90 1031 ms).
  - W3: all 9 live label packets, replacement `ep_c0352caf728f4e5d` and
    runner-up `ep_debf1e9efccc4d20` are in `F:\Evidence-Archive\EC-LIVE`,
    byte-identical by sha256. `ep_6f3f9cf3ea40435b` exists only in the
    archive. Labels written: 0. W3 stays open.
- 2026-10-10 — **Review + repair pass on `0646e8d`** (written while local and
  uncommitted; superseded by the 2026-10-11 entry above).
  Report: `F:\Claude-Tools\reports\2026-10-10__evidence-compiler-review-repair.md`.
  Fixes, each with a regression test that fails without it:
  - (A) `secondary._lex`: drive-letter paths use `ntpath` semantics on every
    host; POSIX paths stay case-sensitive. Fixes the 7 ubuntu CI failures
    (run 38102222104), reproduced under a POSIX simulation.
  - (B) Every collector job (primary and secondary) receives its own config
    slice, so ripgrep `extra_args` takes effect. A malformed value is ignored.
  - (C) Collection gets only the deadline left after scoping and the identity
    probe. Budgets and the secondary split are unchanged.
  - (D) The renderer admits items in ranking's `selection_key` order, so a
    render drop no longer defeats the equal-score tie-break.
  - (E) A failed packet save is logged as `hook-safe:persist_failed <ExcClass>`.
    Injection is unaffected.
  - `gitprobe` worktree id: a main-tree subdirectory is no longer read as a
    linked worktree `.git`.
  - `evidence replay` on an unreadable or malformed file exits 2 with a clean
    error.
  Result: 297 passed, ruff clean (Windows). POSIX coverage is by simulation
  only; CI has not run on these changes.
  Natural-traffic acceptance of the installed `0646e8d` markup stripping is
  met: 3/3 hash-verified `<pasted_content>` prompts with no tag symbol and no
  lost identifier. No post-deploy errors or secondary jobs. p90 1056 ms vs
  1064 ms pre-deploy.

- 2026-09-06 — **Window 3 follow-through pass — final report**
  ([docs/dogfood/2026-09-06__w3-followthrough.md](docs/dogfood/2026-09-06__w3-followthrough.md)).
  PR #14 merged as `358ea45`, v0.3.1 live-installed. Review telemetry: capped
  packets shown `rg=matches+capped`, stalls `rg=timeout+stall`, incident
  categories with an immediate `REVIEW DUE` at 3 same-category human-task
  packets; first-probe git timeout now `head_state=probe_timeout` (was bare
  `head: null`). Determinism flake confirmed as load-induced collector drift
  (20 serial 1 fail → 0; 20 under load 12 fail → 0 fail / 8 skip) and fixed
  test-side. rg stall streak 0/14 reproductions → watch metric. Cadence
  documented (`docs/dogfood-review.md` §6.1). NORTHSTAR W2→W3 patch proposed
  in the report, not applied. Labels written: 0.
- 2026-09-06 — **Window 3 activation pass — final report**
  ([docs/dogfood/2026-09-06__w3-activation-pass.md](docs/dogfood/2026-09-06__w3-activation-pass.md)).
  v0.3.0 live-installed (`92b4e33`); downstream git/rg timeouts 250/500 →
  600/1500 in four repos, smoke-verified (rg 0 timeouts, dirty probe
  resolved, ~1 s hook); W3 live status recorded (BIMpossible 1 candidate /
  0 labels, Workspace 0 / 0; `remind` silent). NORTHSTAR W2→W3 patch
  proposed in the report, not applied.

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

- 2026-10-10 — **Minor review findings, recorded and not activated:**
  - `filenames` cache keyed by (root, HEAD) goes stale on staging changes.
  - Dirty paths are relative to the git toplevel when `repository_root` sits
    below it.
  - `save_packet` leaves a `.tmp` on write failure; retention never removes it.
  - Packet vocabulary constants are not validated on load.
  - `review.load_labels` raises on an unreadable or undecodable labels file.
  - Human prompts that quote harness markers or `/tmp/claude/` paths are
    classified as harness and get zero symbols (by design; revisit only with
    evidence).

- 2026-09-06 — **Frozen: ripgrep total match cap (`_MAX_TOTAL_MATCHES = 100`,
  25/symbol) and its collection-before-ranking order.** Reopen only after at
  least three distinct, reviewed human-task packets show that cap truncation
  hid needed evidence or caused degraded output. Telemetry to detect that is
  live (`rg=matches+capped`, `incidents cap_hit`). Related freeze
  `EC-RG-CAP-DET` (capped-rg determinism redesign) unchanged; the 2026-09-06
  determinism flake was load-induced collector drift, not cap-related — see
  the follow-through report.
- 2026-09-06 — **Watch: rg stall** (every searched symbol times out while rg
  itself answers in < 100 ms). 0/14 reproductions; surfaced as
  `rg=timeout+stall` and incident category `rg_stall`. No collector change
  unless it recurs on human-task packets.

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

- 2026-10-10 — **Hyphenated lowercase names are dropped by symbol extraction,
  even when backticked.** For example, `evidence-packet-v1.md` yields no
  symbol (`scoping.py` symbol-shape rule). Fixing it changes extraction and
  ranking inputs, which is an evidence-quality change, so it was not done
  inline.
- 2026-10-10 — **W3 label for archive-only `ep_6f3f9cf3ea40435b`.**
  `evidence review label` only sees the live store, so no route exists without
  writing to the store or adding a CLI feature.
  - Proposed same-category replacement (pre-deploy runtime, pasted
    process-control prompt, not truncated, no cited file touched):
    `ep_c0352caf728f4e5d`. Runner-up: `ep_debf1e9efccc4d20`.
  - Rotation risk: the remaining 9 set packets sit at live positions 10–170
    of 250. `ep_dc47b3074c88463f` rotates out after about 10 more BIMpossible
    packets, so label soon or refresh the archive.

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
- (resolved 2026-09-06) **Downstream configs still pin `ripgrep.timeout_ms: 500`** (and `git.timeout_ms: 250`)
  — raised to 600/1500 in all four repos (BIMpossible #601, Workspace #123,
  AddIns #118, Families #14) after live measurement showed 4/10 symbols
  searched with 0 matches and git probe timeouts at the old values.
- (resolved 2026-09-02) Pushed lane `claude/evidence-compiler-audit-81162b` to
  `origin` and opened PR #6 against `master` for the audit + code-review fixes.
