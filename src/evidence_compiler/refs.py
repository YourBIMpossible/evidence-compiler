"""Parsing of ``path[:line[:col]]`` reference strings — the one shared rule.

Both the collector boundary (``collectors.base.normalize_reference``) and the
packet's content ordering (``packet._ref_sort_key``) must split a reference
the same way; keeping a single implementation here means a change to the
suffix grammar cannot silently apply to one side only.
"""

from __future__ import annotations

import re

# Matches only the *trailing* ``:line`` or ``:line:col`` suffix, so a colon
# earlier in the path (a Windows drive letter, ``C:/foo.py:10``) is never
# mistaken for the line separator.
_LINE_SUFFIX = re.compile(r"^(?P<path>.*?)(?P<suffix>:(?P<line>\d+)(?::\d+)?)?$")
_TRAILING_NUMERIC_SEGMENT = re.compile(r":\d+$")


def split_line_suffix(reference: str) -> tuple[str, str, int | None]:
    """Split ``reference`` into ``(path, suffix, line)``.

    ``suffix`` is the verbatim ``:line[:col]`` tail (``""`` when absent) and
    ``line`` its numeric line (``None`` when absent). A reference carrying
    more than two trailing numeric segments (``a.py:1:2:3``) does not fit the
    grammar; it is returned whole with no suffix rather than being split at
    an arbitrary interior colon.
    """
    match = _LINE_SUFFIX.match(reference)
    if not match or match.group("suffix") is None:
        return (reference, "", None)
    path = match.group("path")
    if _TRAILING_NUMERIC_SEGMENT.search(path):
        return (reference, "", None)
    return (path, match.group("suffix"), int(match.group("line")))
