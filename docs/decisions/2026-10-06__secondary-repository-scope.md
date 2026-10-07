# Decision: allow-listed secondary repository scope — 2026-10-06

**Status:** accepted by owner. **Code:** `d127a71` (feature), `c3ded8d`
(brief-noise fix). **Separate change:** `7795741` (harness markup tag
stripping) is independent of this decision.

## Authorization

Owner instruction of 2026-10-06T21:56:50Z, item 2b: "support explicitly
prompt-named secondary repository scopes only through an owner-maintained
allow-list, preserving cwd safeguards." The owner later confirmed (same
day) that this is explicit authorization for this narrowly scoped
capability and that no separate phase proposal is required for it. Local
integration was authorized on the condition that it does not change the
code executed by live EC hooks.

## What is authorized

- A secondary scope is collected only when the prompt explicitly names an
  absolute path that lies under exactly one entry of the per-repo
  `scoping.allowed_roots` list (owner-maintained, empty by default).
- Allow-list match is lexical and happens before any filesystem access;
  non-allowed candidates are never resolved or read.
- A lexical match is re-resolved (`realpath`) and must remain under the same
  root, rejecting junction/symlink escapes; the root must be a git work tree.
- The session root (cwd safeguards) is unchanged; a path inside it is not a
  secondary scope, and a session nested in an allowed root is ambiguous.
- Every secondary item carries its root provenance; statements, references
  and absence claims are root-qualified.
- Total collection time is fixed: while a secondary scope is collected,
  every per-collector timeout (primary included) is halved.
- `not_allowed` decisions stay packet diagnostics; only ambiguous or
  unavailable allow-listed targets are noted in the brief.

## Not authorized (do not broaden)

- Discovering or inferring roots (siblings, worktrees, recent repos).
- More than one secondary scope per prompt.
- Cross-repository ranking policy, or any product-specific roots in core.
- Changing the timeout-split policy without a new decision.
- Deploying the changed compiler to live hooks; that remains a separate
  owner action.
