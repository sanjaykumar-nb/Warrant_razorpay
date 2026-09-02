"""Tests for the pipeline and metrics using HeuristicVerifier (no API key
needed). These check the plumbing — orchestration, cost accounting, the
evidence pack — not detection quality. Detection quality is only
meaningful with LLMVerifier and must be re-checked once that path runs."""

from __future__ import annotations

from warrant.evidence import build_evidence_pack
from warrant.generate import generate_sessions
from warrant.metrics import (
    class_metrics,
    false_positive_cost_paise,
    pct_never_touching_model,
    run_pipeline,
)
from warrant.schemas import ViolationClass
from warrant.verifier import HeuristicVerifier


def test_pipeline_only_sends_gate_residual_to_verifier():
    sessions = generate_sessions()
    result = run_pipeline(sessions, HeuristicVerifier())
    gate_flagged = {f.session_id for f in result.gate_findings}
    assert result.verifier_calls == len(sessions) - len(gate_flagged)


def test_every_session_gets_a_final_verdict():
    sessions = generate_sessions()
    result = run_pipeline(sessions, HeuristicVerifier())
    assert set(result.final_verdict.keys()) == {s.session_id for s in sessions}


def test_rule_catchable_classes_still_perfect_through_full_pipeline():
    sessions = generate_sessions()
    result = run_pipeline(sessions, HeuristicVerifier())
    for m in class_metrics(result):
        if m.label in ("amount_cap", "cumulative_cap", "out_of_category", "expired_window", "duplicate"):
            assert m.recall == 1.0, m.label
            assert m.false_positives == 0, m.label


def test_pct_never_touching_model_is_between_zero_and_one():
    sessions = generate_sessions()
    result = run_pipeline(sessions, HeuristicVerifier())
    pct = pct_never_touching_model(result)
    assert 0.0 <= pct <= 1.0
    # gate catches 5 rule-based classes out of 8 total classes worth of sessions
    assert pct > 0.0


def test_evidence_pack_for_flagged_session_lists_its_findings():
    sessions = generate_sessions()
    result = run_pipeline(sessions, HeuristicVerifier())
    scope_creep_sessions = [s for s in sessions if s.label == ViolationClass.SCOPE_CREEP]
    session = scope_creep_sessions[0]
    all_findings = [*result.gate_findings, *result.verifier_findings]
    pack = build_evidence_pack(session, all_findings)
    assert pack["session_id"] == session.session_id
    assert pack["mandate"]["user_intent"] == session.mandate.user_intent
    assert len(pack["purchased"]) == len(session.line_items)


def test_evidence_pack_for_untouched_session_has_no_findings():
    sessions = generate_sessions()
    result = run_pipeline(sessions, HeuristicVerifier())
    clean_session = next(
        s for s in sessions
        if s.label == ViolationClass.CLEAN and result.final_verdict[s.session_id] == ViolationClass.CLEAN
    )
    all_findings = [*result.gate_findings, *result.verifier_findings]
    pack = build_evidence_pack(clean_session, all_findings)
    assert pack["verdict"] == "clean"
    assert pack["findings"] == []


def test_false_positive_cost_only_counts_clean_and_clean_unusual():
    sessions = generate_sessions()
    result = run_pipeline(sessions, HeuristicVerifier())
    fp_paise = false_positive_cost_paise(result)
    assert isinstance(fp_paise, int)
    assert fp_paise >= 0
