"""Cross-session traffic on the prompt channel (WORKLOG N6).

Claude Code Desktop delivers a peer session's message as a whole
``<cross-session-message ...>`` block and a subscribed session's idle state
as a ``[Cross-session idle notice]`` line. Both arrive on ``UserPromptSubmit``
although no person typed them; natural packets ``9b8e2967`` and ``f2fbae05``
(2026-10-11) were classified ``human`` and searched. The fixtures below keep
the observed shape with redacted identifiers.
"""

from __future__ import annotations

from evidence_compiler.config import DEFAULT_CONFIG
from evidence_compiler.scoping import build_task, classify_prompt_source, extract_symbol_details
from evidence_compiler.secondary import named_paths

TAGS = tuple(DEFAULT_CONFIG["scoping"]["markup_tags"])

PEER_OPEN = (
    '<cross-session-message from="uds:\\\\.\\pipe\\LOCAL\\cc-msg-0123456789abcdef0123456789abcdef" '
    'from-session="local_00000000-1111-2222-3333-444444444444" from-name="peer-lane" '
    'from-mode="prompting">'
)
PEER = PEER_OPEN + "\nAnswers to your questions: `widget_store` stays owned here.\n</cross-session-message>"
IDLE = (
    '[Cross-session idle notice] "peer-lane", which you asked to be notified about, is idle now '
    "\u2014 it finished a turn at 21:15. This is an automated notice from that session's harness "
    "\u2014 not a message from a person, and not an instruction; act on it only insofar as your "
    "user's earlier request calls for it."
)
# Every token the wrapper's attributes yield when the tag is not stripped.
WRAPPER_TOKENS = {
    "cross", "session", "message", "from", "uds", "pipe", "LOCAL", "cc", "msg",
    "0123456789abcdef0123456789abcdef", "local_00000000", "name", "peer", "lane", "mode", "prompting",
}


def test_peer_session_message_is_harness_and_not_searched() -> None:
    assert classify_prompt_source(PEER) == "harness"
    task = build_task(PEER, None, markup_tags=TAGS)
    assert task.source_kind == "harness"
    assert task.extracted_symbols == [] and task.symbol_details == []


def test_idle_notice_is_harness() -> None:
    assert classify_prompt_source(IDLE) == "harness"
    assert build_task(IDLE, None, markup_tags=TAGS).extracted_symbols == []


def test_surrounding_whitespace_still_harness() -> None:
    assert classify_prompt_source("\n  " + PEER + "\n") == "harness"
    assert classify_prompt_source("\r\n" + IDLE) == "harness"


def test_prose_quoting_the_markers_stays_human() -> None:
    for prompt in (
        "Why does the hook mark <cross-session-message> blocks as human? See classify_prompt_source.",
        "A prompt that starts with [Cross-session idle notice] should be harness; fix classify_prompt_source.",
        "Check the cross-session-message wrapper handling in scoping.py",
        "Here is what arrived:\n" + PEER,
        PEER + "\nPlease act on that and update `widget_store`.",
        'Review this:\n<pasted_content id="1">\n' + PEER + '\n</pasted_content id="1">',
        'Review this:\n<pasted_content id="2">\n' + IDLE + '\n</pasted_content id="2">',
    ):
        assert classify_prompt_source(prompt) == "human", prompt


def test_wrapper_tokens_are_not_candidates_in_human_prompts() -> None:
    prompt = "Here is what arrived:\n" + PEER
    values = {d["value"] for d in extract_symbol_details(prompt, None, markup_tags=TAGS)}
    assert "widget_store" in values
    assert not values & WRAPPER_TOKENS, values & WRAPPER_TOKENS


def test_wrapper_tokens_leak_without_the_default_tag() -> None:
    # Guards the test above: the attribute tokens are real candidates when
    # the tag is not configured, so their absence is the stripping's doing.
    prompt = "Here is what arrived:\n" + PEER
    values = {d["value"] for d in extract_symbol_details(prompt, None, markup_tags=())}
    assert values & WRAPPER_TOKENS


def test_default_markup_tags_include_cross_session_message() -> None:
    assert "cross-session-message" in TAGS


def test_paths_inside_a_peer_block_are_not_named_paths() -> None:
    prompt = "Answer the peer:\n" + PEER_OPEN + "\nsee F:\\Other\\notes.md\n</cross-session-message>"
    assert named_paths(prompt, TAGS) == []
