"""``evidence`` command-line interface.

Subcommands:

- ``compile``  run the critical path for a prompt and print the brief.
- ``replay``   minimal text report over a persisted packet (build brief §8).
- ``init``     scaffold ``.evidence-compiler/config.yaml`` from the template.
- ``hook``     Claude Code Desktop ``UserPromptSubmit`` adapter (fail-open).
"""

from __future__ import annotations

import argparse
import os
import sys

from . import __version__
from .packet import EvidencePacket, SchemaVersionError
from .storage import load_packet


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="evidence", description=__doc__)
    parser.add_argument("--version", action="version", version=f"evidence-compiler {__version__}")
    sub = parser.add_subparsers(dest="command")

    p_compile = sub.add_parser("compile", help="compile an evidence packet for a prompt")
    p_compile.add_argument("--prompt", required=True, help="the agent prompt text")
    p_compile.add_argument("--repo", default=os.getcwd(), help="repository root (default: cwd)")
    p_compile.add_argument("--cwd", default=None, help="working dir inside the repo")
    p_compile.add_argument("--active-file", default=None, help="active file path, if any")
    p_compile.add_argument("--session", default=None)
    p_compile.add_argument("--turn", default=None)
    p_compile.add_argument("--no-persist", action="store_true", help="do not write the packet")
    p_compile.add_argument("--json", action="store_true", help="print the packet JSON instead of the brief")

    p_replay = sub.add_parser("replay", help="print a text report for a persisted packet")
    p_replay.add_argument("packet", help="path to a packet .json file")

    p_init = sub.add_parser("init", help="scaffold a default .evidence-compiler/config.yaml")
    p_init.add_argument("--repo", default=os.getcwd())
    p_init.add_argument("--force", action="store_true")

    sub.add_parser("hook", help="Claude Code Desktop UserPromptSubmit adapter (reads stdin)")

    args = parser.parse_args(argv)

    if args.command == "compile":
        return _cmd_compile(args)
    if args.command == "replay":
        return _cmd_replay(args)
    if args.command == "init":
        return _cmd_init(args)
    if args.command == "hook":
        from .integrations.claude_code import main as hook_main

        return hook_main()

    parser.print_help()
    return 0


def _cmd_compile(args: argparse.Namespace) -> int:
    from .compiler import compile_packet

    result = compile_packet(
        prompt=args.prompt,
        repository_root=args.repo,
        cwd=args.cwd,
        active_file=args.active_file,
        session_id=args.session,
        turn_id=args.turn,
        persist=not args.no_persist,
    )
    if args.json:
        sys.stdout.write(result.packet.to_json() + "\n")
    else:
        if result.brief:
            sys.stdout.write(result.brief)
        else:
            sys.stderr.write("(no evidence selected — empty brief)\n")
        if result.storage_path:
            sys.stderr.write(f"packet: {result.storage_path}\n")
    return 0


def _cmd_replay(args: argparse.Namespace) -> int:
    try:
        packet = load_packet(args.packet)
    except FileNotFoundError:
        sys.stderr.write(f"error: no such packet file: {args.packet}\n")
        return 2
    except SchemaVersionError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2
    sys.stdout.write(render_replay_report(packet, cwd=os.getcwd()))
    return 0


def render_replay_report(packet: EvidencePacket, *, cwd: str | None = None) -> str:
    selected = [e for e in packet.evidence if e.compiler_assessment.selected]
    omitted = [e for e in packet.evidence if not e.compiler_assessment.selected]
    lines: list[str] = []
    mismatch = _identity_mismatch(packet, cwd)
    if mismatch:
        lines.append(f"WARNING: {mismatch}")
        lines.append("This packet does not describe the current repository/worktree/HEAD.")
        lines.append("Treat it as historical evidence only, not current state.")
        lines.append("")
    lines += [
        f"packet_id      {packet.packet_id}",
        f"schema_version {packet.schema_version}",
        f"created_at     {packet.created_at}",
        f"repository     {packet.identity.repository_root}",
        f"worktree       {packet.identity.worktree_id or '(main)'}",
        f"head           {packet.identity.head or '(unknown)'}  branch {packet.identity.branch or '(none)'}",
        f"intent         {packet.task.intent}",
        f"symbols        {', '.join(packet.task.extracted_symbols) or '(none)'}",
        f"scope          {packet.scope.confidence} [{', '.join(packet.scope.sources) or 'none'}]",
        "",
        f"evidence       {len(packet.evidence)} total  |  {len(selected)} selected  |  {len(omitted)} omitted",
        f"negative       {len(packet.negative_evidence)} absence item(s)",
        f"budget         injected {packet.budget.injected_tokens} / max {packet.budget.max_tokens} tokens "
        f"(candidate {packet.budget.candidate_tokens})",
        "",
        "collectors:",
    ]
    for run in packet.collectors_run:
        reason = run.diagnostic.get("reason") if isinstance(run.diagnostic, dict) else None
        suffix = f"  ({reason})" if reason else ""
        lines.append(f"  {run.name:<10} {run.status:<8} {run.duration_ms:>8.1f} ms{suffix}")
    lines.append("")
    lines.append(f"timing         total {packet.timing.total_ms:.1f} ms  stages {packet.timing.stages}")
    if selected:
        lines.append("")
        lines.append("selected evidence:")
        for e in selected:
            why = "; ".join(e.compiler_assessment.selected_because)
            lines.append(
                f"  [{e.provenance.collector}] {e.source_claim.statement[:80]}"
                f"  (score {e.compiler_assessment.final_score:.2f}; {why})"
            )
    return "\n".join(lines) + "\n"


def _identity_mismatch(packet: EvidencePacket, cwd: str | None) -> str | None:
    """Return a human-readable reason if ``packet`` was not captured for
    ``cwd``'s repository, or ``None`` if they match / cannot be compared.

    Only checks ``repository_root`` (verifiable without shelling out to git);
    this keeps ``render_replay_report`` a pure function of its inputs, as
    ``evidence replay`` is a read-only diagnostic tool (build brief §8).
    """
    root = packet.identity.repository_root
    if not cwd or not root:
        return None
    norm_cwd = os.path.abspath(cwd).replace("\\", "/")
    norm_root = os.path.abspath(root).replace("\\", "/")
    if norm_cwd != norm_root and not norm_cwd.startswith(norm_root + "/"):
        return f"packet was captured for repository {norm_root!r}, not {norm_cwd!r}"
    return None


def _cmd_init(args: argparse.Namespace) -> int:
    from .templates import claude_settings_json, default_config_yaml

    target_dir = os.path.join(args.repo, ".evidence-compiler")
    os.makedirs(target_dir, exist_ok=True)
    target = os.path.join(target_dir, "config.yaml")
    if os.path.exists(target) and not args.force:
        sys.stderr.write(f"config already exists: {target} (use --force to overwrite)\n")
        return 1
    with open(target, "w", encoding="utf-8") as fh:
        fh.write(default_config_yaml())
    sys.stdout.write(f"wrote {target}\n")
    # Guidance only — never write .claude/settings.json ourselves, to avoid
    # clobbering the user's existing hooks. They merge this block in manually.
    sys.stdout.write(
        "\nTo enable the Claude Code Desktop adapter, merge this block into "
        "your project's .claude/settings.json:\n\n"
    )
    sys.stdout.write(claude_settings_json().rstrip() + "\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
