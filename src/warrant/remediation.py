"""Deciding what to actually DO about a finding.

Two criticisms drove this module, and both were correct.

**"Telling a human after the payment is useless."** Mostly true — but a
payment is not one moment. Between authorisation and capture the funds
are held, not taken, and that window is far longer than a verification
takes. So the question is not "block or allow" but "what is still
possible at this stage".

**"The false positive rate is too high to act on."** Also true, and it is
why nothing here blocks a purchase outright. The system's own measured
failure was 32% on statutory charges, at confidence 0.85-1.0 — so
confidence thresholds alone could not have saved it. Taxes are now
settled arithmetically before the model is asked (see taxes.py), and what
remains is handled by never spending a false positive on the whole
purchase.

The primitive that makes this work is **partial capture**: authorise
Rs.8,850, decide that Rs.1,050 of add-ons were not asked for, capture
Rs.7,800. The flight still books. The customer is not charged for what
they did not request. Nobody is blocked. A false positive costs one line
item, not the transaction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from warrant.schemas import Finding, PaymentStage, Session


class Action(StrEnum):
    CAPTURE_FULL = "capture_full"
    PARTIAL_CAPTURE = "partial_capture"      # capture minus the disputed lines
    HOLD_FOR_CONFIRMATION = "hold_for_confirmation"  # ask the human first
    REFUND_LINE = "refund_line"              # already captured; give it back
    FLAG_FOR_DISPUTE = "flag_for_dispute"    # settled; only a dispute remains
    LOG_ONLY = "log_only"                    # too uncertain to act on


# Above this, an unrequested charge is worth interrupting a human for.
# Below it, silently declining the line is less annoying than a prompt.
CONFIRMATION_THRESHOLD_PAISE = 200_000  # Rs.2,000

# Below this confidence the finding is recorded but never acted on.
ACTION_CONFIDENCE_FLOOR = 0.75


@dataclass
class Remediation:
    session_id: str
    action: Action
    stage: PaymentStage
    disputed_skus: list[str] = field(default_factory=list)
    disputed_paise: int = 0
    capture_paise: int = 0
    rationale: str = ""

    @property
    def customer_protected_paise(self) -> int:
        """Money the customer does not pay because of this decision."""
        return self.disputed_paise if self.action in (
            Action.PARTIAL_CAPTURE, Action.REFUND_LINE, Action.HOLD_FOR_CONFIRMATION
        ) else 0


def decide(session: Session, findings: list[Finding]) -> Remediation:
    """Choose the narrowest action that fixes the problem.

    Deliberately, no branch blocks the whole purchase. The worst outcome
    for a legitimate line item is that it is held for one confirmation,
    and the worst outcome for a false positive is that one line is not
    captured — recoverable, and far cheaper than a declined transaction.
    """
    # Filter by session as well as by detector. Callers routinely pass the
    # whole batch's findings, and without the session_id check every
    # session inherits every other session's findings — which showed up
    # as all 340 sessions reporting partial_capture.
    verifier_findings = [
        f for f in findings
        if f.detected_by == "verifier" and f.session_id == session.session_id
    ]
    total = session.total_paise

    if not verifier_findings:
        return Remediation(
            session_id=session.session_id, action=Action.CAPTURE_FULL,
            stage=session.stage, capture_paise=total,
            rationale="Nothing flagged; every line item was within the mandate.",
        )

    actionable = [f for f in verifier_findings if f.confidence >= ACTION_CONFIDENCE_FLOOR]
    if not actionable:
        return Remediation(
            session_id=session.session_id, action=Action.LOG_ONLY,
            stage=session.stage, capture_paise=total,
            rationale=(
                f"{len(verifier_findings)} finding(s) below the {ACTION_CONFIDENCE_FLOOR} "
                "confidence floor. Recorded for review; the purchase is unaffected."
            ),
        )

    disputed_skus = sorted({sku for f in actionable for sku in f.offending_items})
    by_sku = {i.sku: i.amount_paise for i in session.line_items}
    disputed = sum(by_sku.get(s, 0) for s in disputed_skus)

    common = dict(
        session_id=session.session_id, stage=session.stage,
        disputed_skus=disputed_skus, disputed_paise=disputed,
    )

    if session.stage is PaymentStage.AUTHORISED:
        # Funds are held, so the disputed lines can simply not be taken.
        if disputed >= CONFIRMATION_THRESHOLD_PAISE:
            return Remediation(
                **common, action=Action.HOLD_FOR_CONFIRMATION,
                capture_paise=total - disputed,
                rationale=(
                    f"Rs.{disputed/100:,.2f} of unrequested charges — above the "
                    f"Rs.{CONFIRMATION_THRESHOLD_PAISE/100:,.0f} threshold, so the customer "
                    "is asked before anything is captured."
                ),
            )
        return Remediation(
            **common, action=Action.PARTIAL_CAPTURE,
            capture_paise=total - disputed,
            rationale=(
                f"Capturing Rs.{(total-disputed)/100:,.2f} of Rs.{total/100:,.2f}. The "
                f"{len(disputed_skus)} unrequested line(s) are simply not taken — the "
                "purchase itself completes."
            ),
        )

    if session.stage is PaymentStage.CAPTURED:
        return Remediation(
            **common, action=Action.REFUND_LINE, capture_paise=total,
            rationale=(
                f"Already captured, so Rs.{disputed/100:,.2f} is refunded line-by-line "
                "rather than reversing the whole purchase."
            ),
        )

    return Remediation(
        **common, action=Action.FLAG_FOR_DISPUTE, capture_paise=total,
        rationale=(
            "Already settled to the merchant. Only a dispute remains — the evidence "
            "pack is what makes that winnable."
        ),
    )


def summarise(remediations: list[Remediation]) -> str:
    counts: dict[str, int] = {}
    protected = 0
    for r in remediations:
        counts[r.action.value] = counts.get(r.action.value, 0) + 1
        protected += r.customer_protected_paise

    lines = ["Remediation actions taken", ""]
    for action, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        lines.append(f"    {action:<24}{n:>5}")
    lines += [
        "",
        f"  Customer money protected: Rs.{protected/100:,.2f}",
        "  No purchase was blocked outright. A wrong finding costs one line",
        "  item, never the whole transaction.",
    ]
    return "\n".join(lines)
