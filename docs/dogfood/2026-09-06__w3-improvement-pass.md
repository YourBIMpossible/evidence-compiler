# 2026-09-06 — Window 3 improvement pass (anchor doc)

Mandate: take Evidence Compiler from "operational but unproven" to a fair,
measurable, higher-quality dogfood state in one continuous pass. Lane branch
`claude/w3-evidence-quality` off `master@36e83ac`.

## Findings that drove the changes (Window 2 corpus, 343 packets)

| Signal | Corpus | Root cause (verified) |
|---|---|---|
| ripgrep `error` 119× (35 %) | reproduced on `36e83ac` | `subprocess.run(text=True)` without `encoding=` decodes rg stdout as cp1252 on Windows; a non-cp1252 byte kills the reader thread, `proc.stdout` is `None`, `_parse_rg_json` raises `AttributeError`. Same command with `encoding="utf-8"` returns 478 KB in 63 ms. |
| ripgrep `timeout` 53× (15 %) | 31 at the 12-symbol cap, 8 single-symbol | 12-symbol case: 100 ms floor × 12 > 500 ms budget, symbols 6–12 never ran. Single-symbol case: rg took 510–614 ms while git/scoping were also 2–3× slower than median — machine-wide contention, not a pattern or cwd problem (standalone rg ≈ 55 ms). |
| `identity.head: null` 15× | all with `scope_ms` 387–543 (median 240) | `gitprobe.probe` per-call budget = `max(250 // 4, 50)` = 62 ms; `rev-parse HEAD` timed out under load. Not a detached HEAD. |
| harness notifications compiled as prompts 77× (22 %) | `<task-notification>` text | Claude Code fires `UserPromptSubmit` for background-task notifications; path fragments (`Users`, `AppData`, `Temp`) became symbols. |
| common-word symbols (S10/S15/S17/S21/S22) | `There`, `Before`, `Check`, repo self-name, tool names | `_is_symbolish` admits any Capitalized word; no ranking, no cap-aware selection. |
| absolute `rg.EXE` path in `provenance.command` | every lexical item | `command=" ".join(cmd)` with `shutil.which` result. |

## Phases

1. **Anchor + branch** — this doc; lane branch. ✔
2. **Collector reliability** (`ripgrep.py`, `gitprobe.py`, `git.py`) — UTF-8
   decode, None-stdout guard, per-symbol outcome categories, dynamic
   per-symbol budget, unsearched-symbol accounting, `rg` basename in
   provenance, deadline-shared git probe with `head_state`.
3. **Symbol quality** (`scoping.py`, `config.py`, `packet.py`) — categorized,
   ranked, bounded selection with explainable `task.symbol_details`;
   harness/human `task.source_kind`; repo self-name and per-repo
   `scoping.ignore_symbols` rejection. Compound behaviour (Phase 1B) untouched.
4. **Review workflow** (`review.py`, `cli.py`) — `evidence review
   inventory|sample|label|status|window`. Local-only artifacts under
   `.evidence-compiler/logs/review/` (already git-ignored downstream).
5. **Tests + docs + version** — regression tests per workstream; `docs/dogfood-review.md`;
   README/quickstart; spec 1.x-additions note; `0.1.0 → 0.2.0`.
6. **Ship** — separate code and WORKLOG commits; push; PR; merge; non-editable
   install into the live hook interpreter; smoke tests; Window 3 start.

## Fenced decisions

| Decision | Rationale |
|---|---|
| Collector status precedence stays `timeout > ok > empty`, with `error` only when every searched symbol failed | Keeps contract tests and downstream semantics; counts in the diagnostic give the finer picture. |
| Sentence-initial bare Capitalized words are rejected, mid-sentence ones ranked lowest | S21/S22 noise was sentence-initial and was the *only* symbol, so ranking alone could not help. |
| Compound + derived snake pair exempt from normalized dedupe | Phase 1B contract: both searched (word vs substring). |
| Core default ripgrep timeout raised 500 → 1500 ms | 8 single-symbol timeouts sat at 510–614 ms; 25 s ceiling leaves ample room. Downstream configs pin 500 and are not edited by this pass. |
| Identity git probe gets its own 1000 ms budget, shared across calls | Identity binding is worth more than 250 ms; per-call floor 100 ms. |
| Harness prompts still produce a packet (no symbols, no rg) | Keeps the hook path uniform and the packet stream auditable; the review tool classifies them out. |
| Review artifacts under `logs/review/` not a new top-level dir | Downstream `.gitignore` only covers `packets/` and `logs/`; downstream edits are out of scope. |
| `EC-RG-CAP-DET` frozen; Phase 1B not reopened | Per mandate. |

## Post-deploy follow-up (same day)

`test_determinism` flaked 1-in-15 under the hook interpreter. Probe: one
compile lost the `dirty: src/beta.py` line while git/rg statuses were all
nominal — the git collector's 250 ms budget across six git calls starved
`git status`, and a status timeout returned an empty overlay with no trace.
Fixed in PR #10 (merge `ab6dc90`, v0.2.1): `GitInfo.dirty_state`
(`resolved | probe_timeout | error`) surfaced in the `git_meta` claim and the
collector diagnostic; default git budget 600 ms. Installed in the hook
interpreter; smoke and Window 3 start ran against this revision.

| Decision | Rationale |
|---|---|
| Unknown dirty overlay is reported, never rendered as clean | Invariant 4: absence of evidence under timeout is not evidence of a clean tree. |
| Default git budget 250 → 600 ms, not a status-first reorder | Six calls × 100 ms floor must fit; ordering keeps HEAD (identity) ahead of the overlay. Downstream configs pin 250 and are not edited by this pass. |
| Non-ASCII identifier tokenisation left as a Window 3 watch item | Observed once in a synthetic probe (`größe`); no corpus recurrence yet. |
