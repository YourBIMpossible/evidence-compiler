"""Per-repo config loading and defaults (build brief §7)."""

from __future__ import annotations

import os

from evidence_compiler.config import DEFAULT_DEADLINE_MS, load_config


def test_defaults_when_no_file(tmp_path):
    cfg = load_config(str(tmp_path))
    assert cfg.collector_enabled("git") is True
    assert cfg.collector_enabled("ripgrep") is True
    assert cfg.collector_timeout_ms("ripgrep") == 500
    assert cfg.deadline_ms == DEFAULT_DEADLINE_MS
    assert cfg.budget["max_tokens"] == 1200


def test_override_merges_over_defaults(tmp_path):
    cfgdir = tmp_path / ".evidence-compiler"
    cfgdir.mkdir()
    (cfgdir / "config.yaml").write_text(
        "collectors:\n  ripgrep:\n    timeout_ms: 900\n  graphify:\n    enabled: false\n"
        "budget:\n  max_tokens: 800\n",
        encoding="utf-8",
    )
    cfg = load_config(str(tmp_path))
    assert cfg.collector_timeout_ms("ripgrep") == 900  # overridden
    assert cfg.collector_enabled("ripgrep") is True     # default preserved
    assert cfg.collector_enabled("graphify") is False   # overridden
    assert cfg.budget["max_tokens"] == 800


def test_malformed_config_falls_back_to_defaults(tmp_path):
    cfgdir = tmp_path / ".evidence-compiler"
    cfgdir.mkdir()
    (cfgdir / "config.yaml").write_text(":\n  - not: valid: yaml: [", encoding="utf-8")
    cfg = load_config(str(tmp_path))
    assert cfg.collector_enabled("git") is True  # defaults still apply


def test_storage_dir_default(tmp_path):
    cfg = load_config(str(tmp_path))
    expected = os.path.join(str(tmp_path), ".evidence-compiler", "packets")
    assert cfg.storage_dir(str(tmp_path)) == expected
