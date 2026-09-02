"""The evidence pack: what a merchant would actually be shown when
defending or explaining a flagged transaction. This is the project's
'auto-responder' — Track 02's own word for the third thing a submission
in this track is asked to be, alongside a detector and a verifier.
"""

from __future__ import annotations

from typing import Any

from warrant.schemas import Finding, Session


def build_evidence_pack(session: Session, findings: list[Finding]) -> dict[str, Any]:
    session_findings = [f for f in findings if f.session_id == session.session_id]
    return {
        "session_id": session.session_id,
        "merchant": session.merchant,
        "timestamp": session.timestamp.isoformat(),
        "mandate": {
            "mandate_id": session.mandate.mandate_id,
            "user_intent": session.mandate.user_intent,
            "max_amount_paise": session.mandate.max_amount_paise,
            "cumulative_cap_paise": session.mandate.cumulative_cap_paise,
            "allowed_categories": session.mandate.allowed_categories,
            "valid_from": session.mandate.valid_from.isoformat(),
            "valid_until": session.mandate.valid_until.isoformat(),
        },
        "purchased": [
            {
                "sku": i.sku,
                "description": i.description,
                "amount_paise": i.amount_paise,
                "category": i.category,
            }
            for i in session.line_items
        ],
        "total_paise": session.total_paise,
        "verdict": "flagged" if session_findings else "clean",
        "findings": [
            {
                "violation": f.violation.value,
                "detected_by": f.detected_by,
                "confidence": f.confidence,
                "reason": f.reason,
                "offending_items": f.offending_items,
                "supporting_quote": f.supporting_quote,
            }
            for f in session_findings
        ],
    }
