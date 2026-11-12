# Design: Assistant first-steps guide

Status: DRAFT, awaiting founder review of the open decisions and all user copy.
Date: 2026-11-01
Builds on: `tu-primer-dolar.md` (approved 2026-10-06, never built).

## Why now

`tu-primer-dolar.md` chose a Home hero for never-funded users and rejected a
proactive bubble as "a dismissable popup". The hero was never built: only the
first-use question and the "¿Cómo pongo mis primeros dólares?" chip shipped, and
both wait for the person to open the assistant.

This design replaces that hero. Home stays as it is. The assistant starts the
conversation after onboarding, and the person confirms and taps every step
themselves. It also goes past the first top-up.

Measured on prod, signups 2026-10-01 to 10-29 (1,330 people):

| Step | People | Share of signups |
|---|---:|---:|
| Signed up | 1,330 | 100% |
| Used the assistant | 421 | 32% |
| Started identity verification | 235 | 18% |
| Verified | 94 | 7% |
| Created a top-up order | 23 | 1.7% |
| Paid a top-up order | 12 | 0.9% |
| Funded by any route | 16 | 1.2% |

- 71 of the 94 verified people never created an order.
- An order left unpaid ends as FAILED. There is no expired status, so those rows
  mean "not paid", not a failed rail.

After the first top-up (37 people, first top-up 2026-08-01 to 10-25):

| After first top-up | People |
|---|---:|
| Sent or paid someone | 25 |
| Holds stocks today | 12 |
| Bought in the presale | 0 |
| Bought in Comprar | 0 |
| None of these | 12 (32%) |

This cohort is small, counts only completed on-ramp orders, and does not show why
money was sent. Comprar is new and limited to its pilot cities.

## Rules

- The assistant never moves money, and it never changes screen on its own. Every
  move follows a tap by the person.
- It never recommends a stock, ETF, market or leverage. Invest steps open the list
  and explain how buying works and that the price can fall. They never use the
  `stock` destination.
- Numbers come from code: limits from the live top-up limits for that country, fees
  from configuration. Minimums differ by country and are never written into copy.
- Personal accounts only. Employees and business accounts see no guide.
- One guide prompt per session. "Ahora no" stops that step for good. Any failure
  evaluating the guide means no guide.
- No control group (standing founder decision).
- Code identifiers in English, user copy in neutral Spanish.

## Stages

The server computes one stage per person from existing records. Nothing is stored
except what was shown, accepted or dismissed.

| Stage | Condition | Next step offered |
|---|---|---|
| `verify` | Top-up rail needs identity, none verified | Open verification |
| `verifying` | Verification in review | Say it is in review, no action |
| `top_up` | Rail usable, nothing funded | Open Recibir, point at "Recargar ahora" |
| `awaiting_payment` | Unpaid order still open | Explain how to pay this order |
| `international_waitlist` | No local rail, international top-up off | Say it arrives soon, offer USDT |
| `international_top_up` | No local rail, international top-up on | Open the international top-up |
| `usdt_only` | No local rail, Guardarian doesn't serve the country | Offer USDT, promise nothing |
| `first_action` | Funded | One step from the ladder below |
| `done` | Ladder finished or dismissed | No guide |

A person who is funded by a send or USDT skips to `first_action`.

## Country routing

- **Local top-up:** AR, BO, BR, CL, CO, MX, PE, VE open the top-up screen.
  - Each country's entry point lives in `assistant/rails.py`, as a row id on Recibir:
    `recharge_now` by default, `receive_ve_pagomovil` in Venezuela, and `receive_bo_qr`
    in Bolivia as soon as `koywe_replaced` turns on after partner approval.
  - The app circles any row by its id, so changing an entry is a server change.
  - Use the same availability as the top-up screen, including paused countries and
    the rejection lock.
  - VE follows the existing Pago Móvil rules: build 5.2.8 or later and a verified
    identity. Older builds get the existing update note.
- **Countries Guardarian serves:** international top-up, in the logic but off.
  - `ASSISTANT_INTERNATIONAL_TOPUP_ENABLED`, default `False`.
  - While off, say it arrives in about two weeks, with no date, and offer USDT through
    Recibir → Avanzado as today. The timing depends on Guardarian, so no date is set
    in code. The line stays until the flag is turned on or the copy is changed.
  - Coverage comes from Guardarian's `/v1/countries` catalog (`supported: true`, 127
    of 250 on 2026-11-01). This includes EC, US, ES, PY, GT, SV, HN, DO, CR and UY.
- **Countries Guardarian doesn't serve:** USDT only, no promise. Among countries with
  Confío users that means PA, NI, CU and PR.
- `NO_RAMP_NOTE`, `NO_RAMP_COUNTRIES` and the FAQ lines on countries without Recargar
  must carry the same split, or the assistant contradicts the guide.

## After funding: the first-action ladder

One step at a time, and only steps the person can use. A step is complete when the
records show it happened, not when it was offered.

| Step | Shown when | Destination |
|---|---|---|
| Send | Has not sent to anyone | `send` |
| Invest | Ondo policy allows it, holds no stocks | `stocks` |
| Comprar | Comprar serves their city, no order yet | `comprar` |

Order comes from the first-use answer:

- family: Send, Invest, Comprar
- devaluation, savings: Invest, Send, Comprar
- pay: Comprar, Send, Invest
- no answer: Send, Invest, Comprar

Where Dollar+ and stocks are unavailable (Brazil, for example), the Invest step is
dropped by the same policy the Invest screens use.

## Experience

The chat sheet covers half the screen, so the guide gets its own surface: a compact
**guide card** docked at the bottom. It never dims or blocks the screen.

1. **Opening.** Right after onboarding the card opens by itself and the assistant
   speaks first, starting from the first-use question.
2. **Conversation.** Reply chips, plus a text field for anything else. The answer
   appears in the card. The chevron expands it into the normal chat.
3. **Move.** A confirming chip opens the real screen. The assistant never moves
   screens without a tap.
4. **Teach.** On the destination the card shrinks to one line, and a pencil draws a
   circle around the real button. The person taps it.
5. **Continue.** When the stage changes, the card returns with the next step.

Closing the card, or "Ahora no", stops that step. The bubble stays available.

## Server-driven guide

No fixed script. The client renders one generic contract, so new situations need a
server change, not a build:

```
guide { text, chips: [{label, action}], target, stage }
```

- **Text comes from the assistant model**, through the same engine, FAQ and rules as
  every reply, given the person's stage, country, first-use answer and eligibility.
- **Actions come from the server.** The model picks only from the actions the stage
  allows. It can't invent a step, a destination or a target. `navigate` stays limited
  to `assistant/destinations.py`.
- **Anything off-script is a normal assistant turn**, which then steers back to the
  current step.
- **Fallback:** each stage keeps one fixed sentence, shown if the model is slow or
  fails. The card must never wait on the model.
- **Cost:** about US$1 a month at current signups, assuming 5 turns per person.

A build is needed only for a new `target` anchor. Unknown targets show the card
without the pencil, so older builds keep working.

Anchors in the first build: Recibir, Recargar ahora, Enviar, Invertir, stocks list,
Comprar, Verificación, Avanzado.

## Phases

**Phase 1, server:**

- stage computation in `assistant/suggestions.py`
- country routing and flags
- the guide contract, allowed actions per stage, fixed fallbacks
- first-action ladder
- a table recording shown, accepted and dismissed per step (migration needed)

**Phase 2, store build (required, the card doesn't exist yet):**

- guide card, opened after onboarding
- pencil and hand-drawn circle (react-native-svg, Reanimated), anchored to `target`
- served in its own query, so older servers don't fail shared queries

## Measurement

Baseline is the October signup cohort above, read by country because the mix is
mostly Bolivian. Compare signups after launch, each followed for at least 7 days:

- **Primary:** share of signups funded within 7 days.
- **Secondary:** share of funded people with a first action within 7 days.
- **Diagnostic:** shown → accepted → screen opened → step done, per stage.
- **Guardrails:** "no llega" threads do not rise; dismissal rate per step.

## Copy (awaiting founder sign-off)

Fixed text exists only as the fallback per stage. Everything else is generated.

| Stage | Fallback | Allowed actions |
|---|---|---|
| Opening | ¿Para qué te gustaría usar Confío? | First-use answers |
| `verify` | Para recargar, primero necesitas verificar tu identidad. | Open verification |
| `verifying` | Tu verificación sigue en revisión. | None |
| `top_up` | Ya puedes recargar. | Open Recibir, target Recargar ahora |
| `awaiting_payment` | Tu orden de recarga sigue esperando el pago. | Open the order |
| `international_waitlist` | La recarga internacional llegará a tu país en unas dos semanas. | Open Avanzado |
| `usdt_only` | Puedes recibir USDT desde Binance u otra billetera. | Open Avanzado |
| Send | ¿Te muestro cómo enviarle a alguien? | Open Enviar |
| Invest | ¿Te muestro cómo funciona invertir? | Open the stocks list |
| Comprar | ¿Quieres ver qué venden cerca de ti? | Open Comprar |
