# 5-minute pitch — shot list

Screen recording with voiceover. **No slides.** Numbers in `[brackets]` get
filled from the final `uv run warrant demo` output before recording.

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
> `[p99]`ms at p99. Whatever survives the gate is the only thing the model
> sees. `[X]%` of sessions never reach a model at all.
>
> The model fills a fixed schema. It has no tool that moves money. It cannot
> execute anything — it returns a list of findings, and that's the whole
> surface."

Say **"the model is never in the money path"** out loud.

## 1:40–3:00 · The live run

Terminal. `uv run warrant demo`. Let the real table appear.

Walk the rows in this order:

1. The five rule classes — `[100%]` recall, gate only, no model calls.
2. **scope_creep** — `[N]` cases, caught by the verifier alone. Point out
   the gate catches **zero** of these. That is a regression test, not a claim.
3. **Cost:** ₹0.00 actual, `[₹X]` projected at paid-model rates.
   > "Zero, because it runs on a free tier. The projection is what the same
   > token volume would cost on a paid frontier model — that's the scaling
   > number, and it is not spend I incurred."

## 3:00–4:10 · The two closing results — this is the part that lands

**First: the discretion clause.**

Show a `clean_unusual` session.

> *"Book a hotel in Chennai... feel free to add breakfast if it seems
> reasonable."*

> "The agent added breakfast. A keyword matcher flags 'add-on' and is wrong —
> the human authorised exactly that call. `[0]` false positives on `[25]`
> of these."

**Second: where it actually fails.** Show `clean_mandatory`.

> "These are unavoidable statutory fees. The agent didn't choose them — you
> can't book the hotel without paying the levy. Flagging one blocks a
> legitimate purchase.
>
> It gets GST right. It flags 'Mandatory state tourism levy' as scope creep.
> `[N]` false positives out of `[25]`, `[₹X]` of legitimate spend wrongly
> held. It recognises familiar tax labels and not unfamiliar statutory ones —
> and that's the honest limit of what I built."

**Do not skip this.** Volunteering your failure mode is the strongest thirty
seconds in the video.

## 4:10–4:40 · Evidence pack

`uv run warrant evidence <session_id>` on a flagged session.

> "For any flagged purchase: the mandate, the line items, which item was
> flagged, the reason, and the quote from the intent it was checked against.
> That's what a merchant needs to defend or explain a charge."

## 4:40–5:00 · Honest close

> "Every number regenerates from one command against a committed seed.
>
> The scores on the clear-cut classes are high because the ground-truth rule
> is consistent — flag what the intent didn't authorise. What that measures
> is that the pipeline works and the model applies a stated policy reliably.
> What it doesn't measure is genuinely contested cases. Building that harder
> benchmark is the next thing I'd do."

---

## Rules

- Lead with the ₹850 nobody asked for. Not your name, not the track.
- Say "the model is never in the money path" — once, clearly.
- Show the false positives. Do not round them away.
- Never say "100% accurate." Say what was measured and on which class.
- Read the real table off the screen. Don't recite from memory.
