"""Claude Code Desktop adapter — ``UserPromptSubmit`` hook.

Thin adapter over the core compiler. Contract (architecture §4,
context-brief §5, build brief §6):

- Read the hook payload from stdin.
- Run the compiler for the current repo/worktree.
- On success with a non-empty brief, inject it via structured
  ``additionalContext`` on stdout.
- On ANY error, or on deadline expiry, inject nothing, log, and **exit 0** —
  never block or fail the parent Claude Code session.

The adapter enforces a bounded *end-to-end* deadline (not just per-collector
timeouts) with a watchdog thread: if the compiler has not returned by the
hard ceiling, we abandon it (daemon thread), inject nothing, and exit 0.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import traceback


def main() -> int:
    # The whole body is wrapped: fail-open is the top-level guarantee.
    try:
        payload = _read_payload()
        return _run(payload)
    except Exception:  # noqa: BLE001 - last-resort isolation; must exit 0
        _safe_log("adapter top-level exception:\n" + traceback.format_exc(), cwd=os.getcwd())
        return 0


def _read_payload() -> dict:
    try:
        raw = sys.stdin.read()
    except Exception:  # noqa: BLE001
        return {}
    raw = (raw or "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except (ValueError, json.JSONDecodeError):
        return {}


def _run(payload: dict) -> int:
    prompt = str(payload.get("prompt") or "")
    cwd = str(payload.get("cwd") or os.getcwd())
    session_id = payload.get("session_id")
    repo = _find_repo_root(cwd)

    if not prompt.strip():
        return 0  # nothing to scope

    # Deadline from config (hard safety ceiling). Loaded defensively.
    deadline_ms = _load_deadline_ms(repo)

    result_box: dict = {}

    def work() -> None:
        try:
            from ..compiler import compile_packet

            result_box["result"] = compile_packet(
                prompt=prompt,
                repository_root=repo,
                cwd=cwd,
                session_id=str(session_id) if session_id is not None else None,
                deadline_ms=deadline_ms,
                persist=True,
            )
        except Exception:  # noqa: BLE001
            result_box["error"] = traceback.format_exc()

    worker = threading.Thread(target=work, daemon=True)
    start = time.perf_counter()
    worker.start()
    # Watchdog: never wait longer than the hard ceiling (+ small grace).
    worker.join(timeout=(deadline_ms / 1000.0) + 0.5)

    if worker.is_alive():
        _safe_log(
            f"compiler exceeded end-to-end deadline {deadline_ms}ms; injecting nothing", cwd=repo
        )
        return 0

    if "error" in result_box:
        _safe_log("compiler error:\n" + result_box["error"], cwd=repo)
        return 0

    result = result_box.get("result")
    if result is None:
        return 0

    # Identity isolation: only inject a brief compiled for THIS repo root.
    if result.packet.identity.repository_root != _norm(repo):
        _safe_log("identity mismatch; injecting nothing", cwd=repo)
        return 0

    brief = (result.brief or "").strip()
    elapsed_ms = round((time.perf_counter() - start) * 1000.0, 1)
    if not brief:
        return 0  # empty brief → inject nothing (spec §4)

    output = {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": result.brief,
        }
    }
    try:
        sys.stdout.write(json.dumps(output))
        sys.stdout.flush()
    except Exception:  # noqa: BLE001 - even stdout failure must not raise
        return 0
    _safe_log(
        f"injected brief ({result.packet.budget.injected_tokens} tok) in {elapsed_ms}ms; "
        f"packet={result.storage_path}",
        cwd=repo,
    )
    return 0


# --------------------------------------------------------------------------
# helpers (all defensive; none may raise)
# --------------------------------------------------------------------------


def _find_repo_root(cwd: str) -> str:
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
    except Exception:  # noqa: BLE001
        return os.path.abspath(cwd)


def _load_deadline_ms(repo: str) -> int:
    try:
        from ..config import DEFAULT_DEADLINE_MS, load_config

        return load_config(repo).deadline_ms
    except Exception:  # noqa: BLE001
        try:
            from ..config import DEFAULT_DEADLINE_MS

            return DEFAULT_DEADLINE_MS
        except Exception:  # noqa: BLE001
            return 25_000


def _norm(path: str) -> str:
    return os.path.abspath(path).replace("\\", "/")


def _safe_log(message: str, cwd: str) -> None:
    try:
        log_dir = os.path.join(cwd, ".evidence-compiler", "logs")
        os.makedirs(log_dir, exist_ok=True)
        with open(os.path.join(log_dir, "hook.log"), "a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {message}\n")
    except Exception:  # noqa: BLE001 - logging is best-effort only
        pass


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
