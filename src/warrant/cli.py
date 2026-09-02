"""Command-line entry point.

`uv run warrant gate` runs the batch through the deterministic gate only
(no API key needed, no cost). `uv run warrant demo` — added once the
verifier exists — will run the full pipeline and print every metric in
the README.
"""

from __future__ import annotations

import argparse
import json

from warrant.gate import gate_verdict, run_gate
from warrant.generate import DATA_PATH, generate_sessions
from warrant.schemas import Session


def _load_or_generate() -> list[Session]:
    if DATA_PATH.exists():
        data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
        return [Session.model_validate(d) for d in data]
    return generate_sessions()


def cmd_generate(_args: argparse.Namespace) -> None:
    from warrant.generate import main as generate_main
    generate_main()


def cmd_gate(_args: argparse.Namespace) -> None:
    sessions = _load_or_generate()
    findings, p50, p99 = run_gate(sessions)
    verdicts = {s.session_id: gate_verdict(s, findings) for s in sessions}

    by_label: dict[str, dict[str, int]] = {}
    for s in sessions:
        label = s.label.value
        by_label.setdefault(label, {"total": 0, "flagged": 0})
        by_label[label]["total"] += 1
        if verdicts[s.session_id] != s.label and verdicts[s.session_id].value != "clean":
            pass  # detailed accuracy is metrics.py's job once the verifier exists
        if verdicts[s.session_id].value != "clean":
            by_label[label]["flagged"] += 1

    print(f"Sessions: {len(sessions)}")
    print(f"Gate findings: {len(findings)}")
    print(f"Gate latency: p50={p50:.4f}ms  p99={p99:.4f}ms\n")
    print(f"{'label':<18}{'total':>8}{'gate-flagged':>15}")
    for label, c in sorted(by_label.items()):
        print(f"{label:<18}{c['total']:>8}{c['flagged']:>15}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="warrant")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("generate", help="regenerate the synthetic session batch").set_defaults(func=cmd_generate)
    sub.add_parser("gate", help="run the deterministic gate over the batch and print a summary").set_defaults(func=cmd_gate)

    return parser


def app() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    app()
