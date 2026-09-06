"""Unicode-aware symbol extraction (Window 3 field evidence: ``größe``).

Identifier shape is decided by Unicode word characters, not ``[A-Za-z]``, so
German-like, accented-Latin and mixed ASCII/Unicode identifiers are recognised
under the same categories as ASCII ones. Prose in any language is still
rejected by the existing shape rules — a lowercase word is a symbol only when
it carries snake/camel/dotted/path/quoted/called shape. Every ASCII behaviour
covered elsewhere is unchanged; this file adds only the non-ASCII cases.
"""

from __future__ import annotations

import os
import shutil
import unicodedata

import pytest

from evidence_compiler.compiler import compile_packet
from evidence_compiler.scoping import (
    build_task,
    extract_symbol_details,
    extract_symbols,
    normalize_prompt_text,
)

rg_required = pytest.mark.skipif(shutil.which("rg") is None, reason="ripgrep not installed")


def _detail(details, value):
    for d in details:
        if d["value"] == value:
            return d
    return None


# -- recognised identifiers --------------------------------------------------


def test_german_like_snake_dotted_and_called_identifiers():
    prompt = "fix fenster_größe in Fenster.größe_berechnen() please"
    details = extract_symbol_details(prompt)
    assert _detail(details, "fenster_größe")["category"] == "snake"
    assert _detail(details, "Fenster.größe_berechnen")["category"] == "dotted"
    assert _detail(details, "größe_berechnen")["category"] == "member"
    assert set(extract_symbols(prompt)) == {"Fenster.größe_berechnen", "fenster_größe", "größe_berechnen"}


def test_accented_latin_identifiers():
    details = extract_symbol_details("update señal_activa and calcularÁrea() now")
    assert _detail(details, "calcularÁrea")["category"] == "called"
    assert _detail(details, "señal_activa")["category"] == "snake"
    assert _detail(details, "update")["reason"] == "no_symbol_shape"


def test_non_ascii_dotted_member_and_path():
    dotted = extract_symbol_details("Größe.berechnen returns wrong values")
    assert _detail(dotted, "Größe.berechnen")["category"] == "dotted"
    assert _detail(dotted, "berechnen")["category"] == "member"
    path = extract_symbol_details("öffne src/übersicht.py")
    assert _detail(path, "übersicht.py")["category"] == "path"
    assert _detail(path, "öffne")["reason"] == "no_symbol_shape"


def test_mixed_ascii_unicode_camel_case():
    details = extract_symbol_details("fensterGröße and ÜbergangsZone leak")
    assert _detail(details, "fensterGröße")["category"] == "camel"
    assert _detail(details, "ÜbergangsZone")["category"] == "camel"
    assert extract_symbols("fensterGröße and ÜbergangsZone leak") == ["fensterGröße", "ÜbergangsZone"]


def test_backticked_unicode_identifier_is_top_ranked():
    details = extract_symbol_details("check `größe` please")
    assert _detail(details, "größe")["category"] == "backticked"
    assert extract_symbols("check `größe` please") == ["größe"]


# -- prose stays prose ---------------------------------------------------------


def test_lowercase_non_english_prose_is_not_promoted():
    assert extract_symbols("die größe des fensters ist falsch") == []
    assert extract_symbols("größe is too big") == []
    details = extract_symbol_details("größe is too big")
    assert _detail(details, "größe")["reason"] == "no_symbol_shape"


def test_capitalised_german_nouns_are_a_known_low_rank_limitation():
    # German capitalises every noun, so the ASCII "capitalized word mid-sentence"
    # rule admits them at the lowest rank (30). Documented in dogfood-review.md;
    # this test pins the behaviour so a change is a conscious one.
    details = extract_symbol_details("Die Größe des Fensters ist falsch")
    assert _detail(details, "Die")["reason"] == "sentence_initial"
    assert _detail(details, "Größe")["category"] == "capitalized"
    assert _detail(details, "Fensters")["category"] == "capitalized"
    assert _detail(details, "Größe")["rank"] == 30


def test_lowercase_unicode_hyphen_span_splits_and_compounds_survive():
    details = extract_symbol_details("see größen-abhängig and X-Forwarded-For and User-Agent")
    assert _detail(details, "X-Forwarded-For")["category"] == "compound"
    assert _detail(details, "User-Agent")["category"] == "compound"
    assert _detail(details, "größen-abhängig") is None  # not compound-shaped → split
    assert _detail(details, "größen")["reason"] == "no_symbol_shape"
    assert _detail(details, "abhängig")["reason"] == "no_symbol_shape"


# -- normalisation -------------------------------------------------------------


def test_decomposed_input_is_normalised_to_nfc_only():
    nfd = unicodedata.normalize("NFD", "fenster_größe")
    assert nfd != "fenster_größe"
    assert normalize_prompt_text(nfd) == "fenster_größe"
    assert extract_symbols(f"fix {nfd} now") == ["fenster_größe"]
    # NFKC/casefold are deliberately not applied: the query is what was typed.
    assert normalize_prompt_text("ﬁle_Größe") == "ﬁle_Größe"


def test_build_task_carries_unicode_symbols_and_details():
    task = build_task("fix fenster_größe in Fenster.größe_berechnen()", None)
    assert "fenster_größe" in task.extracted_symbols
    assert any(d["value"] == "Fenster.größe_berechnen" for d in task.symbol_details)
    assert task.source_kind == "human"


# -- end to end through ripgrep --------------------------------------------------


@rg_required
def test_unicode_symbol_reaches_ripgrep_and_the_brief(golden_repo):
    target = os.path.join(golden_repo, "src", "übersicht.py")
    with open(target, "wb") as fh:
        fh.write("def größe_berechnen(fenster_größe):\n    return fenster_größe * 2\n".encode("utf-8"))
    result = compile_packet("fix fenster_größe in größe_berechnen()", golden_repo, persist=False)
    rg = next(r for r in result.packet.collectors_run if r.name == "ripgrep")
    assert rg.status == "ok", rg.diagnostic
    assert rg.diagnostic["outcome"] == "matches"
    lexical = [i for i in result.packet.evidence if i.provenance.collector == "ripgrep"]
    assert any("übersicht.py" in ref for i in lexical for ref in i.source_claim.references)
    assert "übersicht.py" in result.brief
    assert "fenster_größe" in result.brief
