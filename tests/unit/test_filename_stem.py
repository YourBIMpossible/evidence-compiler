"""Exact filename-stem evidence: exact names only, one item per token, outside the content caps."""

from __future__ import annotations

import os
import shutil
import subprocess

import pytest

from evidence_compiler.collectors import filenames
from evidence_compiler.collectors import ripgrep as rgmod
from evidence_compiler.collectors.ripgrep import RipgrepCollector
from tests.support import make_context

rg_required = pytest.mark.skipif(shutil.which("rg") is None or shutil.which("git") is None,
                                 reason="ripgrep/git not installed")

PATHS = [
    "backend/aec/nl_filter.py",
    "frontend/lib/nl_filter.ts",
    "backend/aec/nl_filter_utils.py",
    "scripts/Invoke-NlFilter.ps1",
    "docs/NL_FILTER.md",
    "src/main.py",
]


def test_bare_token_matches_exact_stem_case_insensitive_only():
    assert filenames.match_token("nl_filter", PATHS) == [
        "backend/aec/nl_filter.py", "frontend/lib/nl_filter.ts", "docs/NL_FILTER.md",
    ]


def test_token_with_extension_matches_basename_exactly():
    assert filenames.match_token("nl_filter.py", PATHS) == ["backend/aec/nl_filter.py"]


def test_path_token_matches_whole_segments_only():
    assert filenames.match_token("aec/nl_filter.py", PATHS) == ["backend/aec/nl_filter.py"]
    assert filenames.match_token("ec/nl_filter.py", PATHS) == []


def test_no_substring_prefix_or_camel_containment():
    assert filenames.match_token("nl", PATHS) == []
    assert filenames.match_token("filter", PATHS) == []
    assert filenames.match_token("NlFilter", PATHS) == []


def test_one_item_per_token_deduplicated_and_bounded():
    many = [f"pkg{i}/main.py" for i in range(9)]
    claims = filenames.stem_claims(["main", "nl_filter"], {"backend/aec/nl_filter.py"}, PATHS + many)
    assert [c.extra["symbol"] for c in claims] == ["main", "nl_filter"]
    main, nl = claims
    assert nl.references == ["docs/NL_FILTER.md", "frontend/lib/nl_filter.ts"]
    assert nl.statement.startswith("file name exactly matches `nl_filter`")
    assert nl.extra == {
        "symbol": "nl_filter", "evidence_source": "tracked_filename_stem", "matched_term": "nl_filter",
        "exact_stem_match": True, "content_match_retained": True, "matched_file_count": 3,
    }
    assert len(main.references) == filenames.MAX_PATHS_PER_ITEM
    assert main.statement.endswith("(+5 more)")


def test_fully_retained_token_emits_nothing():
    assert filenames.stem_claims(["nl_filter.py"], {"backend/aec/nl_filter.py"}, PATHS) == []


def _commit_file(repo: str, rel: str, text: str) -> None:
    path = os.path.join(repo, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "add"], cwd=repo, check=True, capture_output=True)


@rg_required
def test_named_file_survives_content_cap(golden_repo, monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "cache"))
    # 30 files mention the symbol before the named file can appear in the capped stream.
    for i in range(30):
        _commit_file(golden_repo, f"aaa/user{i:02d}.py", "".join(f"cap_target_sym({j})\n" for j in range(3)))
    _commit_file(golden_repo, "zzz/cap_target_sym.py", "def cap_target_sym():\n    pass\n")
    result = RipgrepCollector().collect(make_context(golden_repo, "x", extracted_symbols=["cap_target_sym"]))
    content = [c for c in result.items if c.kind != filenames.KIND]
    stems = [c for c in result.items if c.kind == filenames.KIND]
    assert len(content) == rgmod._MAX_MATCHES_PER_SYMBOL  # cap unchanged
    retained = {r.split(":")[0] for c in content for r in c.references}
    if "zzz/cap_target_sym.py" in retained:
        assert stems == []  # rg happened to emit it: deduplicated
    else:
        assert [c.references for c in stems] == [["zzz/cap_target_sym.py"]]
    assert result.diagnostic["filename_stem"]["outcome"] == "ok"


@rg_required
def test_stem_only_match_makes_status_ok(golden_repo, monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "cache"))
    _commit_file(golden_repo, "tools/lonely_name.py", "x = 1\n")
    result = RipgrepCollector().collect(make_context(golden_repo, "x", extracted_symbols=["lonely_name"]))
    assert result.status == "ok"
    assert [c.references for c in result.items] == [["tools/lonely_name.py"]]


def test_tracked_files_cache_is_keyed_by_head(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    cache = filenames._cache_path(str(tmp_path / "repo"), "abc")
    cache.parent.mkdir(parents=True)
    cache.write_text("cached/one.py", encoding="utf-8")
    assert filenames.tracked_files(str(tmp_path / "repo"), "abc") == ["cached/one.py"]
