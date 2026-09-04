# Architecture

## The loss class

**Agent-mediated unauthorised spend.** A human gives an AI shopping agent a
mandate in plain language — *"Book me a flight to Delhi, under ₹8,000"* — and
the agent buys the flight at ₹7,800, plus travel insurance at ₹450, plus seat
selection at ₹600.

A rule engine catches the total. **Nothing but a language model catches that
nobody asked for insurance.**

That gap is the entire project.

## The one design decision that matters

**Deterministic gate first. Model on the residual only. Model never in the
money path.**

```
                        ┌─────────────────────────────┐
  295+ sessions ───────▶│  DETERMINISTIC GATE          │
                        │  amount cap                  │
                        │  cumulative cap              │──▶ flagged, done.
                        │  category                    │    no model call.
                        │  mandate window              │
                        │  duplicate (idempotency)     │
                        └──────────────┬───────────────┘
                                       │ residual
                                       ▼
                        ┌─────────────────────────────┐
                        │  SEMANTIC VERIFIER (LLM)     │
                        │  intent  vs  line items      │──▶ scope_creep
                        │  forced structured output    │
                        └──────────────┬───────────────┘
                                       ▼
                        ┌─────────────────────────────┐
                        │  EVIDENCE PACK               │
                        │  mandate + purchase +        │
                        │  findings + reasoning        │
                        └─────────────────────────────┘
```

Every consequence of this ordering is deliberate:

**The gate is pure functions over one session.** No I/O, no model, no
non-determinism. Sub-millisecond at p99, so it could sit inline in a real
checkout path without anyone noticing.

**The model never re-litigates a rule decision.** If the gate has already
established that a purchase breached its cap, there is nothing for a language
model to add — and a model that could *disagree* with arithmetic is a
liability, not a feature.

**The model cannot execute anything.** It fills a fixed schema. It has no tool
that moves money, cancels an order, or writes to a ledger. Its entire output
surface is a list of findings.

**Money is integer paise, everywhere.** Never floats. Enforced at the type
level in `schemas.py`.

## Why the verifier needs a model at all

This is the load-bearing claim, so it is worth stating precisely.

Detecting scope creep is a **semantic** comparison between a natural-language
intent and a set of purchased items. It cannot be done with a join, a
threshold, or a keyword list. Two cases prove it:

**Case 1 — the discretion clause.** Intent: *"...and add travel insurance if
you think it's worth it."* A keyword matcher that treats "insurance" as
suspicious flags this and is **wrong** — the human explicitly authorised that
exact judgment call.

**Case 2 — the mandatory fee.** Intent: *"Book a hotel in Chennai."* Line
items include a mandatory state tourism levy. The naive rule — *anything the
intent didn't name is a violation* — flags it and is **wrong**. The agent did
not choose that charge; the booking cannot be made without it.

Both cases are in the test set precisely because the naive rule fails them.

**Empirically, the gate catches 0% of scope creep.** Not a small amount —
zero, verified as a regression test. So every scope-creep number in the
results is attributable to the model, and every false positive on a
legitimate purchase is too.

## Ground truth is specified, not inferred

The usual weakness of synthetic evaluation is circularity: you invent the
labels, then measure yourself against your own invention.

This project narrows that gap in one specific way — **the mandate's
`user_intent` is written independently of the verifier and is the ground
truth**. It is a spec, in the human's own words, not a label inferred from
the thing being tested. Whether a purchase matches an intent is checkable by
reading the intent.

This does not eliminate the limitation, and the Limitations section says so
plainly.

## Provider abstraction

`Verifier` is a Protocol with four implementations:

| Implementation | Transport | Cost |
|---|---|---|
| `GroqVerifier` | OpenAI-compatible, forced tool call | free tier |
| `LLMVerifier` | Anthropic, forced tool use | paid |
| `GeminiVerifier` | Google, forced function call | free tier |
| `HeuristicVerifier` | substring check, no model | none |

All four share the same system prompt, the same tool schema, and the same
`Finding` output shape, so results are comparable across providers rather
than entangled with one vendor's API.

`HeuristicVerifier` exists so the pipeline could be built and tested before
any API key was available. It prints a loud warning and its numbers are never
reported — it scores well here only because the generator's discretion clause
names its add-on verbatim, which is a property of this data, not evidence the
approach works.

**Failure is loud, not silent.** A 403 raises immediately instead of retrying
or degrading to a weaker verifier mid-run. A silent provider downgrade would
corrupt the reported metrics, which is worse than a failed run.

## Cost: actual vs projected

These are different numbers and the report keeps them apart.

- **Actual** — what the run cost at the provider's real rates. On a free tier
  that is ₹0, and reporting anything else would be inventing spend.
- **Projected** — what the same token volume would cost on a paid frontier
  model. This is the at-scale economics argument, valid only when labelled
  as a projection.

An earlier version of this code applied Claude pricing to Groq token counts
and printed the result as cost incurred. It wasn't. Two regression tests now
assert that a free tier reports zero and a paid provider does not.

## Reproducibility

`data/sessions.json` is generated from a committed seed and is byte-identical
on regeneration — verified as a test. Every number in the README comes from
one command:

```bash
uv run warrant demo
```

## What I would build next

**Confidence-tiered escalation.** Findings carry a confidence score that
nothing currently consumes. High-confidence findings could auto-block while
borderline ones queue for a human, instead of treating every finding alike.

**Signed provenance.** Hash-chain the mandate, the agent's reasoning and the
transaction so an evidence pack is tamper-evident — the difference between
"here is our record" and "here is a record that provably has not been
altered."

**Harder ground truth.** The current test set has one genuinely contested
tier. A serious benchmark needs cases where human annotators disagree with
each other, with inter-annotator agreement reported.
