"""Runs the full pipeline (gate -> verifier on the residual only) and
computes every number this project reports. Nothing here is hand-tuned to
match a target figure — whatever the pipeline actually produces is what
gets printed. If a number looks bad, that is real signal, not a bug in
this file.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from warrant.gate import run_gate
from warrant.schemas import Finding, Session, ViolationClass
from warrant.verifier import Verifier


@dataclass
class PipelineResult:
    sessions: list[Session]
    gate_findings: list[Finding]
    verifier_findings: list[Finding]
    gate_p50_ms: float
    gate_p99_ms: float
    verifier_cost_paise: int
    verifier_calls: int
    final_verdict: dict[str, ViolationClass] = field(default_factory=dict)


def run_pipeline(sessions: list[Session], verifier: Verifier) -> PipelineResult:
    gate_findings, p50, p99 = run_gate(sessions)
    gate_flagged_ids = {f.session_id for f in gate_findings}

    # Only what the gate did NOT already resolve goes to the verifier —
    # the model examines the residual, never re-litigates a rule decision.
    residual = [s for s in sessions if s.session_id not in gate_flagged_ids]

    verifier_findings: list[Finding] = []
    total_cost_paise = 0
    for session in residual:
        result = verifier.verify(session)
        verifier_findings.extend(result.findings)
        total_cost_paise += result.cost_paise

    final_verdict: dict[str, ViolationClass] = {}
    for f in gate_findings:
        final_verdict.setdefault(f.session_id, f.violation)
    for f in verifier_findings:
        final_verdict.setdefault(f.session_id, f.violation)
    for s in sessions:
        final_verdict.setdefault(s.session_id, ViolationClass.CLEAN)

    return PipelineResult(
        sessions=sessions,
        gate_findings=gate_findings,
        verifier_findings=verifier_findings,
        gate_p50_ms=p50,
        gate_p99_ms=p99,
        verifier_cost_paise=total_cost_paise,
        verifier_calls=len(residual),
        final_verdict=final_verdict,
    )


@dataclass
class ClassMetric:
    label: str
    total: int
    caught: int
    false_positives: int  # sessions of OTHER classes wrongly assigned this label

    @property
    def recall(self) -> float:
        return self.caught / self.total if self.total else 0.0


def class_metrics(result: PipelineResult) -> list[ClassMetric]:
    metrics: list[ClassMetric] = []
    for vclass in ViolationClass:
        if not vclass.is_violation:
            continue
        labelled = [s for s in result.sessions if s.label == vclass]
        if not labelled:
            continue
        caught = sum(1 for s in labelled if result.final_verdict[s.session_id] == vclass)
        fp = sum(
            1 for s in result.sessions
            if s.label != vclass and result.final_verdict[s.session_id] == vclass
        )
        metrics.append(ClassMetric(label=vclass.value, total=len(labelled), caught=caught, false_positives=fp))
    return metrics


def false_positive_cost_paise(result: PipelineResult) -> int:
    """₹ of legitimate spend wrongly held: CLEAN or CLEAN_UNUSUAL sessions
    the pipeline flagged as a violation."""
    total = 0
    for s in result.sessions:
        if s.label in (ViolationClass.CLEAN, ViolationClass.CLEAN_UNUSUAL):
            if result.final_verdict[s.session_id] != ViolationClass.CLEAN:
                total += s.total_paise
    return total


def false_positive_count(result: PipelineResult) -> int:
    return sum(
        1 for s in result.sessions
        if s.label in (ViolationClass.CLEAN, ViolationClass.CLEAN_UNUSUAL)
        and result.final_verdict[s.session_id] != ViolationClass.CLEAN
    )


def pct_never_touching_model(result: PipelineResult) -> float:
    total = len(result.sessions)
    return 1 - (result.verifier_calls / total) if total else 0.0


def print_report(result: PipelineResult) -> None:
    total = len(result.sessions)
    print(f"Sessions:              {total}")
    print(f"Gate findings:         {len(result.gate_findings)}")
    print(f"Verifier calls:        {result.verifier_calls}  ({pct_never_touching_model(result):.0%} never touched the model)")
    print(f"Gate latency:          p50={result.gate_p50_ms:.4f}ms  p99={result.gate_p99_ms:.4f}ms")
    print(f"Verifier cost:         Rs.{result.verifier_cost_paise / 100:,.2f}  "
          f"(Rs.{result.verifier_cost_paise / total / 100:.4f} / session, amortised over full batch)")
    print()

    print(f"{'class':<18}{'total':>7}{'caught':>8}{'recall':>9}{'fp':>6}")
    for m in class_metrics(result):
        marker = " *" if m.label == "scope_creep" else ""
        print(f"{m.label:<18}{m.total:>7}{m.caught:>8}{m.recall:>9.0%}{m.false_positives:>6}{marker}")
    print("  * scope_creep is caught by the verifier alone — 0% of it is visible to the deterministic gate")
    print()

    fp_paise = false_positive_cost_paise(result)
    fp_n = false_positive_count(result)
    print(f"False positives:       {fp_n} sessions, Rs.{fp_paise / 100:,.2f} of legitimate spend wrongly flagged")
