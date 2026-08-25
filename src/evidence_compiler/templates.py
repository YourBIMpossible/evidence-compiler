"""Embedded default templates used by ``evidence init``.

Kept as in-package string constants so scaffolding does not depend on
package-data path resolution across editable/wheel installs. The repo-root
``templates/`` directory holds human-readable copies of the same content.
"""

from __future__ import annotations

_CONFIG_YAML = """\
# Evidence Compiler — per-repo configuration.
# Core runs on built-in defaults if this file is absent; every key here is
# optional. Product-specific policy belongs in this file, never in core code.

storage:
  # Must resolve beneath .evidence-compiler/ — the hook-safe launcher refuses
  # to run (fail-open, nothing injected) if this escapes that boundary.
  dir: .evidence-compiler/packets

# Bounded packet retention, applied by `evidence hook-safe` after each
# successful persist: the newest max_packets files are kept, older packets
# are deleted. Set 0 to disable retention entirely.
retention:
  max_packets: 250

# Adapter end-to-end hard safety ceiling (ms). Operational target is p95 < 1s.
deadline_ms: 25000

budget:
  min_tokens: 600
  default_tokens: 1000
  max_tokens: 1200

collectors:
  git:
    enabled: true
    timeout_ms: 250
  ripgrep:
    enabled: true
    timeout_ms: 500
    extra_args: []
  graphify:
    # Phase 1A stub: always reports "skipped / not implemented".
    enabled: true
    timeout_ms: 1250
"""

_CLAUDE_SETTINGS_JSON = """\
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "evidence",
            "args": ["hook-safe"]
          }
        ]
      }
    ]
  }
}
"""


def default_config_yaml() -> str:
    return _CONFIG_YAML


def claude_settings_json() -> str:
    return _CLAUDE_SETTINGS_JSON
