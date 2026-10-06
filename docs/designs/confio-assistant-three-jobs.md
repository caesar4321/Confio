# Design: Confio Assistant's three jobs

Status: BUILT (2026-10-06; guidance always on by Julian's decision, no switch) · Owner: Julian · Related: `tu-primer-dolar.md`, `tu-mes-insights.md`

## Why three, and why not "where to put it"

There is no allocation decision for the assistant to help with:

- Ondo-eligible users' idle balance **is** Confío Dollar+ by default.
- Everyone else (Brazil, the US, …) holds Confío Dollar: no yield, 0.9% conversion fee
  at the perimeter.
- Moving money always needs the user's own signature on their phone.

So the assistant is useful in exactly three ways:

1. **Investment info and guidance**, including US tokenized stocks.
2. **Spending habits and money flow** ("Tu mes").
3. **Collecting needs and intents** from what people say, as evidence for product decisions.

---

## Job 1: Investment info and guidance

**Already live:**
- `get_stock_quote`: Ondo Global Markets price, 24h and 1-month change.
- `search_market_news`: cited news, past events only.
- Public tokenomics and whitepaper.
- An FAQ that explains Confío Dollar+ and stocks.

**The prompt today forbids** saying whether anything is worth it, Confío's own products
included ("nunca digas si conviene"). That's why "¿Debería comprar Apple?" gets a polite
no. Users will ask exactly this, and a refusal plus generic facts is useless to them.

**The line (always on since 2026-10-06; legal check for Duende still open):**

| Allowed | Not allowed |
|---|---|
| Explain any instrument: single stock vs. broad ETF vs. Confío Dollar+, concentration, volatility, time horizon, what "tokenized" means | Telling them to buy, sell or hold a specific ticker, or when |
| Say whether a *type* of instrument fits their situation | A "fits you" verdict on a named ticker (only info and risks for those) |
| **Use the person's own numbers**: "you spend about US$420 a month and have about US$600; a single stock is a lot of risk for money you might need next month" | Price targets, predictions, "this will go up" |
| Compare two things they name, with the risks of each | A % or amount to put into a specific ticker |
| Reflect their stated risk preference back ("you said you don't want the principal to move…") | Promising or implying returns |
| Open the stock's page (`navigate`) so they decide there | Pre-filling a buy, or any buy "on their behalf" |

- **Eligibility:** stocks and Confío Dollar+ only for Ondo-eligible users. For others, the
  assistant explains why it isn't available and never promotes it.
- **Fees** only when the person asks about costs (Julian, 2026-10-06): the app shows the exact cost
  before every confirmation, so the assistant doesn't repeat it in other answers.
- **New tool `get_portfolio`** (read-only, JWT-scoped), so guidance uses real numbers
  instead of guesses:
  - Confío Dollar or Confío Dollar+ balance;
  - stock holdings with current value;
  - average monthly spending over 3 months (from Tu mes).
- **Known gap to respect:** `cusdPlusSummary.earned_month_usd` is hardcoded 0 on the server.
  The assistant must not quote "this month you earned…" until that has a real computation.

## Job 2: Spending habits and money flow

**Already live:**
- `get_month_summary`, `get_transactions`, `analyze_finances` (Sol);
- categorizing with the 12 Tu mes categories, applied only on the user's "sí";
- per-person suggestions (server-ranked since `0b0dfd17`).

**Nothing new here for now.** Proactive insights belong to `tu-mes-insights.md`. Job 1's
`get_portfolio` also feeds this job (spending vs. what they hold).

## Job 3: Collecting needs and intents

**Already live:**
- the one-time probe "¿Para qué te gustaría usar Confío?" (`ProbeAnswer`);
- full thread history in the DB.

**New: a nightly need tagger.**
- **Input:** a Celery task reads the day's user messages from the assistant and support
  threads.
- **Classification:** each message gets a fixed category, using Luna with `store=False`,
  about US$0.0001 per message:
  - Product needs: `invest_stocks` · `savings_yield` · `spending_insight` · `top_up` ·
    `withdraw` · `send_family` · `receive_abroad` · `pay_qr` · `cash` ·
    `business_payroll` · `crypto_deposit` · `presale_token`
  - Things Confío doesn't offer: `loan_credit` · `card`
  - Problems: `verification_issue` · `money_stuck`
  - Other: `how_to_app` · `other`
- **Storage:** one `AssistantNeed` row per tagged message: user, message, category,
  `met_by_confio`, country, funded, and a short paraphrase (max 120 chars, numbers and
  emails redacted).
- **Read-only admin**, plus `manage.py assistant_needs_report`: counts by category ×
  country × funded, and the top unmet needs with paraphrased examples.
- **Not a conversation change:** the assistant never asks extra questions to "collect
  data". The probe is the only question, and it is asked once.

**Why:** it turns the 418-thread manual analysis into a weekly report that never goes
stale. For example, loans would have shown up as the #1 unmet need without anyone reading
threads. Together with the probe, it answers "why would someone choose Confío" from
behaviour, not opinions.

---

## Decisions

1. **Job 1 line:** approved and always on (Julian, 2026-10-06). No switch.
2. **Legal check (open):** may Duende (Seychelles) give this kind of situation-based guidance to
   users in AR, BO, MX, PE, CO and CL?
3. **Build order:** both jobs built in parallel.

## Implementation notes

- `get_portfolio` never turns "couldn't read" into 0: unknown balances, prices and eligibility
  are "desconocido". Eligibility is request-aware (`ONDO_POLICY.evaluate`, IP + phone). Holdings
  are read from the last scan (no chain scan in a chat turn) and shown regardless of eligibility.
- Average spending counts only full months since the account opened.
- The tagger runs daily at 03:40 Bolivia time over a 72h window (missed runs catch up),
  redacting emails, numbers, links, wallets and ids before Luna sees the text.

## Out of scope

- Allocation or "park your surplus" flows: there is no choice to make.
- Any AI-initiated money movement.
- External agents (MCP / x402) and delegated signing: later, per the agent-era discussion.
