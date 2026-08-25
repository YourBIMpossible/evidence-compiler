"""Hardened Claude Code hook launcher — ``evidence hook-safe``.

The strict superset of the ``hook`` adapter contract, intended to be the ONLY
process on the hook path (no Node or shell wrapper doing safety work):

- Read the hook payload from stdin **as bytes**; decode/parse defensively.
- Exit 0 on every path, expected or not — a ``UserPromptSubmit`` hook that
  exits non-zero can block the user's turn.
- Emit hook JSON on stdout only for a successful, validated, non-empty brief;
  every other outcome emits **nothing** on stdout (no logs, warnings, or
  stack traces — stdout is the injection channel and must stay clean).
- Preserve arbitrary valid UTF-8 byte-for-byte (stdout is written as encoded
  bytes, never through a platform-dependent text codec).
- Refuse to run against a configured storage dir that escapes
  ``<repo-root>/.evidence-compiler/`` (symlinks resolved before comparison).
- Apply bounded packet retention after a successful persist (config
  ``retention.max_packets``, default 250, ``0`` disables); retention failures
  never suppress a valid injection.
- Record every non-success outcome as one sanitized line (timestamp +
  category + short detail) in ``.evidence-compiler/logs/hook.log``. Prompt
  text, evidence text, and environment values are never written there.

Disable with ``EVIDENCE_HOOK=0`` (canonical) or ``BIMP_EVIDENCE_HOOK=0``
(compatibility alias); either alone silences the hook entirely.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time

_MAX_DETAIL = 200


def main() -> int:
    """Entry point for ``evidence hook-safe``. Always returns 0."""
    try:
        _run()
    except Exception as exc:  # noqa: BLE001 - last-resort isolation
        try:
            _diag(_repo_root(), "launcher_exception", type(exc).__name__)
        except Exception:  # noqa: BLE001
            pass
    return 0


def _disabled() -> bool:
    return (
        os.environ.get("EVIDENCE_HOOK") == "0"
        or os.environ.get("BIMP_EVIDENCE_HOOK") == "0"
    )


def _repo_root() -> str:
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env and env.strip():
        return os.path.abspath(env)
    from .claude_code import _find_repo_root

    return _find_repo_root(os.getcwd())


def _diag(root: str, category: str, detail: str = "") -> None:
    """Append one sanitized diagnostic line. Best-effort; never raises.

    The log lives at a fixed path beneath the repo root regardless of any
    storage configuration, so a bad config cannot redirect log writes.
    """
    try:
        log_dir = os.path.join(root, ".evidence-compiler", "logs")
        os.makedirs(log_dir, exist_ok=True)
        ts = time.strftime("%Y-%m-%dT%H:%M:%S")
        detail = " ".join(str(detail).split())[:_MAX_DETAIL]
        line = f"{ts} hook-safe:{category} {detail}".rstrip() + "\n"
        with open(os.path.join(log_dir, "hook.log"), "a", encoding="utf-8") as fh:
            fh.write(line)
    except Exception:  # noqa: BLE001 - logging is best-effort only
        pass


def _read_stdin_bytes() -> bytes:
    try:
        buf = getattr(sys.stdin, "buffer", None)
        if buf is not None:
            return buf.read()
        return sys.stdin.read().encode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return b""


def _parse_payload(raw: bytes, root: str) -> dict | None:
    """Decode + parse the hook payload. ``None`` means fail open (logged)."""
    stripped = raw.lstrip(b"\xef\xbb\xbf").strip()
    if not stripped:
        _diag(root, "empty_input")
        return None
    try:
        data = json.loads(stripped.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        _diag(root, "malformed_input", "stdin was not a valid UTF-8 JSON document")
        return None
    if not isinstance(data, dict):
        _diag(root, "malformed_input", "hook payload was not a JSON object")
        return None
    return data


def _storage_dir_if_safe(root: str) -> str | None:
    """Resolved storage dir, or ``None`` if it escapes ``.evidence-compiler/``.

    Both sides are fully resolved (``realpath``) so relative, absolute, ``..``,
    and symlink escapes are all caught by one containment check.
    """
    from ..config import load_config

    configured = load_config(root).storage_dir(root)
    target = os.path.normcase(os.path.realpath(configured))
    boundary = os.path.normcase(os.path.realpath(os.path.join(root, ".evidence-compiler")))
    if target == boundary or target.startswith(boundary + os.sep):
        return os.path.realpath(configured)
    return None


def _run() -> None:
    if _disabled():
        return

    root = _repo_root()
    payload = _parse_payload(_read_stdin_bytes(), root)
    if payload is None:
        return

    prompt = str(payload.get("prompt") or "")
    if not prompt.strip():
        return  # valid no-op: nothing to scope, nothing to log

    cwd = str(payload.get("cwd") or os.getcwd())
    session_id = payload.get("session_id")

    storage_dir = _storage_dir_if_safe(root)
    if storage_dir is None:
        _diag(
            root,
            "storage_dir_unsafe",
            "configured storage.dir resolves outside .evidence-compiler/; refusing injection",
        )
        return

    from ..config import load_config

    config = load_config(root)
    deadline_ms = config.deadline_ms

    result_box: dict = {}

    def work() -> None:
        try:
            from ..compiler import compile_packet

            result_box["result"] = compile_packet(
                prompt=prompt,
                repository_root=root,
                cwd=cwd,
                session_id=str(session_id) if session_id is not None else None,
                deadline_ms=deadline_ms,
                persist=True,
            )
        except Exception as exc:  # noqa: BLE001
            result_box["error"] = type(exc).__name__

    worker = threading.Thread(target=work, daemon=True)
    worker.start()
    worker.join(timeout=(deadline_ms / 1000.0) + 0.5)

    if worker.is_alive():
        _diag(root, "timeout", f"compiler exceeded {deadline_ms}ms end-to-end deadline; abandoned")
        return
    if "error" in result_box:
        # Exception class name only: messages can embed prompt-derived text.
        _diag(root, "compiler_error", result_box["error"])
        return

    result = result_box.get("result")
    if result is None:
        return
    if result.packet.identity.repository_root != os.path.abspath(root).replace("\\", "/"):
        _diag(root, "identity_mismatch", "packet was compiled for a different repository root")
        return

    brief = (result.brief or "").strip()
    if not brief:
        return  # empty brief → inject nothing (spec §4); healthy silence

    encoded = _validated_output_bytes(result.brief)
    if encoded is None:
        _diag(root, "malformed_output", "generated hook response failed validation")
        return

    try:
        sys.stdout.buffer.write(encoded)
        sys.stdout.buffer.flush()
    except Exception:  # noqa: BLE001
        _diag(root, "stdout_write_error")
        return

    _apply_retention(root, storage_dir, config)


def _validated_output_bytes(brief: str) -> bytes | None:
    """Serialize + re-validate the hook response; UTF-8 bytes or ``None``."""
    try:
        output = {
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": brief,
            }
        }
        encoded = json.dumps(output, ensure_ascii=False).encode("utf-8")
        reparsed = json.loads(encoded.decode("utf-8"))
        if (
            not isinstance(reparsed, dict)
            or reparsed["hookSpecificOutput"]["additionalContext"] != brief
        ):
            return None
        return encoded
    except Exception:  # noqa: BLE001
        return None


def _apply_retention(root: str, storage_dir: str, config) -> None:
    """Bounded packet retention. Never raises; never suppresses an injection."""
    try:
        from ..storage import prune_packets

        prune_packets(storage_dir, config.retention_max_packets)
    except Exception as exc:  # noqa: BLE001
        _diag(root, "retention_error", type(exc).__name__)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
