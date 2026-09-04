"""Command-line entry point.

`uv run warrant gate`     — deterministic checks only. No API key, no cost.
`uv run warrant demo`     — full pipeline: gate, then verifier on the
                              residual. Prints every metric and caches
                              results to results/ so `evidence` doesn't
                              need to re-run (and re-pay for) the verifier.
`uv run warrant evidence <session_id>` — the evidence pack for one session.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from warrant.evidence import build_evidence_pack
from warrant.gate import gate_verdict, run_gate
from warrant.generate import DATA_PATH, generate_sessions
from warrant.metrics import print_report, run_pipeline
from warrant.schemas import Finding, Session
from warrant.verifier import get_verifier

RESULTS_DIR = DATA_PATH.parent.parent / "results"
FINDINGS_CACHE = RESULTS_DIR / "findings.json"
VERIFIER_CACHE = RESULTS_DIR / "verifier_cache.json"


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
        if verdicts[s.session_id].value != "clean":
            by_label[label]["flagged"] += 1

    print(f"Sessions: {len(sessions)}")
    print(f"Gate findings: {len(findings)}")
    print(f"Gate latency: p50={p50:.4f}ms  p99={p99:.4f}ms\n")
    print(f"{'label':<18}{'total':>8}{'gate-flagged':>15}")
    for label, c in sorted(by_label.items()):
        print(f"{label:<18}{c['total']:>8}{c['flagged']:>15}")


def cmd_demo(_args: argparse.Namespace) -> None:
    sessions = _load_or_generate()
    verifier = get_verifier()
    print(f"(verifier: {verifier.name} / {getattr(verifier, 'MODEL', 'n/a')})\n")
    result = run_pipeline(sessions, verifier, cache_path=VERIFIER_CACHE)
    print_report(result)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    all_findings: list[Finding] = [*result.gate_findings, *result.verifier_findings]
    FINDINGS_CACHE.write_text(
        json.dumps([f.model_dump(mode="json") for f in all_findings], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\nCached {len(all_findings)} findings -> {FINDINGS_CACHE}")


def cmd_evidence(args: argparse.Namespace) -> None:
    sessions = _load_or_generate()
    session = next((s for s in sessions if s.session_id == args.session_id), None)
    if session is None:
        print(f"No session with id {args.session_id!r}. Run 'warrant demo' first or check the id.")
        return

    if FINDINGS_CACHE.exists():
        findings = [Finding.model_validate(d) for d in json.loads(FINDINGS_CACHE.read_text(encoding="utf-8"))]
    else:
        print("No cached findings found — running the full pipeline once (this may call the API)...\n")
        verifier = get_verifier()
        result = run_pipeline(sessions, verifier, cache_path=VERIFIER_CACHE)
        findings = [*result.gate_findings, *result.verifier_findings]

    pack = build_evidence_pack(session, findings)
    print(json.dumps(pack, indent=2, ensure_ascii=False))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="warrant")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("generate", help="regenerate the synthetic session batch").set_defaults(func=cmd_generate)
    sub.add_parser("gate", help="run the deterministic gate only").set_defaults(func=cmd_gate)
    sub.add_parser("demo", help="run the full pipeline and print every metric").set_defaults(func=cmd_demo)

    ev = sub.add_parser("evidence", help="print the evidence pack for one session")
    ev.add_argument("session_id")
    ev.set_defaults(func=cmd_evidence)

    return parser


def app() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    app()
