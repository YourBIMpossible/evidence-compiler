"""Exact filename-stem evidence from the tracked file list.

A content search keeps at most 25 lines per symbol in rg stream order, so the
file *named* after a heavily-referenced symbol (``nl_filter`` ->
``backend/aec/nl_filter.py``) can be cut before ranking ever sees it. This
lookup is not a second search: it compares each extracted token against the
tracked file list and emits at most one item per token, outside the content
caps.

Matching is exact and case-insensitive, never substring/prefix/containment:

- a token with ``/`` matches a tracked path equal to it or ending in ``/<token>``
- a token with an extension matches a file basename exactly (``nl_filter.py``)
- any other token matches a basename minus its last extension (``nl_filter``
  matches ``nl_filter.py`` and ``nl_filter.ts``, never ``nl_filter_utils.py``
  or ``Invoke-NlFilter.ps1``)

The tracked list comes from ``git ls-files`` and is cached per HEAD outside
the analysed repository (user cache directory).
"""

from __future__ import annotations

import hashlib
import os
import posixpath
import subprocess
from pathlib import Path

from .base import RawClaim

EVIDENCE_SOURCE = "tracked_filename_stem"
KIND = "lexical_filename"

# One item per token; a generic stem (``index``, ``main``) must not flood it.
MAX_PATHS_PER_ITEM = 5

_LS_FILES_TIMEOUT_MS = 1000


def tracked_files(root: str, head: str | None, timeout_ms: int = _LS_FILES_TIMEOUT_MS) -> list[str] | None:
    """Repo-relative forward-slash tracked paths, or None when git could not answer."""
    cache = _cache_path(root, head) if head else None
    if cache is not None:
        try:
            return cache.read_text(encoding="utf-8").splitlines()
        except OSError:
            pass
    try:
        proc = subprocess.run(
            ["git", "-c", "core.quotepath=off", "ls-files", "-z"],
            cwd=root,
            capture_output=True,
            timeout=timeout_ms / 1000.0,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0 or not isinstance(proc.stdout, bytes):
        return None
    paths = [p for p in proc.stdout.decode("utf-8", errors="replace").split("\0") if p]
    if cache is not None:
        _write_cache(cache, paths)
    return paths


def match_token(token: str, paths: list[str]) -> list[str]:
    """Tracked paths whose name exactly matches ``token`` (rules in module docstring)."""
    t = token.strip().replace("\\", "/").strip("/").lower()
    if not t:
        return []
    if "/" in t:
        return [p for p in paths if p.lower() == t or p.lower().endswith("/" + t)]
    if posixpath.splitext(t)[1]:
        return [p for p in paths if posixpath.basename(p).lower() == t]
    return [p for p in paths if posixpath.splitext(posixpath.basename(p))[0].lower() == t]


def stem_claims(
    symbols: list[str],
    content_paths: set[str],
    paths: list[str],
) -> list[RawClaim]:
    """At most one claim per token, deduplicated against retained content hits.

    ``content_paths`` are the lowercase repo-relative paths already present in
    the capped content results; a matched file already there adds nothing.
    """
    claims: list[RawClaim] = []
    for symbol in symbols:
        matched = sorted(match_token(symbol, paths), key=str.lower)
        if not matched:
            continue
        retained = [p for p in matched if p.lower() in content_paths]
        fresh = [p for p in matched if p.lower() not in content_paths]
        if not fresh:
            continue
        shown = fresh[:MAX_PATHS_PER_ITEM]
        more = len(fresh) - len(shown)
        claims.append(
            RawClaim(
                kind=KIND,
                statement=f"file name exactly matches `{symbol}`: {', '.join(shown)}"
                + (f" (+{more} more)" if more else ""),
                references=shown,
                authority="inferred",
                freshness="current",
                confidence=0.7,
                command="git ls-files",
                extra={
                    "symbol": symbol,
                    "evidence_source": EVIDENCE_SOURCE,
                    "matched_term": symbol,
                    "exact_stem_match": True,
                    "content_match_retained": bool(retained),
                    "matched_file_count": len(matched),
                },
            )
        )
    return claims


def _cache_path(root: str, head: str) -> Path | None:
    base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), ".cache")
    if not base:
        return None
    key = hashlib.sha256(os.path.normcase(os.path.abspath(root)).encode("utf-8")).hexdigest()[:16]
    return Path(base, "evidence-compiler", "tracked-files", f"{key}-{head}.txt")


def _write_cache(cache: Path, paths: list[str]) -> None:
    """Best effort; drops older HEAD entries for the same repository."""
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        prefix = cache.name.split("-", 1)[0] + "-"
        for old in cache.parent.glob(prefix + "*.txt"):
            if old != cache:
                old.unlink(missing_ok=True)
        tmp = cache.with_suffix(".tmp")
        tmp.write_text("\n".join(paths), encoding="utf-8")
        tmp.replace(cache)
    except OSError:
        pass
