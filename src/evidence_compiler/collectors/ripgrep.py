"""Ripgrep collector — exact lexical symbol matches.

Enabled by default when the ``rg`` binary is present; otherwise returns
``status: skipped`` with a diagnostic. Emits negative evidence
(searched, found nothing) for symbols with no matches — absence after search
is first-class (packet spec §4).

Every symbol search ends in exactly one outcome category (``OUTCOMES``), so a
packet can always say *why* a symbol produced no evidence:

- ``matches``        — at least one match was parsed into evidence
- ``no_matches``     — rg ran to completion and found nothing
- ``timeout``        — the per-symbol budget elapsed (rg was killed)
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

        for index, symbol in enumerate(symbols):
            remaining_ms = int((deadline - time.perf_counter()) * 1000)
            if remaining_ms < _MIN_CALL_MS:
                # Deadline spent: account for every symbol that never ran so
                # "not looked" is distinguishable from "looked, found none".
                for later in symbols[index:]:
                    _negative(later, "not_searched", budget_ms=context.timeout_ms)
                break
            # Dynamic budget: the remaining time is shared evenly across the
            # symbols still to run, so fast searches donate their slack to
            # later ones instead of a fixed slice starving the tail.
            call_ms = max(remaining_ms // (len(symbols) - index), _MIN_CALL_MS)
            call_ms = min(call_ms, remaining_ms)
            # snake_case candidates (including compound-derived ones like
            # ``user_agent`` from ``User-Agent``) must also match when
            # embedded in a longer identifier (``default_user_agent``), so
            # they are searched as plain substrings. Everything else keeps
            # whole-word matching to avoid noise inside unrelated words.
            match_args = ["--fixed-strings"] if "_" in symbol else ["--word-regexp", "--fixed-strings"]
            cmd = [rg, "--json", *match_args, *extra_args, symbol, "."]
            logical_cmd = " ".join([_RG_LOGICAL, *cmd[1:]])
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
                _negative(symbol, "timeout", budget_ms=call_ms)
                continue
            except OSError as exc:
                # Isolate the failure to this symbol only — matches already
                # accumulated for prior symbols in this run remain valid and
                # must not be discarded (interface §4 failure isolation).
                _negative(symbol, "launch_error", error_type=type(exc).__name__)
                continue

            if proc.stdout is None:
                # The reader thread died (historically: platform-codec decode
                # failure). Explicit UTF-8 decoding should make this
                # unreachable, but the guard keeps a regression from
                # escalating into an AttributeError crash of the whole pass.
                _negative(symbol, "decode_error", reason="rg stdout could not be read")
                continue

            if proc.returncode not in (0, 1):
                # 2 = rg error; keep going for other symbols but note it
                _negative(
                    symbol,
                    "process_error",
                    rg_returncode=proc.returncode,
                    stderr=(proc.stderr or "")[:200],
                )
                continue

            matches = _parse_rg_json(proc.stdout, context, symbol, logical_cmd)
            if not matches:
                _negative(symbol, "no_matches", symbol_found_in_text=False)
                continue

            counts["matches"] += 1
            for claim in matches:
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

        return EvidenceResult(
            collector=self.name,
            status=status,
            items=items,
            negative_items=negatives,
            diagnostic=diagnostic,
            error_message=error_message,
        )


def _unique_symbols(symbols: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for sym in symbols:
        s = (sym or "").strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _parse_rg_json(
    stdout: str, context: CollectorContext, symbol: str, command: str
) -> list[RawClaim]:
    claims: list[RawClaim] = []
    per_symbol = 0
    for line in stdout.splitlines():
        if per_symbol >= _MAX_MATCHES_PER_SYMBOL:
            break
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except (ValueError, json.JSONDecodeError):
            # malformed output line — skip, do not crash (interface spec §7)
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
        kind = "lexical_def" if _looks_like_def(matched_text, symbol) else "lexical_match"
        snippet = matched_text[:160]
        claims.append(
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
        per_symbol += 1
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
