"""Tests for the remediation policy.

The central property: no branch blocks a whole purchase. A false positive
must cost one line item, never the transaction — that is what makes it
safe to act on findings from a system with a measured error rate.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from warrant.remediation import (
    ACTION_CONFIDENCE_FLOOR,
    CONFIRMATION_THRESHOLD_PAISE,
    Action,
    decide,
    summarise,
)
from warrant.schemas import (
    Finding,
    LineItem,
    Mandate,
    PaymentStage,
    Session,
    ViolationClass,
)

NOW = datetime(2026, 8, 15, 10, 0, 0)


def session(items, stage=PaymentStage.AUTHORISED) -> Session:
    return Session(
        session_id="S-1",
        mandate=Mandate(
            mandate_id="M-1", user_intent="Book a flight to Delhi under Rs.8,000.",
            max_amount_paise=900_000, cumulative_cap_paise=2_000_000,
            allowed_categories=["flight"],
            valid_from=NOW - timedelta(days=5), valid_until=NOW + timedelta(days=5),
        ),
        merchant="SkyBook", line_items=items, timestamp=NOW,
        stage=stage, label=ViolationClass.SCOPE_CREEP,
    )


def li(sku, paise, desc="item") -> LineItem:
    return LineItem(sku=sku, description=desc, amount_paise=paise, category="flight")


def finding(sku, confidence=0.95) -> Finding:
    return Finding(
        session_id="S-1", violation=ViolationClass.SCOPE_CREEP, detected_by="verifier",
        confidence=confidence, reason="not authorised", offending_items=[sku],
    )


def test_no_findings_captures_in_full():
    r = decide(session([li("A", 780_000)]), [])
    assert r.action is Action.CAPTURE_FULL
    assert r.capture_paise == 780_000


def test_small_unrequested_addon_is_partially_captured_not_blocked():
    """The core behaviour: the flight still books, the add-on is not taken."""
    s = session([li("A", 780_000, "Flight"), li("INS", 45_000, "Insurance")])
    r = decide(s, [finding("INS")])
    assert r.action is Action.PARTIAL_CAPTURE
    assert r.capture_paise == 780_000          # the legitimate part still goes through
    assert r.disputed_paise == 45_000
    assert r.customer_protected_paise == 45_000


def test_large_unrequested_charge_asks_the_human_first():
    big = CONFIRMATION_THRESHOLD_PAISE + 1
    s = session([li("A", 780_000), li("UPG", big)])
    r = decide(s, [finding("UPG")])
    assert r.action is Action.HOLD_FOR_CONFIRMATION


def test_low_confidence_findings_never_touch_the_money():
    """Below the floor a finding is recorded, not acted on. This is what
    stops an uncertain model from costing a customer anything."""
    s = session([li("A", 780_000), li("INS", 45_000)])
    r = decide(s, [finding("INS", confidence=ACTION_CONFIDENCE_FLOOR - 0.01)])
    assert r.action is Action.LOG_ONLY
    assert r.capture_paise == s.total_paise
    assert r.customer_protected_paise == 0


def test_after_capture_the_remedy_is_a_line_refund():
    s = session([li("A", 780_000), li("INS", 45_000)], stage=PaymentStage.CAPTURED)
    r = decide(s, [finding("INS")])
    assert r.action is Action.REFUND_LINE
    assert r.customer_protected_paise == 45_000


def test_after_settlement_only_a_dispute_remains():
    s = session([li("A", 780_000), li("INS", 45_000)], stage=PaymentStage.SETTLED)
    r = decide(s, [finding("INS")])
    assert r.action is Action.FLAG_FOR_DISPUTE
    assert r.customer_protected_paise == 0


@pytest.mark.parametrize("stage", list(PaymentStage))
def test_no_stage_ever_blocks_the_whole_purchase(stage):
    """The property that makes acting on an imperfect signal defensible."""
    s = session([li("A", 780_000), li("INS", 45_000)], stage=stage)
    r = decide(s, [finding("INS")])
    assert r.capture_paise > 0, "a legitimate purchase was blocked entirely"
    assert r.disputed_paise < s.total_paise


def test_gate_findings_are_ignored_here():
    """The gate already resolved those; remediation only acts on the
    semantic verifier's output."""
    s = session([li("A", 780_000)])
    gate_finding = Finding(
        session_id="S-1", violation=ViolationClass.AMOUNT_CAP, detected_by="gate",
        confidence=1.0, reason="over cap", offending_items=["A"],
    )
    assert decide(s, [gate_finding]).action is Action.CAPTURE_FULL


def test_summary_reports_money_protected():
    s = session([li("A", 780_000), li("INS", 45_000)])
    out = summarise([decide(s, [finding("INS")])])
    assert "partial_capture" in out
    assert "450.00" in out


def test_findings_from_other_sessions_are_ignored():
    """Callers pass the whole batch's findings, so decide() must filter by
    session as well as by detector. Without this, every session inherits
    every other session's findings — which showed up as all 340 sessions
    reporting partial_capture on a batch with 8 real findings."""
    s = session([li("A", 780_000)])
    other = Finding(
        session_id="SOMEONE-ELSE", violation=ViolationClass.SCOPE_CREEP,
        detected_by="verifier", confidence=0.99, reason="not mine",
        offending_items=["ZZ"],
    )
    r = decide(s, [other])
    assert r.action is Action.CAPTURE_FULL
    assert r.disputed_paise == 0
