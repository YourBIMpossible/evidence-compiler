# Evidence Compiler — Audit Report

**Date:** 2026-09-01
**Type:** incremental
**Scope:** commits since `STATUS.md`'s last-reviewed cutoff (2026-08-23) — i.e.
everything on `master`/this branch dated 2026-08-24:

| Commit | Subject |
|---|---|
| `0f2346d` | Fix F-D1: canonicalize evidence order by content, not collector arrival order |
| `23edd5a` | Phase 1B: compound-symbol extraction (`User-Agent`, `Response.iter_content`) |
| `4d615f8` | Single-source the package version from `evidence_compiler.__version__` |
| `874bd7f` | Add `evidence hook-safe`: hardened fail-open hook launcher with bounded retention |

Persona/method: exacting code review — every design decision questioned,
untested behavior treated as broken until proven otherwise, `file:line`
citations throughout. Anti-slop checklist applied: silent-catch census,
counter-integrity, tested-but-dead.

**Verdict: no BLOCKER or HIGH findings.** One MEDIUM (untested false-positive
gap in symbol extraction), one MEDIUM (architectural — duplicated hook
adapters with diverging safety guarantees), remainder LOW/informational.

---

## Findings

### M1 — Title-Case prose hyphenations are admitted as symbols unconditionally

**`src/evidence_compiler/scoping.py:96-103`**

```python
if "-" in token:
    _admit(token)
    _admit(token.lower().replace("-", "_"))
else:
    if not _is_symbolish(token, called, backticked):
        continue
    _admit(token)
    ...
```

The hyphenated-compound branch admits unconditionally — no call to
`_is_symbolish()`. The `else` branch (plain tokens) is gated by that prose
guard; this one isn't.

The regex that feeds this branch (`_COMPOUND_PART = r"[A-Z][A-Za-z0-9]*"`,
requiring **every** hyphen-joined component to start uppercase) does correctly
exclude ordinary sentence-case prose — `"fail-open"`, `"well-known"` never
reach this branch, and `test_lowercase_hyphen_prose_not_treated_as_compound`
(`tests/unit/test_compound_symbols.py:67`) locks that.

But it does not exclude **Title-Case** prose phrases, which are entirely
plausible in a debugging prompt: `"Off-By-One"`, `"Out-Of-Bounds"`,
`"Copy-On-Write"`. Every component is capitalized, so `_TOKEN_RE` matches the
whole phrase and it is admitted as a symbol candidate — plus its
`lower().replace("-", "_")` derivative — unconditionally. Each such
false-positive:

- burns one of the `_MAX_SYMBOLS = 12` slots (`scoping.py:53`), potentially
  displacing a real symbol on a prompt with several capitalized phrases,
- and downstream, becomes a real ripgrep query for a term that's near-certain
  to only exist in prose/comments (`ripgrep.py`), the exact "generic-flood"
  failure mode this same commit's docstring (`scoping.py:30-34`) says Phase 1B
  was built to eliminate for hyphenated fragments.

**Untested.** I read `tests/unit/test_compound_symbols.py` in full (215
lines) — it has strong coverage of the intended behaviors (`User-Agent` →
`user_agent`, dotted-member derivation, determinism, end-to-end acceptance)
but no test exercises a Title-Case prose hyphenation. This is exactly the
kind of input the module's own docstring anticipates guarding against for
every other token shape, and doesn't for this one.

**Fix:** apply `_is_symbolish`-equivalent screening to the compound branch
too — e.g. require at least one component to look identifier-ish (mixed
case, digits, or backticked/called-adjacent) rather than admitting on hyphen
+ capitalization alone. Add a test alongside
`test_lowercase_hyphen_prose_not_treated_as_compound` for the Title-Case
case.

---

### M2 — Two live hook adapters with diverging safety guarantees, no deprecation path

**`src/evidence_compiler/integrations/hook_safe.py`** (new, 245 lines) vs.
**`src/evidence_compiler/integrations/claude_code.py`** (pre-existing, 182
lines)

`hook_safe.py` is a near-total reimplementation of `claude_code.py`'s job —
same threading/watchdog pattern (daemon thread + `result_box` dict +
`worker.join(timeout=...)`), same disable-env-var contract, same overall
shape — but with materially different safety guarantees:

| | `claude_code.py` | `hook_safe.py` |
|---|---|---|
| stdin/stdout | text mode (`sys.stdin.read()`, `json.dumps(...)` via `sys.stdout.write`) | byte-exact (`sys.stdin.buffer`, `sys.stdout.buffer.write`), validated round-trip before write (`hook_safe.py:212-230`) |
| error logging | `"compiler error:\n" + traceback.format_exc()` written to `.evidence-compiler/logs/hook.log` | exception **class name only** (`hook_safe.py:172`, `183`) — `test_compiler_exception_logs_class_name_only` (`tests/unit/test_hook_safe.py:164`) pins this |
| storage-dir escape check | not reviewed in this pass (out of this window's diff) | `os.path.realpath` + `normcase` + prefix containment (`hook_safe.py:111-124`), covered by 3 parametrized traversal cases + a symlink/junction escape test |
| packet retention | none | bounded, config-driven (`hook_safe.py:233-240`) |

Both are fully wired and shipped: `cli.py` registers both `hook` and
`hook-safe` subcommands; `templates/claude-settings.json` now points at
`hook-safe`; README and `docs/quickstart.md` call `hook-safe` "the
recommended hook command." Nothing marks `hook` / `claude_code.py` as
deprecated — no docstring note, no README callout, no runtime warning.

I checked whether the `claude_code.py` traceback-to-log behavior is a live
prompt-leakage risk right now: grepped `src/` for f-strings that embed
`prompt`/`statement`/text into raised exceptions — none found; the prompt
flows into `scoping.build_task` and is stored as data, never interpolated
into an exception message. So today this is latent, not demonstrated. But
that's exactly the kind of thing that regresses silently the next time
someone adds an f-string exception message anywhere on that call path,
precisely because there's no single hardened implementation both entry
points funnel through.

**This is a DRY violation with a real blast radius**, not a style nit: any
future fix to the adapter contract (redaction policy, timeout handling,
storage safety) now has to be remembered and ported to two places, and the
weaker of the two is still the one wired into any pre-existing
`claude-settings.json` a user set up before `hook-safe` existed.

**Fix:** either (a) make `claude_code.py` a thin compatibility shim that
delegates to `hook_safe`'s implementation, or (b) mark `hook`/`claude_code.py`
deprecated in its docstring + README with a stated removal version. Don't
leave two independently-maintained copies of a security-relevant code path.

---

### L1 — `_ref_sort_key` doesn't handle absolute Windows-drive-letter references, and the codebase's own sibling utility documents that case as reachable

**`src/evidence_compiler/packet.py:171-183`**

```python
def _ref_sort_key(ref: str) -> tuple[str, int]:
    norm = ref.replace("\\", "/")
    path, sep, line = norm.partition(":")
    if sep:
        try:
            return (path, int(line))
        except ValueError:
            return (path, -1)
    return (norm, -1)
```

`partition(":")` splits on the **first** colon. For a normal repo-relative
reference (`"src/alpha.py:12"`) that's correct. For an absolute Windows path
with a drive letter (`"C:/foo/bar.py:10"`), it isn't: `path` becomes `"C"`,
`line` becomes `"/foo/bar.py:10"`, `int(line)` raises, and the function
degrades to `("C", -1)` — collapsing every reference on the same drive to an
identical, useless sort key and defeating the whole point of
`canonical_item_key` (this commit's own fix for order-dependence, F-D1).

I checked whether this is reachable through the two shipped collectors.
Both `ripgrep.py:195` and `git.py:55,60` route every reference through
`normalize_reference` → `normalize_path`
(`src/evidence_compiler/collectors/base.py:128-153`), whose docstring states:
"Paths outside the repo are returned POSIX-normalized but **absolute**" and
whose code explicitly handles "different drive on Windows; fall through to
absolute form" (`base.py:149-151`). In today's normal flow (rg/git invoked
with `cwd=repository_root`, matches on the same drive as the repo) neither
collector actually emits an absolute cross-drive path, so this isn't
currently triggered in practice. But `normalize_path` was written to
anticipate exactly that input, on a project explicitly targeting a Windows
+ Revit/APS environment (per `CLAUDE.md`) — this isn't a hypothetical
platform mismatch, it's the primary platform. Anything that produces an
absolute reference outside the repo root (a future collector, a symlinked
worktree that resolves to a different drive, a misconfigured
`repository_root`) will silently degrade ranking determinism rather than
error.

**Untested.** Grepped `tests/` for `_ref_sort_key`/`canonical_item_key` — no
direct unit test exists for either function; the only coverage is indirect,
through the determinism regression suite (`tests/unit/test_determinism.py`),
none of whose fixtures use absolute or drive-letter references.

**Fix:** partition on the **last** `:` that's followed by an all-digit
suffix (mirroring the `_LINE_SUFFIX` regex approach already used in
`collectors/base.py`), or reuse that same regex here instead of a bespoke
`partition(":")`. Add a direct unit test for `_ref_sort_key` covering a
Windows absolute path.

---

### L2 — commit message overstates the ripgrep match-mode change's scope

**`src/evidence_compiler/collectors/ripgrep.py`** (line ~in the query-building
function)

```python
match_args = ["--fixed-strings"] if "_" in symbol else ["--word-regexp", "--fixed-strings"]
```

The commit describes this as scoped to "compound-derived candidates," but
the collector only ever receives flat symbol strings — there is no
compound/plain flag threaded through from `scoping.py`. In practice this
changes match semantics for **every** underscore-containing symbol reaching
ripgrep, whether it came from compound derivation (`user_agent`) or was
typed verbatim by the user in the prompt (any ordinary `snake_case`
identifier). That's a broader behavior change than the commit message
states — plain snake_case symbols now get substring matching
(`--fixed-strings` without `--word-regexp`) instead of whole-word matching,
so a query for `run` embedded in `dry_run` would now match inside
`dry_run_mode` too.

Tempered by `_MAX_MATCHES_PER_SYMBOL = 25` / `_MAX_TOTAL_MATCHES = 100` caps
and downstream relevance-based ranking, so this isn't a correctness bug —
just a scope overstatement worth correcting in the commit record /
`06-roadmap.md` if this behavior is referenced there later.

---

### L3 (informational) — version guard test silently no-ops in the common local dev path

**`tests/unit/test_version.py`**

```python
def test_distribution_version_matches_package_constant() -> None:
    try:
        dist_version = importlib.metadata.version("evidence-compiler")
    except importlib.metadata.PackageNotFoundError:
        return
    assert dist_version == evidence_compiler.__version__
```

Per this project's own memory note, local worktree dev runs use
`PYTHONPATH=src python -m pytest` — no install, so
`importlib.metadata.version("evidence-compiler")` raises
`PackageNotFoundError` and the test silently `return`s without asserting
anything. I checked `.github/workflows/tests.yml`: CI does
`pip install -e ".[dev]"` before running pytest, so the real assertion **does**
fire in CI — this doesn't let a version-drift bug ship silently, just means
the test is a no-op for anyone running it locally without an install.

**Fix (optional, cosmetic):** `pytest.skip(...)` instead of a bare `return`,
so a local run reports "skipped" rather than "passed" for a check that
didn't check anything.

---

### L4 (minor nit) — `_read_stdin_bytes` failure is silently relabeled as "empty input"

**`src/evidence_compiler/integrations/hook_safe.py:84-91`**

```python
def _read_stdin_bytes() -> bytes:
    try:
        buf = getattr(sys.stdin, "buffer", None)
        if buf is not None:
            return buf.read()
        return sys.stdin.read().encode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return b""
```

An actual I/O error reading stdin (not just "stdin was empty") returns
`b""`, which `_parse_payload` then logs as category `"empty_input"`
(`hook_safe.py:98`). This is justified-and-logged in the sense that fail-open
behavior is correct and *something* is logged — but it's a real
diagnostic-fidelity loss: a genuine read failure and a genuinely empty
invocation become indistinguishable in `hook.log`, which matters if someone
is ever debugging why the hook silently produced no context on a real
prompt.

**Fix (optional):** log a distinct category (e.g. `"stdin_read_error"`) from
inside this function's `except` before returning `b""`, rather than letting
it masquerade as the empty-input path.

---

## Anti-slop checklist

**Silent-catch census** (all four commits' new/changed `except` sites):

| Site | Classification | Note |
|---|---|---|
| `hook_safe.py:42-46` (`main`'s outer catch) | justified-and-logged | delegates to `_diag`; inner catch around `_diag` itself is justified-but-silent (avoids recursive logging failure) |
| `hook_safe.py:80-81` (`_diag`'s own catch) | justified-but-silent | logging must never crash the hook; correct |
| `hook_safe.py:90-91` (`_read_stdin_bytes`) | justified-but-mislabeled | see **L4** — logged, but under the wrong category |
| `hook_safe.py:171-172` (`work()` compiler exception) | justified-and-logged | class-name only, verified by `test_compiler_exception_logs_class_name_only` |
| `hook_safe.py:205-207` (stdout write failure) | justified-and-logged | correct; can't do more once the pipe is broken |
| `hook_safe.py:229-230` (`_validated_output_bytes`) | justified-and-logged | caller logs `malformed_output` |
| `hook_safe.py:239-240` (`_apply_retention`) | justified-and-logged | class-name only, verified by `test_retention_failure_does_not_suppress_injection` |
| `storage.py:64-68` (`prune_packets` per-file `os.unlink`) | justified-but-silent | acceptable: retention is best-effort by design, one file's `OSError` (e.g. concurrent delete) shouldn't abort the rest of the batch; no counter to falsify since the function's own return value (`deleted`) already reflects only successful deletes |
| `config.py:101-102` (`load_config` YAML parse) | justified-and-... not logged | pre-existing pattern (not part of this window's diff), returns silent defaults per its own docstring contract ("a missing, empty, or malformed config file never breaks the compiler") — consistent with invariant 5, flagging only as a note that a malformed config is currently undiagnosable by the user with zero log trace |

No site swallows a failure that should have propagated; the one real finding
here is L4 (fidelity, not correctness).

**Counter-integrity:** `prune_packets`' `deleted` counter only increments
inside the `try` block after a successful `os.unlink` (`storage.py:64-68`) —
a failed delete correctly does not inflate the count. `hook_safe.py` has no
aggregate "N succeeded" counters; every path is a single pass/fail outcome,
so this check doesn't apply beyond what's already covered above.

**Tested-but-dead:** Read `tests/unit/test_retention.py` (108 lines) and
`tests/unit/test_hook_safe.py` (268 lines) in full. Both genuinely exercise
shipped code, not just the surface:

- `test_retention.py` covers oldest-first pruning, at/under-limit no-op,
  zero/negative disables retention, missing-directory no-op, non-packet
  files/directories never touched, symlinked *and* junction-based escape
  attempts neither followed nor deleted (with a real platform-appropriate
  fallback, not a stub), and non-recursion into subdirectories.
- `test_hook_safe.py` covers both disable env vars, empty/malformed/non-object
  stdin, empty-prompt no-op, successful injection, a 120k-multibyte-char
  byte-exact roundtrip past the 64 KiB pipe-chunk boundary, an unencodable
  (lone-surrogate) brief correctly failing validation and emitting nothing,
  compiler-exception redaction (asserts the literal secret string is absent
  from the log line, not just that *some* line exists), timeout, three
  parametrized storage-dir traversal attempts plus a symlink/junction escape,
  a safe custom storage dir still injecting, and retention failure not
  suppressing a valid injection.

I did not find a claimed-but-unexercised behavior in either file. This is
the strongest-tested commit of the four.

`tests/unit/test_determinism.py` (152 lines, commit `0f2346d`) and
`tests/unit/test_compound_symbols.py` (215 lines, commit `23edd5a`) were
likewise read in full — both test what they claim to, with the one gap
being **M1** (untested input shape, not a dead test).

---

## Commit-by-commit verdict

- **`0f2346d`** (determinism fix) — solid, well-tested fix for a real bug
  class (F-D1). One real latent gap: **L1**.
- **`23edd5a`** (compound symbols) — correctly solves the dogfood flood
  problem it targets. One real gap in the new code path: **M1**. One
  commit-message-accuracy nit: **L2**.
- **`4d615f8`** (version single-source) — clean; **L3** is cosmetic only.
- **`874bd7f`** (hook-safe launcher) — the strongest-engineered and
  best-tested of the four (byte-exact I/O, validated output round-trip,
  correct symlink-safe containment checks, fail-open threading pattern,
  verified chronological-sort-via-ISO8601-lexicographic-order retention).
  Its one real issue is architectural, not local: **M2**. Minor: **L4**.

No finding in this window rises to BLOCKER or HIGH. M1 and M2 are worth
fixing before the next dogfood round — M1 because it's a direct regression
risk against the exact failure mode Phase 1B was built to close, M2 because
every day both adapters ship is another day the weaker one can regress
unnoticed.
