# Collector Interface v1 — Specification

**Status:** Frozen for Phase 1A plugin boundary  
**Last updated:** 2026-08-21

---

## 1. Purpose

A **Collector** is a replaceable evidence source. The compiler must not embed collector-specific control flow beyond registration and timeout.

```text
Collector.collect(context) → EvidenceResult
```

Minimum viable install: **Git + ripgrep** (and filesystem).  
**Graphify is optional.** LSP and others are optional.

---

## 2. Context input (logical)

```yaml
context:
  repository_root: string
  worktree_id: string | null
  cwd: string
  prompt_text: string
  prompt_hash: string
  active_file: string | null
  extracted_symbols: [string]
  dirty_paths: [string]
  head: string | null
  timeout_ms: number              # hard deadline for this collector
  config: object                  # collector-specific config slice
```

---

## 3. EvidenceResult (logical)

```yaml
collector: string                 # stable name, e.g. "graphify"
status: ok | empty | timeout | error | skipped
duration_ms: number

items:                            # zero or more source claims
  - kind: string
    statement: string
    references: [string]
    authority: authoritative | convention | inferred
    freshness: current | dirty_overlay | stale | unknown
    confidence: number
    provenance:
      command: string | null
      source_revision: string | null
      graph_hash: string | null
      extra: object

negative_items: []                # optional absences

diagnostic: object                # required on empty/timeout/error when possible
error_message: string | null
```

Collectors **do not** set `selected`, `final_score`, or `selected_because`. That is compiler judgment.

---

## 4. Behavioral contract

| Requirement | Rule |
|-------------|------|
| Timeout | Honor `timeout_ms`; return `status: timeout` with partial items optional |
| Failure isolation | Exceptions → `status: error`; never crash the compiler process |
| Empty | `status: empty` + diagnostic (not silent zero with `ok`) |
| Provenance | Every item carries collector name + capture metadata |
| Paths | Normalize to repo-relative POSIX-style where possible; accept Windows inputs |
| No task policy | Collectors must not implement project validation policy |
| Idempotence | Same context should produce stable statements (ordering may vary) |

---

## 5. Built-in collectors (Phase 1A)

| Name | Required? | Role |
|------|-----------|------|
| `git` | Yes (if git repo) | HEAD, branch, dirty paths, basic meta |
| `ripgrep` | Yes if binary present | Exact symbol defs/refs |
| `graphify` | No | Structural graph query/path/explain |

Skipped if binary missing or `enabled: false` in config → `status: skipped`.

---

## 6. Graphify-specific diagnostics (when enabled)

On empty/timeout, prefer:

```yaml
diagnostic:
  index_current: true | false | unknown
  symbol_found_in_text: true | false
  graph_node_found: true | false
  language_supported: true | false | unknown
```

Optional **conditional** fallback is compiler/collector policy, not a hard multi-run always:

```text
graphify query → (empty?) explain/path → else rely on rg lane
```

---

## 7. Contract test suite (required direction)

Every collector implementation SHOULD pass tests for:

- timeout behavior  
- malformed/empty output handling  
- provenance present on items  
- authority/freshness populated  
- path normalization  
- Windows path inputs (where CI allows)  
- failure isolation (no uncaught throw to compiler)  
- duplicate-heavy input does not explode  

Golden-repo integration tests assert end-to-end packet shape, not only unit mocks.

---

## 8. Config slice example

```yaml
collectors:
  git:
    enabled: true
    timeout_ms: 250
  ripgrep:
    enabled: true
    timeout_ms: 500
    extra_args: []
  graphify:
    enabled: true
    timeout_ms: 1250
```
