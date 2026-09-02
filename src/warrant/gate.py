"""The deterministic gate: five rule-based checks, no LLM, no ambiguity.

This runs first and catches everything a plain rule engine can see. What
survives the gate is what actually needs judgment — that residual is the
only thing handed to the semantic verifier. The gate never calls a model
and never has to; every check here is a pure function over the session.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from warrant.schemas import Finding, Session, ViolationClass


def check_amount_cap(session: Session) -> Finding | None:
    if session.total_paise > session.mandate.max_amount_paise:
        return Finding(
            session_id=session.session_id,
            violation=ViolationClass.AMOUNT_CAP,
            detected_by="gate",
            confidence=1.0,
            reason=(
                f"Session total ₹{session.total_paise/100:,.2f} exceeds the "
                f"mandate cap of ₹{session.mandate.max_amount_paise/100:,.2f}."
            ),
            offending_items=[i.sku for i in session.line_items],
        )
    return None


def check_cumulative_cap(session: Session) -> Finding | None:
    running_total = session.prior_spend_paise + session.total_paise
    if running_total > session.mandate.cumulative_cap_paise:
        return Finding(
            session_id=session.session_id,
            violation=ViolationClass.CUMULATIVE_CAP,
            detected_by="gate",
            confidence=1.0,
            reason=(
                f"Prior spend ₹{session.prior_spend_paise/100:,.2f} plus this "
                f"session's ₹{session.total_paise/100:,.2f} = "
                f"₹{running_total/100:,.2f}, over the cumulative cap of "
                f"₹{session.mandate.cumulative_cap_paise/100:,.2f}."
            ),
            offending_items=[i.sku for i in session.line_items],
        )
    return None


def check_category(session: Session) -> Finding | None:
    allowed = set(session.mandate.allowed_categories)
    bad_items = [i for i in session.line_items if i.category not in allowed]
    if bad_items:
        return Finding(
            session_id=session.session_id,
            violation=ViolationClass.OUT_OF_CATEGORY,
            detected_by="gate",
            confidence=1.0,
            reason=(
                f"Item categories {sorted({i.category for i in bad_items})} "
                f"are not in the mandate's allowed categories {sorted(allowed)}."
            ),
            offending_items=[i.sku for i in bad_items],
        )
    return None


def check_window(session: Session) -> Finding | None:
    if session.mandate.is_expired_at(session.timestamp):
        return Finding(
            session_id=session.session_id,
            violation=ViolationClass.EXPIRED_WINDOW,
            detected_by="gate",
            confidence=1.0,
            reason=(
                f"Purchase at {session.timestamp.isoformat()} falls outside the "
                f"mandate's valid window "
                f"[{session.mandate.valid_from.isoformat()}, "
                f"{session.mandate.valid_until.isoformat()}]."
            ),
            offending_items=[i.sku for i in session.line_items],
        )
    return None


@dataclass
class DuplicateRegistry:
    """Tracks idempotency keys already seen, in processing order.

    This is deliberately stateful and sequential — duplicate detection is
    inherently about *order*, not a property of any single session in
    isolation. A key seen twice means the second occurrence is a duplicate,
    regardless of which one was "originally" correct.
    """

    seen: dict[str, str] = None  # key -> first session_id that used it

    def __post_init__(self) -> None:
        if self.seen is None:
            self.seen = {}

    def check(self, session: Session) -> Finding | None:
        key = session.idempotency_key
        if key is None:
            return None
        first_seen = self.seen.get(key)
        if first_seen is not None:
            return Finding(
                session_id=session.session_id,
                violation=ViolationClass.DUPLICATE,
                detected_by="gate",
                confidence=1.0,
                reason=(
                    f"Idempotency key '{key}' was already used by session "
                    f"{first_seen}. This is a repeat submission, not a new purchase."
                ),
                offending_items=[i.sku for i in session.line_items],
            )
        self.seen[key] = session.session_id
        return None


GATE_CHECKS = (check_amount_cap, check_cumulative_cap, check_category, check_window)


def run_gate(sessions: list[Session]) -> tuple[list[Finding], float, float]:
    """Run every deterministic check over a batch, in timestamp order (so
    duplicate detection sees sessions in the sequence they actually happened).

    Returns (findings, p50_latency_ms, p99_latency_ms).
    """
    ordered = sorted(sessions, key=lambda s: s.timestamp)
    registry = DuplicateRegistry()
    findings: list[Finding] = []
    latencies_ms: list[float] = []

    for session in ordered:
        start = time.perf_counter()

        for check in GATE_CHECKS:
            f = check(session)
            if f is not None:
                findings.append(f)

        dup_finding = registry.check(session)
        if dup_finding is not None:
            findings.append(dup_finding)

        latencies_ms.append((time.perf_counter() - start) * 1000)

    latencies_ms.sort()
    n = len(latencies_ms)
    p50 = latencies_ms[n // 2] if n else 0.0
    p99 = latencies_ms[int(n * 0.99)] if n else 0.0
    return findings, p50, p99


def gate_verdict(session: Session, findings: list[Finding]) -> ViolationClass:
    """The single violation class the gate assigns to a session, for
    sessions where the gate found something. Multiple checks can fire on
    one session in principle; we report the first (most severe by check
    order) for the metrics table, but ALL findings are kept in the
    evidence pack — nothing is dropped, only summarised."""
    session_findings = [f for f in findings if f.session_id == session.session_id]
    if not session_findings:
        return ViolationClass.CLEAN
    return session_findings[0].violation
