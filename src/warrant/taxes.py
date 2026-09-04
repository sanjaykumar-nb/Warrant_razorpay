"""Establishing which line items were NOT the agent's choice.

This module exists because of the single worst failure this system had:
it flagged unavoidable statutory charges as unauthorised purchases 32% of
the time. "Get me running shoes under ₹3,722" → it bought the shoes, and
flagged **GST (12%)** as something the human never authorised. You cannot
buy anything in India without paying GST.

The diagnosis mattered more than the number. The same blind spot appeared
on three models from two different labs, at confidence 0.85–1.0, which
rules out both "one model's quirk" and "threshold it away". The real
problem was the question being asked: a model was being made to INFER,
from a description string, whether a charge was the agent's decision.
That is not reliably answerable from text, so no amount of prompting
fixes it.

A tax is arithmetic, not judgment. So it is settled here, before the
model sees anything:

  1. If the merchant DECLARED `is_mandatory`, believe it. Payment
     processors already know which lines are taxes; this is the real
     production path.
  2. Otherwise try to derive it: does this line equal a standard tax rate
     applied to the taxable base? A 12% GST line is exactly 12% of the
     items it is levied on.
  3. Only if both fail does the line go to the model at all.

Anything classified mandatory is EXCLUDED from semantic review — the
model is never given the opportunity to flag it. That converts a
judgment problem into an arithmetic one, which is the same move the
deterministic gate already makes for spending caps.
"""

from __future__ import annotations

from dataclasses import dataclass

from warrant.schemas import LineItem

# Statutory rates that appear on Indian invoices. A line matching one of
# these against the taxable base is a tax, whatever it is called.
GST_RATE_BPS = (0, 50, 300, 500, 1200, 1800, 2800)  # 0.5%, 3%, 5%, 12%, 18%, 28%

# Tolerance for rounding. Invoices round to the paise, and a percentage of
# an integer rarely lands exactly, so an exact match would be too strict.
RATE_TOLERANCE_BPS = 25  # 0.25 percentage points

# Wording that names a charge as statutory. Deliberately a LAST resort:
# it is the same string-matching that failed before, so it is only
# consulted when the arithmetic is inconclusive, and it is kept narrow —
# these are terms of art, not general "fee-like" words.
STATUTORY_TERMS = (
    "gst", "vat", "cess", "levy", "statutory", "government tax",
    "airport tax", "airport taxes", "service tax", "tcs", "tds",
)


@dataclass(frozen=True)
class Classification:
    is_mandatory: bool
    basis: str  # how it was decided — carried into the audit trail

    @property
    def excluded_from_review(self) -> bool:
        return self.is_mandatory


def _matches_a_statutory_rate(amount_paise: int, base_paise: int) -> int | None:
    """Return the matched rate in basis points, or None.

    A tax line is a known percentage of the value it is levied on. If the
    amount lands on one of those rates within rounding tolerance, it is a
    tax — regardless of what the description says it is.
    """
    if base_paise <= 0 or amount_paise <= 0:
        return None
    actual_bps = round(amount_paise / base_paise * 10_000)
    for rate in GST_RATE_BPS:
        if rate and abs(actual_bps - rate) <= RATE_TOLERANCE_BPS:
            return rate
    return None


def _named_as_statutory(description: str) -> bool:
    d = description.lower()
    return any(term in d for term in STATUTORY_TERMS)


def classify(item: LineItem, taxable_base_paise: int) -> Classification:
    """Decide whether one line item was the agent's choice.

    Order is deliberate: declared beats derived, derived beats naming.
    Naming is the weakest signal and the one that failed before, so it
    never overrides arithmetic — it only fills the gap where arithmetic
    could not decide.
    """
    if item.is_mandatory is True:
        return Classification(True, "declared by merchant")
    if item.is_mandatory is False:
        return Classification(False, "declared by merchant as discretionary")

    rate = _matches_a_statutory_rate(item.amount_paise, taxable_base_paise)
    if rate is not None:
        pct = rate / 100
        if _named_as_statutory(item.description):
            return Classification(True, f"{pct:g}% of the taxable base, and named as statutory")
        # Arithmetic alone is strong but not conclusive — a discretionary
        # add-on can coincidentally land on a tax rate. Require the naming
        # to agree before excluding it from review.
        return Classification(False, f"matches {pct:g}% but is not named as a statutory charge")

    if _named_as_statutory(item.description):
        # Named like a tax but the arithmetic does not agree. Suspicious:
        # this is exactly how a padded "fee" would disguise itself, so it
        # goes to review rather than being trusted.
        return Classification(False, "named as statutory but the amount does not match any rate")

    return Classification(False, "no mandatory basis established")


def split_for_review(items: list[LineItem]) -> tuple[list[LineItem], list[tuple[LineItem, Classification]]]:
    """Split a session's line items into (reviewable, mandatory).

    The taxable base is everything not itself a tax. Computed by first
    taking declared-mandatory lines out, so a tax is never measured as a
    percentage of another tax.
    """
    declared_mandatory = {id(i) for i in items if i.is_mandatory is True}
    base = sum(i.amount_paise for i in items if id(i) not in declared_mandatory)

    reviewable: list[LineItem] = []
    mandatory: list[tuple[LineItem, Classification]] = []
    for item in items:
        c = classify(item, base - (item.amount_paise if id(item) not in declared_mandatory else 0))
        if c.is_mandatory:
            mandatory.append((item, c))
        else:
            reviewable.append(item)
    return reviewable, mandatory
