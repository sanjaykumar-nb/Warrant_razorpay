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

from warrant.annotate import build_items, load_annotations, report, run_session
from warrant.baseline import inter_model_agreement, print_comparison
from warrant.baseline import summarise as summarise_comparison
from warrant.evidence import build_evidence_pack
from warrant.gate import gate_verdict, run_gate
from warrant.generate import DATA_PATH, generate_sessions
from warrant.metrics import print_report, run_pipeline
from warrant.remediation import decide
from warrant.remediation import summarise as summarise_remediation
from warrant.schemas import Finding, Session
from warrant.verifier import HeuristicVerifier, get_verifier

RESULTS_DIR = DATA_PATH.parent.parent / "results"
FINDINGS_CACHE = RESULTS_DIR / "findings.json"
VERIFIER_CACHE = RESULTS_DIR / "verifier_cache.json"
ANNOTATIONS_DIR = RESULTS_DIR.parent / "annotations"
ANNOTATION_SEED = 4242


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

    print()
    print(summarise_remediation([decide(sess, all_findings) for sess in sessions]))


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



def cmd_baseline(_args: argparse.Namespace) -> None:
    """Compare a rule-based keyword verifier against the semantic one on
    the same batch. Uses the cached model results, so this costs nothing
    and needs no API key."""
    sessions = _load_or_generate()

    heuristic_result = run_pipeline(sessions, HeuristicVerifier())
    baseline = summarise_comparison(heuristic_result, "keyword baseline")

    verifier = get_verifier()
    model_result = run_pipeline(sessions, verifier, cache_path=VERIFIER_CACHE)
    model = summarise_comparison(model_result, getattr(verifier, "MODEL", verifier.name).split("/")[-1])

    print_comparison(baseline, model)



def cmd_agreement(_args: argparse.Namespace) -> None:
    sessions = _load_or_generate()
    by_id = {s.session_id: s for s in sessions}
    print(inter_model_agreement(RESULTS_DIR, by_id))



def _annotation_items():
    from warrant.generate import SEED
    return build_items(_load_or_generate(), seed=ANNOTATION_SEED)


def cmd_annotate(args: argparse.Namespace) -> None:
    items = _annotation_items()
    out = ANNOTATIONS_DIR / f"{args.name}.json"
    run_session(items, args.name, out)


def cmd_annotation_report(_args: argparse.Namespace) -> None:
    sessions = _load_or_generate()
    by_id = {s.session_id: s for s in sessions}
    items = _annotation_items()

    model_flagged: set[str] = set()
    if FINDINGS_CACHE.exists():
        for f in json.loads(FINDINGS_CACHE.read_text(encoding="utf-8")):
            if f.get("detected_by") == "verifier":
                model_flagged.add(f["session_id"])

    print(report(load_annotations(ANNOTATIONS_DIR), items, by_id, model_flagged))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="warrant")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("generate", help="regenerate the synthetic session batch").set_defaults(func=cmd_generate)
    sub.add_parser("gate", help="run the deterministic gate only").set_defaults(func=cmd_gate)
    sub.add_parser("demo", help="run the full pipeline and print every metric").set_defaults(func=cmd_demo)
    sub.add_parser("baseline", help="compare the rule-based baseline against the semantic verifier").set_defaults(func=cmd_baseline)
    sub.add_parser("agreement", help="inter-model agreement across cached runs").set_defaults(func=cmd_agreement)

    ann = sub.add_parser("annotate", help="label the contested cases yourself (blind to ground truth)")
    ann.add_argument("--name", required=True, help="annotator name, e.g. your first name")
    ann.set_defaults(func=cmd_annotate)

    sub.add_parser("annotation-report",
                   help="inter-annotator agreement + human vs model vs ground truth").set_defaults(func=cmd_annotation_report)

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
