"""``evidence hook-safe`` launcher: fail-open, byte-exact UTF-8, storage gate,
sanitized diagnostics. Every non-success path must exit 0, emit nothing on
stdout, and (where the contract says so) leave exactly one safe log line."""

from __future__ import annotations

import io
import json
import os
import sys
import time

import pytest

from evidence_compiler import compiler as compiler_mod
from evidence_compiler.integrations import hook_safe


def _feed(monkeypatch, data: bytes) -> None:
    wrapper = io.TextIOWrapper(io.BytesIO(data), encoding="utf-8")
    monkeypatch.setattr(sys, "stdin", wrapper)


def _feed_payload(monkeypatch, repo: str, prompt: str) -> None:
    _feed(monkeypatch, json.dumps({"prompt": prompt, "cwd": repo}).encode("utf-8"))


def _write_config(repo: str, text: str) -> None:
    cfg_dir = os.path.join(repo, ".evidence-compiler")
    os.makedirs(cfg_dir, exist_ok=True)
    with open(os.path.join(cfg_dir, "config.yaml"), "w", encoding="utf-8") as fh:
        fh.write(text)


def _log_lines(repo: str) -> list[str]:
    path = os.path.join(repo, ".evidence-compiler", "logs", "hook.log")
    if not os.path.isfile(path):
        return []
    with open(path, "r", encoding="utf-8") as fh:
        return [line.rstrip("\n") for line in fh if line.strip()]


@pytest.fixture(autouse=True)
def _project_dir_unset(monkeypatch):
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.delenv("EVIDENCE_HOOK", raising=False)
    monkeypatch.delenv("BIMP_EVIDENCE_HOOK", raising=False)


def test_canonical_off_switch_is_silent(monkeypatch, capsysbinary, golden_repo):
    monkeypatch.setenv("EVIDENCE_HOOK", "0")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", golden_repo)
    _feed_payload(monkeypatch, golden_repo, "where is alpha defined")
    assert hook_safe.main() == 0
    assert capsysbinary.readouterr().out == b""
    assert _log_lines(golden_repo) == []


def test_alias_off_switch_is_silent(monkeypatch, capsysbinary, golden_repo):
    monkeypatch.setenv("BIMP_EVIDENCE_HOOK", "0")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", golden_repo)
    _feed_payload(monkeypatch, golden_repo, "where is alpha defined")
    assert hook_safe.main() == 0
    assert capsysbinary.readouterr().out == b""
    assert _log_lines(golden_repo) == []


def test_empty_stdin_fails_open_and_logs(monkeypatch, capsysbinary, golden_repo):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", golden_repo)
    _feed(monkeypatch, b"")
    assert hook_safe.main() == 0
    assert capsysbinary.readouterr().out == b""
    lines = _log_lines(golden_repo)
    assert len(lines) == 1 and "hook-safe:empty_input" in lines[0]


def test_stdin_read_error_is_logged_distinctly_from_empty_input(monkeypatch, capsysbinary, golden_repo):
    # A genuine I/O error while reading stdin must not be silently swallowed
    # and miscategorized downstream as an ordinary empty invocation.
    class BrokenBuffer:
        def read(self):
            raise OSError("pipe broken")

    class BrokenStdin:
        buffer = BrokenBuffer()

    monkeypatch.setenv("CLAUDE_PROJECT_DIR", golden_repo)
    monkeypatch.setattr(sys, "stdin", BrokenStdin())
    assert hook_safe.main() == 0
    assert capsysbinary.readouterr().out == b""
    lines = _log_lines(golden_repo)
    assert len(lines) == 1
    assert "hook-safe:stdin_read_error OSError" in lines[0]
    assert "empty_input" not in lines[0]


def test_malformed_stdin_fails_open_and_logs(monkeypatch, capsysbinary, golden_repo):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", golden_repo)
    _feed(monkeypatch, b"{not json")
    assert hook_safe.main() == 0
    assert capsysbinary.readouterr().out == b""
    lines = _log_lines(golden_repo)
    assert len(lines) == 1 and "hook-safe:malformed_input" in lines[0]
    assert "{not json" not in lines[0]


def test_non_object_payload_fails_open(monkeypatch, capsysbinary, golden_repo):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", golden_repo)
    _feed(monkeypatch, b"[1, 2, 3]")
    assert hook_safe.main() == 0
    assert capsysbinary.readouterr().out == b""
    assert any("malformed_input" in line for line in _log_lines(golden_repo))


def test_empty_prompt_is_silent_noop(monkeypatch, capsysbinary, golden_repo):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", golden_repo)
    _feed_payload(monkeypatch, golden_repo, "   ")
    assert hook_safe.main() == 0
    assert capsysbinary.readouterr().out == b""
    assert _log_lines(golden_repo) == []


def test_success_injects_valid_hook_json(monkeypatch, capsysbinary, golden_repo):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", golden_repo)
    _feed_payload(monkeypatch, golden_repo, "where is alpha defined")
    assert hook_safe.main() == 0
    out = capsysbinary.readouterr().out
    parsed = json.loads(out.decode("utf-8"))
    inner = parsed["hookSpecificOutput"]
    assert inner["hookEventName"] == "UserPromptSubmit"
    assert inner["additionalContext"].strip()


def test_success_logs_one_injected_line(monkeypatch, capsysbinary, golden_repo):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", golden_repo)
    _feed_payload(monkeypatch, golden_repo, "where is alpha defined")
    assert hook_safe.main() == 0
    assert capsysbinary.readouterr().out
    lines = _log_lines(golden_repo)
    assert len(lines) == 1
    assert "hook-safe:injected" in lines[0]
    assert " tok " in lines[0] and "ms packet=" in lines[0]
    assert "alpha" not in lines[0]  # never the prompt


def test_repo_root_comes_from_payload_cwd_when_env_unset(monkeypatch, capsysbinary, golden_repo, tmp_path):
    # Process cwd is an unrelated directory; the payload names the repo. The
    # packet and log must land in the payload's repo, not the process cwd.
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    _feed_payload(monkeypatch, golden_repo, "where is alpha defined")
    assert hook_safe.main() == 0
    assert json.loads(capsysbinary.readouterr().out.decode("utf-8"))["hookSpecificOutput"]
    assert os.path.isdir(os.path.join(golden_repo, ".evidence-compiler", "packets"))
    assert not (elsewhere / ".evidence-compiler").exists()
    assert any("hook-safe:injected" in line for line in _log_lines(golden_repo))


def test_payload_cwd_outside_project_dir_is_refused(monkeypatch, capsysbinary, golden_repo, tmp_path):
    # CLAUDE_PROJECT_DIR says repo A; the payload cwd is a different repo B.
    # Compiling repo B's git state under repo A's identity must never happen.
    other = tmp_path / "other-repo"
    (other / ".git").mkdir(parents=True)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", golden_repo)
    _feed_payload(monkeypatch, str(other), "where is alpha defined")
    assert hook_safe.main() == 0
    assert capsysbinary.readouterr().out == b""
    lines = _log_lines(golden_repo)
    assert len(lines) == 1 and "hook-safe:cwd_outside_root" in lines[0]
    assert not os.path.isdir(os.path.join(golden_repo, ".evidence-compiler", "packets"))


def test_worker_ending_without_result_is_logged(monkeypatch, capsysbinary, golden_repo):
    def bail(**kwargs):
        raise SystemExit(3)  # BaseException: escapes the worker's ``except Exception``

    monkeypatch.setattr(compiler_mod, "compile_packet", bail)
    monkeypatch.setattr(hook_safe.threading, "excepthook", lambda args: None)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", golden_repo)
    _feed_payload(monkeypatch, golden_repo, "where is alpha defined")
    assert hook_safe.main() == 0
    assert capsysbinary.readouterr().out == b""
    lines = _log_lines(golden_repo)
    assert len(lines) == 1 and "hook-safe:compiler_error" in lines[0]


def test_multibyte_brief_roundtrips_byte_exactly(monkeypatch, capsysbinary, golden_repo):
    # 120k multi-byte chars, far past the 64 KiB pipe-chunk boundary.
    brief = "\u4e2d\u6587\u30c6\u30b9\u30c8\u00e9" * 20_000

    class FakeResult:
        pass

    real_compile = compiler_mod.compile_packet

    def fake_compile(**kwargs):
        real = real_compile(**kwargs)
        result = FakeResult()
        result.packet = real.packet
        result.brief = brief
        result.storage_path = real.storage_path
        return result

    monkeypatch.setattr(compiler_mod, "compile_packet", fake_compile)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", golden_repo)
    _feed_payload(monkeypatch, golden_repo, "where is alpha defined")
    assert hook_safe.main() == 0
    out = capsysbinary.readouterr().out
    decoded = out.decode("utf-8")  # strict: any mojibake raises
    assert "\ufffd" not in decoded
    assert json.loads(decoded)["hookSpecificOutput"]["additionalContext"] == brief


def test_unencodable_brief_logs_malformed_output(monkeypatch, capsysbinary, golden_repo):
    # A lone surrogate cannot be encoded as UTF-8: the response fails
    # validation and nothing may reach stdout.
    real_compile = compiler_mod.compile_packet

    def fake_compile(**kwargs):
        real = real_compile(**kwargs)

        class R:
            packet = real.packet
            brief = "broken \ud800 surrogate"
            storage_path = real.storage_path

        return R()

    monkeypatch.setattr(compiler_mod, "compile_packet", fake_compile)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", golden_repo)
    _feed_payload(monkeypatch, golden_repo, "where is alpha defined")
    assert hook_safe.main() == 0
    assert capsysbinary.readouterr().out == b""
    assert any("hook-safe:malformed_output" in line for line in _log_lines(golden_repo))


def test_compiler_exception_logs_class_name_only(monkeypatch, capsysbinary, golden_repo):
    def boom(**kwargs):
        raise RuntimeError("secret prompt text must never reach the log")

    monkeypatch.setattr(compiler_mod, "compile_packet", boom)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", golden_repo)
    _feed_payload(monkeypatch, golden_repo, "where is alpha defined")
    assert hook_safe.main() == 0
    assert capsysbinary.readouterr().out == b""
    lines = _log_lines(golden_repo)
    assert len(lines) == 1 and "hook-safe:compiler_error RuntimeError" in lines[0]
    assert "secret" not in lines[0]


def test_timeout_fails_open_and_logs(monkeypatch, capsysbinary, golden_repo):
    os.makedirs(os.path.join(golden_repo, ".evidence-compiler"), exist_ok=True)
    with open(
        os.path.join(golden_repo, ".evidence-compiler", "config.yaml"), "w", encoding="utf-8"
    ) as fh:
        fh.write("deadline_ms: 50\n")

    def sleepy(**kwargs):
        time.sleep(5)

    monkeypatch.setattr(compiler_mod, "compile_packet", sleepy)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", golden_repo)
    _feed_payload(monkeypatch, golden_repo, "where is alpha defined")
    assert hook_safe.main() == 0
    assert capsysbinary.readouterr().out == b""
    assert any("hook-safe:timeout" in line for line in _log_lines(golden_repo))


@pytest.mark.parametrize(
    "unsafe_dir",
    ["../outside-packets", "C:/Windows/Temp/ec-escape", ".evidence-compiler/../escape"],
)
def test_unsafe_storage_dir_refuses_injection(monkeypatch, capsysbinary, golden_repo, unsafe_dir):
    os.makedirs(os.path.join(golden_repo, ".evidence-compiler"), exist_ok=True)
    with open(
        os.path.join(golden_repo, ".evidence-compiler", "config.yaml"), "w", encoding="utf-8"
    ) as fh:
        fh.write(f'storage:\n  dir: "{unsafe_dir}"\n')
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", golden_repo)
    _feed_payload(monkeypatch, golden_repo, "where is alpha defined")
    assert hook_safe.main() == 0
    assert capsysbinary.readouterr().out == b""
    lines = _log_lines(golden_repo)
    assert len(lines) == 1 and "hook-safe:storage_dir_unsafe" in lines[0]


def test_symlink_escape_is_rejected(monkeypatch, capsysbinary, golden_repo, tmp_path):
    outside = tmp_path / "outside-target"
    outside.mkdir()
    os.makedirs(os.path.join(golden_repo, ".evidence-compiler"), exist_ok=True)
    link = os.path.join(golden_repo, ".evidence-compiler", "linked")
    try:
        os.symlink(str(outside), link, target_is_directory=True)
    except (OSError, NotImplementedError):
        # Windows without symlink privilege: a directory junction reparses the
        # same way through realpath(), so it exercises the identical escape.
        try:
            import _winapi

            _winapi.CreateJunction(str(outside), link)
        except Exception:  # noqa: BLE001
            pytest.skip("symlinks/junctions not available on this platform")
    os.makedirs(os.path.join(golden_repo, ".evidence-compiler"), exist_ok=True)
    with open(
        os.path.join(golden_repo, ".evidence-compiler", "config.yaml"), "w", encoding="utf-8"
    ) as fh:
        fh.write("storage:\n  dir: .evidence-compiler/linked\n")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", golden_repo)
    _feed_payload(monkeypatch, golden_repo, "where is alpha defined")
    assert hook_safe.main() == 0
    assert capsysbinary.readouterr().out == b""
    assert any("storage_dir_unsafe" in line for line in _log_lines(golden_repo))


def test_safe_explicit_storage_dir_still_injects(monkeypatch, capsysbinary, golden_repo):
    os.makedirs(os.path.join(golden_repo, ".evidence-compiler"), exist_ok=True)
    with open(
        os.path.join(golden_repo, ".evidence-compiler", "config.yaml"), "w", encoding="utf-8"
    ) as fh:
        fh.write("storage:\n  dir: .evidence-compiler/custom-packets\n")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", golden_repo)
    _feed_payload(monkeypatch, golden_repo, "where is alpha defined")
    assert hook_safe.main() == 0
    out = capsysbinary.readouterr().out
    assert json.loads(out.decode("utf-8"))["hookSpecificOutput"]["additionalContext"]
    assert os.path.isdir(os.path.join(golden_repo, ".evidence-compiler", "custom-packets"))


def test_retention_failure_does_not_suppress_injection(monkeypatch, capsysbinary, golden_repo):
    import evidence_compiler.storage as storage_mod

    def broken_prune(storage_dir, max_packets):
        raise OSError("disk went away")

    monkeypatch.setattr(storage_mod, "prune_packets", broken_prune)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", golden_repo)
    _feed_payload(monkeypatch, golden_repo, "where is alpha defined")
    assert hook_safe.main() == 0
    out = capsysbinary.readouterr().out
    assert json.loads(out.decode("utf-8"))["hookSpecificOutput"]["additionalContext"]
    assert any("hook-safe:retention_error OSError" in line for line in _log_lines(golden_repo))
