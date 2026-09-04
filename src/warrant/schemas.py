"""Core data types for Warrant.

All money is integer paise. Never float — floating point rupees is the
single fastest way to lose credibility with anyone who has worked on a
payments system, and it is a real (if small) source of bugs.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class ViolationClass(StrEnum):
    """The loss class this project targets: agent-mediated unauthorised spend.

    CLEAN and CLEAN_UNUSUAL are not violations — they exist so the
    generator (and the metrics) can measure false positives honestly.
    """

    CLEAN = "clean"
    CLEAN_UNUSUAL = "clean_unusual"  # authorised but odd — must NOT be flagged
    # Two hard non-violation classes. The naive rule a verifier tends to
    # apply — "anything the intent didn't name is a violation" — gives the
    # WRONG answer on both, which is exactly what makes them worth testing.
    CLEAN_MANDATORY = "clean_mandatory"          # unavoidable fee, not an agent choice
    CLEAN_UNDERSPECIFIED = "clean_underspecified"  # vague intent, several items legitimately fit
    AMOUNT_CAP = "amount_cap"
    CUMULATIVE_CAP = "cumulative_cap"
    OUT_OF_CATEGORY = "out_of_category"
    EXPIRED_WINDOW = "expired_window"
    DUPLICATE = "duplicate"
    SCOPE_CREEP = "scope_creep"  # LLM-only — no deterministic rule can see this

    @property
    def is_violation(self) -> bool:
        return self.value not in (
            "clean", "clean_unusual", "clean_mandatory", "clean_underspecified",
        )

    @property
    def is_rule_catchable(self) -> bool:
        """Classes a deterministic gate can catch without any model call."""
        return self in (
            ViolationClass.AMOUNT_CAP,
            ViolationClass.CUMULATIVE_CAP,
            ViolationClass.OUT_OF_CATEGORY,
            ViolationClass.EXPIRED_WINDOW,
            ViolationClass.DUPLICATE,
        )


class LineItem(BaseModel):
    sku: str
    description: str
    amount_paise: int = Field(ge=0)
    category: str

    # Whether this charge was the AGENT's choice or an unavoidable
    # component of the purchase. Taxes, statutory levies and mandatory
    # fees are not the agent's decision — flagging one blocks a
    # legitimate purchase, which was this system's single worst failure
    # mode (32% false positives) when it had to infer this from the
    # description string.
    #
    # None means "not declared" — the merchant did not tell us. The tax
    # classifier then tries to establish it arithmetically before any
    # model is asked to reason about it.
    is_mandatory: bool | None = None


class PaymentStage(StrEnum):
    """Where a session sits in the payment lifecycle.

    This matters because it decides what the system is still ABLE to do.
    Between authorisation and capture the funds are held, not taken — so
    an unauthorised line item can simply not be captured, without
    blocking the legitimate part of the purchase. After capture the only
    remedies are refund and dispute, which are weaker.
    """

    AUTHORISED = "authorised"  # funds held; full remedy available
    CAPTURED = "captured"      # funds taken; refund only
    SETTLED = "settled"        # money with the merchant; dispute only


class Mandate(BaseModel):
    """What the human actually authorised, in their own words.

    `user_intent` is written independently of the verifier — it is the
    ground truth against which everything else is judged. This is what
    makes the project's metrics defensible rather than circular: the
    label comes from a spec, not from the system grading itself.
    """

    mandate_id: str
    user_intent: str
    max_amount_paise: int = Field(gt=0)
    cumulative_cap_paise: int = Field(gt=0)
    allowed_categories: list[str]
    valid_from: datetime
    valid_until: datetime

    def is_expired_at(self, ts: datetime) -> bool:
        return ts < self.valid_from or ts > self.valid_until


class Session(BaseModel):
    """One purchase attempt made by an agent under a mandate."""

    session_id: str
    mandate: Mandate
    merchant: str
    line_items: list[LineItem]
    timestamp: datetime
    idempotency_key: str | None = None
    prior_spend_paise: int = 0  # spend already committed under this mandate before this session
    stage: PaymentStage = PaymentStage.AUTHORISED

    # ground truth, used only for metrics — never read by the gate or verifier
    label: ViolationClass

    # How hard this case is *meant* to be. "clear" cases have obvious
    # separation; "ambiguous" ones are deliberately borderline — an add-on
    # a reasonable person might argue is implied by the intent. Reported
    # as a separate row so a perfect score on easy cases can't hide a poor
    # one on hard cases.
    difficulty: Literal["clear", "ambiguous"] = "clear"

    @property
    def total_paise(self) -> int:
        return sum(item.amount_paise for item in self.line_items)


class Finding(BaseModel):
    """A flagged issue on a session, produced by either the gate or the verifier."""

    session_id: str
    violation: ViolationClass
    detected_by: Literal["gate", "verifier"]
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str
    offending_items: list[str] = Field(default_factory=list)
    supporting_quote: str | None = None  # for verifier findings: the phrase in user_intent it checked against


class VerifierResponse(BaseModel):
    """Structured output contract for the LLM call. The model fills this
    schema — it never emits free-form text or executable code."""

    findings: list[Finding]


DEFAULT_MANDATE_WINDOW = timedelta(days=14)
