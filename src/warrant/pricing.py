"""Token pricing.

Two numbers matter and they are NOT the same number:

  actual cost      — what this run genuinely cost. On a free tier that is
                     zero, and reporting anything else would be inventing
                     a number we did not pay.

  projected cost   — what the same token volume WOULD cost on a paid
                     frontier model. This is the at-scale economics
                     argument, and it is only honest when labelled as a
                     projection rather than presented as spend.

An earlier version of this file applied Claude pricing to Groq token
counts and reported the result as cost incurred. It wasn't.
"""

from __future__ import annotations

from pydantic import BaseModel


class TokenPrice(BaseModel):
    input_usd_per_mtok: float
    output_usd_per_mtok: float
    label: str

    @property
    def is_free(self) -> bool:
        return self.input_usd_per_mtok == 0.0 and self.output_usd_per_mtok == 0.0


# Groq free tier: no credits system, no per-token charge (verified 3 Sep 2026).
FREE_TIER = TokenPrice(
    input_usd_per_mtok=0.0,
    output_usd_per_mtok=0.0,
    label="free tier (no per-token charge)",
)

# Verified via web search on 2 Sep 2026 — recheck before submission, a
# judge can look this up in thirty seconds.
CLAUDE_SONNET_5 = TokenPrice(
    input_usd_per_mtok=2.0,
    output_usd_per_mtok=10.0,
    label="Claude Sonnet 5",
)

USD_TO_INR = 95.0  # approx spot rate, 1 Sep 2026


def cost_paise(input_tokens: int, output_tokens: int, price: TokenPrice = CLAUDE_SONNET_5) -> int:
    usd = (
        input_tokens / 1_000_000 * price.input_usd_per_mtok
        + output_tokens / 1_000_000 * price.output_usd_per_mtok
    )
    return round(usd * USD_TO_INR * 100)
