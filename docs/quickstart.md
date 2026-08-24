# Quickstart — Any Repo in 5 Minutes

This walks through Evidence Compiler against a public repo, not a private
one, so the value is visible without any project-specific setup. Every
command and substantive output line below was captured from a real run. The
local checkout path in the replay output is intentionally redacted as
`/path/to/requests`; no behavior, evidence citation, collector status, or
result was fabricated — in keeping with the project's own no-guessing
invariant.

## 1. Install

```bash
pip install -e /path/to/evidence-compiler
```

## 2. Clone a repo you're curious about

Any repo works. This example uses [`requests`](https://github.com/psf/requests):

```bash
git clone https://github.com/psf/requests
cd requests
```

## 3. Scaffold config

```bash
evidence init --repo .
```

Writes `.evidence-compiler/config.yaml` and prints the Claude Code
`UserPromptSubmit` hook block (also available as
[templates/claude-settings.json](../templates/claude-settings.json)) — you
don't need the hook for this quickstart, just the config.

## 4. Compile a brief

```bash
evidence compile --prompt "Why does get_adapter raise InvalidSchema for an unknown URL prefix?" --active-file src/requests/sessions.py
```

This runs the git and ripgrep collectors against the repo, ranks the
resulting evidence, and prints a token-budgeted brief to stdout:

```
<context_brief packet_id="ep_57d50ffc5fe64a1c" head="8f8b212de8c2129d7954c6cd373762880375620a">
Scope confidence: high
Sources: active_file, prompt_symbol, git_diff

## Lexical
- [ripgrep] get_adapter at src/requests/sessions.py:778  |  adapter = self.get_adapter(url=request.url)
  why: references prompt symbol 'get_adapter'; touches the active file; exact lexical match
- [ripgrep] InvalidSchema at src/requests/sessions.py:33  |  InvalidSchema,
  why: references prompt symbol 'invalidschema'; touches the active file; exact lexical match
- [ripgrep] InvalidSchema at src/requests/sessions.py:881  |  raise InvalidSchema(f"No connection adapters were found for {url!r}")
  why: references prompt symbol 'invalidschema'; touches the active file; exact lexical match
- [ripgrep] get_adapter at src/requests/sessions.py:870  |  def get_adapter(self, url: str) -> BaseAdapter:
  why: references prompt symbol 'get_adapter'; touches the active file; exact symbol definition (lexical)
- [ripgrep] InvalidSchema at src/requests/adapters.py:44  |  InvalidSchema,
  why: references prompt symbol 'invalidschema'; same module as active file; exact lexical match
...
## Repository
- [git] HEAD 8f8b212de8c2 on branch main
  why: authoritative source

(3 additional item(s) omitted for budget/relevance)
```

Every claim carries a real `file:line` citation and a `why:` reason it was
selected — nothing here is guessed or summarized from memory. `sessions.py:870`
and `:881` are the actual definition and raise site; the compiler found and
ranked the relevant definition and raise site from the prompt, using the
supplied active file only as an additional relevance signal—without
requiring manual file attachment in the agent UI.

The full packet (all 25 evidence items collected, not just the 22 that fit
the budget) is written to `.evidence-compiler/packets/<packet-id>.json` —
the EvidencePacket is the system of record; the brief above is a budgeted
view derived from it.

## 5. Replay the full packet

```bash
evidence replay .evidence-compiler/packets/<packet-id>.json
```

```
packet_id      ep_57d50ffc5fe64a1c
schema_version 1
repository     /path/to/requests
worktree       (main)
head           8f8b212de8c2129d7954c6cd373762880375620a  branch main
intent         debugging
symbols        get_adapter, InvalidSchema
scope          high [active_file, prompt_symbol, git_diff]

evidence       25 total  |  22 selected  |  3 omitted
negative       0 absence item(s)
budget         injected 1058 / max 1200 tokens (candidate 1070)

collectors:
  git        ok
  ripgrep    ok
  graphify   skipped  (not implemented)
```

`replay` reconstructs a full text report from any persisted packet: every
evidence item collected (selected and omitted), per-collector health
(`ok`/`empty`/`skipped`/`timeout`), and the repository identity
(`repository_root`/`worktree_id`/`head`) the packet was captured against —
so a stale packet replayed from a different checkout warns instead of
silently lying to you.

## Next

- [README](../README.md) for the full CLI surface and the Claude Code
  Desktop hook (`evidence hook`) that injects the brief automatically on
  every prompt.
- [docs/specifications/evidence-packet-v1.md](specifications/evidence-packet-v1.md)
  and [docs/specifications/context-brief-v1.md](specifications/context-brief-v1.md)
  for the two schemas.
