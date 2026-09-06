# Dogfood review — a fair, local way to answer "did the brief help?"

The hook is only worth running if the injected brief is useful more often
than it is noise. This document explains the four things that are easy to
conflate when judging that, the packet fields that let you tell them apart,
and the `evidence review` workflow that turns persisted packets into a
labeled, durable record.

## 1. Four separate questions

| Question | Where the answer lives | What it is *not* |
|---|---|---|
| **Safety** — can the hook ever block or break the agent? | `evidence hook-safe` contract: fail-open, exit 0, inject nothing on error, `logs/hook.log` categories | A measure of usefulness. A hook that injects nothing every time is perfectly safe. |
| **Coverage** — did the collectors run and finish? | `collectors_run[].status` (`ok/empty/timeout/error/skipped`) and the per-collector `diagnostic` | Evidence that the injected text was relevant. |
| **Usefulness** — did the brief help the task? | Reviewer labels in `logs/review/labels.jsonl` | Something the compiler can score itself. Only a person reading the packet against the task can say. |
| **Retention / artifacts** — what is kept, for how long, and where? | `retention.max_packets`, `.evidence-compiler/packets/`, `.evidence-compiler/logs/` | Shared state. Everything under `.evidence-compiler/` is local and gitignored. |

`evidence review status` prints operational health (coverage) and usefulness
(labels) as separate blocks so one never masquerades as the other.

## 2. Ripgrep outcome categories

Every symbol search ends in exactly one category. The collector reports
counts per category in its `diagnostic` and a negative-evidence item per
symbol that produced no match:

| Category | Meaning | Negative outcome |
|---|---|---|
| `matches` | rg ran, exit 0, at least one parsed match | — |
| `no_matches` | rg ran, exit 1, nothing found — *looked, found none* | `no_existing_reference` |
| `timeout` | this symbol's share of the collector budget expired | `search_timeout` |
| `not_searched` | never launched: budget already spent, or the total match cap was reached — *not looked* | `not_searched` |
| `decode_error` | rg's output could not be read (historically: platform-codec decode failure on Windows) | `search_error` |
| `process_error` | rg exited with a code other than 0/1 (e.g. bad pattern) | `search_error` |
| `launch_error` | the process could not be started (`OSError`) | `search_error` |
| `unavailable` | no `rg` on PATH; the collector is `skipped` | — |

Collector `status` derives from these: `timeout` if any symbol timed out or
was not searched (and the run was not cut by the match cap), `ok` if any
matches, `error` only when every searched symbol failed, else `empty`. The
`diagnostic.outcome` field (`matches / partial_timeout / timeout / error /
no_matches / no_symbols / unavailable`) is the one-word summary for review.

Only `no_existing_reference` counts as "absence after search" in the brief.
`search_timeout`, `not_searched`, and `search_error` are recorded in the
packet but never rendered as absence — a timeout is not evidence that the
symbol does not exist.

## 3. Identity: `head_state`

`identity.head` is bound by a dedicated probe with its own budget. When it
is `null`, `identity.head_state` says why:

| `head_state` | Meaning |
|---|---|
| `resolved` | `git rev-parse HEAD` answered |
| `probe_timeout` | the probe did not answer within budget (loaded machine); the repo does have a HEAD |
| `unresolved` | git answered but there is no commit (unborn branch) |

A detached checkout keeps `head` and sets `branch: null`; the git collector
labels it `(detached)`.

The dirty overlay has the same discipline. The git collector's `git_meta`
claim and its `collectors_run[].diagnostic` carry `dirty_state`:

| `dirty_state` | Meaning |
|---|---|
| `resolved` | `git status --porcelain` answered; the `git_dirty` claims are complete |
| `probe_timeout` | status did not answer within the collector's remaining budget; the overlay is *unknown*, not clean |
| `error` | status exited non-zero |

Before v0.2.1 a status timeout produced an empty overlay with no trace, which
is how a compile could non-deterministically lose a `dirty:` line. The default
git budget is now 600 ms for six git calls (a Windows git spawn costs ~40 ms).

## 4. Task provenance: `source_kind` and `symbol_details`

Claude Code's `UserPromptSubmit` channel also carries text no person typed:
background task notifications, system reminders, CI monitor events. The
compiler classifies each prompt deterministically:

- `task.source_kind: harness` — the text contains a harness tag
  (`<task-notification`, `<system-reminder`, `<ci-monitor-event`,
  `<local-command-stdout`, `<command-name>`) or a harness temp-file path.
  No symbols are extracted, the packet is still written (so the traffic is
  visible), and review classifies it as `harness` traffic.
- `task.source_kind: human` — everything else.

For human prompts, `task.symbol_details` records every candidate token the
scoper considered:

```json
{"value": "X-Forwarded-For", "category": "compound", "rank": 85, "selected": true, "reason": "compound"}
{"value": "There", "category": "capitalized", "rank": 30, "selected": false, "reason": "sentence_initial"}
```

Categories, highest rank first: `backticked`, `called`, `path`, `dotted`,
`compound`, `compound_snake`, `snake`, `camel`, `member`, `capitalized`.
Skip reasons: `stopword`, `too_short`, `no_symbol_shape`, `sentence_initial`,
`repo_self_name`, `ignored_by_config`, `duplicate_normalized`, `over_cap`.
At most twelve symbols are searched, chosen by rank and then prompt order,
so a backticked identifier at the end of a long prompt still wins over
twenty capitalized prose words at the start. Values are single tokens;
prompt text is never stored.

Per-repo tuning lives in `.evidence-compiler/config.yaml`:

```yaml
scoping:
  ignore_symbols: [Revit, Dynamo]   # case-insensitive; repo's own name is automatic
```

## 5. Privacy boundary

Packets and review artifacts contain: hashes, ids, timestamps, symbol
tokens, file references, collector statuses and counts, short reviewer
notes. They never contain raw prompt text, raw collector stdout, secrets,
or environment variables. `provenance.command` records the logical `rg …`
command line, not the absolute executable path. Everything lives under
`<repo>/.evidence-compiler/`, which the hook keeps local and which the
recommended `.gitignore` excludes (`packets/` and `logs/`).

## 6. The review workflow

All commands take `--repo <root>` (default: cwd) and only read packets.

```bash
evidence review --repo F:/MyRepo window start --name W3 --note "clean baseline on v0.2.0"
```

Records `logs/review/window.json` with the timestamp and a baseline count.
Historical packets are untouched; the window is a cut line, so `status`,
`inventory`, and `sample` consider only packets created after it unless you
pass `--all`.

```bash
evidence review --repo F:/MyRepo inventory        # one line per packet: traffic, symbols, rg/git outcome, latency, label
evidence review --repo F:/MyRepo status           # traffic split, operational health, label aggregates, due check
evidence review --repo F:/MyRepo sample --seed 3 --n 8
```

`sample` draws a reproducible stratified sample (same corpus + seed → same
packets): about 80 % candidate packets (human prompt with symbols), the rest
no-symbol packets; harness and probe traffic is never sampled; already
labeled packets are skipped unless `--include-labeled`. Review each with
`evidence replay <path>`, then:

```bash
evidence review --repo F:/MyRepo label ep_1234abcd helped --note "surfaced the def before I asked"
```

Labels: `helped` (the brief changed what the agent did, for the better),
`neutral` (accurate but did not matter), `hurt-noise` (took budget or
attention with irrelevant items), `insufficient` (the relevant evidence
existed but was not collected or was omitted). Records are appended to
`logs/review/labels.jsonl`; the latest label per packet wins.

`status` prints `REVIEW DUE` when the window has been open longer than
`review.window_days` or has accumulated `review.window_candidates` unlabeled
candidate packets (defaults 14 / 10; `0` disables a trigger).

## 7. Traffic classes

| Class | Rule |
|---|---|
| `probe` | `identity.session_id` starts with `probe` (smoke tests) |
| `harness` | `task.source_kind == harness`, or (packets written before that field existed) three or more generic notification/path words among the symbols |
| `nosym` | human prompt, no symbols extracted |
| `candidate` | human prompt with symbols — the only class whose usefulness is worth labeling |

## 8. What this does not do

No web dashboard, no service, no upload. No automatic usefulness score:
the compiler can prove it looked, it cannot prove the agent benefited.
Labels are written by a person; the tool refuses nothing but also
fabricates nothing.
