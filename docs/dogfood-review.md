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

### 2.1 The total match cap and where ranking happens

The collector stops collecting at `_MAX_TOTAL_MATCHES = 100` lexical matches
(at most 25 per symbol). The cap is applied **at collection time, in symbol
rank order, before ranking and before the token budget**: high-ranked symbols
are searched first and may each contribute up to 25 matches; once the total
reaches 100 the remaining, lower-ranked symbols are never launched and get a
`not_searched` negative item with reason `total match cap reached`. The
collector then sets `diagnostic.truncated: true` and `diagnostic.cap: 100`;
status stays `ok` and `outcome` stays `matches` — a cap hit is not a timeout.
`ranking.rank()` and the token-budget selection run afterwards on the ≤100
surviving items, so a capped packet typically selects ~20 of them and omits
the rest as `exceeds token budget`, while the evidence for the tail symbols
was never collected at all. That is the evidence a cap hit can hide: the
lowest-ranked symbols of a many-symbol prompt, not a random subset.

Every review view labels such a packet unmistakably as truncated: `queue`,
`sample`, and `inventory` show `rg=matches+capped`, `status` counts
`rg capped N packet(s) truncated by the total match cap`, and the summary
records `rg_truncated: true`. Reviewers should read the `not_searched`
negatives before labeling a capped packet `insufficient`. The numeric cap is
unchanged and its redesign is frozen (see `WORKLOG.md`, *Roadmap*): it reopens
only after at least three distinct, reviewed human-task packets show that cap
truncation hid needed evidence or caused a degraded answer.

### 2.2 The ripgrep stall watch

On 2026-09-06 a streak of packets showed rg `timeout` with every searched
symbol timing out (10/10 symbols, 0 matches) although rg itself answers in
under 100 ms — a machine-wide contention pattern that did not reproduce on
demand (0 of 14 attempts). No collector change was made. The review layer
marks the pattern as a **stall** (`rg=timeout+stall`; `status` line
`rg stall N packet(s) where every searched symbol timed out`) when the
collector timed out and `symbols_timeout == symbols_searched >= 2`. A single
slow symbol among fast ones is a partial timeout, not a stall.

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

### 4.1 Unicode identifiers (v0.3.0)

Identifier shape is decided by Unicode word characters, not `[A-Za-z]`.
`fenster_größe`, `Fenster.größe_berechnen()`, `señal_activa`, `fensterGröße`
and `` `größe` `` are recognised under the same categories and ranks as their
ASCII equivalents, and ripgrep's `-w -F` search honours the same word
boundaries, so a hit in `src/übersicht.py` reaches the brief. Prompt text is
normalised to NFC before tokenising (a decomposed `ö` typed on macOS matches
the composed one in source); NFKC and case folding are deliberately *not*
applied — the query is what was typed (`ﬁle` stays `ﬁle`).

Known limits, pinned by tests so a change is a conscious one:

- Every German noun is capitalised, so `Die Größe des Fensters` admits
  `Größe` and `Fensters` as rank-30 `capitalized` candidates exactly like
  English mid-sentence capitals. They lose to any shaped identifier and are
  the first to fall under the twelve-symbol cap.
- Source files stored in NFD are not matched by an NFC query (ripgrep
  compares bytes). Rare in git-managed repos; not normalised on purpose.
- A lowercase hyphenated Unicode span (`größen-abhängig`) splits into its
  parts like any lowercase span; `X-Forwarded-For`-style compounds survive.

### 4.2 Duplicate references render once (v0.3.0)

Two prompt symbols that hit the same line (`pyproject.toml` and `toml` both
matching `pyproject.toml:3`) used to cost two brief lines for one fact. The
renderer now folds selected items whose `(collector, kind, sorted references)`
are identical — separators normalised, otherwise verbatim, so `a.py:10` and
`a.py:10:5` stay distinct, and items without references are never folded.
The highest-scored item is rendered; the others' symbols are appended to its
`why` line as `; also matches toml`. In the packet the folded items remain
`selected: true` with the note `same reference as <id>; rendered once` in
`selected_because`; they are not added to `omitted_evidence_ids`, because
their fact *is* in the brief. `RenderResult.merged_ids` maps each folded id
to its survivor. Nothing about ranking changes — this is presentation only,
which keeps the packet the single source of truth.

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
`review.window_days`, has accumulated `review.window_candidates` unlabeled
candidate packets, or when `review.incident_threshold` candidate packets in
the window share one incident category (defaults 14 / 10 / 3; `0` disables a
trigger). Incident categories are `degraded:<collector>` (error or timeout),
`cap_hit`, `rg_stall`, and the usefulness label `hurt-noise`; harness and
probe traffic never counts toward them.

### 6.1 Queue and reminder (v0.3.0)

`sample` answers "give me a fair subset"; `queue` answers "what do I review
next" and never shuffles under you:

```bash
evidence review --repo F:/MyRepo queue --n 5     # next unlabeled packets, fixed order
evidence review --repo F:/MyRepo remind          # one line if a review is due, else nothing
```

The queue ranks every unlabeled candidate packet (then every unlabeled
no-symbol packet) by `sha256(window_name:packet_id)`. Labeling a packet
removes it and leaves the rest in place, so two sittings a week apart see the
same order; harness and probe traffic never appears. `remind` is safe for a
shell prompt or a scheduled task: silent until `window_days` or
`window_candidates` trips, then a single line pointing at `queue`.

`label` requires `--note`; a label without a reason is rejected (exit 2) —
an unexplained `hurt-noise` cannot be acted on later. Notes are
whitespace-collapsed and cut at 200 characters.

`status` also reports the window baseline (packets on disk when the window
was cut), the degraded-packet rate, `candidates reviewed X / unreviewed Y`,
and a watch metric `head N packet(s) without a head commit` (expected 0 since
v0.2.0's dedicated identity-probe budget; every historical `head: null`
packet predates it and coincided with the old shared 62 ms probe timeout).

**Cadence (Window 3 onward).** Review when `remind` speaks, and only then:

- **First review:** 10 eligible human-task (`candidate`) packets in the
  window, or 14 days after the window started, whichever comes first.
- **Routine reviews:** every further 10 unlabeled candidates, or every 14
  days after the previous sitting.
- **Immediate review:** three or more candidate packets in the window share
  one incident category (`degraded:<collector>`, `cap_hit`, `rg_stall`, or
  `hurt-noise`). `remind` names the category so the sitting can start from
  those packets.

At each sitting, label the queue until it is empty or you have read ten
packets; never label harness, probe, smoke, or inferred traffic. Raw packet
count is activity, not usefulness: only labels answer "did it help", and the
review-window baseline exists so that "N packets since W3 started" is never
mistaken for progress. Operational counters (`degraded`, `rg capped`,
`rg stall`, `head`) describe collector health, which is a different question
from whether the brief helped.

## 7. Traffic classes

| Class | Rule |
|---|---|
| `probe` | `identity.session_id` starts with `probe` (smoke tests) |
| `harness` | `task.source_kind == harness`, or — only for packets written before `symbol_details` existed — three or more generic notification/path words among the symbols. Packets with `symbol_details` trust `source_kind`. |
| `nosym` | human prompt, no symbols extracted |
| `candidate` | human prompt with symbols — the only class whose usefulness is worth labeling |

## 8. What this does not do

No web dashboard, no service, no upload. No automatic usefulness score:
the compiler can prove it looked, it cannot prove the agent benefited.
Labels are written by a person; the tool refuses nothing but also
fabricates nothing.
