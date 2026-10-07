"""Prompt-named secondary scopes, gated by ``scoping.allowed_roots`` (D2b)."""

from __future__ import annotations

import os
import shutil
import subprocess
import time

import pytest

from evidence_compiler import secondary
from evidence_compiler.collectors.base import Collector, CollectorContext, EvidenceResult, RawClaim
from evidence_compiler.compiler import compile_packet
from evidence_compiler.config import Config
from evidence_compiler.secondary import decide, named_paths

from tests.support import HangingCollector

TAGS = ("pasted_content", "system-reminder")


class _Recorder:
    """Filesystem fakes that log every path they are asked about."""

    def __init__(self, links: dict[str, str] | None = None, dirs=(), gits=()) -> None:
        self.seen: list[str] = []
        self.links = links or {}
        self.dirs = set(dirs)
        self.gits = set(gits)

    def realpath(self, p: str) -> str:
        self.seen.append(p)
        for src, dst in self.links.items():
            if p == src or p.startswith(src + "/"):
                return dst + p[len(src):]
        return p

    def isdir(self, p: str) -> bool:
        self.seen.append(p)
        return p in self.dirs

    def exists(self, p: str) -> bool:
        self.seen.append(p)
        return p in self.gits

    def kw(self) -> dict:
        return {"realpath": self.realpath, "isdir": self.isdir, "exists": self.exists, "markup_tags": TAGS}


def _lc(p: str) -> str:
    return os.path.normcase(p).replace("\\", "/")


S, A, B = "c:/work/session", "c:/repos/other", "c:/repos/third"


def _fs(**kw) -> _Recorder:
    return _Recorder(dirs={_lc(A), _lc(B)}, gits={_lc(A) + "/.git", _lc(B) + "/.git"}, **kw)


# -- path detection ---------------------------------------------------------


def test_named_path_forms() -> None:
    prompt = 'see C:\\repos\\other\\a.py, also c:/repos/third/b.py; "D:/My Repo/x.py" and /f/Evidence/y.'
    found = named_paths(prompt)
    assert "C:\\repos\\other\\a.py" in found and "c:/repos/third/b.py" in found
    assert "D:/My Repo/x.py" in found and "/f/Evidence/y" in found


def test_paths_inside_markup_blocks_ignored() -> None:
    prompt = "<pasted_content>C:/repos/other/a.py</pasted_content> fix it <system-reminder>D:/x"
    assert named_paths(prompt, TAGS) == []
    assert named_paths("plain words, relative src/a.py", TAGS) == []


# -- decisions --------------------------------------------------------------


def test_no_allow_list_never_allows() -> None:
    fs = _fs()
    d = decide("look at C:/repos/other/a.py", S, [], **fs.kw())
    assert d.status == secondary.NOT_ALLOWED
    assert not any("repos/other" in p for p in fs.seen)


def test_non_allowed_target_triggers_no_filesystem_access() -> None:
    fs = _fs()
    d = decide("look at C:/secret/stuff/a.py", S, [A], **fs.kw())
    assert d.status == secondary.NOT_ALLOWED
    assert not any("secret" in p for p in fs.seen)


def test_traversal_rejected_lexically() -> None:
    fs = _fs()
    d = decide("open C:/repos/other/../../secret/a.py", S, [A], **fs.kw())
    assert d.status == secondary.NOT_ALLOWED
    assert not any("secret" in p for p in fs.seen)


def test_link_escape_rejected() -> None:
    fs = _fs(links={_lc(A) + "/vendor": "c:/secret"})
    d = decide("open C:/repos/other/vendor/a.py", S, [A], **fs.kw())
    assert d.status == secondary.NOT_ALLOWED
    assert not any(p.endswith("/.git") for p in fs.seen)


def test_allowed_root_resolved_canonically() -> None:
    # allow-list entry is itself a junction to the real repo
    fs = _fs(links={"c:/alias": _lc(A)})
    d = decide("open C:\\repos\\other\\src\\a.py", S, ["c:/alias"], **fs.kw())
    assert d.status == secondary.ALLOWED and d.root == _lc(A)


def test_allowed_and_case_and_slash_forms() -> None:
    for prompt in ("open C:\\Repos\\Other\\a.py", "open c:/repos/other/a.py", 'open "C:/repos/other/x y.py"'):
        assert decide(prompt, S, [A], **_fs().kw()).status == secondary.ALLOWED, prompt


def test_ambiguous_nested_roots() -> None:
    d = decide("open C:/repos/other/sub/a.py", S, [A, A + "/sub"], **_fs().kw())
    assert d.status == secondary.AMBIGUOUS and d.root is None


def test_ambiguous_two_roots_named() -> None:
    fs = _fs()
    d = decide("compare C:/repos/other/a.py with C:/repos/third/b.py", S, [A, B], **fs.kw())
    assert d.status == secondary.AMBIGUOUS
    assert not any(p.endswith("/.git") for p in fs.seen)


def test_unavailable_not_dir_or_not_git() -> None:
    fs = _Recorder(dirs=set(), gits=set())
    assert decide("open C:/repos/other/a.py", S, [A], **fs.kw()).status == secondary.UNAVAILABLE
    fs = _Recorder(dirs={_lc(A)}, gits=set())
    d = decide("open C:/repos/other/a.py", S, [A], **fs.kw())
    assert d.status == secondary.UNAVAILABLE and "git" in d.reason


def test_session_root_is_same() -> None:
    assert decide("open C:/work/session/a.py", S, [A, S], **_fs().kw()).status == secondary.SAME


def test_session_nested_in_allowed_root_is_ambiguous() -> None:
    d = decide("open C:/repos/other/a.py", A + "/wt/x", [A], **_fs().kw())
    assert d.status == secondary.AMBIGUOUS


def test_config_allowed_roots() -> None:
    assert Config().allowed_roots == ()
    assert Config(data={"scoping": {"allowed_roots": ["F:/X", " "]}}).allowed_roots == ("F:/X",)
    assert Config(data={"scoping": {"allowed_roots": "F:/X"}}).allowed_roots == ()


# -- end to end -------------------------------------------------------------


class _Rec(Collector):
    name = "rec"

    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    def collect(self, context: CollectorContext) -> EvidenceResult:
        self.calls.append((context.repository_root, context.timeout_ms))
        return EvidenceResult(
            collector=self.name,
            status="ok",
            items=[RawClaim(kind="symbol_definition", statement="widget defined in src/w.py",
                            references=["src/w.py"], authority="observed", freshness="current",
                            confidence=0.9)],
        )


def _repo(path) -> str:
    os.makedirs(path / ".git", exist_ok=True)
    return str(path).replace("\\", "/")


def _cfg(roots: list[str]) -> Config:
    return Config(data={"scoping": {"allowed_roots": roots}, "collectors": {"rec": {"timeout_ms": 400}}})


def test_compile_two_scopes_provenance_and_split_budget(tmp_path) -> None:
    session, other = _repo(tmp_path / "session"), _repo(tmp_path / "other")
    rec = _Rec()
    res = compile_packet(f"fix widget like {other}/src/w.py", session, config=_cfg([other]),
                         collectors=[rec], persist=False)
    roots = sorted(r for r, _ in rec.calls)
    assert len(rec.calls) == 2 and all(t == 200 for _, t in rec.calls)
    assert _lc(roots[0]) != _lc(roots[1])
    names = [r.name for r in res.packet.collectors_run]
    assert names == ["rec", "rec@secondary", "scope@secondary"]
    by_run = {i.provenance.collector: i for i in res.packet.evidence}
    sec = by_run["rec@secondary"]
    assert _lc(sec.provenance.extra["root"]) == _lc(os.path.realpath(other))
    assert sec.source_claim.references[0].startswith(sec.provenance.extra["root"] + "/")
    assert "(in " in sec.source_claim.statement
    assert "root" in by_run["rec"].provenance.extra
    assert "(in " not in by_run["rec"].source_claim.statement


def _scope_run(res):
    return next(r for r in res.packet.collectors_run if r.name == "scope@secondary")


def test_compile_not_allowed_reads_nothing_and_stays_in_diagnostics(tmp_path) -> None:
    session, other = _repo(tmp_path / "session"), _repo(tmp_path / "other")
    rec = _Rec()
    res = compile_packet(f"fix widget like {other}/src/w.py", session, config=_cfg([session + "/nope"]),
                         collectors=[rec], persist=False)
    assert len(rec.calls) == 1 and rec.calls[0][1] == 400
    assert _scope_run(res).diagnostic["decision"] == secondary.NOT_ALLOWED
    assert "## Scope" not in res.brief
    assert all("root" not in i.provenance.extra for i in res.packet.evidence)


@pytest.mark.parametrize(
    "prompt",
    ["/review-all the ranking code", "please run /next then fix Foo", "fix the 1/2 ratio in /etc-like text"],
)
def test_slash_commands_never_render_scope_notice(tmp_path, prompt) -> None:
    session, other = _repo(tmp_path / "session"), _repo(tmp_path / "other")
    rec = _Rec()
    res = compile_packet(prompt, session, config=_cfg([other]), collectors=[rec], persist=False)
    assert len(rec.calls) == 1 and rec.calls[0][1] == 400
    assert _scope_run(res).diagnostic["decision"] == secondary.NOT_ALLOWED
    assert "## Scope" not in res.brief


def test_allowed_root_keeps_on_disk_casing(tmp_path) -> None:
    session, other = _repo(tmp_path / "session"), _repo(tmp_path / "Other")
    res = compile_packet(f"fix widget like {other.lower() if os.name == 'nt' else other}/src/w.py", session,
                         config=_cfg([other]), collectors=[_Rec()], persist=False)
    run = _scope_run(res)
    assert run.status == "ok"
    assert run.diagnostic["root"] == os.path.realpath(other).replace("\\", "/")
    assert "## Scope" not in res.brief


def test_allowed_but_uncollectable_renders_notice(tmp_path) -> None:
    session = _repo(tmp_path / "session")
    plain = tmp_path / "plain"
    plain.mkdir()
    plain_root = str(plain).replace("\\", "/")
    rec = _Rec()
    res = compile_packet(f"fix widget like {plain_root}/w.py", session, config=_cfg([plain_root]),
                         collectors=[rec], persist=False)
    assert len(rec.calls) == 1
    assert _scope_run(res).diagnostic["decision"] == secondary.UNAVAILABLE
    assert "secondary scope not collected (unavailable): allowed root is not a git work tree" in res.brief

    a, b = _repo(tmp_path / "a"), _repo(tmp_path / "b")
    res = compile_packet(f"compare {a}/x.py with {b}/y.py", session, config=_cfg([a, b]),
                         collectors=[_Rec()], persist=False)
    assert "secondary scope not collected (ambiguous)" in res.brief


def test_compile_without_allow_list_unchanged(tmp_path) -> None:
    session, other = _repo(tmp_path / "session"), _repo(tmp_path / "other")
    rec = _Rec()
    res = compile_packet(f"fix widget like {other}/src/w.py", session,
                         config=Config(data={"collectors": {"rec": {"timeout_ms": 400}}}),
                         collectors=[rec], persist=False)
    assert [r.name for r in res.packet.collectors_run] == ["rec"]
    assert "## Scope" not in res.brief


def test_total_deadline_fixed_across_scopes(tmp_path) -> None:
    session, other = _repo(tmp_path / "session"), _repo(tmp_path / "other")
    t0 = time.perf_counter()
    res = compile_packet(f"see {other}/a.py", session, config=_cfg([other]),
                         collectors=[HangingCollector(5.0)], deadline_ms=300, persist=False)
    assert time.perf_counter() - t0 < 2.0
    assert {r.name: r.status for r in res.packet.collectors_run}["hang@secondary"] == "timeout"


def _can_symlink(tmp_path) -> bool:
    try:
        os.symlink(tmp_path, tmp_path / "_probe", target_is_directory=True)
        return True
    except (OSError, NotImplementedError):
        return False


def _junction(link, target) -> bool:
    if os.name != "nt":
        return False
    r = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True)
    return r.returncode == 0


def test_real_link_escape_rejected(tmp_path) -> None:
    other, outside = _repo(tmp_path / "other"), tmp_path / "outside"
    outside.mkdir()
    link = tmp_path / "other" / "vendor"
    if _can_symlink(tmp_path):
        os.symlink(outside, link, target_is_directory=True)
    elif not _junction(link, outside):
        pytest.skip("no symlink or junction support")
    d = decide(f"read {other}/vendor/a.py", str(tmp_path / "session"), [other])
    assert d.status == secondary.NOT_ALLOWED
    shutil.rmtree(tmp_path / "other", ignore_errors=True)
