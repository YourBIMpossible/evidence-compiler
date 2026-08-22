"""Ripgrep collector — exact lexical symbol matches.

Enabled by default when the ``rg`` binary is present; otherwise returns
``status: skipped`` with a diagnostic. Emits negative evidence
(searched, found nothing) for symbols with no matches — absence after search
is first-class (packet spec §4).
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
                diagnostic={"reason": "ripgrep (rg) binary not found on PATH"},
            )

        symbols = _unique_symbols(context.extracted_symbols)
        if not symbols:
            return EvidenceResult(
                collector=self.name,
                status="empty",
                diagnostic={"reason": "no symbols extracted from prompt to search"},
            )

        root = context.repository_root
        per_symbol_ms = max(context.timeout_ms // len(symbols), 100)
        extra_args = list(context.config.get("extra_args", []) or [])

        items: list[RawClaim] = []
        negatives: list[RawNegative] = []
        total = 0
        truncated = False
        timed_out = False
        deadline = time.perf_counter() + (context.timeout_ms / 1000.0)

        for symbol in symbols:
            if time.perf_counter() >= deadline:
                timed_out = True
                break
            remaining_ms = int((deadline - time.perf_counter()) * 1000)
            call_ms = min(per_symbol_ms, max(remaining_ms, 50))
            cmd = [rg, "--json", "--word-regexp", "--fixed-strings", *extra_args, symbol, "."]
            try:
                proc = subprocess.run(
                    cmd,
                    cwd=root,
                    capture_output=True,
                    text=True,
                    timeout=call_ms / 1000.0,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                timed_out = True
                continue
            except OSError as exc:
                # Isolate the failure to this symbol only — matches already
                # accumulated for prior symbols in this run remain valid and
                # must not be discarded (interface §4 failure isolation).
                negatives.append(
                    RawNegative(
                        query=symbol,
                        outcome="search_error",
                        searched_roots=[root],
                        diagnostic={"reason": "failed to launch rg", "error": str(exc)},
                    )
                )
                continue

            if proc.returncode not in (0, 1):
                # 2 = rg error; keep going for other symbols but note it
                negatives.append(
                    RawNegative(
                        query=symbol,
                        outcome="search_error",
                        searched_roots=[root],
                        diagnostic={"rg_returncode": proc.returncode, "stderr": proc.stderr[:200]},
                    )
                )
                continue

            matches = _parse_rg_json(proc.stdout, context, symbol, cmd)
            if not matches:
                negatives.append(
                    RawNegative(
                        query=symbol,
                        outcome="no_existing_reference",
                        searched_roots=[root],
                        diagnostic={"symbol_found_in_text": False},
                    )
                )
                continue

            for claim in matches:
                if total >= _MAX_TOTAL_MATCHES:
                    truncated = True
                    break
                items.append(claim)
                total += 1
            if total >= _MAX_TOTAL_MATCHES:
                truncated = True
                break

        diagnostic: dict = {"symbols_searched": len(symbols), "matches": total}
        if truncated:
            diagnostic["truncated"] = True
            diagnostic["cap"] = _MAX_TOTAL_MATCHES
        if timed_out:
            diagnostic["reason"] = "one or more symbol searches hit the collector deadline"
            status = "timeout"
        elif items:
            status = "ok"
        else:
            status = "empty"
            diagnostic.setdefault("reason", "no lexical matches for any extracted symbol")

        return EvidenceResult(
            collector=self.name,
            status=status,
            items=items,
            negative_items=negatives,
            diagnostic=diagnostic,
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
    stdout: str, context: CollectorContext, symbol: str, cmd: list[str]
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
                command=" ".join(cmd),
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
