# Evidence Compiler

A local, deterministic control plane that collects evidence about your
repository, normalizes it into an immutable **EvidencePacket**, and renders a
token-budgeted **ContextBrief** for an AI coding agent.

Collectors collect, the compiler evaluates, the agent reasons. Claude Code
Desktop is the first integration adapter — not the core. Graphify is a planned
optional structural collector (a Phase 1A stub today).

> Status: **Phase 1A**. The critical path (prompt → adapter → compiler →
> packet → brief → agent) is implemented, deterministic, and fail-open. See
> [docs/roadmap.md](docs/roadmap.md) for what is deliberately deferred.

## Install

```bash
pip install -e .
```

Requires Python ≥ 3.10 and PyYAML. Two collectors shell out to external
binaries when present and cleanly **skip** when absent:

- `git` — repository HEAD, branch, worktree, and dirty overlay.
- `rg` ([ripgrep](https://github.com/BurntSushi/ripgrep)) — exact lexical
  symbol matches and searched-but-absent (negative) evidence.

Neither is required: with both missing the compiler still runs and produces a
(smaller) packet. Missing collectors never cause a failure.

## Quickstart (CLI)

```bash
# scaffold per-repo config and print the Claude Code hook snippet
evidence init --repo .

# compile a packet for a prompt and print the brief
evidence compile --prompt "Why does AlphaService.run break?" --active-file src/alpha.py

# re-read a persisted packet as a text report
evidence replay .evidence-compiler/packets/<packet>.json
```

`compile` writes the full packet to `.evidence-compiler/packets/` (the
EvidencePacket is the system of record) and prints the derived brief to stdout.
`replay` reconstructs a human-readable report from any persisted packet.

## Claude Code Desktop hook (dogfooding)

The `evidence hook` subcommand is a fail-open `UserPromptSubmit` adapter: it
reads the hook payload on stdin, compiles a packet for the active repo, and — on
success with a non-empty brief — injects it via `additionalContext`. On any
error, empty result, or deadline expiry it injects nothing, logs to
`.evidence-compiler/logs/hook.log`, and exits 0, so it can never block or fail
your Claude Code session.

`evidence init` prints the exact hook block to add to your project's
`.claude/settings.json`; a standalone copy also lives in
[templates/claude-settings.json](templates/claude-settings.json). After adding
it, run a normal Claude Code Desktop prompt in a repo and confirm the brief
appears as injected context (and that a packet lands under
`.evidence-compiler/packets/`).

## Configuration

Core runs on built-in defaults. Optional per-repo settings live in
`.evidence-compiler/config.yaml` (deep-merged over defaults). Product-specific
policy belongs here, never in core package code. See the file written by
`evidence init` for every supported key.

## Documents

| Doc | Covers |
|---|---|
| [architecture](docs/architecture/architecture.md) | Product boundary, components, critical path, repo layout |
| [evidence-packet-v1](docs/specifications/evidence-packet-v1.md) | EvidencePacket schema — the system of record |
| [context-brief-v1](docs/specifications/context-brief-v1.md) | ContextBrief schema — the agent-facing render |
| [collector-interface-v1](docs/specifications/collector-interface-v1.md) | Collector plugin boundary + contract tests |
| [graphify-evaluation](docs/graphify-evaluation.md) | Graphify's role, evaluation tiers, guardrails |
| [roadmap](docs/roadmap.md) | Phased delivery, v0.1 → v1.0, explicit non-goals |

## Core invariants

1. Collectors collect; compiler evaluates; agent reasons. A collector never
   sets `selected`, `final_score`, or relevance.
2. The compiler stays functional if any collector is missing, times out, or
   errors — no collector failure propagates to a crash.
3. EvidencePacket is truth (full fidelity, persisted, immutable). ContextBrief
   is a budgeted presentation derived from it.
4. Provisional/stale evidence never satisfies verification. Authority and
   freshness are orthogonal.
5. The critical path is deterministic and fail-open: on any error, inject
   nothing, log, exit success. Never block the agent.
6. Product-specific policy lives in per-repo config, never in core code.

## Development

```bash
pip install -e ".[dev]"
python -m pytest
```

The suite includes collector contract tests and an end-to-end golden-fixture
integration test. Tests that require `git` or `rg` skip automatically when the
binary is absent.

## License

[Apache-2.0](LICENSE).
