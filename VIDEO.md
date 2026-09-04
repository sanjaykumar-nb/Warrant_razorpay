# 5-minute pitch — shot list

Screen recording with voiceover. **No slides.** All numbers below are the
real output of `uv run warrant demo` (340 sessions, `openai/gpt-oss-20b`).

---

## 0:00–0:25 · The gap, on screen, no intro

Split screen. Left: the mandate, as the human wrote it.

> *"Book me a flight to Delhi, under ₹8,000."*

Right: what the agent actually bought.

```
Flight to Delhi        ₹7,800
Travel insurance         ₹450   ← nobody asked for this
Seat selection           ₹600   ← or this
                       ───────
                       ₹8,850
```

> "A rule engine catches the total. **Nothing but a language model catches
> that nobody asked for insurance.** That gap is what this project detects."

**Do not** open with your name, the track name, or a title card. Open here.

## 0:25–1:00 · Why this is a real loss class

> "When an AI agent spends on your behalf, two things can go wrong. It can
> break a hard limit — over budget, wrong category, expired mandate, charged
> twice. Those are rules, and rules catch them.
>
> Or it can buy something you simply never asked for, inside every limit you
> set. No rule sees that. It shows up as a support ticket, or a chargeback
> sixty days later."

Name the loss class out loud: **agent-mediated unauthorised spend.**

## 1:00–1:40 · Architecture, one breath

Show the diagram from ARCHITECTURE.md.

> "Deterministic gate first — five rule checks, pure functions,
> 0.02ms at p99. Whatever survives the gate is the only thing the model
> sees. 29% of sessions never reach a model at all.
>
> The model fills a fixed schema. It has no tool that moves money. It cannot
> execute anything — it returns a list of findings, and that's the whole
> surface."

Say **"the model is never in the money path"** out loud.

## 1:40–3:00 · The live run

Terminal. `uv run warrant demo`. Let the real table appear.

Walk the rows in this order:

1. The five rule classes — 100% recall, gate only, no model calls.
2. **scope_creep** — 60 cases (35 clear + 25 ambiguous), caught by the verifier alone. Point out
   the gate catches **zero** of these. That is a regression test, not a claim.
3. **Cost:** ₹0.00 actual, ₹69.49 projected at paid-model rates.
   > "Zero, because it runs on a free tier. The projection is what the same
   > token volume would cost on a paid frontier model — that's the scaling
   > number, and it is not spend I incurred."

## 2:35–3:15 · Is the model even necessary? Prove it

`uv run warrant baseline`. This is the strongest 40 seconds in the video —
do not cut it.

> "Obvious question: do you need a language model for this, or would a
> keyword matcher do? So I measured it.
>
> The keyword baseline catches **more** violations than the model — 60 out
> of 60, versus 58. But look at what it costs: it wrongly blocks 45
> legitimate purchases, ₹1.43 lakh of real spend. It flags **every single**
> mandatory tax and **every** underspecified basket, because it can't tell
> an add-on nobody asked for from a tax you can't avoid.
>
> The model blocks ₹20,881. That's **6.9 times less**. The trade is two
> violations missed against ₹1.2 lakh of legitimate spend not blocked —
> and that trade is the whole argument for the model. It's a measurement,
> not a claim."

## 3:15–4:20 · The two closing results — this is the part that lands

**First: the discretion clause.**

Show a `clean_unusual` session.

> *"Book a hotel in Chennai... feel free to add breakfast if it seems
> reasonable."*

> "The agent added breakfast. A keyword matcher flags 'add-on' and is wrong —
> the human authorised exactly that call. **Zero** false positives across all
> 25 of these."

**Second: where it actually fails.** Show `clean_mandatory`.

> "These are unavoidable statutory fees. The agent didn't choose them — you
> can't book the hotel without paying the levy. Flagging one blocks a
> legitimate purchase.
>
> **8 false positives out of 25 — 32% — ₹20,881 of legitimate spend wrongly
> held.**
>
> And the interesting part is *how* it fails. It never once flagged 'Airport
> taxes and statutory fees' — the wording that spells out it's unavoidable.
> But the identical string 'GST 18%' it accepted once and flagged twice.
> That's not a knowledge gap about what GST is. It's the absence of a stable
> policy on mandatory charges — and it showed up on all three models I
> tested, so it's a property of the task, not one model's quirk.
>
> The fix isn't a better prompt. Mandatory charges need to be declared as
> line-item metadata instead of inferred from a description string."

**Do not skip this.** Volunteering your failure mode is the strongest thirty
seconds in the video.

## 4:20–4:40 · Evidence pack

`uv run warrant evidence <session_id>` on a flagged session.

> "For any flagged purchase: the mandate, the line items, which item was
> flagged, the reason, and the quote from the intent it was checked against.
> That's what a merchant needs to defend or explain a charge."

## 4:40–5:00 · Honest close

> "Every number regenerates from one command against a committed seed.
>
> Two things I'd want you to know before you judge the table. The five
> gate rows at 100% are a self-test — the generator makes a violation by
> putting the amount over the cap, and the gate catches it by checking the
> amount against the cap. That proves there's no bug, not that it's clever.
> The rows I'd defend are the verifier ones, where nothing is shared.
>
> And it's entirely synthetic data — because there is no public dataset of
> AI-agent purchases. The phenomenon barely exists yet. That's the honest
> limit: I've shown the pipeline works and where it breaks, not that it
> survives production traffic."

---

## Rules

- Lead with the ₹850 nobody asked for. Not your name, not the track.
- Say "the model is never in the money path" — once, clearly.
- Show the false positives. Do not round them away.
- Run `warrant baseline` on camera. It is the strongest evidence you have.
- Say the 100% rows are a self-test BEFORE a judge works it out themselves.
- Never say "100% accurate." Say what was measured and on which class.
- Read the real table off the screen. Don't recite from memory.
