"""Runs the full pipeline (gate -> verifier on the residual only) and
computes every number this project reports. Nothing here is hand-tuned to
match a target figure — whatever the pipeline actually produces is what
gets printed. If a number looks bad, that is real signal, not a bug in
this file.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

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
    verifier_cost_paise: int          # what this run ACTUALLY cost
    verifier_projected_paise: int     # what it WOULD cost on a paid frontier model
    verifier_price_label: str
    verifier_calls: int
    final_verdict: dict[str, ViolationClass] = field(default_factory=dict)


def run_pipeline(
    sessions: list[Session],
    verifier: Verifier,
    cache_path: Path | None = None,
) -> PipelineResult:
    """Gate first, then the verifier on the residual only.

    Verifier results are cached per session and flushed to disk as they
    arrive. Free-tier providers enforce a daily token cap, and hitting it
    mid-batch previously discarded every completed call — ~199k tokens of
    finished work lost to a 429 on the last session. With the cache, a
    re-run skips what is already done and resumes where it stopped.

    The cache key includes the model, so switching providers or models
    correctly invalidates rather than silently mixing results from two
    different models into one reported number.
    """
    gate_findings, p50, p99 = run_gate(sessions)
    gate_flagged_ids = {f.session_id for f in gate_findings}

    # Only what the gate did NOT already resolve goes to the verifier —
    # the model examines the residual, never re-litigates a rule decision.
    residual = [s for s in sessions if s.session_id not in gate_flagged_ids]

    model = getattr(verifier, "MODEL", verifier.name)

    # One cache file per model. Results from different models must never
    # be mixed into a single reported number, but nor should switching
    # models destroy work already done on the previous one — that lesson
    # cost 170 completed sessions the first time round.
    if cache_path:
        slug = model.replace("/", "_").replace(":", "_")
        cache_path = cache_path.with_name(f"{cache_path.stem}_{slug}{cache_path.suffix}")

    cache: dict[str, dict] = {}
    if cache_path and cache_path.exists():
        raw = json.loads(cache_path.read_text(encoding="utf-8"))
        if raw.get("model") == model:
            cache = raw.get("entries", {})
            print(f"  resuming: {len(cache)} sessions already verified for {model}")

    def flush() -> None:
        if cache_path:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(
                json.dumps({"model": model, "entries": cache}, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

    verifier_findings: list[Finding] = []
    total_cost_paise = 0
    total_projected_paise = 0
    price_label = getattr(verifier, "PRICE", None)
    price_label = price_label.label if price_label else "unknown"

    for i, session in enumerate(residual):
        if session.session_id in cache:
            entry = cache[session.session_id]
        else:
            try:
                r = verifier.verify(session)
            except Exception:
                flush()  # never lose completed work to a failure on a later call
                print(f"\n  verifier failed after {len(cache)}/{len(residual)} sessions; "
                      f"progress saved to {cache_path}. Re-run to resume.")
                raise
            entry = {
                "findings": [f.model_dump(mode="json") for f in r.findings],
                "cost_paise": r.cost_paise,
                "projected_cost_paise": r.projected_cost_paise,
            }
            cache[session.session_id] = entry
            if (i + 1) % 10 == 0:
                flush()

        verifier_findings.extend(Finding.model_validate(f) for f in entry["findings"])
        total_cost_paise += entry["cost_paise"]
        total_projected_paise += entry["projected_cost_paise"]

    flush()

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
        verifier_projected_paise=total_projected_paise,
        verifier_price_label=price_label,
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
    """One row per violation class — except SCOPE_CREEP, which is split by
    difficulty. A strong score on clear-cut cases means little if the
    ambiguous ones fail, so collapsing them into one number would hide
    exactly the thing worth knowing."""
    metrics: list[ClassMetric] = []
    for vclass in ViolationClass:
        if not vclass.is_violation:
            continue
        labelled = [s for s in result.sessions if s.label == vclass]
        if not labelled:
            continue

        fp = sum(
            1 for s in result.sessions
            if s.label != vclass and result.final_verdict[s.session_id] == vclass
        )

        tiers = sorted({s.difficulty for s in labelled})
        if len(tiers) == 1:
            caught = sum(1 for s in labelled if result.final_verdict[s.session_id] == vclass)
            metrics.append(ClassMetric(label=vclass.value, total=len(labelled),
                                       caught=caught, false_positives=fp))
        else:
            for tier in tiers:
                subset = [s for s in labelled if s.difficulty == tier]
                caught = sum(1 for s in subset if result.final_verdict[s.session_id] == vclass)
                # False positives belong to the CLASS, not to a difficulty
                # tier — attributing them to whichever tier sorts first
                # reads as if that tier caused them, which is wrong. They
                # are reported in the per-class breakdown below instead.
                metrics.append(ClassMetric(
                    label=f"{vclass.value} ({tier})",
                    total=len(subset),
                    caught=caught,
                    false_positives=-1,  # -1 renders as "-"
                ))
    return metrics


def false_positive_cost_paise(result: PipelineResult) -> int:
    """₹ of legitimate spend wrongly held: CLEAN or CLEAN_UNUSUAL sessions
    the pipeline flagged as a violation."""
    total = 0
    for s in result.sessions:
        if not s.label.is_violation:
            if result.final_verdict[s.session_id] != ViolationClass.CLEAN:
                total += s.total_paise
    return total


def false_positive_count(result: PipelineResult) -> int:
    return sum(
        1 for s in result.sessions
        if not s.label.is_violation
        and result.final_verdict[s.session_id] != ViolationClass.CLEAN
    )


def false_positives_by_class(result: PipelineResult) -> dict[str, tuple[int, int]]:
    """{label: (wrongly_flagged, total)} for every non-violation class.
    Broken out because a single FP number hides WHICH kind of legitimate
    purchase the system blocks — and the hard classes are the point."""
    out: dict[str, tuple[int, int]] = {}
    for vclass in ViolationClass:
        if vclass.is_violation:
            continue
        subset = [s for s in result.sessions if s.label == vclass]
        if not subset:
            continue
        wrong = sum(
            1 for s in subset
            if result.final_verdict[s.session_id] != ViolationClass.CLEAN
        )
        out[vclass.value] = (wrong, len(subset))
    return out


def pct_never_touching_model(result: PipelineResult) -> float:
    total = len(result.sessions)
    return 1 - (result.verifier_calls / total) if total else 0.0


def print_report(result: PipelineResult) -> None:
    total = len(result.sessions)
    print(f"Sessions:              {total}")
    print(f"Gate findings:         {len(result.gate_findings)}")
    print(f"Verifier calls:        {result.verifier_calls}  ({pct_never_touching_model(result):.0%} never touched the model)")
    print(f"Gate latency:          p50={result.gate_p50_ms:.4f}ms  p99={result.gate_p99_ms:.4f}ms")
    print(f"Verifier cost (ACTUAL):    Rs.{result.verifier_cost_paise / 100:,.2f}  "
          f"[{result.verifier_price_label}]")
    print(f"  projected on paid model: Rs.{result.verifier_projected_paise / 100:,.2f}  "
          f"(Rs.{result.verifier_projected_paise / total / 100:.4f}/session at Claude Sonnet 5 rates)")
    print(f"  ^ projection only - NOT spend incurred on this run")
    print()

    print(f"{'class':<26}{'total':>7}{'caught':>8}{'recall':>9}{'fp':>6}")
    for m in class_metrics(result):
        marker = " *" if m.label.startswith("scope_creep") else ""
        fp_cell = "-" if m.false_positives < 0 else str(m.false_positives)
        print(f"{m.label:<26}{m.total:>7}{m.caught:>8}{m.recall:>9.0%}{fp_cell:>6}{marker}")
    print("  * scope_creep is caught by the verifier alone — 0% of it is visible to the deterministic gate")
    print()

    fp_paise = false_positive_cost_paise(result)
    fp_n = false_positive_count(result)
    print(f"False positives:       {fp_n} sessions, Rs.{fp_paise / 100:,.2f} of legitimate spend wrongly flagged")
    print()
    print("  false positives by legitimate-purchase class:")
    for label, (wrong, tot) in false_positives_by_class(result).items():
        rate = wrong / tot if tot else 0.0
        note = "  <- hard case" if label in ("clean_mandatory", "clean_underspecified") else ""
        print(f"    {label:<24}{wrong:>4}/{tot:<5}  {rate:>6.0%}{note}")
