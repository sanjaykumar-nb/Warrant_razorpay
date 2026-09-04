# 5-minute pitch — shot list

Screen recording with voiceover. **No slides.** Every number below is the real
output of `uv run warrant demo` on 340 sessions.

**Console:** https://sanjaykumar-nb.github.io/Warrant_razorpay/

---

## Before you hit record

- [ ] Open the console in a browser tab. Check the **Review queue** loads with items.
- [ ] Terminal open at the repo, font size up.
- [ ] Run `uv run warrant demo` once so it's warm — it replays from cache in seconds.
- [ ] Close Slack, email, notifications.
- [ ] Practise the first 25 seconds twice. Nothing else needs rehearsing.

---

## 0:00 – 0:25 · The gap

**Screen:** console, **Review queue**, top of page.

Say it over the queue, no intro, no name, no title card:

> "This is a queue of purchases an AI shopping assistant made on someone's behalf —
> where it bought something the person never asked for.
>
> Somebody said *book me a flight to Delhi under eight thousand rupees*. The agent
> booked the flight at seven thousand eight hundred — and added travel insurance,
> and seat selection. Every fraud check passes. The card is valid, the merchant is
> real, the customer's own agent started it.
>
> **And a thousand rupees of that was never authorised.**"

## 0:25 – 1:20 · One purchase, end to end

**Screen:** click **`S-CRP-668092`** in the queue.

> *"Order a USB-C charger, budget up to ₹4,363."* — and it bought the charger,
> **plus expedited shipping, plus an extended warranty.**

Point at the two red rows, then the reasoning underneath:

> "It tells you which items, why, its confidence, and the phrase from the original
> request it checked against. That's what a merchant needs to defend the charge."

Now scroll to the recommended action:

> "And here's the part I care about most. It does **not** block the purchase.
> It captures **₹3,192 of ₹3,645** — the charger goes through, the two add-ons are
> simply not taken.
>
> Between authorisation and capture, the money is *held*, not taken. A check takes
> a second or two. That window is much longer. So this is never block-or-allow —
> **a wrong decision costs one line item, never the transaction.**"

Click **Apply this action.** The queue count drops.

## 1:20 – 2:10 · Where it used to fail — the best 50 seconds

**Screen:** click **Correctly cleared** in the sidebar, then the **Statutory charge** tab.
Open **`S-MND-994455`**.

> "Not flagging things wrongly matters just as much. This one is a winter jacket
> plus **GST at 12%**."

Point at the teal row and the line underneath it — *12% of the taxable base, and named as statutory*.

> "Two weeks ago this system flagged that. It told you **GST was an unauthorised
> purchase.** You cannot buy anything in India without paying GST. It did that
> **32% of the time**, at 0.85 to 1.0 confidence — so no confidence threshold would
> have saved it.
>
> Then I tested it on three models from two different labs. **All three failed the
> same way.** That told me it wasn't the model. It was the question: I was asking a
> language model to *guess, from a text string,* whether a charge was the agent's
> choice. That isn't answerable from text.
>
> So I stopped asking. A twelve percent GST line is exactly twelve percent of the
> base — that's arithmetic. It's settled before the model is ever involved, and
> anything identified as statutory is removed from review entirely.
>
> **Thirty-two percent to zero. And it halved the cost, because a third of sessions
> stopped needing a model at all.**"

## 2:10 – 2:50 · Do you even need AI for this?

**Screen:** terminal.

```bash
uv run warrant baseline
```

> "Fair question, so I measured it. Same 340 sessions through a keyword matcher.
>
> The keyword matcher catches **more** violations than the model — sixty out of
> sixty against fifty-six. But it blocks **₹33,188** of legitimate customer money
> doing it. The model blocks **zero.**
>
> It flags every vague basket — *stock the office pantry* becomes tea, biscuits,
> cups, and it flags all of them. The trade is four violations missed against
> thirty-three thousand rupees of real spend not wrongly held.
>
> That comparison holds even though my data is synthetic, because both approaches
> saw identical sessions."

## 2:50 – 3:30 · It's a real system

**Screen:** terminal.

```bash
uv run pytest -q
uv run warrant demo
```

> "Eighty-one tests. Every number regenerates from a committed seed with one command
> — you can reproduce all of this without an API key.
>
> Notice: **69% of sessions never reach a language model.** Five deterministic rules
> handle caps, categories, expiry and duplicates in **0.03 milliseconds** — fast
> enough to sit inline in a real checkout. The model only sees what genuinely needs
> judgment, and it fills a fixed schema. **It has no tool that moves money.**"

## 3:30 – 4:20 · What I'd want you to distrust

**Screen:** console → **Performance**.

Do not skip this. It is the strongest part.

> "Five of these seven rows are at 100%, and those five are close to meaningless.
> My generator creates an over-cap violation by putting the amount over the cap, and
> my gate detects it by comparing the amount to the cap. **Same condition on both
> sides.** That's arithmetic, not capability — anything less would be a bug.
>
> The rows I'd defend are the two model rows, 97% and 88%, and the false-positive
> table — because there the generator and the detector share no code.
>
> And it's **entirely synthetic data.** There's no public dataset of AI-agent
> purchases, because the behaviour barely exists yet. So I make no claim about
> real-world accuracy. What I measured is the comparison, and that survives.
>
> It also still misses things. Four cases — it decided reusable carry bags were in
> scope for *order groceries for the week*. Honestly, **it might be right and my
> label might be wrong.** I counted it as a miss anyway."

## 4:20 – 5:00 · Close

**Screen:** console → **How it decides**, scroll to *What this is not*.

> "Gate, tax classifier, semantic verifier, remediation — each stage exists to keep
> the next one honest, and the expensive one runs last on the smallest input.
>
> This is not production. It has never seen a real transaction, and nothing in it
> actually executes a payment — remediation decides to partially capture, it doesn't
> capture. Next would be real API integration, a mandate store, and shadow-mode
> validation on live traffic.
>
> What it is: a validated architecture, with one real failure mode found, diagnosed
> across three models, and closed — and honest measurement of everything that's
> left."

---

## Rules

- **Open on the queue, not on your name.** No title card, no introduction.
- **Say "it has no tool that moves money"** — once, clearly.
- **Never say "100% accurate."** Say which rows are self-tests before anyone works it out.
- **Do not skip the 32% story.** Finding your own failure, proving it across three
  models, and fixing it with arithmetic instead of prompt-tuning is the single most
  hireable thing in this project.
- **Read numbers off the screen**, don't recite from memory.
- A rough single take beats no video.

## If you only have 90 seconds

The queue → `S-CRP-668092` → partial capture → the GST story. That's the whole
project.
