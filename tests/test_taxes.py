"""Tests for the tax classifier — the fix for this system's worst failure.

Before this module, the verifier flagged unavoidable statutory charges as
unauthorised purchases 32% of the time, at confidence 0.85-1.0, on three
different models. These tests pin the behaviour that replaced it.
"""

from __future__ import annotations

import pytest

from warrant.schemas import LineItem
from warrant.taxes import classify, split_for_review


def item(desc: str, paise: int, mandatory=None, sku="X-1") -> LineItem:
    return LineItem(sku=sku, description=desc, amount_paise=paise,
                    category="apparel", is_mandatory=mandatory)


def test_declared_mandatory_is_believed_without_arithmetic():
    """The production path: the PSP already knows which lines are taxes."""
    c = classify(item("Anything at all", 12345, mandatory=True), taxable_base_paise=100_000)
    assert c.is_mandatory
    assert "declared" in c.basis


def test_declared_discretionary_is_believed_even_if_it_looks_like_tax():
    c = classify(item("GST (18%)", 18_000, mandatory=False), taxable_base_paise=100_000)
    assert not c.is_mandatory


def test_gst_is_derived_from_the_arithmetic():
    """18% of 1,00,000 paise is 18,000 — a real invoice computes it exactly."""
    c = classify(item("GST (18%)", 18_000), taxable_base_paise=100_000)
    assert c.is_mandatory
    assert "18%" in c.basis


def test_rounding_tolerance_accepts_real_invoice_amounts():
    """A percentage of an integer rarely lands exactly; 12% of 39,627 is
    4,755.24, which an invoice rounds. An exact-match rule would reject it."""
    c = classify(item("GST (12%)", 4_755), taxable_base_paise=39_627)
    assert c.is_mandatory


def test_tax_naming_without_matching_arithmetic_is_NOT_trusted():
    """This is how a padded fee would disguise itself — call it 'GST' but
    charge 40%. Naming alone must never be sufficient."""
    c = classify(item("GST (18%)", 40_000), taxable_base_paise=100_000)
    assert not c.is_mandatory
    assert "does not match" in c.basis


def test_coincidental_rate_match_without_tax_naming_is_NOT_trusted():
    """A discretionary add-on can land on a tax rate by chance. Arithmetic
    alone is not enough either — both signals must agree."""
    c = classify(item("Travel insurance", 18_000), taxable_base_paise=100_000)
    assert not c.is_mandatory
    assert "not named as a statutory charge" in c.basis


def test_ordinary_addon_is_reviewable():
    c = classify(item("Extended warranty", 3_137), taxable_base_paise=100_000)
    assert not c.is_mandatory


@pytest.mark.parametrize("desc", [
    "GST (12%)", "Airport taxes and statutory fees",
    "Mandatory state tourism levy", "Statutory handling charge",
])
def test_the_real_failure_cases_are_now_excluded_from_review(desc):
    """Every description that produced a false positive in the measured run,
    priced as a real invoice would price it."""
    base = 200_000
    fee = round(base * 0.12)
    reviewable, mandatory = split_for_review([
        item("Running shoes", base, sku="SKU-1"),
        item(desc, fee, sku="FEE-1"),
    ])
    assert [i.sku for i in mandatory and [m[0] for m in mandatory]] == ["FEE-1"]
    assert [i.sku for i in reviewable] == ["SKU-1"]


def test_a_tax_is_never_measured_as_a_percentage_of_another_tax():
    """With two declared taxes present, the taxable base must exclude them,
    or the second is measured against an inflated denominator."""
    items = [
        item("Hotel booking", 500_000, sku="SKU-1"),
        item("GST (12%)", 60_000, mandatory=True, sku="GST-1"),
        item("Tourism levy", 25_000, mandatory=True, sku="LEV-1"),
    ]
    reviewable, mandatory = split_for_review(items)
    assert {m[0].sku for m in mandatory} == {"GST-1", "LEV-1"}
    assert [i.sku for i in reviewable] == ["SKU-1"]


def test_zero_and_negative_bases_do_not_crash():
    assert not classify(item("GST (18%)", 100), taxable_base_paise=0).is_mandatory
    assert not classify(item("GST (18%)", 100), taxable_base_paise=-500).is_mandatory
