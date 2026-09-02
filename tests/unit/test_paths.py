"""Path normalization: repo-relative POSIX; accept Windows inputs (interface §4)."""

from __future__ import annotations

from evidence_compiler.collectors.base import normalize_path, normalize_reference

ROOT = "C:/repo"


def test_windows_backslash_input_relativized():
    assert normalize_path(r"C:\repo\src\a.py", ROOT) == "src/a.py"


def test_posix_absolute_relativized():
    assert normalize_path("C:/repo/src/a.py", ROOT) == "src/a.py"


def test_already_relative_posix_kept():
    assert normalize_path("src/a.py", ROOT) == "src/a.py"


def test_relative_backslash_converted():
    assert normalize_path(r"src\a.py", ROOT) == "src/a.py"


def test_reference_line_suffix_preserved():
    assert normalize_reference(r"C:\repo\src\a.py:42", ROOT) == "src/a.py:42"


def test_reference_line_col_suffix_preserved():
    assert normalize_reference("C:/repo/src/a.py:42:7", ROOT) == "src/a.py:42:7"


def test_reference_with_extra_numeric_segments_is_not_split_mid_path():
    # Shares one rule with packet._ref_sort_key: three numeric segments are
    # not a ``path:line[:col]`` reference, so no suffix is peeled off.
    assert normalize_reference("C:/repo/src/a.py:1:2:3", ROOT) == "src/a.py:1:2:3"


def test_outside_repo_not_falsely_relativized():
    out = normalize_path("D:/other/x.py", "C:/repo")
    assert out.endswith("other/x.py")
    assert not out.startswith("src")


def test_empty_input_safe():
    assert normalize_path("", ROOT) == ""
    assert normalize_reference("", ROOT) == ""
