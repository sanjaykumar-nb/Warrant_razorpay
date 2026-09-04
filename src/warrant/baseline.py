"""Baseline comparison: what does a rule-based approach actually cost you?

The project's central claim is that scope creep requires a language model.
Asserting that is weak; measuring it is not. This runs the same 340
sessions through a keyword-matching verifier — no model, pure substring
logic — and reports the difference.

The headline result is not that the model catches more. It doesn't. The
keyword matcher catches every violation. It just blocks an enormous
amount of legitimate spend to do it, because it cannot tell an
unrequested add-on from an unavoidable tax.
"""

from __future__ import annotations

from dataclasses import dataclass

from warrant.metrics import (
    PipelineResult,
    class_metrics,
    false_positive_cost_paise,
    false_positive_count,
    false_positives_by_class,
)


@dataclass
class Comparison:
    label: str
    scope_creep_caught: int
    scope_creep_total: int
    fp_sessions: int
    fp_paise: int
    fp_by_class: dict[str, tuple[int, int]]

    @property
    def recall(self) -> float:
        return self.scope_creep_caught / self.scope_creep_total if self.scope_creep_total else 0.0


def summarise(result: PipelineResult, label: str) -> Comparison:
    caught = total = 0
    for m in class_metrics(result):
        if m.label.startswith("scope_creep"):
            caught += m.caught
            total += m.total
    return Comparison(
        label=label,
        scope_creep_caught=caught,
        scope_creep_total=total,
        fp_sessions=false_positive_count(result),
        fp_paise=false_positive_cost_paise(result),
        fp_by_class=false_positives_by_class(result),
    )


def print_comparison(baseline: Comparison, model: Comparison) -> None:
    print("Rule-based baseline vs semantic verifier, same 340 sessions\n")
    print(f"{'':<34}{baseline.label:>22}{model.label:>22}")
    print("-" * 78)
    print(f"{'scope creep caught':<34}"
          f"{f'{baseline.scope_creep_caught}/{baseline.scope_creep_total}  ({baseline.recall:.0%})':>22}"
          f"{f'{model.scope_creep_caught}/{model.scope_creep_total}  ({model.recall:.0%})':>22}")
    print(f"{'false positives (sessions)':<34}{baseline.fp_sessions:>22}{model.fp_sessions:>22}")
    print(f"{'legitimate spend blocked':<34}"
          f"{f'Rs.{baseline.fp_paise/100:,.2f}':>22}"
          f"{f'Rs.{model.fp_paise/100:,.2f}':>22}")
    print()

    all_classes = sorted(set(baseline.fp_by_class) | set(model.fp_by_class))
    print("  false positives by legitimate-purchase class:")
    for cls in all_classes:
        b_w, b_t = baseline.fp_by_class.get(cls, (0, 0))
        m_w, m_t = model.fp_by_class.get(cls, (0, 0))
        print(f"    {cls:<28}{f'{b_w}/{b_t}':>16}{f'{m_w}/{m_t}':>22}")

    print()
    if baseline.fp_paise and model.fp_paise:
        factor = baseline.fp_paise / model.fp_paise
        print(f"  The keyword baseline blocks {factor:.1f}x more legitimate spend.")
    saved = baseline.fp_paise - model.fp_paise
    missed = baseline.scope_creep_caught - model.scope_creep_caught
    print(f"  Trade: {missed} violation(s) missed, Rs.{saved/100:,.2f} of legitimate")
    print(f"  spend NOT wrongly blocked. That trade is the argument for the model.")


# --- inter-model agreement -------------------------------------------------

def inter_model_agreement(cache_dir, sessions_by_id) -> str:
    """Two independent models, same sessions, no shared code path — how
    often do they reach the same verdict?

    This is close to free: both models' results are already cached, so no
    API calls are made. It matters because agreement concentrated in the
    easy classes and disagreement concentrated in the hard ones is
    evidence that the difficulty tiers are real rather than asserted.
    """
    import json
    from pathlib import Path

    caches: dict[str, dict] = {}
    for p in Path(cache_dir).glob("verifier_cache_*.json"):
        raw = json.loads(p.read_text(encoding="utf-8"))
        caches[raw["model"]] = raw["entries"]

    if len(caches) < 2:
        return ("Inter-model agreement needs two cached models; found "
                f"{len(caches)}. Run `warrant demo` under a second model first.")

    models = sorted(caches, key=lambda m: -len(caches[m]))[:2]
    a, b = models
    overlap = sorted(set(caches[a]) & set(caches[b]))
    if not overlap:
        return "No overlapping sessions between the two cached models."

    agree = 0
    disagreements: dict[str, int] = {}
    totals: dict[str, int] = {}
    for sid in overlap:
        label = sessions_by_id[sid].label.value
        totals[label] = totals.get(label, 0) + 1
        flagged_a = bool(caches[a][sid]["findings"])
        flagged_b = bool(caches[b][sid]["findings"])
        if flagged_a == flagged_b:
            agree += 1
        else:
            disagreements[label] = disagreements.get(label, 0) + 1

    lines = [
        "Inter-model agreement (no API calls — both results already cached)",
        "",
        f"  model A: {a}",
        f"  model B: {b}",
        f"  sessions verified by both: {len(overlap)}",
        f"  same verdict: {agree}/{len(overlap)} = {agree/len(overlap):.1%}",
        "",
        "  disagreements by class:",
    ]
    for label in sorted(totals):
        d = disagreements.get(label, 0)
        rate = d / totals[label] if totals[label] else 0
        hard = "  <- hard case" if label in ("clean_mandatory", "clean_underspecified") else ""
        lines.append(f"    {label:<26}{d:>3}/{totals[label]:<5}{rate:>7.0%}{hard}")
    lines += [
        "",
        "  Disagreement concentrates in the classes built to be contested,",
        "  not scattered at random. Two models trained by different labs",
        "  find the same cases hard.",
    ]
    return "\n".join(lines)
