"""Deterministic prompt scoping: intent classification and symbol extraction.

Pure functions of the prompt text (and optional active file / repository
name / ignore list). No clock, no network, no model — same input always
yields the same scope, which keeps the downstream packet reproducible.

Symbol extraction is a *ranked, bounded selection*: every candidate token is
categorized by its technical shape, ranked, and the top ``_MAX_SYMBOLS`` are
searched. Each candidate's category, rank, and selection/skip reason is
reported (:func:`extract_symbol_details`) so a packet can explain why a
symbol was or was not searched without storing prompt text.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from itertools import pairwise
from typing import Any, Iterable, Iterator

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
#
# Unicode-aware on purpose: ``\w`` in a ``str`` pattern matches every letter
# and digit the Unicode database knows (plus ``_``), so ``fenster_größe``,
# ``Größe.berechnen`` and ``señal_activa`` are single identifiers instead of
# the ASCII fragments ``fenster_gr`` / ``e`` an ``[A-Za-z]`` class produced.
# ``[^\W\d]`` is "a word character that is not a digit" — the identifier
# start rule (letter or underscore) in any script.
_IDENT_START = r"[^\W\d]"
_IDENT = rf"{_IDENT_START}\w*"
_SYMBOL_RE = re.compile(rf"{_IDENT}(?:\.{_IDENT})*")

# Hyphenated technical compounds (``User-Agent``, ``Content-Type``,
# ``X-Request-Id``): every component starts uppercase, which separates header/
# protocol-style terms from prose hyphenations like "well-known". Hyphenated
# spans are matched first so a compound is captured whole instead of being
# split into generic fragments (Phase 1B); a span whose components do not all
# start uppercase is re-scanned as plain identifiers (see :func:`_tokens`).
_COMPOUND_PART = rf"{_IDENT_START}\w*"
_HYPHEN_SPAN_RE = re.compile(rf"{_COMPOUND_PART}(?:-{_COMPOUND_PART})+")
_TOKEN_RE = re.compile(rf"{_HYPHEN_SPAN_RE.pattern}|{_SYMBOL_RE.pattern}")
_CALL_RE = re.compile(rf"({_IDENT})\s*\(")

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

# Bounded number of candidate records kept in ``task.symbol_details`` (the
# selected ones always fit; rejected ones fill the remainder in prompt order).
_MAX_DETAILS = 32

# Symbol categories, ranked. Higher searches first and survives the cap.
CATEGORY_RANK: dict[str, int] = {
    "backticked": 100,      # author quoted it: explicit intent
    "called": 95,           # followed by "(": a call site
    "path": 90,             # file-like: config.yaml, model_policy.py
    "dotted": 85,           # AlphaService.run, Response.iter_content
    "compound": 85,         # User-Agent, X-Forwarded-For (Phase 1B)
    "compound_snake": 80,   # user_agent, derived from the compound
    "snake": 80,            # compute_alpha
    "camel": 75,            # AlphaService, iterContent
    "member": 60,           # member derived from a dotted name
    "capitalized": 30,      # bare Capitalized word mid-sentence: weakest shape
}

SKIP_REASONS = (
    "stopword",
    "too_short",
    "no_symbol_shape",
    "sentence_initial",
    "repo_self_name",
    "ignored_by_config",
    "duplicate_normalized",
    "over_cap",
    "harness_prompt",
)

_PATH_EXTENSIONS = frozenset(
    "py cs ts tsx js jsx mjs json yaml yml md txt csproj sln xml ps1 sh bat toml cfg ini "
    "html css rs go java kt swift rb php c h cpp hpp sql xaml rfa rvt rte dyn svg png".split()
)

# Text the hook receives on the prompt channel that no person typed: Claude
# Code task notifications, system reminders, CI monitor events, and the
# harness temp-file paths they carry.
_HARNESS_MARKERS = (
    "<task-notification",
    "<system-reminder",
    "<ci-monitor-event",
    "<local-command-stdout",
    "<command-name>",
)
_HARNESS_PATH_RE = re.compile(
    r"AppData[\\/]Local[\\/]Temp[\\/]claude[\\/]|[\\/]tmp[\\/]claude[\\/]", re.IGNORECASE
)

SOURCE_KINDS = ("human", "harness")


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


def classify_prompt_source(prompt: str) -> str:
    """``harness`` when the text carries tool/system-notification markers a
    person would not type; ``human`` otherwise. Deterministic and cheap."""
    text = prompt or ""
    if any(marker in text for marker in _HARNESS_MARKERS):
        return "harness"
    if _HARNESS_PATH_RE.search(text):
        return "harness"
    return "human"


def normalize_prompt_text(prompt: str) -> str:
    r"""Canonical (NFC) form of ``prompt`` for tokenization.

    Decomposed input (``o`` + combining diaeresis) would otherwise split an
    identifier at the combining mark, which ``\w`` does not match. NFC is the
    only normalization applied: it never changes which characters a token is
    made of beyond canonical equivalence, so the token is still what the
    author typed and what ripgrep should be asked for. Case folding, NFKC
    (``ﬁ`` → ``fi``) and transliteration are deliberately *not* applied — they
    would search for text that is not in the prompt.
    """
    return unicodedata.normalize("NFC", prompt or "")


def _is_compound(span: str) -> bool:
    """Every hyphen component starts with an uppercase letter."""
    return all(part[:1].isupper() for part in span.split("-"))


def _tokens(text: str) -> Iterator[tuple[str, int]]:
    """Yield ``(token, start)`` for every identifier-shaped token in ``text``.

    A hyphenated span is yielded whole only when it is a technical compound
    (``User-Agent``); otherwise (``well-known``, ``größen-abhängig``) each
    component is yielded on its own, exactly as it would be without the
    hyphen. Pure and order-preserving.
    """
    for match in _TOKEN_RE.finditer(text):
        token = match.group(0)
        if "-" not in token or _is_compound(token):
            yield token, match.start()
        else:
            for part in _SYMBOL_RE.finditer(token):
                yield part.group(0), match.start() + part.start()


# --------------------------------------------------------------------------
# Symbol extraction
# --------------------------------------------------------------------------


def extract_symbols(
    prompt: str,
    active_file: str | None = None,
    *,
    repository_name: str | None = None,
    ignore_symbols: Iterable[str] = (),
) -> list[str]:
    """Selected candidate code symbols, best-ranked first (ties in prompt order).

    See :func:`extract_symbol_details` for the categorized, explainable form.
    """
    return [
        d["value"]
        for d in extract_symbol_details(
            prompt, active_file, repository_name=repository_name, ignore_symbols=ignore_symbols
        )
        if d["selected"]
    ]


def extract_symbol_details(
    prompt: str,
    active_file: str | None = None,
    *,
    repository_name: str | None = None,
    ignore_symbols: Iterable[str] = (),
) -> list[dict[str, Any]]:
    """Categorize, rank, and select symbol candidates from ``prompt``.

    Returns one record per candidate — selected ones first in rank order,
    then rejected ones in prompt order (bounded by ``_MAX_DETAILS``):
    ``{"value", "category", "rank", "selected", "reason"}``. Values are
    single tokens; prompt text is never reproduced.
    """
    if not prompt:
        return []
    prompt = normalize_prompt_text(prompt)

    called = set(_CALL_RE.findall(prompt))
    backticked = set(re.findall(r"`([^`]+)`", prompt))
    self_name = (repository_name or "").strip().lower()
    self_keys = {self_name, self_name.replace("-", "_"), self_name.replace("_", "-")} - {""}
    ignored = {str(v).strip().lower() for v in ignore_symbols if str(v).strip()}

    candidates: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    seen_exact: set[str] = set()
    seen_norm: set[str] = set()

    def _consider(value: str, category: str, *, sentence_initial: bool = False) -> None:
        if value in seen_exact:
            return
        seen_exact.add(value)
        record = {"value": value, "category": category, "rank": CATEGORY_RANK[category]}
        norm = value.lower()
        reason: str | None = None
        if norm in self_keys:
            reason = "repo_self_name"
        elif norm in ignored:
            reason = "ignored_by_config"
        elif category == "capitalized" and sentence_initial:
            reason = "sentence_initial"
        elif norm in seen_norm:
            reason = "duplicate_normalized"
        if reason:
            rejected.append({**record, "selected": False, "reason": reason})
            return
        seen_norm.add(norm)
        candidates.append(record)

    def _reject(value: str, category: str, reason: str) -> None:
        if value in seen_exact:
            return
        seen_exact.add(value)
        rejected.append(
            {"value": value, "category": category, "rank": 0, "selected": False, "reason": reason}
        )

    for token, start in _tokens(prompt):
        if token in seen_exact:
            continue
        if "-" in token:
            # Hyphenated compound: preserve it whole and derive exactly one
            # structural candidate — the normalized snake_case identifier
            # (``User-Agent`` → ``user_agent``). The hyphen components are
            # never admitted as peer symbols: splitting them into generic
            # words was the flood vector behind dogfood prompts 5/8/10.
            #
            # Deliberately unconditional: unlike the plain-token branch below,
            # this does not run the token through the stopword check. Real
            # technical compounds routinely contain a component that is also
            # an English stopword — ``X-Forwarded-For`` ("for"),
            # ``If-Modified-Since`` / ``If-None-Match`` ("if") — so rejecting
            # on stopword-component would drop legitimate HTTP-header-style
            # identifiers (a false negative, silently losing evidence). The
            # accepted trade-off is the reverse, bounded false positive: prose
            # that happens to be Title-Case-hyphenated (``Off-By-One``) can
            # still take one of the 12 symbol slots and one ripgrep query,
            # which downstream ranking / no-match filtering absorbs.
            _consider(token, "compound")
            _consider(token.lower().replace("-", "_"), "compound_snake")
            continue

        category, skip = _categorize(token, called, backticked)
        if skip:
            _reject(token, category, skip)
            continue
        _consider(
            token,
            category,
            sentence_initial=category == "capitalized" and _is_sentence_initial(prompt, start),
        )
        # A dotted member expression (``Response.iter_content``) rarely
        # appears verbatim in source; derive only the member name so the
        # definition (``def iter_content``) is matchable. The leading
        # identifier is deliberately not derived — class names like
        # ``Response`` are generic enough to flood the lexical lane.
        #
        # The dot is itself the symbol signal, so the member is admitted
        # on a looser rule than a standalone token: any call/backtick
        # target, or a non-stopword identifier of length >= 3. Requiring
        # the member to independently pass the shape check would drop real
        # lowercase method names (``Parser.tokenize`` -> ``tokenize``,
        # ``db.connect`` -> ``connect``) that carry no underscore or
        # camelCase hump, losing exactly the ``def`` match this derivation
        # exists to find. A generic member (``Response.data`` -> ``data``)
        # is the accepted, bounded false positive — one of 12 slots and one
        # ripgrep query, absorbed by downstream ranking / no-match filtering.
        if category == "dotted":
            member = token.rsplit(".", 1)[1]
            if (
                member in called
                or member in backticked
                or (len(member) >= 3 and member.lower() not in _STOPWORDS)
            ):
                _consider(member, "member")

    # Stable selection: rank desc, then prompt order (list order is prompt order).
    ordered = sorted(enumerate(candidates), key=lambda pair: (-pair[1]["rank"], pair[0]))
    selected: list[dict[str, Any]] = []
    over_cap: list[dict[str, Any]] = []
    for _, record in ordered:
        if len(selected) < _MAX_SYMBOLS:
            selected.append({**record, "selected": True, "reason": record["category"]})
        else:
            over_cap.append({**record, "selected": False, "reason": "over_cap"})

    details = selected + over_cap + rejected
    return details[:_MAX_DETAILS]


def _categorize(token: str, called: set[str], backticked: set[str]) -> tuple[str, str | None]:
    """Return ``(category, skip_reason)``; ``skip_reason`` is ``None`` when admitted."""
    if token in backticked:
        return "backticked", None
    if token in called:
        return "called", None
    low = token.lower()
    if low in _STOPWORDS:
        return "capitalized" if token[0].isupper() else "snake", "stopword"
    if len(token) < 3:
        return "snake", "too_short"
    if "." in token:
        head, _, tail = token.rpartition(".")
        if tail.lower() in _PATH_EXTENSIONS and "." not in head and not head[0].isupper():
            return "path", None
        return "dotted", None
    if "_" in token:
        return "snake", None
    if _has_case_hump(token):  # camelCase / PascalCase hump
        return "camel", None
    if token[0].isupper() and any(c.islower() for c in token[1:]):  # Capitalized word
        return "capitalized", None
    return "snake", "no_symbol_shape"


def _has_case_hump(token: str) -> bool:
    """A lowercase letter immediately followed by an uppercase one, in any
    script that has case (``iterContent``, ``fensterGröße``, ``señalActiva``)."""
    return any(a.islower() and b.isupper() for a, b in pairwise(token))


def _is_sentence_initial(prompt: str, start: int) -> bool:
    """True when the token at ``start`` opens the text, a line, or a sentence.

    ``There``/``Before``/``Check`` at sentence start were the Window 2 noise
    class: capitalized only by grammar, not by naming. Mid-sentence
    Capitalized words keep their (lowest) rank instead.
    """
    before = prompt[:start]
    stripped = before.rstrip()
    if not stripped:
        return True
    if "\n" in before[len(stripped):]:
        return True
    last = stripped[-1]
    if last in ".!?:;":
        return True
    # bullet / quote openers: "- There", "* There", "\"There"
    if last in "-*>\"'(" and (len(stripped) < 2 or stripped[-2] in " \n"):
        return True
    return False


def _is_symbolish(token: str, called: set[str], backticked: set[str]) -> bool:
    """Backwards-compatible shape check (admitted by :func:`_categorize`)."""
    _, skip = _categorize(token, called, backticked)
    return skip is None


# --------------------------------------------------------------------------
# Task / scope assembly
# --------------------------------------------------------------------------


def build_task(
    prompt: str,
    active_file: str | None,
    *,
    repository_root: str | None = None,
    ignore_symbols: Iterable[str] = (),
) -> Task:
    ph = prompt_hash(prompt)
    source_kind = classify_prompt_source(prompt)
    if source_kind == "harness":
        # Harness/system text is not a task: nothing to search, and the
        # packet records why so review tooling can separate the traffic.
        return Task(
            raw_prompt_hash=ph,
            intent="unknown",
            active_file=active_file,
            extracted_symbols=[],
            source_kind=source_kind,
            symbol_details=[],
        )
    repo_name = _basename(repository_root) if repository_root else None
    details = extract_symbol_details(
        prompt, active_file, repository_name=repo_name, ignore_symbols=ignore_symbols
    )
    return Task(
        raw_prompt_hash=ph,
        intent=infer_intent(prompt),
        active_file=active_file,
        extracted_symbols=[d["value"] for d in details if d["selected"]],
        source_kind=source_kind,
        symbol_details=details,
    )


def _basename(path: str) -> str:
    return path.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]


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
