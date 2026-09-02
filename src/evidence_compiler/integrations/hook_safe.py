"""Hardened Claude Code hook launcher — ``evidence hook-safe``.

A hardened evolution of the ``hook`` adapter contract, intended to be the ONLY
process on the hook path (no Node or shell wrapper doing safety work). It is
not a strict superset: it adds refusals the base contract did not have (an
out-of-root payload ``cwd``, an unsafe storage dir, and the ``EVIDENCE_HOOK``
off switch), so some inputs the old ``hook`` compiled are now declined:

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
- Resolve the repository root from ``CLAUDE_PROJECT_DIR`` when set, else by
  walking up from the hook payload's ``cwd``; a payload ``cwd`` outside the
  resolved root is refused (``cwd_outside_root``) so evidence from one
  repository can never be injected under another's identity.
- Record every outcome as one sanitized line (timestamp + category + short
  detail) in ``.evidence-compiler/logs/hook.log`` — ``injected`` with token
  count / latency / packet filename on success, a stable failure category
  otherwise. Prompt text, evidence text, and environment values are never
  written there.

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


def _repo_root(cwd: str | None = None) -> str:
    """Repository root: ``CLAUDE_PROJECT_DIR`` if set, else walk up from ``cwd``
    (the hook payload's ``cwd`` once parsed; the process cwd before that)."""
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env and env.strip():
        return os.path.abspath(env)
    return _find_repo_root(cwd or os.getcwd())


def _within(child: str, parent: str) -> bool:
    """True when ``child`` is ``parent`` or beneath it (symlinks resolved)."""
    c = os.path.normcase(os.path.realpath(child))
    p = os.path.normcase(os.path.realpath(parent))
    return c == p or c.startswith(p + os.sep)


def _find_repo_root(cwd: str) -> str:
    """Walk up from ``cwd`` looking for a ``.git`` directory or file.

    Falls back to ``cwd`` itself (absolute) if nothing is found or the walk
    fails for any reason — repo-root detection must never raise.
    """
    try:
        path = os.path.abspath(cwd)
        while True:
            if os.path.isdir(os.path.join(path, ".git")) or os.path.isfile(
                os.path.join(path, ".git")
            ):
                return path
            parent = os.path.dirname(path)
            if parent == path:
                return os.path.abspath(cwd)
            path = parent
    except Exception as exc:  # noqa: BLE001
        fallback = os.path.abspath(cwd)
        _diag(fallback, "repo_root_error", type(exc).__name__)
        return fallback


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


def _read_stdin_bytes(root: str) -> bytes | None:
    """Read raw stdin. ``None`` means the read itself failed — distinct from
    ``b""``, a genuinely empty invocation, so a real I/O error is never
    miscategorized downstream as ``empty_input``.
    """
    try:
        buf = getattr(sys.stdin, "buffer", None)
        if buf is not None:
            return buf.read()
        return sys.stdin.read().encode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001
        _diag(root, "stdin_read_error", type(exc).__name__)
        return None


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


def _storage_dir_if_safe(root: str, config) -> str | None:
    """Resolved storage dir, or ``None`` if it escapes ``.evidence-compiler/``.

    Both sides are fully resolved (``realpath``) so relative, absolute, ``..``,
    and symlink escapes are all caught by one containment check. ``config`` is
    passed in so the per-repo config is parsed once per invocation, not twice.
    """
    configured = config.storage_dir(root)
    target = os.path.normcase(os.path.realpath(configured))
    boundary = os.path.normcase(os.path.realpath(os.path.join(root, ".evidence-compiler")))
    if target == boundary or target.startswith(boundary + os.sep):
        return os.path.realpath(configured)
    return None


def _run() -> None:
    if _disabled():
        return

    started = time.perf_counter()
    # Pre-payload root: only used to place the early diagnostics below
    # (stdin_read_error / empty_input / malformed_input), which necessarily
    # happen before a payload cwd exists. CLAUDE_PROJECT_DIR (the recommended
    # setup) makes this the correct repo. With the env var unset (deprecated
    # ``hook`` path) there is no better source than the process cwd — the
    # payload has not been read, so its repo is unknowable here.
    root = _repo_root()
    raw = _read_stdin_bytes(root)
    if raw is None:
        return  # read failure already logged as stdin_read_error
    payload = _parse_payload(raw, root)
    if payload is None:
        return

    prompt = str(payload.get("prompt") or "")
    if not prompt.strip():
        return  # valid no-op: nothing to scope, nothing to log

    payload_cwd = str(payload.get("cwd") or "").strip()
    if payload_cwd:
        cwd = os.path.abspath(payload_cwd)
        root = _repo_root(cwd)
    else:
        # No cwd in the payload: fall back to the resolved root itself, not the
        # hook process's launch directory. Using os.getcwd() here could sit
        # outside CLAUDE_PROJECT_DIR and trip the containment check below,
        # refusing a legitimate prompt (cwd_outside_root) over a missing field.
        root = _repo_root()
        cwd = root
    if not _within(cwd, root):
        _diag(
            root,
            "cwd_outside_root",
            "hook payload cwd is not inside the resolved repository root; refusing injection",
        )
        return
    session_id = payload.get("session_id")

    from ..config import load_config

    config = load_config(root)  # parsed once; reused for the storage gate + retention

    storage_dir = _storage_dir_if_safe(root, config)
    if storage_dir is None:
        _diag(
            root,
            "storage_dir_unsafe",
            "configured storage.dir resolves outside .evidence-compiler/; refusing injection",
        )
        return

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
        # Worker ended without a result or an Exception (e.g. a BaseException
        # such as SystemExit escaped it): never fall through silently.
        _diag(root, "compiler_error", "worker finished without producing a result")
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

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    tokens = getattr(getattr(result.packet, "budget", None), "injected_tokens", "?")
    packet_name = os.path.basename(str(getattr(result, "storage_path", "") or ""))
    _diag(root, "injected", f"{tokens} tok {elapsed_ms}ms packet={packet_name}")

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
