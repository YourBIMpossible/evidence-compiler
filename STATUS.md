# Evidence Compiler — Status

**Last updated:** 2026-08-23
**North Star:** locked and active — see [NORTHSTAR.md](NORTHSTAR.md). The stale `NORTHSTAR.draft.md` (superseded by the lock) has been deleted.

---

## Where we are right now

Phase 1A implementation is complete, independently audited, and the audit's
5 confirmed findings (F-1 through F-5) are fixed and regression-tested. A
full read-only readiness review followed. Verdict:

**CLEAR TO PAUSE AND DOGFOOD AFTER MIGRATION**

No blockers, no highs, no mediums. The mojibake `§` in `evidence --help`
output and a stale `pyproject.toml` Homepage/Documentation URL (pointed at
`evidence-compiler/evidence-compiler` instead of the actual origin,
`YourBIMpossible/evidence-compiler`) were found and fixed 2026-08-23,
alongside a new `docs/quickstart.md` (public-repo walkthrough, linked from
the README) and deletion of the superseded `NORTHSTAR.draft.md`.

Repo is public: https://github.com/YourBIMpossible/evidence-compiler
CI is green on Python 3.10/3.11/3.12 (rg installed in CI).
Local test evidence: `60 passed, 10 skipped` (rg absent) / `70 passed` (rg
available).

## What happens next (the plan)

1. **Pause here.** Do not start v0.2 roadmap work, local-AI integration, or
   any other Phase 1A-adjacent feature. Nothing is blocking a pause.
2. **Wait for BIMpossible's local path to settle.** It may be moving to a
   new location; Evidence Compiler's packet identity binding
   (`repository_root`/`worktree_id`/`head`) means dogfooding against a
   moving target would produce packets that go stale mid-test. Don't
   generate real `.evidence-compiler/` runtime state until the target repo's
   path is final.
3. **After migration, one-time setup:**
   ```bash
   evidence init --repo /path/to/settled/BIMpossible
   ```
   then merge the printed `.claude/settings.json` hook block into
   BIMpossible's own settings by hand (the CLI never writes that file
   itself).
4. **First dogfood prompt** (read-only, no edits):
   > "Why does `<some real function/class in BIMpossible>` behave the way
   > it does, and what else references it?"
5. **Inspect the result:**
   ```bash
   evidence replay .evidence-compiler/packets/<latest-file>.json
   ```
6. **Success bar for that first run:** the injected brief cites at least one
   real, correct `file:line` reference you recognize as relevant, collector
   statuses show `ok` (not universal skip/error), and the Claude Code
   session wasn't perceptibly slowed or blocked.

Do not carry forward any packet captured against BIMpossible's old path —
`evidence replay` will warn (`WARNING: packet was captured for repository
...`) if one is replayed from the wrong cwd, but the right move is simply
not persisting/copying old-path packets forward at all.

## What's deliberately NOT in scope right now

Confirmed absent from the codebase as of this review (see full audit below
for the checks run): verification hooks/hard-Stop/change contracts, a
resident daemon, local-AI/Ollama in the critical path, LLM-based ranking or
autonomous loops, GPU/vector-DB/embeddings/RAG/MCP server, a second agent
adapter, and any BIMpossible/Revit/APS-specific logic in core. These stay
out unless the now-locked [NORTHSTAR.md](NORTHSTAR.md) is explicitly
revised or a separately approved phase proposal authorizes them — not
implicitly, not "while we're in there."

Local-AI is **partly ready** to add later in the correct form (opt-in,
outside the critical path, `INFERRED`-authority, never satisfies
verification) — the collector interface and the `authority`/`confidence`
split in the packet schema are already the right extension points. The one
gap: `authority: inferred` currently means "compiler-inferred," not
"model-inferred" — that naming will need to be disambiguated before any
local-AI work starts, not now.

## Full detailed review

The complete requirement-by-requirement audit table, deferred-capability
confirmation table, repo hygiene check, and findings list are preserved
below, generated 2026-08-22 by a read-only pass over `CLAUDE.md`,
`BUILD_BRIEF.md`, all `docs/` specs, git history, CI, and local test/CLI
runs.

---

# Evidence Compiler — Phase 1A Readiness Review

Read-only. No files modified, no commits, no pushes, no installs.

# Verdict

**CLEAR TO PAUSE AND DOGFOOD AFTER MIGRATION**

# Phase 1A compliance

| Requirement | Status | Evidence inspected |
|---|---|---|
| Core is agent/model/provider agnostic | PASS | `grep -rniE "anthropic\|openai\|ollama"` over `src/` → no matches; only `integrations/claude_code.py` names Claude, and it's an adapter, not core |
| Claude Code Desktop is the only first-party adapter | PASS | `src/evidence_compiler/integrations/` contains only `claude_code.py` |
| No BIMpossible/Revit/APS/Autodesk dependency in core | PASS | `grep -rniE "bimpossible\|revit\|autodesk\| aps "` over `src/` → no matches |
| Collectors collect, compiler ranks | PASS | `collectors/git.py`, `collectors/ripgrep.py` never set `selected`/`final_score`; `ranking.py:_select_under_budget` is the sole writer |
| Git/ripgrep collectors degrade explicitly | PASS | contract tests `test_git_skipped_outside_repo`, `test_rg_skipped_when_binary_missing`, `test_rg_timeout_does_not_crash`; per-symbol `OSError` isolation added this session ([ripgrep.py](src/evidence_compiler/collectors/ripgrep.py)) |
| Graphify remains stub-only | PASS | [graphify.py](src/evidence_compiler/collectors/graphify.py) unconditionally returns `status: skipped`, `reason: "not implemented"` |
| EvidencePacket/ContextBrief remain distinct | PASS | packet is source-of-truth persisted JSON; `render_brief()` is pure ([rendering.py](src/evidence_compiler/rendering.py)); F-1 fix this session made packet mutation happen only pre-finalization, never after |
| Provenance/authority/freshness/identity/isolation preserved | PASS | `EvidencePacket.identity` carries `repository_root`/`worktree_id`/`head`; every `EvidenceItem` carries `source_claim` + `compiler_assessment` as distinct layers (verified in [evidence-packet-v1.md](docs/specifications/evidence-packet-v1.md) §2 against `packet.py`) |
| Ranking deterministic, no LLM in critical path | PASS | `ranking.py` header states "No ML, no LLM, no clock, no hidden state"; `grep` for model/http/requests calls in `ranking.py` → none |
| Claude Code adapter is fail-open | PASS | `main()` wraps everything in `try/except Exception → return 0`; watchdog thread enforces end-to-end deadline independent of per-collector timeouts ([claude_code.py](src/evidence_compiler/integrations/claude_code.py)); `tests/test_adapter_failopen.py` exists |
| Replay warns on identity mismatch | PASS | F-2 fix this session: `_identity_mismatch()` in [cli.py](src/evidence_compiler/cli.py:146); verified live via CLI smoke test (WARNING printed from mismatched cwd, silent from matching cwd) |
| Runtime packets/logs/caches gitignored | PASS | `.gitignore` covers `.evidence-compiler/packets/`, `.evidence-compiler/logs/`, `__pycache__/`, `*.egg-info/`; `git ls-files \| grep -iE "pycache\|egg-info\|\.evidence-compiler\|packets\|secret"` → none tracked |
| CI passing, rg-absent and rg-available coverage | PASS | rg-absent: `python -m pytest` → `60 passed, 10 skipped`; rg-available: `70 passed`; CI workflow ([tests.yml](.github/workflows/tests.yml)) runs on Ubuntu with `rg` installed across Python 3.10/3.11/3.12; latest run green |

# Deferred work confirmation

| Deferred capability | Confirmed absent? | Notes |
|---|---|---|
| Verification hooks / hard Stop / change contracts / validation ledger | YES | `grep -rniE "verification\|hard.?stop\|change.?contract"` over `src/` → no matching code, only a docstring reference to "never satisfies verification" (a negative constraint, not an implementation) |
| Resident daemon / background graph watcher / AST daemon | YES | Only hits for "daemon" are `threading.Thread(..., daemon=True)` — Python daemon *threads* for bounding collector calls, not a resident background process |
| Local Ollama/Qwen/local-model worker in critical path | YES | No such dependency anywhere in `src/` or `pyproject.toml` |
| LLM-based routing/semantic ranking/autonomous tool loops/policy mutation | YES | `ranking.py` is pure component-score arithmetic; no autonomous loop code exists |
| GPU / vector DB / embeddings / RAG / MCP server | YES | No such dependency in `pyproject.toml` (only `PyYAML`, `pytest` for dev) or `src/` |
| Second agent adapter / plugin marketplace / IDE extension / HTTP service / extra CI-PR integration | YES | `integrations/` has one adapter; CI workflow is exactly the `tests.yml` test matrix, nothing else |
| BIMpossible/Revit/APS-specific logic or policy in core | YES | confirmed above under compliance table |

# Public-repository hygiene

- **Git status:** clean, `master` up to date with `origin/master`, nothing uncommitted.
- **Runtime artifacts:** `.evidence-compiler/packets/` and `.evidence-compiler/logs/` are gitignored and confirmed untracked; `__pycache__/` and `*.egg-info/` present locally (build byproducts of this session's test runs) but also gitignored and untracked.
- **No local paths, secrets, or BIMpossible/private info tracked** — file listing (`git ls-files`) is exclusively `docs/`, `src/`, `tests/`, `templates/`, config, and license/readme files; no `.env`, credentials, or absolute local paths committed.
- **CI/test status:** latest two workflow runs (`de1e0fc`, `9856d23`) both green on all three Python matrix legs; local re-run this turn confirms `60 passed/10 skipped` (rg absent) and `70 passed` (rg available) — consistent with CI's rg-installed environment.

# Local-AI future readiness

**Partly ready.**

Rationale:
- `EvidenceItem.authority` already has an enum (`authoritative | convention | inferred`) and `confidence` is already tracked as a field orthogonal to authority/freshness (per [evidence-packet-v1.md](docs/specifications/evidence-packet-v1.md) §2, §7) — this is the right shape to add an `inferred` (or future `INFERRED`-cased) local-AI-sourced claim without a schema break.
- Collectors are already a pluggable interface with mandatory provenance, timeout, and fail-open contract tests (`04-collector-interface-v1.md` §7) — a future local-AI collector could reuse this boundary and inherit the same "must not block the critical path" guarantee for free.
- Ranking is already a pure function with no model/network calls, so adding a local-AI-sourced item does not require ranking to change — it would simply be scored like any other authority-tagged item.

What's missing (not a defect — just not yet specified, since Phase 1A intentionally has no local-AI scope):
- No documented contract yet for the specific fields a local-AI-derived claim must carry (`model`, `model_version`, `input_hash`, `timestamp`, source claim IDs it was derived from). `authority: inferred` exists but doesn't yet distinguish "human/deterministic-tool inferred" from "model-inferred."
- No documented rule yet that an `authority: inferred`-from-model item is permanently ineligible to satisfy verification (verification itself doesn't exist yet in Phase 1A, so this is naturally deferred, not missing).

Smallest future contract addition (do not implement now):
- Add an optional `provenance.model` sub-object (`name`, `version`, `input_hash`, `generated_at`) to `EvidenceItem.provenance`, and reserve a new `authority` value (e.g. `model_inferred`) distinct from the existing `inferred` (which today means "compiler inferred from context," not "LLM inferred"). This is a strictly additive schema change — no existing consumer needs to change to tolerate the new optional field/enum value.

# Findings

**BLOCKER:** none.

**HIGH:** none.

**MEDIUM:** none.

**LOW:** none outstanding.
- ~~The CLI help text has a mojibake artifact (`build brief §8`) in `evidence --help` output~~ — fixed 2026-08-23: `§` replaced with `section` in the [cli.py](src/evidence_compiler/cli.py:6) docstring.
- ~~`pyproject.toml` `Homepage`/`Documentation` URLs pointed at `evidence-compiler/evidence-compiler`, not the actual origin~~ — fixed 2026-08-23: both now point at `YourBIMpossible/evidence-compiler`, matching `git remote -v` and the README badge.

**Informational:**
- `authority: inferred` in the current schema means "compiler-inferred from context," not "LLM/model-inferred." When local-AI work is eventually scoped, this naming will need disambiguation (see Local-AI future readiness) — not an action item now, just a naming collision to be aware of before that work starts.
- `__pycache__/` and `*.egg-info/` directories exist locally from this session's test/install activity; correctly gitignored and untracked, no action needed, noted only for completeness of the hygiene check.
