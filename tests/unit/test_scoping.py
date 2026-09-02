"""Prompt scoping: intent, symbol extraction, token estimate."""

from __future__ import annotations

import hashlib

from evidence_compiler import scoping


def test_intent_debugging():
    assert scoping.infer_intent("There's a bug where compute_alpha crashes") == "debugging"


def test_intent_refactor():
    assert scoping.infer_intent("Please refactor AlphaService to be simpler") == "refactor"


def test_intent_implementation():
    assert scoping.infer_intent("implement a new caching layer") == "implementation"


def test_intent_unknown():
    assert scoping.infer_intent("hello there") == "unknown"


def test_symbol_extraction_picks_identifiers():
    syms = scoping.extract_symbols("Why does AlphaService.run call compute_alpha()?")
    assert "AlphaService.run" in syms or "AlphaService" in syms
    assert "compute_alpha" in syms


def test_dotted_symbol_derives_member_not_head():
    # Phase 1B: a dotted member expression derives only the member name (with
    # the prose guard — "run" is a stopword, so nothing is derived here). The
    # leading identifier is no longer auto-derived; generic class names were
    # the flood vector in dogfooding.
    syms = scoping.extract_symbols("Why does AlphaService.run break?")
    assert syms == ["AlphaService.run"]
    syms2 = scoping.extract_symbols("Why does AlphaService.compute_all break?")
    assert syms2 == ["AlphaService.compute_all", "compute_all"]


def test_dotted_member_derivation_favors_recall():
    # The dot is the symbol signal, so a derived member uses a looser rule than
    # a standalone token: a call/backtick target, or any non-stopword
    # identifier of length >= 3. A lowercase method name with no underscore or
    # camelCase hump (which _is_symbolish alone would reject) must still be
    # derived so ripgrep can match its ``def`` — this is the recall the shared
    # standalone validator was silently dropping.
    assert scoping.extract_symbols("why does Parser.tokenize fail") == [
        "Parser.tokenize",
        "tokenize",
    ]
    # A generic lowercase member ("data") is the accepted, bounded false
    # positive that comes with favouring recall — derived, not rejected.
    assert scoping.extract_symbols("How does Response.data get parsed?") == [
        "Response.data",
        "data",
    ]
    # A short member ("at", length 2, and a stopword) is admissible only via
    # the call-site shortcut, and is still derived because of the call.
    assert scoping.extract_symbols("Why does Frame.at() misbehave?") == ["Frame.at", "at"]


def test_symbol_extraction_drops_prose():
    syms = scoping.extract_symbols("please help me understand the code here")
    assert syms == []


def test_symbol_extraction_is_deterministic():
    prompt = "Trace OriginSystem through build_service and AlphaService"
    assert scoping.extract_symbols(prompt) == scoping.extract_symbols(prompt)


def test_backticked_symbols_included():
    syms = scoping.extract_symbols("look at `x` and `do_thing`")
    assert "do_thing" in syms


def test_token_estimate_monotonic():
    assert scoping.estimate_tokens("") == 0
    assert scoping.estimate_tokens("a b c") <= scoping.estimate_tokens("a b c d e f g")


def test_prompt_hash_ordinary_unicode_unchanged():
    # Pins prompt_hash to plain strict-utf8 sha256 for well-formed input, so
    # the surrogatepass error handler never changes output for normal prompts.
    prompt = "Explain why café ordering fails 🔥"
    expected = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    assert scoping.prompt_hash(prompt) == expected


def test_prompt_hash_unpaired_surrogate_does_not_raise():
    prompt = "before \udc9d after"
    scoping.prompt_hash(prompt)  # must not raise UnicodeEncodeError


def test_prompt_hash_unpaired_surrogate_is_deterministic():
    prompt = "before \udc9d after"
    first = scoping.prompt_hash(prompt)
    second = scoping.prompt_hash(prompt)
    assert first == second
    assert len(first) == 64
