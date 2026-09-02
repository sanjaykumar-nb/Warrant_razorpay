"""Regression tests for the deterministic gate, run against the actual
generated batch. These assertions were how three real generator bugs were
caught during development (a window-timing bug that mislabelled clean
sessions as expired, an unpaired 'duplicate' label with nothing to be a
duplicate of, and a random idempotency-key collision) — they stay as
permanent tests so no future change to the generator can reintroduce them
silently."""

from __future__ import annotations

from collections import defaultdict

import pytest

from warrant.gate import gate_verdict, run_gate
from warrant.generate import generate_sessions
from warrant.schemas import ViolationClass


@pytest.fixture(scope="module")
def sessions():
    return generate_sessions()


@pytest.fixture(scope="module")
def gate_result(sessions):
    return run_gate(sessions)


def test_batch_size_and_class_distribution(sessions):
    counts: dict[str, int] = defaultdict(int)
    for s in sessions:
        counts[s.label.value] += 1
    # CLEAN includes both the plain-clean batch and every duplicate pair's
    # legitimate origin session, so it's larger than CLASS_COUNTS["clean"].
    assert counts["clean"] >= 90
    assert counts["clean_unusual"] == 25
    assert counts["amount_cap"] == 25
    assert counts["cumulative_cap"] == 20
    assert counts["out_of_category"] == 20
    assert counts["expired_window"] == 15
    assert counts["duplicate"] == 20
    assert counts["scope_creep"] == 35


def test_every_idempotency_key_globally_unique_except_duplicate_pairs(sessions):
    """No two sessions should accidentally share a key unless one is the
    intentional DUPLICATE retry of the other."""
    key_owners: dict[str, list[str]] = defaultdict(list)
    for s in sessions:
        if s.idempotency_key:
            key_owners[s.idempotency_key].append(s.label.value)
    for key, labels in key_owners.items():
        if len(labels) > 1:
            assert sorted(labels) == ["clean", "duplicate"], (
                f"key {key} shared by unexpected label combination {labels}"
            )


@pytest.mark.parametrize("violation_class", [
    ViolationClass.AMOUNT_CAP,
    ViolationClass.CUMULATIVE_CAP,
    ViolationClass.OUT_OF_CATEGORY,
    ViolationClass.EXPIRED_WINDOW,
    ViolationClass.DUPLICATE,
])
def test_gate_perfect_recall_on_rule_catchable_classes(sessions, gate_result, violation_class):
    findings, _, _ = gate_result
    flagged_ids = {f.session_id for f in findings if f.violation == violation_class}
    labelled_ids = {s.session_id for s in sessions if s.label == violation_class}
    assert labelled_ids, "fixture produced zero sessions of this class"
    missed = labelled_ids - flagged_ids
    assert not missed, f"gate missed {len(missed)}/{len(labelled_ids)} {violation_class.value} sessions"


def test_gate_raises_zero_false_positives_on_clean(sessions, gate_result):
    findings, _, _ = gate_result
    verdicts = {s.session_id: gate_verdict(s, findings) for s in sessions}
    clean_sessions = [s for s in sessions if s.label == ViolationClass.CLEAN]
    flagged = [s.session_id for s in clean_sessions if verdicts[s.session_id] != ViolationClass.CLEAN]
    assert not flagged, f"gate incorrectly flagged {len(flagged)} CLEAN sessions: {flagged}"


def test_gate_raises_zero_false_positives_on_clean_unusual(sessions, gate_result):
    findings, _, _ = gate_result
    verdicts = {s.session_id: gate_verdict(s, findings) for s in sessions}
    unusual = [s for s in sessions if s.label == ViolationClass.CLEAN_UNUSUAL]
    flagged = [s.session_id for s in unusual if verdicts[s.session_id] != ViolationClass.CLEAN]
    assert not flagged, f"gate incorrectly flagged {len(flagged)} CLEAN_UNUSUAL sessions: {flagged}"


def test_scope_creep_is_entirely_invisible_to_the_deterministic_gate(sessions, gate_result):
    """This is the whole point of the class: if the gate can catch scope
    creep, the project has no argument that the model is load-bearing."""
    findings, _, _ = gate_result
    verdicts = {s.session_id: gate_verdict(s, findings) for s in sessions}
    scope_creep = [s for s in sessions if s.label == ViolationClass.SCOPE_CREEP]
    leaked = [s.session_id for s in scope_creep if verdicts[s.session_id] != ViolationClass.CLEAN]
    assert not leaked, f"gate leaked on {len(leaked)} scope_creep sessions: {leaked}"


def test_all_money_fields_are_integers(sessions):
    """Guards against a float ever creeping into a paise field."""
    for s in sessions:
        assert isinstance(s.mandate.max_amount_paise, int)
        assert isinstance(s.mandate.cumulative_cap_paise, int)
        assert isinstance(s.prior_spend_paise, int)
        for item in s.line_items:
            assert isinstance(item.amount_paise, int)


def test_gate_is_deterministic_across_runs():
    a = generate_sessions()
    b = generate_sessions()
    assert [s.session_id for s in a] == [s.session_id for s in b]
    assert [s.model_dump() for s in a] == [s.model_dump() for s in b]
