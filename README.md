# Warrant

Detects **agent-mediated unauthorised spend** — purchases an AI shopping
agent made that fall outside what the human actually asked for.

> Status: gate + pipeline + evidence pack are built and tested. The
> semantic verifier (`LLMVerifier`) is implemented but has not yet been
> run against the real API — see **Setup** below. The full README
> (metrics table, architecture rationale, limitations) lands once real
> numbers exist to report; a fabricated table is worse than none.

## The one-sentence pitch

A human writes *"Flight to Delhi, under ₹8,000."* The agent books
₹7,800 — plus travel insurance ₹450, plus seat selection ₹600. A rule
engine catches the total. **Only a language model catches that nobody
asked for insurance.**

## Setup

```bash
uv sync
```

Requires an Anthropic API key for the real numbers:

```bash
cp .env.example .env
# edit .env, add your key
uv run --env-file .env warrant demo
```

Without a key, every command still runs — `get_verifier()` falls back to
a heuristic placeholder and prints a loud warning. That path exists so
the rest of the pipeline is buildable and testable without a key; **its
numbers must never be reported as results** (see `verifier.py`).

## Commands

```bash
uv run warrant generate            # regenerate the 270-session synthetic batch
uv run warrant gate                # deterministic checks only, no API, no cost
uv run warrant demo                # full pipeline + every metric, caches findings
uv run warrant evidence <session_id>   # the evidence/defense pack for one session
```

## Tests

```bash
uv run pytest -q
```

19 passing. Covers the generator's own correctness (three real bugs were
caught this way during development — see `tests/test_gate.py`), the
gate's recall/precision, and pipeline plumbing via the heuristic
verifier. Detection-quality claims are only meaningful once the same
tests are re-verified against `LLMVerifier`.
