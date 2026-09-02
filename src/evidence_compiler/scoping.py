"""Deterministic prompt scoping: intent classification and symbol extraction.

Pure functions of the prompt text (and optional active file). No clock, no
network, no model — same input always yields the same scope, which keeps the
downstream packet reproducible.
"""

from __future__ import annotations

import hashlib
import re

from .packet import Scope, Task

# Keyword → intent. First matching group wins; order is significant.
_INTENT_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("debugging", ("bug", "debug", "error", "traceback", "exception", "crash", "fails",
                   "failing", "broken", "regression", "stack trace", "why is", "why does")),
    ("refactor", ("refactor", "rename", "clean up", "cleanup", "extract", "simplify",
                  "restructure", "deduplicate", "move ")),
    ("implementation", ("implement", "add ", "create", "build", "write ", "feature",
                        "support for", "new ", "wire up")),
    ("discovery", ("where is", "how does", "what calls", "explain", "understand",
                   "find ", "locate", "trace", "walk me through")),
]

# Identifier-ish tokens: dotted paths, CamelCase, snake_case, calls.
_SYMBOL_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")

# Hyphenated technical compounds (``User-Agent``, ``Content-Type``,
# ``X-Request-Id``): every component starts uppercase, which separates header/
# protocol-style terms from prose hyphenations like "well-known". Tried before
# _SYMBOL_RE so the compound is captured whole instead of being split into
# generic fragments (Phase 1B).
_COMPOUND_PART = r"[A-Z][A-Za-z0-9]*"
_TOKEN_RE = re.compile(
    rf"{_COMPOUND_PART}(?:-{_COMPOUND_PART})+"
    r"|[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*"
)

# Common English / prose words to drop so they are not treated as symbols.
_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "if", "then", "else", "for", "while", "with",
    "this", "that", "these", "those", "is", "are", "was", "were", "be", "been", "being",
    "to", "of", "in", "on", "at", "by", "from", "as", "it", "its", "into", "about",
    "why", "how", "what", "where", "when", "which", "who", "does", "do", "did", "not",
    "can", "could", "should", "would", "will", "please", "help", "me", "my", "you",
    "add", "fix", "make", "use", "using", "get", "set", "run", "call", "called",
    "code", "file", "files", "function", "method", "class", "test", "tests", "bug",
    "error", "issue", "line", "lines", "value", "return", "returns", "new", "old",
}

_MAX_SYMBOLS = 12


def prompt_hash(prompt: str) -> str:
    # surrogatepass: prompt text may contain unpaired UTF-16 surrogate code
    # points (e.g. from truncated multi-byte input upstream). Strict "utf-8"
    # raises UnicodeEncodeError on those; surrogatepass encodes them losslessly
    # so the hash stays deterministic without silently dropping prompt data.
    return hashlib.sha256((prompt or "").encode("utf-8", errors="surrogatepass")).hexdigest()


def infer_intent(prompt: str) -> str:
    low = (prompt or "").lower()
    for intent, keywords in _INTENT_KEYWORDS:
        if any(kw in low for kw in keywords):
            return intent
    return "unknown"


def extract_symbols(prompt: str, active_file: str | None = None) -> list[str]:
    """Extract candidate code symbols from the prompt, deterministically ordered.

    Heuristics favour precision over recall: tokens that look like identifiers
    (CamelCase, snake_case, dotted, or appearing next to ``(``) and are not
    common prose words. Preserves first-seen order; caps the count.
    """
    if not prompt:
        return []

    called = set(re.findall(r"([A-Za-z_][A-Za-z0-9_]*)\s*\(", prompt))
    backticked = set(re.findall(r"`([^`]+)`", prompt))

    seen: set[str] = set()
    out: list[str] = []

    def _admit(tok: str) -> None:
        if tok and tok not in seen and len(out) < _MAX_SYMBOLS:
            seen.add(tok)
            out.append(tok)

    for token in _TOKEN_RE.findall(prompt):
        if token in seen:
            continue
        if "-" in token:
            # Hyphenated compound: preserve it whole and derive exactly one
            # structural candidate — the normalized snake_case identifier
            # (``User-Agent`` → ``user_agent``). The hyphen components are
            # never admitted as peer symbols: splitting them into generic
            # words was the flood vector behind dogfood prompts 5/8/10.
            #
            # Deliberately unconditional: unlike the plain-token branch below,
            # this does not run the token through _is_symbolish's stopword
            # check. Real technical compounds routinely contain a component
            # that is also an English stopword — ``X-Forwarded-For`` ("for"),
            # ``If-Modified-Since`` / ``If-None-Match`` ("if") — so rejecting
            # on stopword-component would drop legitimate HTTP-header-style
            # identifiers (a false negative, silently losing evidence). The
            # accepted trade-off is the reverse, bounded false positive: prose
            # that happens to be Title-Case-hyphenated (``Off-By-One``) can
            # still take one of the 12 symbol slots and one ripgrep query,
            # which downstream ranking / no-match filtering absorbs.
            _admit(token)
            _admit(token.lower().replace("-", "_"))
        else:
            if not _is_symbolish(token, called, backticked):
                continue
            _admit(token)
            # A dotted member expression (``Response.iter_content``) rarely
            # appears verbatim in source; derive only the member name so the
            # definition is matchable. The leading identifier is deliberately
            # not derived — class names like ``Response`` are generic enough
            # to flood the lexical lane. The member goes through the same
            # validator as any plain token so the two paths cannot drift.
            if "." in token:
                member = token.rsplit(".", 1)[1]
                if _is_symbolish(member, called, backticked):
                    _admit(member)
        if len(out) >= _MAX_SYMBOLS:
            break
    return out


def _is_symbolish(token: str, called: set[str], backticked: set[str]) -> bool:
    if token in called or token in backticked:
        return True
    low = token.lower()
    if low in _STOPWORDS:
        return False
    if len(token) < 3:
        return False
    if "." in token or "_" in token:
        return True
    if re.search(r"[a-z][A-Z]", token):  # camelCase / PascalCase hump
        return True
    if token[0].isupper() and any(c.islower() for c in token[1:]):  # Capitalized name
        return True
    return False


def build_task(prompt: str, active_file: str | None) -> Task:
    ph = prompt_hash(prompt)
    return Task(
        raw_prompt_hash=ph,
        intent=infer_intent(prompt),
        active_file=active_file,
        extracted_symbols=extract_symbols(prompt, active_file),
    )


def build_scope(task: Task, head: str | None) -> Scope:
    sources: list[str] = []
    if task.active_file:
        sources.append("active_file")
    if task.extracted_symbols:
        sources.append("prompt_symbol")
    if head:
        sources.append("git_diff")

    if task.active_file and task.extracted_symbols:
        confidence = "high"
    elif task.extracted_symbols or task.active_file:
        confidence = "medium"
    else:
        confidence = "low"
    return Scope(confidence=confidence, sources=sources)


def estimate_tokens(text: str) -> int:
    """Deterministic, model-agnostic token estimate (~4 chars/token, min 1/word).

    Kept intentionally simple and reproducible; the budget is a guardrail, not
    an exact accounting of any specific tokenizer.
    """
    if not text:
        return 0
    char_estimate = (len(text) + 3) // 4
    word_estimate = len(text.split())
    return max(char_estimate, word_estimate)
