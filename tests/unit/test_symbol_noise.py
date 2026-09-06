"""Symbol-noise controls observed in Window 2 dogfood (W3 improvement pass).

Noise classes seen: sentence-initial capitalized prose words (``There``,
``Before``, ``Check``), the repository's own name, generic tool words
(``Monitor``), and harness/system-notification text on the prompt channel.
Every control here is a counterexample-tested ranking or rejection — the
Phase 1B compound behavior (``X-Forwarded-For``) is preserved untouched.
"""

from __future__ import annotations

from evidence_compiler.scoping import (
    CATEGORY_RANK,
    build_task,
    classify_prompt_source,
    extract_symbol_details,
    extract_symbols,
)


def _reason(details, value):
    for d in details:
        if d["value"] == value:
            return d["reason"]
    return None


# -- sentence-initial prose ------------------------------------------------


def test_sentence_initial_capitalized_words_rejected():
    prompt = "There is a bug. Before that happened! Check the AlphaService path? Never mind:\nMark it done."
    details = extract_symbol_details(prompt)
    for word in ("There", "Before", "Check", "Never", "Mark"):
        assert _reason(details, word) == "sentence_initial", word
    assert extract_symbols(prompt) == ["AlphaService"]


def test_mid_sentence_capitalized_word_kept_but_ranked_lowest():
    symbols = extract_symbols("compute_alpha fails when Monitor restarts")
    assert symbols == ["compute_alpha", "Monitor"]
    details = extract_symbol_details("compute_alpha fails when Monitor restarts")
    assert _reason(details, "Monitor") == "capitalized"
    assert CATEGORY_RANK["capitalized"] < CATEGORY_RANK["snake"]


def test_bullet_and_line_initial_words_are_sentence_initial():
    details = extract_symbol_details("- Yeah that's odd\n* Maybe later\nReally AlphaService")
    for word in ("Yeah", "Maybe", "Really"):
        assert _reason(details, word) == "sentence_initial", word


# -- protected identifiers ---------------------------------------------------


def test_http_header_compounds_preserved():
    prompt = "Check the X-Forwarded-For and If-Modified-Since handling."
    symbols = extract_symbols(prompt)
    assert "X-Forwarded-For" in symbols
    assert "If-Modified-Since" in symbols
    assert "x_forwarded_for" in symbols
    assert "if_modified_since" in symbols
    assert "Check" not in symbols


def test_code_shaped_tokens_survive_and_outrank_prose():
    prompt = "Why does `retry_policy` in model_policy.py break AlphaService.run() with PushNotification"
    symbols = extract_symbols(prompt)
    assert symbols[0] == "retry_policy"           # backticked wins
    assert "model_policy.py" in symbols          # path-like retained
    assert "AlphaService.run" in symbols
    assert symbols.index("PushNotification") > symbols.index("model_policy.py")


# -- repo self-name / config ignore -----------------------------------------


def test_repo_self_name_rejected():
    details = extract_symbol_details("BIMpossible crashes in AlphaService", repository_name="BIMpossible")
    assert _reason(details, "BIMpossible") == "repo_self_name"
    assert extract_symbols("bimpossible-workspace docs", repository_name="BIMpossible_Workspace") == []


def test_config_ignore_list_is_case_insensitive():
    details = extract_symbol_details("Revit crashed in AlphaService", ignore_symbols=["revit"])
    assert _reason(details, "Revit") == "ignored_by_config"
    assert extract_symbols("Revit crashed in AlphaService", ignore_symbols=["revit"]) == ["AlphaService"]


def test_duplicate_normalized_tokens_collapse():
    details = extract_symbol_details("AlphaService and alphaservice and ALPHASERVICE")
    selected = [d["value"] for d in details if d["selected"]]
    assert selected == ["AlphaService"]
    assert _reason(details, "alphaservice") in ("duplicate_normalized", "no_symbol_shape")


# -- bounded selection with explainable metadata -----------------------------


def test_cap_prefers_rank_over_prompt_order():
    prose = " ".join(f"Word{i}Thing" for i in range(20))  # 20 camel candidates
    prompt = prose + " then `the_one` breaks"
    symbols = extract_symbols(prompt)
    assert len(symbols) == 12
    assert symbols[0] == "the_one"
    details = extract_symbol_details(prompt)
    assert any(d["reason"] == "over_cap" for d in details)
    assert all({"value", "category", "rank", "selected", "reason"} <= d.keys() for d in details)


def test_details_never_contain_prompt_text():
    prompt = "Secret plan: rotate the AlphaService key tonight"
    details = extract_symbol_details(prompt)
    assert all(" " not in d["value"] for d in details)
    assert not any(prompt in str(d) for d in details)


# -- harness / system traffic ------------------------------------------------


HARNESS = (
    "<task-notification>\n<status>completed</status>\n"
    "<output-file>C:\\Users\\someone\\AppData\\Local\\Temp\\claude\\x\\out.txt</output-file>\n"
    "</task-notification>"
)


def test_harness_notification_is_classified_and_not_searched():
    assert classify_prompt_source(HARNESS) == "harness"
    task = build_task(HARNESS, None)
    assert task.source_kind == "harness"
    assert task.extracted_symbols == []
    assert task.symbol_details == []


def test_temp_path_alone_marks_harness():
    assert classify_prompt_source("Background task wrote /tmp/claude/abc/output.txt") == "harness"


def test_human_prompt_stays_human():
    assert classify_prompt_source("Why does AlphaService.run crash?") == "human"
    task = build_task("Why does AlphaService.run crash?", None, repository_root="F:/Repo")
    assert task.source_kind == "human"
    assert task.extracted_symbols == ["AlphaService.run"]  # "run" is a stopword member
    assert task.symbol_details[0]["selected"] is True
