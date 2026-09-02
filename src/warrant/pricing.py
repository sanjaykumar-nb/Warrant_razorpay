"""Cost constants for the ₹/session metric.

Verified via web search on 2 Sep 2026 — update these if you check again
closer to submission, since a judge can and will fact-check this number.
"""

CLAUDE_SONNET_5_INPUT_USD_PER_MTOK = 2.0
CLAUDE_SONNET_5_OUTPUT_USD_PER_MTOK = 10.0
USD_TO_INR = 95.0  # approx spot rate, 1 Sep 2026


def cost_paise(input_tokens: int, output_tokens: int) -> int:
    usd = (
        input_tokens / 1_000_000 * CLAUDE_SONNET_5_INPUT_USD_PER_MTOK
        + output_tokens / 1_000_000 * CLAUDE_SONNET_5_OUTPUT_USD_PER_MTOK
    )
    return round(usd * USD_TO_INR * 100)
