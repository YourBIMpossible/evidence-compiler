"""Agent-message traffic on the prompt channel (WORKLOG N7).

Claude Code Desktop delivers a teammate/subagent message as one whole
``<agent-message from="...">...</agent-message>`` block on
``UserPromptSubmit`` although no person typed it. Natural packets
``2c0d975d``, ``304249ed``, ``1a0b2783`` (pre-N6) and 15 more after the N6
install (2026-10-11/12) were classified ``human``, searched and injected.
Every observed instance was a single block with a ``from`` attribute and
nothing after the closing tag. The fixtures keep that shape, redacted.
"""

from __future__ import annotations

from evidence_compiler.config import DEFAULT_CONFIG
from evidence_compiler.scoping import build_task, classify_prompt_source, extract_symbol_details
from evidence_compiler.secondary import named_paths

TAGS = tuple(DEFAULT_CONFIG["scoping"]["markup_tags"])

AGENT_OPEN = '<agent-message from="review-helper">'
AGENT = AGENT_OPEN + "\nFinished: `widget_store` passes; see ReportBuilder.\n</agent-message>"
# Every token the wrapper yields when the tag is not stripped.
WRAPPER_TOKENS = {"agent", "message", "from", "review", "helper", "review-helper"}


def test_agent_message_is_harness_and_not_searched() -> None:
    assert classify_prompt_source(AGENT) == "harness"
    task = build_task(AGENT, None, markup_tags=TAGS)
    assert task.source_kind == "harness"
    assert task.extracted_symbols == [] and task.symbol_details == []


def test_surrounding_whitespace_still_harness() -> None:
    assert classify_prompt_source("\n  " + AGENT + "\r\n") == "harness"


def test_bare_tag_without_attributes_is_harness() -> None:
    assert classify_prompt_source("<agent-message>\nok\n</agent-message>") == "harness"


def test_human_and_mixed_prompts_stay_human() -> None:
    for prompt in (
        "Why are <agent-message> blocks classified human? See classify_prompt_source.",
        "Check the agent-message wrapper handling in scoping.py",
        "Here is what arrived:\n" + AGENT,
        AGENT + "\nPlease act on that and update `widget_store`.",
        AGENT + "\n" + AGENT,
        'Review this:\n<pasted_content id="1">\n' + AGENT + '\n</pasted_content id="1">',
        "<agent-message-log>\nnot an envelope\n</agent-message-log>",
        "<agent-message from=\"x\">\nunclosed",
    ):
        assert classify_prompt_source(prompt) == "human", prompt


def test_wrapper_tokens_are_not_candidates_in_human_prompts() -> None:
    prompt = "Here is what arrived:\n" + AGENT
    values = {d["value"] for d in extract_symbol_details(prompt, None, markup_tags=TAGS)}
    assert {"widget_store", "ReportBuilder"} <= values
    assert not values & WRAPPER_TOKENS, values & WRAPPER_TOKENS


def test_wrapper_tokens_leak_without_the_default_tag() -> None:
    # Guards the test above: the tag tokens are real candidates when the tag
    # is not configured, so their absence is the stripping's doing.
    prompt = "Here is what arrived:\n" + AGENT
    values = {d["value"] for d in extract_symbol_details(prompt, None, markup_tags=())}
    assert values & WRAPPER_TOKENS


def test_default_markup_tags_include_agent_message() -> None:
    assert "agent-message" in TAGS


def test_paths_inside_an_agent_block_are_not_named_paths() -> None:
    prompt = "Answer the helper:\n" + AGENT_OPEN + "\nsee F:\\Other\\notes.md\n</agent-message>"
    assert named_paths(prompt, TAGS) == []


def test_cross_session_envelopes_unchanged() -> None:
    peer = '<cross-session-message from="p">\nhi\n</cross-session-message>'
    assert classify_prompt_source(peer) == "harness"
    assert classify_prompt_source("[Cross-session idle notice] done") == "harness"
