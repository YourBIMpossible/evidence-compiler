# Golden fixture repo

A tiny synthetic repository used by the Evidence Compiler test suite. It is
intentionally NOT a git repository on disk; the integration tests copy it to a
temp dir and `git init` there so the git collector has real HEAD/dirty state.

Exercised scenarios:

- clean symbol match — `AlphaService` is defined in `src/alpha.py` and
  referenced in `src/beta.py`.
- dirty/uncommitted file — a test mutates `src/beta.py` after the initial
  commit to produce a dirty path.
- missing-symbol negative evidence — tests prompt for a symbol that appears
  in no source file (see the integration tests for the exact name, which is
  deliberately kept out of this file so ripgrep genuinely finds nothing), so
  ripgrep records a searched-but-absent result.
- collector timeout/error — a fake collector injected by the test raises or
  hangs to prove failure isolation and the end-to-end deadline.
