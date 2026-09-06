"""``evidence`` command-line interface.

Subcommands:

- ``compile``  run the critical path for a prompt and print the brief.
- ``replay``   minimal text report over a persisted packet (build brief section 8).
- ``init``     scaffold ``.evidence-compiler/config.yaml`` from the template.
- ``hook``     deprecated; a thin shim over ``hook-safe`` kept only for
  existing configurations. Point new setups at ``hook-safe`` instead.
- ``hook-safe`` recommended Claude Code Desktop ``UserPromptSubmit`` adapter:
  fail-open, byte-exact UTF-8, storage-path gate, bounded retention,
  sanitized diagnostics.
"""

from __future__ import annotations

import argparse
import json
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

    sub.add_parser(
        "hook",
        help="[deprecated: use hook-safe] Claude Code Desktop UserPromptSubmit "
        "adapter (reads stdin); now a thin shim over hook-safe",
    )

    sub.add_parser(
        "hook-safe",
        help="recommended UserPromptSubmit launcher: fail-open, byte-exact UTF-8, "
        "storage-path gate, bounded retention, sanitized diagnostics (reads stdin)",
    )

    p_review = sub.add_parser(
        "review",
        help="local packet-review workflow: inventory, queue, sample, label, status, remind, window",
    )
    p_review.add_argument("--repo", default=os.getcwd(), help="repository root (default: cwd)")
    review_sub = p_review.add_subparsers(dest="review_command")
    r_inv = review_sub.add_parser("inventory", help="list packets with traffic class and outcomes")
    r_inv.add_argument("--all", action="store_true", help="include packets before the current window")
    r_sample = review_sub.add_parser("sample", help="draw a reproducible stratified sample to review")
    r_sample.add_argument("--seed", type=int, default=1)
    r_sample.add_argument("--n", type=int, default=8)
    r_sample.add_argument("--all", action="store_true", help="sample across all packets, not only the window")
    r_sample.add_argument("--include-labeled", action="store_true")
    r_queue = review_sub.add_parser(
        "queue", help="deterministic list of the next unlabeled packets to review (labeling never reorders it)"
    )
    r_queue.add_argument("--n", type=int, default=10)
    r_queue.add_argument("--all", action="store_true", help="queue across all packets, not only the window")
    r_label = review_sub.add_parser("label", help="record a usefulness label for a packet")
    r_label.add_argument("packet_id", help="packet id or unique prefix")
    r_label.add_argument("label", choices=("helped", "neutral", "hurt-noise", "insufficient"))
    r_label.add_argument("--note", default=None, help="required short rationale (<= 200 chars)")
    review_sub.add_parser("status", help="aggregates, operational health, and window-due check")
    review_sub.add_parser("remind", help="print one line if a review is due, nothing otherwise")
    r_window = review_sub.add_parser("window", help="manage the review window")
    r_window.add_argument("action", choices=("start", "show"))
    r_window.add_argument("--name", default=None, help="window name (required for start)")
    r_window.add_argument("--note", default=None)

    args = parser.parse_args(argv)

    if args.command == "compile":
        return _cmd_compile(args)
    if args.command == "replay":
        return _cmd_replay(args)
    if args.command == "review":
        return _cmd_review(args, p_review)
    if args.command == "init":
        return _cmd_init(args)
    if args.command == "hook":
        from .integrations.claude_code import main as hook_main

        return hook_main()
    if args.command == "hook-safe":
        from .integrations.hook_safe import main as hook_safe_main

        return hook_safe_main()

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


def _cmd_review(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    from . import review
    from .config import load_config

    repo = os.path.abspath(args.repo)
    cfg = load_config(repo)
    rdir = review.review_dir(repo)
    command = args.review_command
    if command is None:
        parser.print_help()
        return 0

    if command == "window":
        if args.action == "show":
            window = review.load_window(rdir)
            sys.stdout.write((json.dumps(window, indent=2) if window else "(no window)") + "\n")
            return 0
        if not args.name:
            sys.stderr.write("error: --name is required for `window start`\n")
            return 2
        inv = review.scan(repo, cfg)
        window = review.start_window(rdir, args.name, inv, note=args.note)
        sys.stdout.write(
            f"started window {window['name']} at {window['started_at']} "
            f"(baseline {window['baseline']['packets']} packets on disk)\n"
        )
        return 0

    inv = review.scan(repo, cfg)
    window = review.load_window(rdir)

    if command == "inventory":
        sys.stdout.write(review.render_inventory(inv, window, only_window=not args.all))
        return 0
    if command == "status":
        sys.stdout.write(review.render_status(inv, window, cfg))
        return 0
    if command == "sample":
        pool = inv.summaries if args.all else [s for s in inv.summaries if review.in_window(s, window)]
        chosen = review.sample(pool, seed=args.seed, size=args.n, include_labeled=args.include_labeled)
        sys.stdout.write(review.render_sample(chosen, seed=args.seed))
        return 0
    if command == "queue":
        pool = inv.summaries if args.all else [s for s in inv.summaries if review.in_window(s, window)]
        name = window.get("name") if window else None
        chosen = review.queue(pool, size=args.n, window_name=name)
        sys.stdout.write(review.render_queue(chosen, window_name=name))
        return 0
    if command == "remind":
        sys.stdout.write(review.remind(inv, window, cfg))
        return 0
    if command == "label":
        matches = [s for s in inv.summaries if s.packet_id.startswith(args.packet_id)]
        if len(matches) != 1:
            sys.stderr.write(
                f"error: packet id {args.packet_id!r} matches {len(matches)} packet(s); need exactly one\n"
            )
            return 2
        try:
            record = review.append_label(rdir, matches[0], args.label, note=args.note)
        except ValueError as exc:
            sys.stderr.write(f"error: {exc}\n")
            return 2
        sys.stdout.write(f"labeled {record['packet_id']} {record['label']}\n")
        return 0
    parser.print_help()
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
        f"head           {packet.identity.head or '(unknown)'}  branch {packet.identity.branch or '(none)'}"
        + (f"  [{packet.identity.head_state}]" if packet.identity.head_state else ""),
        f"intent         {packet.task.intent}  source {packet.task.source_kind}",
        f"symbols        {', '.join(packet.task.extracted_symbols) or '(none)'}",
        f"rejected       {_rejected_symbols(packet) or '(none)'}",
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


def _rejected_symbols(packet: EvidencePacket) -> str:
    parts = [
        f"{d.get('value')}:{d.get('reason')}"
        for d in packet.task.symbol_details
        if isinstance(d, dict) and not d.get("selected")
    ]
    return ", ".join(parts[:12]) + (" …" if len(parts) > 12 else "")


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
