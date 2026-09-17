"""Ripgrep collector — exact lexical symbol matches.

Enabled by default when the ``rg`` binary is present; otherwise returns
``status: skipped`` with a diagnostic. Emits negative evidence
(searched, found nothing) for symbols with no matches — absence after search
is first-class (packet spec §4).

Every symbol search ends in exactly one outcome category (``OUTCOMES``), so a
packet can always say *why* a symbol produced no evidence:

- ``matches``        — at least one match was parsed into evidence
- ``no_matches``     — rg ran to completion and found nothing
- ``timeout``        — the search budget elapsed (rg was killed)
- ``not_searched``   — the collector deadline was already spent
- ``decode_error``   — rg output could not be read/decoded
- ``process_error``  — rg exited with a non-search status (2+)
- ``launch_error``   — rg could not be started (OSError)
- ``unavailable``    — no ``rg`` on PATH (collector-level, status ``skipped``)

Output is decoded as UTF-8 with replacement explicitly. Relying on the
platform default codec (cp1252 on Windows) let a single non-cp1252 byte in a
matched line kill the reader thread and drop the whole lexical pass — the
Window 2 defect (35 % of packets).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import time

from .base import (
    Collector,
    CollectorContext,
    EvidenceResult,
    RawClaim,
    RawNegative,
    normalize_reference,
)
from ..refs import split_line_suffix
from . import filenames

# Guardrails so duplicate-heavy input cannot explode the packet.
_MAX_MATCHES_PER_SYMBOL = 25
_MAX_TOTAL_MATCHES = 100

# Smallest budget worth launching rg with; below this the process start-up
# alone consumes the slice and the result is a guaranteed timeout.
_MIN_CALL_MS = 100

# Logical executable name recorded in provenance. The resolved absolute path
# (``C:\Users\<user>\...\rg.EXE``) is a machine detail, not evidence.
_RG_LOGICAL = "rg"

OUTCOMES = (
    "matches",
    "no_matches",
    "timeout",
    "not_searched",
    "decode_error",
    "process_error",
    "launch_error",
    "unavailable",
)

# Negative-evidence outcome names (packet spec §4 vocabulary) per category.
_NEGATIVE_OUTCOME = {
    "no_matches": "no_existing_reference",
    "timeout": "search_timeout",
    "not_searched": "not_searched",
    "decode_error": "search_error",
    "process_error": "search_error",
    "launch_error": "search_error",
}

# Cheap heuristic for def-vs-reference labelling only (never authoritative).
_DEF_HINTS = ("def ", "class ", "function ", "func ", "fn ", "const ", "let ", "var ", "public ",
              "private ", "static ", "struct ", "interface ", "type ", "enum ")


class RipgrepCollector(Collector):
    name = "ripgrep"

    def collect(self, context: CollectorContext) -> EvidenceResult:
        rg = shutil.which("rg")
        if rg is None:
            return EvidenceResult(
                collector=self.name,
                status="skipped",
                diagnostic={"outcome": "unavailable", "reason": "ripgrep (rg) binary not found on PATH"},
            )

        symbols = _unique_symbols(context.extracted_symbols)
        if not symbols:
            return EvidenceResult(
                collector=self.name,
                status="empty",
                diagnostic={"outcome": "no_symbols", "reason": "no symbols extracted from prompt to search"},
            )

        root = context.repository_root
        extra_args = list(context.config.get("extra_args", []) or [])

        items: list[RawClaim] = []
        negatives: list[RawNegative] = []
        counts = {name: 0 for name in OUTCOMES}
        total = 0
        truncated = False
        deadline = time.perf_counter() + (context.timeout_ms / 1000.0)

        def _negative(symbol: str, category: str, **detail) -> None:
            counts[category] += 1
            diag = {"category": category}
            diag.update(detail)
            negatives.append(
                RawNegative(
                    query=symbol,
                    outcome=_NEGATIVE_OUTCOME[category],
                    searched_roots=[root],
                    diagnostic=diag,
                )
            )

        # Phase 1 - search. Symbols are batched by match mode into at most two
        # rg processes (one repository walk each) instead of one process per
        # symbol: twelve sequential walks were the Window 3 timeout source
        # (~70 ms each on a 2k-file repo, so a loaded machine overran the
        # 1.5 s slice). Each symbol still ends in exactly one outcome.
        per_symbol: dict[str, tuple[str, object]] = {}
        batches = _batches(symbols)
        for index, batch in enumerate(batches):
            remaining_ms = int((deadline - time.perf_counter()) * 1000)
            if remaining_ms < _MIN_CALL_MS:
                # Deadline spent: "not looked" stays distinguishable from
                # "looked, found none".
                for later in batches[index:]:
                    for symbol in later:
                        per_symbol[symbol] = ("not_searched", {"budget_ms": context.timeout_ms})
                break
            # Remaining time is shared across the batches still to run.
            call_ms = max(remaining_ms // (len(batches) - index), _MIN_CALL_MS)
            call_ms = min(call_ms, remaining_ms)
            per_symbol.update(_search_batch(rg, root, batch, extra_args, call_ms, context, deadline))

        # Phase 2 - account and cap, in symbol rank order. Caps behave exactly
        # as before batching: per-symbol cap in rg stream order, then the total
        # cap filled best-ranked symbol first; symbols past the total cap are
        # reported ``not_searched`` with the cap as the reason.
        for index, symbol in enumerate(symbols):
            category, payload = per_symbol[symbol]
            if category != "matches":
                _negative(symbol, category, **payload)  # type: ignore[arg-type]
                continue
            counts["matches"] += 1
            for claim in payload:  # type: ignore[union-attr]
                if total >= _MAX_TOTAL_MATCHES:
                    truncated = True
                    break
                items.append(claim)
                total += 1
            if total >= _MAX_TOTAL_MATCHES:
                truncated = True
                for later in symbols[index + 1:]:
                    _negative(later, "not_searched", reason="total match cap reached", cap=_MAX_TOTAL_MATCHES)
                break

        errors = counts["decode_error"] + counts["process_error"] + counts["launch_error"]
        searched = len(symbols) - counts["not_searched"]
        diagnostic: dict = {
            "symbols_total": len(symbols),
            "symbols_searched": searched,
            "symbols_matched": counts["matches"],
            "symbols_no_match": counts["no_matches"],
            "symbols_timeout": counts["timeout"],
            "symbols_error": errors,
            "symbols_not_searched": counts["not_searched"],
            "matches": total,
            "budget_ms": context.timeout_ms,
        }
        if truncated:
            diagnostic["truncated"] = True
            diagnostic["cap"] = _MAX_TOTAL_MATCHES
        if errors:
            diagnostic["error_categories"] = sorted(
                c for c in ("decode_error", "process_error", "launch_error") if counts[c]
            )

        error_message: str | None = None
        deadline_hit = counts["timeout"] + counts["not_searched"]
        if deadline_hit and not truncated:
            status = "timeout"
            diagnostic["outcome"] = "partial_timeout" if items else "timeout"
            diagnostic["reason"] = (
                f"{deadline_hit} of {len(symbols)} symbol searches hit the collector deadline"
            )
        elif items:
            status = "ok"
            diagnostic["outcome"] = "matches"
        elif errors and errors == searched:
            status = "error"
            diagnostic["outcome"] = "error"
            diagnostic["reason"] = "every symbol search failed"
            error_message = "ripgrep failed for every symbol: " + ", ".join(diagnostic["error_categories"])
        else:
            status = "empty"
            diagnostic["outcome"] = "no_matches"
            diagnostic["reason"] = "no lexical matches for any extracted symbol"

        # Phase 3 - exact filename-stem evidence, outside both content caps and
        # never counted toward them (see filenames.py).
        stem_items, diagnostic["filename_stem"] = self._stem_items(context, symbols, items, deadline)
        if stem_items:
            items = items + stem_items
            if status == "empty":
                status = "ok"

        return EvidenceResult(
            collector=self.name,
            status=status,
            items=items,
            negative_items=negatives,
            diagnostic=diagnostic,
            error_message=error_message,
        )

    @staticmethod
    def _stem_items(
        context: CollectorContext, symbols: list[str], items: list[RawClaim], deadline: float
    ) -> tuple[list[RawClaim], dict]:
        remaining_ms = int((deadline - time.perf_counter()) * 1000)
        paths = filenames.tracked_files(
            context.repository_root, context.head, max(min(remaining_ms, 1000), _MIN_CALL_MS)
        )
        if paths is None:
            return [], {"outcome": "unavailable", "reason": "git ls-files did not answer"}
        claims = filenames.stem_claims(symbols, _content_paths(items), paths)
        for claim in claims:
            claim.references = [normalize_reference(r, context.repository_root) for r in claim.references]
        return claims, {"outcome": "ok", "items": len(claims)}


def _search_batch(
    rg: str,
    root: str,
    batch: list[str],
    extra_args: list[str],
    call_ms: int,
    context: CollectorContext,
    deadline: float,
) -> dict[str, tuple[str, object]]:
    """Search ``batch`` in one rg process: ``{symbol: (outcome, payload)}``.

    ``payload`` is the symbol's claim list for ``matches`` and the negative
    diagnostic detail otherwise. A process or launch error on a multi-symbol batch
    is retried one symbol at a time, so one bad pattern cannot poison its
    batch-mates (interface section 4 failure isolation).
    """
    cmd = [rg, "--json", *_match_args(batch[0]), *extra_args]
    for symbol in batch:
        cmd += ["-e", symbol]
    cmd.append(".")
    outcome = _run_rg(cmd, root, call_ms)
    if isinstance(outcome, tuple):
        category, detail = outcome
        if category in ("process_error", "launch_error") and len(batch) > 1:
            results: dict[str, tuple[str, object]] = {}
            for i, symbol in enumerate(batch):
                remaining_ms = int((deadline - time.perf_counter()) * 1000)
                if remaining_ms < _MIN_CALL_MS:
                    for later in batch[i:]:
                        results[later] = ("not_searched", {"budget_ms": context.timeout_ms})
                    break
                call = max(remaining_ms // (len(batch) - i), _MIN_CALL_MS)
                results.update(_search_batch(rg, root, [symbol], extra_args, min(call, remaining_ms), context, deadline))
            return results
        if category == "timeout":
            detail = {"budget_ms": call_ms}
        return {symbol: (category, detail) for symbol in batch}

    logical_cmd = " ".join([_RG_LOGICAL, *cmd[1:]])
    by_symbol = _parse_rg_json(outcome, context, batch, logical_cmd)
    return {
        symbol: ("matches", by_symbol[symbol])
        if by_symbol[symbol]
        else ("no_matches", {"symbol_found_in_text": False})
        for symbol in batch
    }


def _match_args(symbol: str) -> list[str]:
    # snake_case candidates (including compound-derived ones like
    # ``user_agent`` from ``User-Agent``) must also match when embedded in a
    # longer identifier (``default_user_agent``), so they are searched as
    # plain substrings. Everything else keeps whole-word matching to avoid
    # noise inside unrelated words.
    return ["--fixed-strings"] if "_" in symbol else ["--word-regexp", "--fixed-strings"]


def _batches(symbols: list[str]) -> list[list[str]]:
    """Group symbols by match mode, preserving rank order within each group.

    The group holding the best-ranked symbol runs first, so a spent deadline
    starves the weaker symbols as the one-process-per-symbol loop did.
    """
    groups: dict[bool, list[str]] = {}
    for symbol in symbols:
        groups.setdefault("_" in symbol, []).append(symbol)
    return list(groups.values())


def _run_rg(cmd: list[str], root: str, call_ms: int) -> str | tuple[str, dict]:
    """rg stdout for a completed search, else ``(outcome_category, detail)``."""
    try:
        proc = subprocess.run(
            cmd,
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=call_ms / 1000.0,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return "timeout", {}
    except OSError as exc:
        return "launch_error", {"error_type": type(exc).__name__}
    if proc.stdout is None:
        # The reader thread died (historically: platform-codec decode
        # failure). Explicit UTF-8 decoding should make this unreachable, but
        # the guard keeps a regression from escalating into a crash.
        return "decode_error", {"reason": "rg stdout could not be read"}
    if proc.returncode not in (0, 1):
        return "process_error", {"rg_returncode": proc.returncode, "stderr": (proc.stderr or "")[:200]}
    return proc.stdout


def _symbol_pattern(symbol: str) -> re.Pattern[str]:
    """Attribution matcher mirroring the rg match mode used for ``symbol``."""
    escaped = re.escape(symbol)
    return re.compile(escaped if "_" in symbol else rf"(?<!\w){escaped}(?!\w)")


def _unique_symbols(symbols: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for sym in symbols:
        s = (sym or "").strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _content_paths(items: list[RawClaim]) -> set[str]:
    return {split_line_suffix(ref)[0].lower() for claim in items for ref in claim.references}


def _parse_rg_json(
    stdout: str, context: CollectorContext, symbols: list[str], command: str
) -> dict[str, list[RawClaim]]:
    """Claims per symbol from one multi-pattern rg run.

    rg reports a matching line once whichever pattern hit, so each line is
    attributed by re-testing every symbol against its text; a symbol whose
    match overlaps another pattern's on the same line is still credited.
    Each symbol keeps its own cap, filled in rg stream order.
    """
    patterns = {symbol: _symbol_pattern(symbol) for symbol in symbols}
    claims: dict[str, list[RawClaim]] = {symbol: [] for symbol in symbols}
    for line in stdout.splitlines():
        if all(len(claims[s]) >= _MAX_MATCHES_PER_SYMBOL for s in symbols):
            break
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except (ValueError, json.JSONDecodeError):
            # malformed output line - skip, do not crash (interface spec section 7)
            continue
        if record.get("type") != "match":
            continue
        data = record.get("data") or {}
        path_text = _text_of(data.get("path"))
        line_no = data.get("line_number")
        if not path_text or line_no is None:
            continue
        matched_text = _text_of(data.get("lines")).strip()
        ref = normalize_reference(f"{path_text}:{line_no}", context.repository_root)
        snippet = matched_text[:160]
        for symbol in symbols:
            if len(claims[symbol]) >= _MAX_MATCHES_PER_SYMBOL or not patterns[symbol].search(matched_text):
                continue
            kind = "lexical_def" if _looks_like_def(matched_text, symbol) else "lexical_match"
            claims[symbol].append(
                RawClaim(
                    kind=kind,
                    statement=f"{symbol} at {ref}"
                    + (f"  |  {snippet}" if snippet else ""),
                    references=[ref],
                    authority="inferred",
                    freshness="current",
                    confidence=0.6 if kind == "lexical_match" else 0.7,
                    command=command,
                    extra={"symbol": symbol, "line": line_no, "snippet": snippet},
                )
            )
    return claims


def _text_of(node) -> str:
    """rg JSON encodes text as {'text': ...} or {'bytes': ...}; return best-effort str."""
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, dict):
        if "text" in node:
            return str(node["text"])
        if "bytes" in node:
            return ""  # non-UTF8 path; unusable as a reference
    return str(node)


def _looks_like_def(line_text: str, symbol: str) -> bool:
    low = line_text.lower()
    return any(hint in low for hint in _DEF_HINTS)
