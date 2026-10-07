"""Harness markup tag tokens are removed before symbol extraction (D2a)."""

from __future__ import annotations

from evidence_compiler.config import DEFAULT_CONFIG, Config
from evidence_compiler.scoping import build_task, extract_symbols, strip_markup_tags

TAGS = tuple(DEFAULT_CONFIG["scoping"]["markup_tags"])


def test_enclosed_code_kept_tag_removed() -> None:
    prompt = 'Fix this:\n<pasted_content id="21fd">\ndef foo_bar(): return parse_rows()\n</pasted_content id="21fd">'
    syms = extract_symbols(prompt, markup_tags=TAGS)
    assert "pasted_content" not in syms
    assert "foo_bar" in syms and "parse_rows" in syms


def test_without_tags_old_behaviour() -> None:
    prompt = "<pasted_content>def foo_bar(): pass</pasted_content>"
    assert "pasted_content" in extract_symbols(prompt)


def test_literal_identifier_kept() -> None:
    for prompt in ("Why is `pasted_content` None?", "x = pasted_content + 1", "call pasted_content() here"):
        assert "pasted_content" in extract_symbols(prompt, markup_tags=TAGS), prompt


def test_unclosed_and_nested() -> None:
    assert "pasted_content" not in extract_symbols("<pasted_content>load_items here", markup_tags=TAGS)
    prompt = "<pasted_content><command-args>run_fast_path</command-args></pasted_content>"
    assert extract_symbols(prompt, markup_tags=TAGS) == ["run_fast_path"]


def test_unlisted_tag_kept() -> None:
    assert "WidgetPanel" in extract_symbols("render <WidgetPanel> now", markup_tags=TAGS)


def test_offsets_preserved() -> None:
    text = '<pasted_content id="x">abc</pasted_content>'
    out = strip_markup_tags(text, TAGS)
    assert len(out) == len(text) and out.strip() == "abc"


def test_prompt_hash_unchanged() -> None:
    prompt = "<pasted_content>def foo_bar(): pass</pasted_content>"
    a = build_task(prompt, None)
    b = build_task(prompt, None, markup_tags=TAGS)
    assert a.raw_prompt_hash == b.raw_prompt_hash
    assert "pasted_content" in a.extracted_symbols and "pasted_content" not in b.extracted_symbols


def test_config_override_and_bad_value() -> None:
    assert Config().markup_tags == tuple(sorted(TAGS))
    assert Config(data={"scoping": {"markup_tags": ["x-tag"]}}).markup_tags == ("x-tag",)
    assert Config(data={"scoping": {"markup_tags": "nope"}}).markup_tags == tuple(TAGS)
    assert Config(data={"scoping": {"markup_tags": []}}).markup_tags == ()
