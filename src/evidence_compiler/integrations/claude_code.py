"""Claude Code Desktop adapter — ``UserPromptSubmit`` hook.

**Deprecated**: this module is now a thin shim over :mod:`hook_safe`
(``evidence hook-safe``), the hardened, actively-maintained implementation
of this same adapter contract. It exists only so existing
``.claude/settings.json`` configurations that invoke ``evidence hook``
keep working without a breaking change. New setups should configure
``evidence hook-safe`` directly (see ``README.md`` / ``docs/quickstart.md``).

``hook_safe.main()`` keeps everything this module used to do (fail-open exit
0, repo root derived from the payload's ``cwd``, one ``injected`` log line
per successful injection) and adds byte-exact UTF-8 stdin/stdout, the
storage-path containment gate, bounded packet retention, and sanitized
(no-traceback) diagnostics. See ``hook_safe.py``'s module docstring for the
full contract.

Behavioral differences from the pre-deprecation implementation:

- ``CLAUDE_PROJECT_DIR``, when set, takes precedence over the payload ``cwd``
  for repo root resolution (matching how Claude Code Desktop invokes hooks).
  A payload ``cwd`` outside that root is refused and logged as
  ``cwd_outside_root`` instead of being compiled against.
- ``EVIDENCE_HOOK=0`` / ``BIMP_EVIDENCE_HOOK=0`` now silence ``evidence hook``
  as well as ``evidence hook-safe``; the two commands share one off switch.
- Log lines are tagged ``hook-safe:<category>`` for both commands.
"""

from __future__ import annotations

from .hook_safe import main

__all__ = ["main"]

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
