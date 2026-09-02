# Evidence Compiler — Worklog

Routing per `NORTHSTAR.md`: small-and-on-mission → Done; worth-doing branch-off
→ Roadmap; would-change-the-mission → Needs your call.

## Roadmap / queued

- Pre-existing ruff `F401` in `tests/contract/test_collector_contract.py:18`
  (`RawClaim` imported but unused). Out of scope for the 2026-09-01 incremental
  audit — the file was not modified this session. One-line fix: drop the unused
  import (auto-fixable with `ruff check --fix`).

## Needs your call

- (resolved 2026-09-02) Pushed lane `claude/evidence-compiler-audit-81162b` to
  `origin` and opened PR #6 against `master` for the audit + code-review fixes.
