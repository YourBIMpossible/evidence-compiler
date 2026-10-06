"""Prompt-named secondary repository scopes, gated by an owner allow-list.

A prompt may name an absolute path in another repository ("compare with
F:/Other/src/x.py"). Collection there happens only when the path falls under
exactly one root in the per-repo ``scoping.allowed_roots`` list. Order of
checks is deliberate, so that a non-allowed target never causes a read:

1. candidate paths are taken from prompt text *outside* harness markup blocks;
2. each candidate is normalized lexically (no filesystem access) and matched
   against the canonical allow-list — no match means no further work;
3. only a lexical match is resolved with ``realpath`` (junctions/symlinks) and
   must still fall under the same canonical root, rejecting link escapes;
4. the root itself must be a directory holding ``.git`` (a git work tree).

Anything ambiguous (nested allowed roots, two distinct roots named) or
unavailable is reported as a decision with a reason and collects nothing.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

# decisions
NONE = "none"  # prompt names no absolute path
SAME = "same"  # named path is inside the session root
ALLOWED = "allowed"
NOT_ALLOWED = "not_allowed"
AMBIGUOUS = "ambiguous"
UNAVAILABLE = "unavailable"

_WIN = re.compile(r"""(?<![\w])[A-Za-z]:[\\/][^\s"'`<>|*?]*""")
_POSIX = re.compile(r"""(?:(?<=^)|(?<=[\s("'`]))/[^\s"'`<>|*?]+""")
_QUOTED = re.compile(r"""(["'`])((?:[A-Za-z]:[\\/]|/)[^"'`\r\n<>|*?]*)\1""")
_TRAIL = ".,;:)]}!"


@dataclass(frozen=True)
class Decision:
    status: str
    root: str | None = None
    reason: str = ""
    named: tuple[str, ...] = field(default_factory=tuple)

    def as_diagnostic(self) -> dict[str, object]:
        return {"decision": self.status, "root": self.root, "reason": self.reason, "named": list(self.named)}


def _block_pattern(tags: Iterable[str]) -> re.Pattern[str] | None:
    names = [re.escape(t) for t in tags if t]
    if not names:
        return None
    alt = "|".join(names)
    # a whole open..close block, or an unclosed open tag to end of text
    return re.compile(rf"<({alt})(?:\s[^<>]*)?>.*?(?:</\1(?:\s[^<>]*)?>|\Z)", re.S)


def named_paths(prompt: str, markup_tags: Iterable[str] = ()) -> list[str]:
    """Absolute paths written in the prompt outside harness markup blocks."""
    pat = _block_pattern(markup_tags)
    text = pat.sub(" ", prompt) if pat else prompt
    found: list[str] = []
    spans: list[tuple[int, int]] = []
    for m in _QUOTED.finditer(text):
        found.append(m.group(2))
        spans.append(m.span())
    for rx in (_WIN, _POSIX):
        for m in rx.finditer(text):
            if any(a <= m.start() < b for a, b in spans):
                continue
            found.append(m.group(0).rstrip(_TRAIL))
    out: list[str] = []
    for p in found:
        if p and p not in out:
            out.append(p)
    return out


def _lex(path: str) -> str:
    """Lexical canonical form: forward slashes, ``..`` collapsed, case-folded
    on Windows. Never touches the filesystem."""
    p = path.replace("\\", "/")
    if os.name == "nt" and re.match(r"^/[A-Za-z]/", p):
        p = f"{p[1]}:/{p[3:]}"  # MSYS form /f/x -> f:/x
    p = os.path.normpath(p).replace("\\", "/")
    return os.path.normcase(p).replace("\\", "/").rstrip("/") or "/"


def _under(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip("/") + "/")


def canonical_roots(roots: Iterable[str], realpath: Callable[[str], str] = os.path.realpath) -> list[str]:
    """Owner allow-list entries, link-resolved and lexically normalized."""
    out: list[str] = []
    for r in roots:
        if not r:
            continue
        c = _lex(realpath(_lex(r)))
        if c not in out:
            out.append(c)
    return out


def decide(
    prompt: str,
    session_root: str,
    allowed_roots: Iterable[str],
    *,
    markup_tags: Iterable[str] = (),
    realpath: Callable[[str], str] = os.path.realpath,
    isdir: Callable[[str], bool] = os.path.isdir,
    exists: Callable[[str], bool] = os.path.exists,
) -> Decision:
    names = named_paths(prompt, markup_tags)
    if not names:
        return Decision(NONE)
    session = _lex(realpath(_lex(session_root)))
    allowed = canonical_roots(allowed_roots, realpath)

    targets: set[str] = set()
    rejected: list[str] = []
    for name in names:
        lex = _lex(name)
        if _under(lex, session):
            continue
        hits = [r for r in allowed if _under(lex, r)]
        if not hits:
            rejected.append(name)  # no filesystem access for this candidate
            continue
        if len(hits) > 1:
            return Decision(AMBIGUOUS, reason="path matches nested allowed roots", named=tuple(names))
        real = _lex(realpath(lex))
        if not _under(real, hits[0]):
            rejected.append(name)  # link/junction escapes the allowed root
            continue
        if _under(real, session):
            continue
        targets.add(hits[0])

    if len(targets) > 1:
        return Decision(AMBIGUOUS, reason="prompt names more than one secondary root", named=tuple(names))
    if not targets:
        if rejected:
            return Decision(NOT_ALLOWED, reason="named path is not under an allowed root", named=tuple(rejected))
        return Decision(SAME, root=session, named=tuple(names))
    root = targets.pop()
    if _under(session, root):
        return Decision(AMBIGUOUS, root=root, reason="session root is nested inside the allowed root", named=tuple(names))
    if not isdir(root):
        return Decision(UNAVAILABLE, root=root, reason="allowed root is not a directory", named=tuple(names))
    if not exists(root + "/.git"):
        return Decision(UNAVAILABLE, root=root, reason="allowed root is not a git work tree", named=tuple(names))
    reason = "" if not rejected else f"{len(rejected)} other named path(s) not under an allowed root"
    return Decision(ALLOWED, root=root, reason=reason, named=tuple(names))
