"""Phase 1B — compound technical terms in symbol extraction (Option A).

Characterization + acceptance tests for the approved Evidence Quality scope:

- Hyphenated compounds (``User-Agent``, ``Content-Type``) are preserved as
  candidates and derive exactly one structural candidate — the normalized
  snake_case identifier (``user_agent``, ``content_type``). Their hyphen
  components (``user``, ``agent``, ``content``, ``type``) must never become
  peer symbols by splitting.
- Dotted names (``Response.iter_content``) are preserved and derive only the
  member name (``iter_content``) — never the leading identifier.
- Derivations are deterministic structural transformations; no
  natural-language word splitting.

These encode the dogfood findings from prompts 5, 8, and 10 (see the local
Phase 1B proposal): generic fragments from split compounds flooded briefs
with prose-file matches while the definition-bearing evidence was displaced.
"""

from __future__ import annotations

import shutil
import subprocess
import textwrap

import pytest

from evidence_compiler import scoping
from evidence_compiler.compiler import compile_packet

HAS_RG = shutil.which("rg") is not None
HAS_GIT = shutil.which("git") is not None


# --- extraction: hyphenated compounds ---------------------------------------


def test_hyphenated_compound_preserved_and_snake_derived():
    syms = scoping.extract_symbols("How does requests build the default User-Agent header value?")
    assert "User-Agent" in syms
    assert "user_agent" in syms


def test_hyphen_components_are_not_peer_symbols():
    syms = scoping.extract_symbols("How does requests build the default User-Agent header value?")
    assert "User" not in syms
    assert "Agent" not in syms
    assert "user" not in syms
    assert "agent" not in syms


def test_content_type_compound():
    syms = scoping.extract_symbols("Where is Content-Type prepared or overridden before a request is sent?")
    assert "Content-Type" in syms
    assert "content_type" in syms
    assert "Content" not in syms
    assert "Type" not in syms


def test_multi_part_hyphen_compound():
    syms = scoping.extract_symbols("Trace the X-Request-Id header through the middleware")
    assert "X-Request-Id" in syms
    assert "x_request_id" in syms
    assert "Request" not in syms


def test_compound_with_stopword_component_still_admitted():
    # "for" and "if" are English stopwords, but X-Forwarded-For and
    # If-Modified-Since are real HTTP header names. The compound branch
    # intentionally skips the plain-token stopword guard (_is_symbolish) so
    # these are not silently dropped — the accepted trade-off is documented
    # at the call site in scoping.py.
    syms = scoping.extract_symbols("Does the proxy set X-Forwarded-For correctly?")
    assert "X-Forwarded-For" in syms
    assert "x_forwarded_for" in syms

    syms = scoping.extract_symbols("Check the If-Modified-Since header handling")
    assert "If-Modified-Since" in syms
    assert "if_modified_since" in syms


def test_title_case_prose_compound_is_accepted_tradeoff():
    # Title-Case-hyphenated prose that is not a real technical compound (no
    # stopword guard applies here, unlike the plain-token branch) is still
    # admitted as a candidate. This is a bounded, accepted false positive:
    # one of 12 symbol slots and one ripgrep query, absorbed by downstream
    # ranking rather than rejected here.
    syms = scoping.extract_symbols("Is this an Off-By-One error in the loop bound?")
    assert "Off-By-One" in syms
    assert "off_by_one" in syms


def test_lowercase_hyphen_prose_not_treated_as_compound():
    # "fail-open" / "well-known" style prose keeps its existing (non-symbol)
    # treatment: no compound candidate, no snake_case derivation.
    syms = scoping.extract_symbols("Is the adapter fail-open under a well-known timeout?")
    assert "fail-open" not in syms
    assert "fail_open" not in syms
    assert "well_known" not in syms


# --- extraction: dotted names ------------------------------------------------


def test_dotted_name_preserved_and_member_derived():
    syms = scoping.extract_symbols(
        "Where does Response.iter_content decide chunk decoding?"
    )
    assert "Response.iter_content" in syms
    assert "iter_content" in syms
    # the leading identifier is no longer auto-derived (Phase 1B): it was the
    # generic-flood vector in dogfood prompt 5.
    assert "Response" not in syms


def test_dotted_member_derivation_session_example():
    syms = scoping.extract_symbols(
        "Why does Session.merge_environment_settings behave differently when trust_env is false?"
    )
    assert "Session.merge_environment_settings" in syms
    assert "merge_environment_settings" in syms
    assert "Session" not in syms


def test_dotted_member_that_is_prose_is_not_derived():
    # member "run" is a common prose word; structural derivation is bounded by
    # the same prose guard that gated the old head derivation.
    syms = scoping.extract_symbols("Why does AlphaService.run break?")
    assert syms == ["AlphaService.run"]


def test_extraction_remains_deterministic():
    prompt = "Where is Content-Type set for Response.iter_content and the User-Agent header?"
    assert scoping.extract_symbols(prompt) == scoping.extract_symbols(prompt)


# --- end-to-end acceptance on a compound fixture -----------------------------


@pytest.fixture()
def compound_repo(tmp_path):
    """A small repo shaped like the dogfood evidence: a code definition whose
    name embeds a compound, plus a prose file dense with the raw fragments."""
    root = tmp_path / "compound-repo"
    (root / "src").mkdir(parents=True)
    (root / "src" / "headers.py").write_text(
        textwrap.dedent(
            '''\
            """Header helpers."""


            def default_user_agent(name: str = "demo") -> str:
                """Build the default User-Agent value."""
                return f"{name}/1.0"


            def build_headers() -> dict:
                return {"User-Agent": default_user_agent()}


            class Response:
                def iter_content(self, chunk_size: int = 1) -> bytes:
                    return b""
            '''
        ),
        encoding="utf-8",
    )
    (root / "CHANGELOG.md").write_text(
        "\n".join(
            [
                "# Changelog",
                "- Improved the user experience for every agent integration.",
                "- The user guide now documents agent content negotiation.",
                "- Content of type mappings were reworked for user agent hints.",
            ]
            * 5
        ),
        encoding="utf-8",
    )
    if HAS_GIT:
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        subprocess.run(["git", "add", "-A"], cwd=root, check=True)
        subprocess.run(
            ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"],
            cwd=root,
            check=True,
        )
    return str(root)


@pytest.mark.skipif(not HAS_RG, reason="ripgrep required")
def test_user_agent_prompt_surfaces_embedding_definition(compound_repo):
    result = compile_packet(
        prompt="How is the default User-Agent header value built?",
        repository_root=compound_repo,
        persist=False,
    )
    # The definition whose identifier embeds the derived compound must appear
    # in the final brief under the fixed budget (approved threshold §7a.1).
    assert "default_user_agent" in result.brief
    assert "headers.py:4" in result.brief
    # No fragment symbol was searched: nothing in the packet may claim the
    # bare fragments as its queried symbol (approved threshold §7a.2).
    searched = {
        str(e.provenance.extra.get("symbol", "")) for e in result.packet.evidence
    }
    assert "user" not in searched
    assert "User" not in searched
    assert "agent" not in searched
    assert "Agent" not in searched


@pytest.mark.skipif(not HAS_RG, reason="ripgrep required")
def test_dotted_prompt_surfaces_member_definition(compound_repo):
    result = compile_packet(
        prompt="Where does Response.iter_content decide chunk size?",
        repository_root=compound_repo,
        persist=False,
    )
    assert "iter_content" in result.brief
    assert "headers.py:14" in result.brief
    searched = {
        str(e.provenance.extra.get("symbol", "")) for e in result.packet.evidence
    }
    assert "Response" not in searched


@pytest.mark.skipif(not HAS_RG, reason="ripgrep required")
def test_compound_prompt_brief_is_deterministic(compound_repo):
    import re

    briefs = set()
    for _ in range(3):
        r = compile_packet(
            prompt="How is the default User-Agent header value built?",
            repository_root=compound_repo,
            persist=False,
        )
        briefs.add(re.sub(r'packet_id="ep_[0-9a-f]+"', 'packet_id="ep_norm"', r.brief))
    assert len(briefs) == 1
