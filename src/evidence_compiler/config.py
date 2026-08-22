"""Per-repo configuration (`.evidence-compiler/config.yaml`).

Core runs on defaults with no config file present (git + ripgrep only). This
module is the *only* place defaults live; product-specific policy belongs in a
repo's own config, never in core package code (invariant 6).
"""

from __future__ import annotations

import copy
import os
from dataclasses import dataclass, field
from typing import Any

try:  # PyYAML is a declared dependency; degrade gracefully if unavailable.
    import yaml
except Exception:  # pragma: no cover - only hit in a broken install
    yaml = None  # type: ignore[assignment]

CONFIG_RELPATH = os.path.join(".evidence-compiler", "config.yaml")
DEFAULT_STORAGE_RELDIR = os.path.join(".evidence-compiler", "packets")

# Adapter end-to-end hard safety ceiling (ms). Operational target is p95 < 1s;
# this is the absolute ceiling from context-brief spec §5 / build brief §6.
DEFAULT_DEADLINE_MS = 25_000

DEFAULT_CONFIG: dict[str, Any] = {
    "storage": {"dir": DEFAULT_STORAGE_RELDIR},
    "deadline_ms": DEFAULT_DEADLINE_MS,
    "budget": {"min_tokens": 600, "default_tokens": 1000, "max_tokens": 1200},
    "collectors": {
        "git": {"enabled": True, "timeout_ms": 250},
        "ripgrep": {"enabled": True, "timeout_ms": 500, "extra_args": []},
        "graphify": {"enabled": True, "timeout_ms": 1250},
    },
}


@dataclass
class Config:
    data: dict[str, Any] = field(default_factory=lambda: copy.deepcopy(DEFAULT_CONFIG))
    source_path: str | None = None

    # -- accessors --------------------------------------------------------

    @property
    def deadline_ms(self) -> int:
        return int(self.data.get("deadline_ms", DEFAULT_DEADLINE_MS))

    @property
    def budget(self) -> dict[str, int]:
        b = self.data.get("budget", {}) or {}
        merged = dict(DEFAULT_CONFIG["budget"])
        merged.update({k: int(v) for k, v in b.items() if k in merged})
        return merged

    def storage_dir(self, repository_root: str) -> str:
        configured = (self.data.get("storage", {}) or {}).get("dir", DEFAULT_STORAGE_RELDIR)
        if os.path.isabs(configured):
            return configured
        return os.path.join(repository_root, configured)

    def collector_slice(self, name: str) -> dict[str, Any]:
        default = DEFAULT_CONFIG["collectors"].get(name, {"enabled": True, "timeout_ms": 500})
        merged = dict(default)
        merged.update((self.data.get("collectors", {}) or {}).get(name, {}) or {})
        return merged

    def collector_enabled(self, name: str) -> bool:
        return bool(self.collector_slice(name).get("enabled", True))

    def collector_timeout_ms(self, name: str) -> int:
        return int(self.collector_slice(name).get("timeout_ms", 500))


def load_config(repository_root: str) -> Config:
    """Load config for ``repository_root``; return defaults if none/invalid.

    A missing, empty, or malformed config file never breaks the compiler — the
    default (git + rg) config applies (build brief §7).
    """
    path = os.path.join(repository_root, CONFIG_RELPATH)
    if not os.path.isfile(path) or yaml is None:
        return Config()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            loaded = yaml.safe_load(fh) or {}
    except Exception:  # noqa: BLE001 - config must never crash core
        return Config()
    if not isinstance(loaded, dict):
        return Config()
    merged = _deep_merge(copy.deepcopy(DEFAULT_CONFIG), loaded)
    return Config(data=merged, source_path=path)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            base[key] = _deep_merge(base[key], value)
        else:
            base[key] = value
    return base
