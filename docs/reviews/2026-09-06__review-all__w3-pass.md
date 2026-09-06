# /review-all — Window 3 improvement pass (v0.2.0 → v0.2.1)

- **Mode:** standard, read-only (profile `.claude/review-profile.yaml`).
- **Fixed point:** `git diff 36e83ac...HEAD` (PRs #9, #10, #11; HEAD `b333bbe`).
  Upstream diff was empty and the working tree clean, so the session's merged
  work is the review scope. 36 files, +2956 / −367.
- **Active lenses:** `code-review` only. `security-diff` is deep-mode only,
  `concurrency` path triggers did not match, `bim-code-review`/`revit-lifecycle`
  disabled by charter. No auto-gate agents declared. With one lens, convergence
  is evidence-check + retention gate; cross-lens dedup did not apply.
- **Evidence check:** findings 1–4 and 9 reproduced against the live tree with
  `PYTHONPATH=src` (outputs recorded inline). Others checked by reading the
  cited lines.
- **Baseline:** 167 tests pass; nothing below is a test failure.

## Retained (ranked)

**1. MEDIUM — Temp-path regex alone flips a human prompt to `harness`**
Location: [scoping.py:107](../../src/evidence_compiler/scoping.py:107)
Raised by: code-review
Why retained: `look at C:\Users\me\AppData\Local\Temp\claude\...\probe.py and fix compute_alpha` → `harness` (reproduced). The maintainer's scratchpad convention puts every session's working files under exactly this path, so real prompts with file references lose all symbols, all ripgrep evidence, and drop out of review sampling.
Action: make the `<...-notification>`-style markers the primary signal; treat the temp path as harness only when it co-occurs with a marker or when no other symbol-shaped token is present.

**2. MEDIUM — `word (` counts as a call and is ranked 95**
Location: [scoping.py:183](../../src/evidence_compiler/scoping.py:183)
Raised by: code-review
Why retained: `compute_alpha fails (Monitor restarts)` → `['fails', 'compute_alpha']` (reproduced). The `\s*\(` in the called-regex admits a prose verb before a parenthetical, and the `called` category bypasses the stopword/shape checks, so noise takes slot 1 and the largest ripgrep budget share.
Action: require `(` adjacent to the identifier, and run the stopword/length checks before granting `called`.

**3. MEDIUM — Sentence-initial rejection is per token, not per occurrence**
Location: [scoping.py:206](../../src/evidence_compiler/scoping.py:206)
Raised by: code-review
Why retained: `Monitor keeps restarting. I think Monitor is the culprit` → `[]` (reproduced). `seen_exact` is filled before the sentence-initial test, so a later mid-sentence occurrence never gets considered.
Action: collect all occurrence positions first; reject only when every occurrence is sentence-initial.

**4. MEDIUM — PascalCase filenames become `dotted` and leak the extension as a symbol**
Location: [scoping.py:310](../../src/evidence_compiler/scoping.py:310)
Raised by: code-review
Why retained: `Fix Program.cs and MainWindow.xaml` → `['Program.cs', 'MainWindow.xaml', 'xaml']` (reproduced). The `path` rule requires a lowercase stem, so the most common filename shape in C#/Revit repos is miscategorised and its extension is searched standalone.
Action: decide `path` on the extension alone; never derive a member from a path token.

**5. MEDIUM — Legacy harness-word heuristic overrides the compiler's `source_kind`**
Location: [review.py:89](../../src/evidence_compiler/review.py:89)
Raised by: code-review
Why retained: `Task.source_kind` defaults to `human`, so v0.2 packets are indistinguishable from pre-v0.2 packets and the word list (`Task`, `Agent`, `Status`, `Summary`, …) reclassifies genuine human prompts as harness, removing them from `sample` and from the `window_due` candidate count.
Action: apply the heuristic only when the on-disk packet lacks `source_kind`; trim the list to path fragments.

**6. LOW — Mixed errors + no-matches summarise as a clean `no_matches`**
Location: [ripgrep.py:233](../../src/evidence_compiler/collectors/ripgrep.py:233)
Raised by: code-review
Why retained: with 2 of 3 symbols in `process_error` and 1 `no_matches`, the else-branch reports `outcome: no_matches` and "no lexical matches for any extracted symbol". Per-symbol counts are right; the one-word outcome the review tool keys on is wrong.
Action: add a partial-error branch or derive `reason` from the counts.

**7. LOW — `dirty_state == "error"` is rendered as "did not answer" and overwrites the head reason**
Location: [git.py:55](../../src/evidence_compiler/collectors/git.py:55), [git.py:101](../../src/evidence_compiler/collectors/git.py:101)
Raised by: code-review
Why retained: a non-zero `git status` (e.g. `index.lock` held) produces `error`, but the claim text says the probe did not answer; when HEAD also timed out its diagnostic reason is replaced. Introduced by PR #10.
Action: branch the statement on `dirty_state`; collect reasons in a list.

**8. LOW — Launch failures after `git_available()` are labelled `probe_timeout`**
Location: [gitprobe.py:105](../../src/evidence_compiler/gitprobe.py:105)
Raised by: code-review
Why retained: `_run` folds `TimeoutExpired`, `FileNotFoundError`, and `OSError` into one `None`, so a `PermissionError` or a deleted cwd reads as "loaded machine" in `head_state`/`dirty_state`.
Action: return a distinguishable result from `_run`; add a `probe_error` state.

**9. LOW — `(` preceded by a space counts as a sentence opener**
Location: [scoping.py:339](../../src/evidence_compiler/scoping.py:339)
Raised by: code-review
Why retained: `compute_alpha fails when (Monitor restarts)` → `Monitor` rejected as `sentence_initial` (reproduced). Parenthetical proper nouns are common in BIM prompts.
Action: drop `(` from the opener set, or honour it only at line start.

**10. LOW — A non-object JSON line in `labels.jsonl` crashes every review subcommand**
Location: [review.py:174](../../src/evidence_compiler/review.py:174)
Raised by: code-review
Why retained: `rec.get(...)` runs without an `isinstance(rec, dict)` guard; `[]` or `null` raises `AttributeError`, which is not caught. Contradicts the module's "unreadable counted, never raised" posture.
Action: skip non-dict records, mirroring `load_window`.

**11. LOW — Vacuous "packets untouched" assertion**
Location: [test_review.py:111](../../tests/unit/test_review.py:111)
Raised by: code-review
Why retained: the loop asserts the storage directory exists seven times and never uses `p`; `start_window` rewriting every packet would pass.
Action: assert each packet file still exists and hash-compare before/after.

**12. LOW — `not_searched` accounting has no test on either producing path**
Location: [test_ripgrep_reliability.py:100](../../tests/unit/test_ripgrep_reliability.py:100)
Raised by: code-review
Why retained: the fake raises synchronously, so `remaining_ms` never drops below the floor and the `+` assertion passes with `not_searched == 0`; the cap-reached block is likewise unexercised.
Action: monkeypatch `time.perf_counter` to consume the deadline after symbol 1 and assert `symbols_not_searched == 1`; add a cap test.

**13. INFO — Identity probe budget is hard-coded and outside `deadline_ms`**
Location: [compiler.py:83](../../src/evidence_compiler/compiler.py:83)
Raised by: code-review
Why retained: a repo that lowers `collectors.git.timeout_ms` still pays up to 1 s before collectors launch, with no packet field showing it.
Action: expose `identity.timeout_ms` and record `stages["identity_ms"]`.

## Not retained

None. Every lens finding carried a precise location and a concrete trigger.

## Disposition

Nothing here is a fail-open, privacy, or invariant breach; the deployed
v0.2.1 stays in the hook environment. Findings 1–5 are evidence-quality
defects in the new ranking layer and belong in the same Phase 1A scope as
the W3 pass; 7–8 are follow-ups to PR #10. Fix work is not started by this
review (read-only). Queue: see WORKLOG *Roadmap*.
