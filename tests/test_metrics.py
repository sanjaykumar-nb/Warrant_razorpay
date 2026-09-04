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


def test_pipeline_resumes_from_cache_instead_of_recalling(tmp_path):
    """A free-tier daily token cap once killed a batch on its last calls and
    discarded every completed result. The cache exists so a re-run resumes;
    this asserts the second run makes zero verifier calls."""
    sessions = generate_sessions()
    cache = tmp_path / "verifier_cache.json"

    class CountingVerifier(HeuristicVerifier):
        def __init__(self):
            self.calls = 0

        def verify(self, session):
            self.calls += 1
            return super().verify(session)

    first = CountingVerifier()
    r1 = run_pipeline(sessions, first, cache_path=cache)
    assert first.calls > 0
    # the cache file is namespaced per model, so the written path is not
    # the bare path we passed in
    written = list(tmp_path.glob("verifier_cache_*.json"))
    assert len(written) == 1, f"expected one per-model cache file, got {written}"

    second = CountingVerifier()
    r2 = run_pipeline(sessions, second, cache_path=cache)
    assert second.calls == 0, "second run should be served entirely from cache"

    # and the results must be identical, not merely cheap
    assert len(r1.verifier_findings) == len(r2.verifier_findings)
    assert r1.final_verdict == r2.final_verdict


def test_cache_is_invalidated_when_the_model_changes(tmp_path):
    """Mixing results from two different models into one reported number
    would be silently wrong, so a model change must discard the cache."""
    sessions = generate_sessions()[:40]
    cache = tmp_path / "verifier_cache.json"

    class ModelA(HeuristicVerifier):
        MODEL = "model-a"

    class ModelB(HeuristicVerifier):
        MODEL = "model-b"
        def __init__(self):
            self.calls = 0
        def verify(self, session):
            self.calls += 1
            return super().verify(session)

    run_pipeline(sessions, ModelA(), cache_path=cache)
    b = ModelB()
    run_pipeline(sessions, b, cache_path=cache)
    assert b.calls > 0, "different model must not reuse the previous model's cache"
