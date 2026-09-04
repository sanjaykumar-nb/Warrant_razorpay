"""Tests for the human annotation harness.

The harness exists to check whether humans agree with each other on the
contested cases. That only means something if the annotator is genuinely
blind to the answer and if careless labelling is detectable — so both of
those properties are tested, not assumed.
"""

from __future__ import annotations

import json

import pytest

from warrant.annotate import (
    FLAG,
    OK,
    UNSURE,
    _cohens_kappa,
    build_items,
    load_annotations,
    report,
)
from warrant.generate import generate_sessions
from warrant.schemas import ViolationClass


@pytest.fixture(scope="module")
def sessions():
    return generate_sessions()


@pytest.fixture(scope="module")
def items(sessions):
    return build_items(sessions, seed=4242)


def test_items_cover_every_contested_session(items, sessions):
    contested = [s for s in sessions if s.label in
                 (ViolationClass.CLEAN_MANDATORY, ViolationClass.CLEAN_UNDERSPECIFIED)]
    covered = {i.session_id for i in items}
    assert all(s.session_id in covered for s in contested)


def test_controls_are_present_and_unambiguous(items):
    controls = [i for i in items if i.is_control]
    assert len(controls) == 6
    assert all(c.control_answer in (FLAG, OK) for c in controls)


def test_annotator_is_blind_to_ground_truth_and_model(items):
    """An AnnotationItem must not carry the label or any verdict — if it
    did, the whole study would be circular."""
    for i in items:
        fields = vars(i)
        assert "label" not in fields
        assert "difficulty" not in fields
        assert "violation" not in fields
        assert "findings" not in fields


def test_item_order_is_shuffled_not_grouped_by_class(items, sessions):
    """Contested items must not arrive in one contiguous block, or an
    annotator can infer the pattern and label mechanically."""
    by_id = {s.session_id: s for s in sessions}
    labels = [by_id[i.session_id].label.value for i in items if not i.is_control]
    # a fully grouped ordering would have very few transitions
    transitions = sum(1 for a, b in zip(labels, labels[1:]) if a != b)
    assert transitions > 5, "items look grouped by class, not shuffled"


def test_cohens_kappa_perfect_and_chance():
    assert _cohens_kappa([FLAG, OK, FLAG, OK], [FLAG, OK, FLAG, OK]) == pytest.approx(1.0)
    # total disagreement on a balanced set is worse than chance
    assert _cohens_kappa([FLAG, FLAG, OK, OK], [OK, OK, FLAG, FLAG]) < 0


def test_kappa_penalises_agreement_that_is_only_class_imbalance():
    """Two annotators who both always answer OK agree 100% of the time but
    demonstrate nothing. Raw agreement says 1.0; kappa must not."""
    a = [OK] * 20
    b = [OK] * 20
    k = _cohens_kappa(a, b)
    assert k != k or k <= 0.0  # NaN (undefined) or non-positive, never 1.0


def test_report_excludes_annotators_who_fail_attention_checks(items, sessions, tmp_path):
    by_id = {s.session_id: s for s in sessions}
    good = {}
    careless = {}
    for i in items:
        truth = FLAG if by_id[i.session_id].label.is_violation else OK
        good[i.session_id] = i.control_answer if i.is_control else truth
        # careless: always the wrong answer on controls
        careless[i.session_id] = (
            (OK if i.control_answer == FLAG else FLAG) if i.is_control else truth
        )
    (tmp_path / "good.json").write_text(json.dumps({"annotator": "good", "answers": good}))
    (tmp_path / "careless.json").write_text(json.dumps({"annotator": "careless", "answers": careless}))

    out = report(load_annotations(tmp_path), items, by_id, model_flagged=set())
    assert "UNRELIABLE" in out
    assert "careless" in out
    # with only one reliable annotator left, it must refuse to report agreement
    assert "at least two" in out


def test_report_handles_no_annotations(items, sessions):
    by_id = {s.session_id: s for s in sessions}
    out = report({}, items, by_id, model_flagged=set())
    assert "No annotations found" in out
