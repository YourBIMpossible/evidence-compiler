"""Exact filename-stem evidence: exact names only, one item per token, outside the content caps."""

from __future__ import annotations

import os
import shutil
import subprocess
import time

import pytest

from evidence_compiler.collectors import filenames
from evidence_compiler.collectors import ripgrep as rgmod
from evidence_compiler.collectors.base import RawClaim
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


# --- collector-deadline respect for filename-stem lookup (fix/stem-respect-deadline) ---


def _content_item(path: str) -> RawClaim:
    return RawClaim(
        kind="lexical_content",
        statement=f"content hit in {path}",
        references=[path],
        authority="observed",
        freshness="current",
        confidence=0.9,
        command="rg",
        extra={"symbol": "x", "evidence_source": "ripgrep"},
    )


def test_expired_deadline_never_calls_git(monkeypatch):
    """No slice left -> git ls-files is never launched; state is 'skipped', not a no-match."""
    called = {"n": 0}

    def boom(*a, **k):  # pragma: no cover - must not run
        called["n"] += 1
        raise AssertionError("tracked_files must not run past the deadline")

    monkeypatch.setattr(filenames, "tracked_files", boom)
    ctx = make_context("/repo", "x", extracted_symbols=["nl_filter"], head="abc")
    items, diag = RipgrepCollector._stem_items(ctx, ["nl_filter"], [], time.perf_counter() - 1.0)
    assert called["n"] == 0
    assert items == []
    assert diag["outcome"] == "skipped"
    assert "deadline" in diag["reason"].lower()


def test_positive_time_passes_upper_bounded_timeout(monkeypatch):
    """Remaining budget is forwarded, capped at the git ls-files upper bound."""
    seen = {}

    def spy(root, head, timeout_ms=filenames._LS_FILES_TIMEOUT_MS):
        seen["timeout_ms"] = timeout_ms
        return ["backend/aec/nl_filter.py"]

    monkeypatch.setattr(filenames, "tracked_files", spy)
    ctx = make_context("/repo", "x", extracted_symbols=["nl_filter"], head="abc")
    # 30 s remaining -> must be clamped to the 1000 ms upper bound.
    items, diag = RipgrepCollector._stem_items(ctx, ["nl_filter"], [], time.perf_counter() + 30.0)
    assert seen["timeout_ms"] == filenames._LS_FILES_TIMEOUT_MS
    assert 0 < seen["timeout_ms"] <= filenames._LS_FILES_TIMEOUT_MS
    assert diag["outcome"] == "ok"
    assert [c.references for c in items] == [["backend/aec/nl_filter.py"]]


def test_short_remaining_time_passed_through_not_floored(monkeypatch):
    """A remaining slice above the minimum but below the cap is forwarded as-is."""
    seen = {}

    def spy(root, head, timeout_ms=filenames._LS_FILES_TIMEOUT_MS):
        seen["timeout_ms"] = timeout_ms
        return []

    monkeypatch.setattr(filenames, "tracked_files", spy)
    ctx = make_context("/repo", "x", extracted_symbols=["nl_filter"], head="abc")
    items, diag = RipgrepCollector._stem_items(ctx, ["nl_filter"], [], time.perf_counter() + 0.4)
    assert rgmod._MIN_CALL_MS <= seen["timeout_ms"] <= filenames._LS_FILES_TIMEOUT_MS


def test_skipped_lookup_preserves_existing_content_evidence():
    """A deadline skip must not erase already-collected ripgrep items or force a no-match."""
    content = [_content_item("backend/aec/nl_filter.py")]
    items, diag = RipgrepCollector._stem_items(
        make_context("/repo", "x", extracted_symbols=["nl_filter"], head="abc"),
        ["nl_filter"], content, time.perf_counter() - 0.5,
    )
    assert items == []                       # stem lookup contributes nothing
    assert diag["outcome"] == "skipped"      # and says why
    assert content == [_content_item("backend/aec/nl_filter.py")]  # content untouched


def test_diagnostic_states_are_distinct(monkeypatch):
    """succeeded vs unavailable/error vs deadline-skipped are three distinct outcomes."""
    ctx = make_context("/repo", "x", extracted_symbols=["nl_filter"], head="abc")

    monkeypatch.setattr(filenames, "tracked_files", lambda *a, **k: ["backend/aec/nl_filter.py"])
    _, ok = RipgrepCollector._stem_items(ctx, ["nl_filter"], [], time.perf_counter() + 5.0)

    monkeypatch.setattr(filenames, "tracked_files", lambda *a, **k: None)
    _, unavailable = RipgrepCollector._stem_items(ctx, ["nl_filter"], [], time.perf_counter() + 5.0)

    _, skipped = RipgrepCollector._stem_items(ctx, ["nl_filter"], [], time.perf_counter() - 5.0)

    outcomes = {ok["outcome"], unavailable["outcome"], skipped["outcome"]}
    assert outcomes == {"ok", "unavailable", "skipped"}
