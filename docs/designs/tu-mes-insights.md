# Design: "Tu mes" insights (phase 1.5)

Status: APPROVED mockup (Julian, 2026-10-04), detailed spec below
Mockup: `~/.gstack/projects/caesar4321-Confio/designs/tu-mes-insights-20261004/polish-A.png`
Builds on: [cashflow-home-tu-mes.md](cashflow-home-tu-mes.md) (Decisions 1-4, R1-R7 stay in force)
Design system: [DESIGN.md](../../DESIGN.md) (app tokens in `apps/src/config/theme.ts`)

## Why

Founder feedback, 2026-10-04: categorization alone "doesn't offer proper value, not even near
Banksalad, Mint or Toss". Those apps sort spending automatically and then *give something back*.
Our money moves mostly person to person (no merchant codes), so asking for a category on
every payment is homework with no payoff.

Tu mes therefore leads with what Confío can show **with zero user effort**, built from data we
already hold. Categories move below the insights as an optional layer.

1. **Te quedaron**: the month's result (Entró − Salió).
2. **Tu dólar te protegió**: the protection value from Decision 3. Only Confío can compute it.
3. **Pagos fijos**: payments that repeat every month, and when the next one is due.
4. **Tu ritmo**: how this month compares with last month at the same day (current month only).

## Changes from the earlier doc (explicit, so nothing contradicts silently)

| Earlier decision | Now | Reason |
|---|---|---|
| "No recurrence labels in phase 1" (Decision 2, revisit after 8 weeks of BO data) | **Pagos fijos ships** with conservative detection (≥2 prior months, see §5) | The founder approved the card on 10-04. Strict thresholds keep false positives rare. A user with no history just doesn't see the card. |
| Protection = one sentence "Hoy esos dólares te costarían Bs 340 más." | Same number and same rules, rendered as a **card with a two-bar comparison** | Decision 3's math is unchanged. The mockup's 3-month market-rate line chart is **not** used: R7 forbids `ExchangeRate` market rates, and those rows are deleted after 7 days anyway. |
| Categories were the main body of Tu mes | Categories become a **compact section below the insights** | Value first, homework optional. |

## 1. Screen anatomy (top → bottom)

```
┌ Header (shared Header, isLight): ← Tu mes             colors.heroField, white title (app-wide convention, 47 screens; contrast fix tracked in TODOS.md, design review 17A)
│ Month switcher: (‹)  Septiembre 2026  (›)               round 40pt white buttons, centered row
│ ── 16 ──
│ [Card A] Te quedaron (+ pace line, §6)                   when the month has movements
│ [Card B / B'] Tu dólar te protegió / Tu ahorro ganó      one dollar slot (§4, R21)
│ [Card C] Pagos habituales                                ≥1 detected recurring payment (§5)
│ ── 24 ──
│ En qué se fue          (existing, compact: CTA + chips)  unchanged logic
│ Entre tus cuentas      (existing)
│ Con quién              (existing)
│ Ver todos los movimientos ›
└ bottom inset + 24
```

- Screen background `colors.surface` (#F9FAFB; `colors.background` is white in theme.ts); cards `colors.white`; hairlines `colors.border`; horizontal gutter 16 (design review 18A).
- The cards are a vertical stack with a 12pt gap. Cards that don't qualify are **omitted** (no
  empty shells), and the gap collapses.
- Past months show A, B' (when that month has a snapshot for every day; design review 23A) and C. B (protection) is current-month only. Card A shows the "vs agosto" comparison line instead of the pace line.
- Employees never see Tu mes (unchanged scope rule). Business owners see A, B' (when the business has savings; design review 4A) and C. B (protection) is personal only.
- Only Card A's result uses the 34pt size; it is the single anchor (design review 3A).

## 2. Card system (shared by A-D)

| Property | Value |
|---|---|
| Background | `colors.white` |
| Radius | 20 |
| Border | hairline `colors.border` |
| Shadow | none, no elevation (design review 14A): white card on `colors.surface` + hairline is the whole separation |
| Padding | 20 (16 below 360pt width) |
| Title row | bare Feather glyph 18pt `colors.flowIn.textSmall` (no circle; design review 13A), 8pt gap, title 17/22 semibold `colors.textFlat` |
| Title row → content | 16 |
| Body text | 15/20 regular `colors.textFlat` |
| Caption | 13/18 regular `colors.text.secondary` (#6B7280) |
| Numbers | `fontVariant: ['tabular-nums']`, exact amounts (no K/M), separators from `useNumberLocale()` |
| Tap target | whole card when it has a destination (≥44pt), `activeOpacity` 0.75, chevron-right 18pt `colors.text.light` at the end of the title row |
| Accessibility | (design review 20A) each card's non-interactive text is grouped into one label read in natural Spanish; every action is its own element with role button: Entró, Salió, ¿Cómo lo calculamos?, each payment row, +N más / Ver menos. Masked → every label says "oculto" instead of amounts, sheet included. Decorative visuals (bars, track, sparkline) `importantForAccessibility="no"`. |

Font scale (design review 21A): all card text follows the system scale up to 1.6× (`maxFontSizeMultiplier={1.6}`). At fontScale ≥ 1.3, rows stack (name / caption / amount + pill) instead of shrinking. Only Card A's result uses `adjustsFontSizeToFit`, with `minimumFontScale={0.85}`. No other amount shrinks. Sentences wrap and never truncate. Month buttons stay 40pt visible with `hitSlop` to a 44pt target.

Narrow screens (design review 22A): in payment rows the name is `numberOfLines={1}` with tail ellipsis and `flexShrink: 1`; "casi cada mes" sits on its own line; the amount and pill are `flexShrink: 0` and never truncate (same as "Con quién").

## 3. Card A: Te quedaron

```
Te quedaron                                  caption 13, text.secondary
+US$39                                       34/40 bold, flowIn.text #059669
(↓) Entró US$215     (↑) Salió US$176        15/20 semibold; chips 20pt (flowIn.chip/flowOut.chip)
████████████████▌██████████                  bar 8pt, radius 4, flowIn.bar / flowOut.bar, 2pt gap
Sin contar recargas, retiros ni ahorro.       caption 13 text.secondary (design review 1A, always)
vs agosto: salió US$6 menos, entró US$11 más  caption 13 (past months, and current month before day 5)
(✓) Vas bien: gastas menos que en septiembre  pace line, current month day ≥ 5 (§6, design review 2A)
A este ritmo, ~US$440 este mes · Septiembre US$390   caption 13, from day 7
```

- No title-row chip: it's the hero. Background: the existing faint mint wash (Svg `tuMesWash`).
- Result states:
  - **> 0:** label "Te quedaron", value `+US$39` in `flowIn.text`.
  - **= 0:** label "Quedaste a mano", value `US$0` in `textFlat`.
  - **< 0:** label "Salió más de lo que entró", value `−US$12` in `textFlat`. **Never red**; blue
    is for "out", not alarm (DESIGN.md "Money in / out").
- Masked balance (eye toggle): every amount becomes `MASK`, and the bar keeps its proportions.
- Tapping "Entró" or "Salió" opens the existing filtered movements list (unchanged).
- a11y: "Septiembre: te quedaron 39 dólares. Entraron 215, salieron 176."

## 4. Card B: Tu dólar te protegió

Math, sources and visibility follow **Decision 3, R7, R13 and R14 exactly** (R13: chronological
replay of every balance-changing USD event, where on-ramps add lots and outflows deplete non-lot dollars first, then lots FIFO;
R14: compared against Confío's current buy quote for a $100 reference, flag per country (legal cleared 2026-10-04: ON for BO/VE, kill switch), show only when positive and ≥ Bs 10
or its equivalent, fail closed).

```
(🛡) Tu dólar te protegió
Tus US$100 hoy costarían Bs 340 más.          body 15, "Bs 340 más" bold flowIn.textSmall (18A: green under 20pt)
Pagaste      ███████████████░░░░  Bs 3.650   bar 10pt, colors.compareNeutral (new token #CBD5E1)
Hoy          ██████████████████   Bs 3.990   bar 10pt, flowIn.bar #34D399
¿Cómo lo calculamos?                          link 13 flowIn.textSmall → D25 bottom sheet (R22)
```

- Bars are horizontal and scaled to the larger value. Labels sit left (width 64) and values right,
  aligned with tabular numbers. The local-currency symbol and separators come from the ramp
  currency (`formatMinorMoney`).
- "Tus US$100" is the protected USD (remaining on-ramp lots after the R13 replay, capped at the balance), formatted
  exactly with no rounding to "100".
- Glyph: Feather `shield`. No illustration.
- Explainer sheet (R22 + approved mockup + design review 9A): bottom sheet with a grab handle, title, three label/value rows (see §8 sheet.rows), one body sentence, and a full-width emerald "Entendido". It is a **snapshot of the same protectionValue result the card used**: no fetch on open, so it can never disagree with the card. Masked → values MASK.
- **Card B' anatomy (approved mockup tu-mes-new-states variant A; design review 3A, 5A, 6A):**
  ```
  (seedling) Tu ahorro ganó
  ~US$0,42                                    28/34 bold flowIn.text; 2 decimals (6A: the one cents exception on Tu mes)
  ▁ ▂ ▂ ▃ ▃ ▄ █                              one bar per day so far, 40pt tall, flowIn.bar, last bar flowIn.text, 2pt gap
  en octubre                                  caption 13 text.secondary (no "protegido")
  ```
  Data: `savingsEarned` adds `dailyUsd[]` (one value per elapsed day). Fewer than 3 days → number only, no bars. Any missing day → card hidden (R20 null rule). Masked → number MASK, bars stay (relative heights only).
- **Slot rule (R21):** one dollar slot per account. Card B when it renders; otherwise Card B' "Tu ahorro ganó ~US$X en {mes}" (R20: daily snapshots; hidden on null / < US$0.01 / savings disabled), in any country. B' also renders on **past months** whose every day has a snapshot (design review 23A); the first such month is the first full month after snapshots start.
- Card B is hidden when the flag is off, there are no lots, there's no quote, the value is
  ≤ threshold, the query errors, or the account isn't personal. No loss copy ever.
- **Past months:** Decision 3 is a "today" number, so on a past month the card shows only if a
  month-end snapshot exists. Phase 1.5 does not snapshot, so **the card shows on the current
  month only**.
- Tap: none in phase 1.5 (no chevron). a11y: "Tu dólar te protegió: tus 100 dólares hoy
  costarían 340 bolívares más que lo que pagaste."

## 5. Card C: Pagos habituales (was "Pagos fijos"; design review 16B)

```
(calendar) Pagos habituales
1 ──●──────●────────────────── 31            track 4pt colors.border, dots 10pt flowOut.text, today tick; end labels only (15A)
(K) Karen       casi cada mes    ~US$100     avatar 36 pastel; name 15 semibold; amount 15 bold
                                  [5 oct]     pill: 12/16 semibold flowIn.textSmall on flowIn.chip, radius 8
────────────────────────────────────────     hairline divider, inset 48
(W) Wilber      casi cada mes     ~US$35
                                  [12 oct]
```

- The track spans the **viewed month's** days (28-31) and is labeled only at its ends ("1" and the last day; design review 15A). Dots mark each payment's expected day.
  Two payments on the same day stack as one dot with a "2" badge (8pt). On the current month a
  1pt `textFlat` tick marks today.
- Rows are sorted by **day of month** and capped at **3** rows. With more than 3, a "+N más" row (15 semibold flowIn.textSmall, ≥44pt) expands the card in place; "Ver menos" collapses it (design review 11A).
- Avatars come from the existing Tu mes pastel set (initials). **Never violet**, because violet is
  reserved for $CONFIO.
- Amount `~US$100` is the median of the detected occurrences, rounded to whole dollars
  (`formatUsd(..., {whole: true})`), with a leading "~" because it's an estimate.
- Pill (design review 7A, supersedes R24's "next expected date"): always the **viewed month's** expected date ("5 oct"), never a next-month date. On the current month, days before today show a hollow dot and the pill in `text.secondary` on `colors.surface`, which says "already passed" without claiming "paid". There is no "Pagado" state.
- Name: the counterparty name as in "Con quién" (unknown wallets use `externalName`). When the
  user has a category on that person, the caption reads "Casa · casi cada mes" instead of "casi cada mes".
- Tap row → `MonthMovements` filtered to that counterparty (existing filter).
- a11y per row: "Karen, pago habitual, alrededor de 100 dólares, el 5 de octubre."

**Detection rule** (server, deterministic, no AI):
- Outbound `Salió` movements only (person, business or external wallet), grouped by
  `counterparty_key`, confirmed only.
- The counterparty appears in **≥2 of the 3 previous calendar months** (in the account timezone).
- The amounts in those months are each within **±25%** of their median.
- The day-of-month of those payments spans **≤ 6 days** (wrap-aware at month end).
- Each month contributes one occurrence: its **first** payment day and the month's summed amount.
- Expected day = the **circular** median of those days (days on a 31-day circle, so 28 and 2 give the 30th/31st, never the 15th), clamped to the month length. Expected amount = the median monthly sum. (Outside-voice correction #3.)
- Exclusions: own-account moves (Recarga, Retiro, Ahorro), conversions, presale, and payments
  under US$1.
- If a counterparty has more than one payment in the same month, use the month's sum (rent split
  in two still counts).

## 6. Pace line inside Card A (current month only; was Card D, folded per design review 2A)

```
(✓) Vas bien: gastas menos que en septiembre   15/20 semibold; badge 16pt; 12pt below the Sin contar caption
A este ritmo, ~US$440 este mes · Septiembre US$390   caption 13
```
No title row, no calendar bar (the bar measured days, not money; removed with the card).

- Shown when: the viewed month = the current month, day ≥ 5, and the **full** previous month had Salió > 0.
- Inputs (outside-voice correction #4): the verdict uses monthSummary's comparable-period `previous` (comparison_window, same day and time, clamped). The caption's "{mes} US$390" and the eligibility use the **full** previous month's Salió, which monthInsights returns as `previousMonthSpendingUsd`. If the comparable-period Salió is 0: this month 0 → "Vas parecido"; this month > 0 → "Vas gastando más".
- Verdict compares Salió to date with **last month's Salió up to the same day**:

  | Ratio this ÷ last | Badge | Copy |
  |---|---|---|
  | ≤ 0.9 | `check-circle` flowIn | "Vas bien: gastas menos que en {mes pasado}" |
  | 0.9 – 1.1 | `minus-circle` text.secondary | "Vas parecido a {mes pasado}" |
  | ≥ 1.1 | `info` flowOut.text | "Vas gastando más que en {mes pasado}" (blue, never red, no scolding) |

  Business accounts (design review 12B) use plain facts with a neutral `minus-circle` text.secondary icon: "Hasta hoy salió menos que a esta altura de {mes}" / "Hasta hoy salió parecido a {mes}" / "Hasta hoy salió más que a esta altura de {mes}". Personal accounts keep the warm copy above. Accepted risk: on personal accounts, "Vas bien" can sit above a projection higher than last month's total.

- Projection (R24) = Salió to date ÷ days elapsed × days in month: linear pace only, with no
  fixed-payment term. Shown only from day 7, rounded to whole dollars with "~".
- Tap: none. a11y (part of Card A's summary): "Vas bien, gastas menos que en septiembre. A este ritmo, alrededor
  de 440 dólares este mes."

## 7. Global states

| State | Behavior |
|---|---|
| Loading | (design review 8A) Card A placeholder (same height) renders first. The insight cards **and the sections below them** are revealed together, in fixed slot order, once every insight query settles or 800ms pass, whichever comes first. A query that answers later is dropped for this view. Refocus refetches silently (no re-fade, no re-grow). Nothing on screen ever moves after the reveal. |
| Month with no movements | (R25 + approved mockup) B/B' and C (current month) render first; A hidden. 32pt below the last card: "Todavía no hay movimientos en {mes}." 15 regular text.secondary, centered, then the existing Enviar (filled) / Recibir (outlined) pills. With no cards at all, today's vertically centered empty state is unchanged. |
| monthSummary error | (design review 10B) Today's full-screen "Reintentar" is unchanged; insight cards hidden until it succeeds. |
| Insights query error | B/B' and C hidden silently; A still renders from `monthSummary` (independent queries) |
| Masked balance | All amounts `MASK`; dots, bars and verdict wording stay (they leak no amounts). The explainer sheet's rate rows also show MASK (9A). |
| Old server (field unknown) | Insights live in **their own isolated query** with try/catch, so `monthSummary` never fails (feedback rule) |
| Month switch | Previous month's cards removed immediately (no stale cards on the new month) |

## 8. Copy (es, final)

| Key | Copy |
|---|---|
| a.positive | Te quedaron |
| a.zero | Quedaste a mano |
| a.negative | Salió más de lo que entró |
| b.title | Tu dólar te protegió |
| b.sentence | Tus {usd} hoy costarían {local} más. |
| b.paid / b.today | Pagaste / Hoy |
| b.how | ¿Cómo lo calculamos? (opens the D25 sheet) |
| sheet.title | ¿Cómo lo calculamos? |
| sheet.rows | Pagaste en promedio · Bs {r} por dólar / Confío hoy (compra de US$100) · Bs {r} por dólar / Cotización · hoy, {HH:mm} (rates 2 decimals, ramp separators) |
| sheet.body | Comparamos lo que pagaste por tus dólares con lo que costaría comprarlos hoy en Confío. |
| sheet.cta | Entendido |
| b2.title | Tu ahorro ganó |
| b2.amount / b2.caption | ~{usd with cents} / en {mes} (R23 estimate; 6A cents) |
| c.title | Pagos habituales |
| c.caption | casi cada mes / {categoría} · casi cada mes |
| c.more / c.less | +{n} más / Ver menos |
| d.less / d.same / d.more | personal: Vas bien: gastas menos que en {mes} / Vas parecido a {mes} / Vas gastando más que en {mes} · business (12B): Hasta hoy salió menos que a esta altura de {mes} / Hasta hoy salió parecido a {mes} / Hasta hoy salió más que a esta altura de {mes} |
| d.projection | A este ritmo, ~{usd} este mes · {mes} {usd} |

Month names are lowercase in sentences ("septiembre") and capitalized in the switcher.

## 9. Motion

- (design review 19A) One authored moment: Card A's result tick-settles on the first open of each month view (DESIGN.md signature). The insight region fades in once (opacity 0→1, 180ms ease-out) at the 8A reveal. Bars, track and sparkline render at final size, with no grow animation. Reduce Motion → no tick, no fade.
- Reduce Motion is read via `AccessibilityInfo.isReduceMotionEnabled`.

## 10. Engineering plan (summary; full review via /plan-eng-review)

**Server (`users/cashflow.py`, `users/cashflow_schema.py`):**
- `month_insights(user, account, ..., year, month, tz, now)` → `recurring: [RecurringPaymentType]`,
  `pace: PaceType | None`. Reuses `classify()` and the same UnifiedTransactionTable source as
  `summarize` (R1), so totals agree with Tu mes and the history list.
- New isolated GraphQL query `monthInsights(year, month, timezone)` with proper object types (no
  JSONString). It returns empty for employees.
- `protectionValue` gets its own isolated query (Decision 3 / R7 / R13 replay / R14 $100 quote: own lots vs Koywe/Infinia buy
  quote, 10-min cache, 2s timeout, fail closed, `TU_MES_PROTECTION_<CC>` flags ON for BO/VE (legal cleared 10-04)).
- Flags: `TU_MES_RECURRING_ENABLED`, `TU_MES_PACE_ENABLED` (settings, default ON for testnet).

**App:**
- `MonthSummaryScreen` gets `InsightCards` (A-D) as separate components in
  `apps/src/components/tuMes/`, plus the `useMonthInsights` hook (no-cache, request counter,
  month-switch guard as in `useMonthHeroLine`).
- Pure formatters/selectors in `apps/src/utils/monthInsights.ts` with unit tests.

**Tests:**
- Server: detection thresholds (±25% amount, ≤6-day spread, 2-of-3 months, wrap at month end,
  split payments, exclusions); pace verdict boundaries 0.9/1.1; projection with and without fixed
  payments; employee → empty; protection fail-closed paths.
- App: each card's visibility matrix, masked state, past vs current month, isolated query
  failure, a11y labels, 320pt layout.

**Open questions:**
1. ~~Legal/compliance sign-off for the protection card in BO and VE~~ **Approved by Julian 2026-10-04** (Decision 3(b) cleared): `TU_MES_PROTECTION_<CC>` defaults ON for BO and VE; it stays a kill switch.
2. Should Pagos fijos also detect recurring **income** (a salary)? Proposed: phase 2, as "Ingresos fijos" in Card A.

## Eng Review (/plan-eng-review, 2026-10-04)

Target: `docs/designs/tu-mes-insights.md` (this file). Builds on the approved ledger in
[cashflow-home-tu-mes.md](cashflow-home-tu-mes.md) (R1-R19); those approvals are cited, not re-asked.

### Scope record
feature answers: no cuts proposed (all 4 cards kept; founder approval 2026-10-04, legal cleared 2026-10-04);
structure: A) Original arrangement (D1 answer 2026-10-04);
accepted scope: apps/src/components/tuMes/{SummaryCard,ProtectionCard,RecurringCard,PaceCard}.tsx, apps/src/hooks/useMonthInsights.ts, apps/src/utils/monthInsights.ts; server users/cashflow.py month_insights(), users/protection.py (T4), users/cashflow_schema.py isolated queries;
pending remedies: Sections 1-4 findings (F2 → R20 approved, D2).

### Scope findings
1. [P1] (confidence: 9/10) §4 said "own on-ramp lots FIFO"; approved R13 (cashflow-home-tu-mes.md:819, D15) is a chronological replay, R14 a $100 quote. **Factual correction applied** (no behavior change).
2. [P2] (confidence: 9/10) The new spec omits approved D24/R8 (non-protection countries see "Tu ahorro ganó US$X"). → R20.
3. [P1] (confidence: 9/10) Card B depends on T4 (replay + quote + flag), which is not built (no protection module in users/ or ramps/). Sequencing only: T4 is its own lane.

## Decision ledger

### R20: Savings-earned slot for non-protection countries (D24)
Finding: Scope #2, P2, confidence 9/10, cashflow-home-tu-mes.md:628-636 (R8 approved via D24); cusd_plus/schema.py:881-883 hardcodes earned_month_usd=0.0. Reviewer Claude (plan-eng-review)
Plan baseline: approved D24 + R17/R19: "Tu ahorro ganó US$X en {mes}" in the protection slot for non-listed countries, gated on daily price+holding snapshots that are NOT built. New spec silently omits it.
Runtime evidence: no CusdPlusPriceSnapshot/CusdPlusHoldingSnapshot in the repo (grep 2026-10-04).
Comparison grid:
| Choice | Current | A | B | C |
|---|---|---|---|---|
| R20 savings slot | D24 approved, unbuilt, omitted from new spec | Keep D24 as Card B' and build R17/R19 snapshots in this plan | Keep D24 in the spec; slot renders nothing until a separate snapshot task ships | Drop D24 (reverses approval) |
| Card B protection rules | approved R7/R13/R14 | unchanged | unchanged | unchanged |
| Cards A, C, D | approved 2026-10-04 | unchanged | unchanged | unchanged |
Question D2:
D2 — What do non-protection countries see in the dollar-card slot?
Project/branch/task: main, Tu mes insights eng review; Card B (protection) itself is unchanged.
ELI10: In the earlier review you decided users outside Bolivia/Venezuela see "Tu ahorro ganó US$X este mes" where the protection card sits. The new spec forgot it. It needs a daily snapshot of the savings price and each user's shares, which isn't built, so today the number would be a fake 0.
Stakes if we pick wrong: Peru, Argentina, Colombia, Brazil and Mexico users (about 37% of MAU (224 of 600 on Oct 2)) get no second insight, or we ship a wrong earnings number.
Recommendation: A because the snapshot design is already approved (R17/R19) and the first real number needs a full month of snapshots, so starting the clock now matters.
Completeness: A=10/10, B=7/10, C=4/10
Pros / cons:
A) Build it now (recommended)
  ✅ Daily snapshots start today, so the first real "Tu ahorro ganó" shows next month
  ✅ Every country gets a second insight card, not only Bolivia and Venezuela
  ❌ Adds 2 models, a celery-beat task and tests (human: ~1.5d / CC: ~1.5h)
B) Keep, build later
  ✅ This plan stays smaller; the slot just stays empty outside BO/VE for now
  ❌ Every day without snapshots pushes the first real number further out
C) Drop it
  ✅ Least work; no snapshot task to run and monitor
  ❌ Reverses your D24 decision and leaves ~37% of users without the second card
Net: start the earnings clock now for a bit more work, or keep the plan lean and push the number out.
Header: Savings slot
Options:
A) Build it now (recommended)
Add CusdPlusPriceSnapshot + CusdPlusHoldingSnapshot and the daily task exactly as R17/R19; Card B' "Tu ahorro ganó US$X en {mes}" for non-protection countries, current month, hidden on null or < US$0.01. Card B rules unchanged.
B) Keep, build later
Spec keeps D24 as Card B'; nothing renders until a separate snapshot task (TODO) ships. Card B rules unchanged.
C) Drop it
Remove D24 from scope; non-protection countries see no second card. Card B rules unchanged.

State: approved
Actual answer: A) Build it now (recommended), D2 answer 2026-10-04
Accepted scope: CusdPlusPriceSnapshot(date unique, pps_wad, block_number) + CusdPlusHoldingSnapshot(account, date, shares, block) registered in confio_admin_site; daily celery-beat task reading at one pinned block (never `latest`, never the 1e18 fallback), skipping on failure; earned_month_usd = Σ days of shares_held(day−1) × (pps(day) − pps(day−1)), null on any missing day (R17/R19 exactly). Card B' "Tu ahorro ganó US$X en {mes}" for non-protection countries, current month only, hidden on null or < US$0.01 or savings disabled. Tests: deposit mid-month, failed read, missing day → null. Card B rules unchanged.
History: none

### R21: Which card fills the dollar slot when protection can't render
Finding: Arch #1, P1, confidence 9/10; `grep -rln VES ramps/` returns nothing (no Venezuelan on-ramp, so no lots, so Card B never renders in VE); R8/D24 shows B' only in "non-listed countries". Reviewer Claude (plan-eng-review)
Plan baseline: R8/D24 + R20: B' only for countries not in the protection list; BO/VE are listed (legal cleared 2026-10-04).
Runtime evidence: VE = 162 of 600 MAU (Oct 2). BO users who never on-ramped through Confío also have no lots.
Comparison grid:
| Choice | Current | A | B |
|---|---|---|---|
| R21 slot fallback | B' only in non-listed countries | One slot per account: show B when it renders, otherwise B' (any country, any reason: no lots, no quote, flag off, ≤ threshold) | Keep per-country: listed countries never see B' |
| Card B rules | approved R7/R13/R14 | unchanged | unchanged |
| R20 snapshots/B' | approved D2 | unchanged | unchanged |
Question D3:
D3 — When the protection card can't show, should the savings card take its place?
Project/branch/task: main, Tu mes insights eng review; protection math and the savings snapshots are already approved.
ELI10: Confío has no bolívar on-ramp, so no Venezuelan user has "dollars they bought in Confío", and the protection card can never appear for them. Bolivians who never bought dollars through Confío are in the same spot. Under today's rule, these users would see neither protection nor "Tu ahorro ganó", just an empty slot.
Stakes if we pick wrong: about 27% of MAU (all of Venezuela) gets the thinnest Tu mes, in the country where protection matters most.
Recommendation: A because it's one simple rule ("protection if we can prove it, savings otherwise"), so no user gets an empty slot.
Completeness: A=10/10, B=6/10
Pros / cons:
A) Fall back to savings (recommended)
  ✅ Every user with savings gets a second insight, including all of Venezuela
  ✅ One rule for every country: easy to test and reason about
  ❌ A Bolivian whose quote times out briefly sees the savings card instead
B) Keep per-country rule
  ✅ Exactly the earlier D24 wording, with no new behavior to test
  ❌ Venezuela never gets a second card until a bolívar on-ramp exists
Net: a universal fallback vs. a strict per-country split that leaves Venezuela empty.
Header: Slot fallback
Options:
A) Fall back to savings (recommended)
Single dollar slot: Card B when it renders; otherwise Card B' (savings earned) for any country and any reason B is hidden. B' keeps its own hide rules (null, < US$0.01, savings disabled).
B) Keep per-country rule
B' only in non-protection countries; BO/VE accounts without protection see no second card.

State: approved
Actual answer: A) Fall back to savings (recommended), D3 answer 2026-10-04
Accepted scope: Single dollar slot per account: Card B when it renders; otherwise Card B' (savings earned) for any country and any reason B is hidden (no lots, no quote, flag off, ≤ threshold, error, non-personal account). B' keeps its own hide rules (null, < US$0.01, savings disabled). Tests: VE account with savings → B'; BO account with lots + quote → B only; BO quote timeout → B'.
History: none

### R22: Protection card copy and the "¿Cómo lo calculamos?" sheet (D25 vs new mockup)
Finding: Arch #2, P2, confidence 9/10; cashflow-home-tu-mes.md:1204 (7C/D25 approved copy + explainer sheet) vs tu-mes-insights.md §4/§8 ("Tus {usd} hoy costarían {local} más.", no sheet). Reviewer Claude (plan-eng-review)
Plan baseline: D25: "Comprar hoy los US$X que compraste en Confío te costaría Bs N más." + "¿Cómo lo calculamos?" bottom sheet (average purchase rate vs today's Confío rate at the US$100 reference, quote time). The 2026-10-04 mockup approval showed the shorter sentence and no sheet.
Runtime evidence: n/a (neither is built).
Comparison grid:
| Choice | Current | A | B |
|---|---|---|---|
| R22 copy + explainer | D25 approved; new mockup differs | Headline from the new mockup ("Tus US$X hoy costarían Bs N más.") + keep D25's "¿Cómo lo calculamos?" link and sheet under the bars | New mockup only: short sentence, no sheet |
| Card B math / R21 fallback | approved | unchanged | unchanged |
Question D4:
D4 — Does the protection card keep the "¿Cómo lo calculamos?" explanation?
Project/branch/task: main, Tu mes insights eng review; the protection math and slot fallback are settled.
ELI10: You approved two versions of this card's words. The earlier one was longer ("Comprar hoy los US$X que compraste en Confío te costaría Bs N más") and had a "¿Cómo lo calculamos?" link that opens a sheet explaining the rates. Today's mockup has the shorter sentence and no link. A money claim like "+Bs 340" is the kind of number people question, so the explanation builds trust.
Stakes if we pick wrong: without it, users who doubt the number have nowhere to check it; with it, the card gets one more line.
Recommendation: A because it keeps the clean new headline and the trust link, which costs one caption line and a small sheet.
Completeness: A=9/10, B=6/10
Pros / cons:
A) Short headline + explainer (recommended)
  ✅ Keeps today's cleaner sentence, which matches the mockup you approved
  ✅ The "¿Cómo lo calculamos?" sheet shows purchase rate, today's rate and quote time
  ❌ One more line on the card, plus a bottom sheet to build and test
B) Mockup only, no sheet
  ✅ Exactly the approved mockup, so it's the least work
  ❌ Nobody can see how +Bs 340 was computed, which invites distrust
Net: a bit more UI for an auditable money claim vs. the leanest card.
Header: Explainer
Options:
A) Short headline + explainer (recommended)
Headline "Tus US$X hoy costarían Bs N más."; "¿Cómo lo calculamos?" link replaces the "Con la tasa de compra de Confío de hoy." caption and opens D25's sheet (average purchase rate, today's Confío rate at the US$100 reference, quote time).
B) Mockup only, no sheet
Headline "Tus US$X hoy costarían Bs N más." + caption "Con la tasa de compra de Confío de hoy."; no sheet (reverses D25's sheet).

State: approved
Actual answer: A) Short headline + explainer (recommended), D4 answer 2026-10-04
Accepted scope: Headline "Tus US$X hoy costarían Bs N más."; a "¿Cómo lo calculamos?" link (13pt, flowIn.textSmall, ≥44pt hit area) replaces the source caption and opens D25's bottom sheet: average purchase rate, today's Confío buy rate at the US$100 reference, quote time. Tests: link opens the sheet; sheet values match the query fields.
History: none

### Section 1: Architecture
- [P1] (confidence: 9/10) No VES on-ramp (`grep -rln VES ramps/` empty), so Card B never renders in VE. → R21, approved A (D3).
- [P2] (confidence: 9/10) Card B copy vs D25 (cashflow-home-tu-mes.md:1204). → R22, approved A (D4).
- [P2] (confidence: 9/10) users/cashflow_schema.py:87 `_summary_context` already enforces JWT context (`get_jwt_business_context_with_validation(info, required_permission='view_transactions')`), business ownership and owner-only. **Required:** monthInsights, protectionValue and savingsEarned resolvers reuse it (CLAUDE.md JWT rule); no new auth path. Carried as necessary implementation, no question.
- [P3] (confidence: 8/10) D26 (business title "El mes de {negocio}") still applies; nothing in this spec changes it. Carried forward.

```
            MonthSummaryScreen (year, month, tz)
   ┌────────────────┬──────────────────┼─────────────────┬────────────────────┐
   ▼                ▼                  ▼                 ▼                    ▼
monthSummary   monthInsights      protectionValue    savingsEarned       monthMovements
(existing)     (new, isolated)    (new, isolated)    (new, isolated)     (existing)
   │                │                  │                 │
   │ summarize()    │ month_insights() │ protection.py   │ cusd_plus snapshots
   │ current vs     │ 4-month rows →   │ R13 replay +    │ Σ shares(d−1)×Δpps
   │ comparison_    │ classify() raw   │ R14 $100 quote  │ null on missing day
   │ window()       │ keys → recurring │ (10-min cache,  │
   │ (same-day,     │ + projection     │ 2s, fail closed)│
   │ clamped)       │                  │                 │
   ▼                ▼                  ▼                 ▼
 Card A + Card D   Card C + Card D    Card B ──hidden?──► Card B' (R21 slot rule)
 verdict           projection
All resolvers: _summary_context() (JWT, owner-only, employees → None)
Each query fails alone: an error hides only its own card(s); Card A never waits on B–D.
```

### Section 2: Code quality
- [P2] (confidence: 9/10) users/cashflow.py:71 `comparison_window()` already computes "same day last month, clamped to the shorter month, same time of day", and `summarize()` returns it as `previous` with `partial`. **Card D's verdict uses monthSummary's existing current vs previous Salió**; monthInsights adds only the projection inputs. That's reuse of the approved behavior, so no new server query for the verdict. No question.
- [P2] (confidence: 9/10) users/cashflow.py:415 `_merge_unknown_wallets` collapses ≥2 unknown wallets into one 'external' entry for display. **Recurring detection must run on raw `counterparty_key`s before any merge**, or four different wallets would read as one "fixed payment". This is required correctness for the approved §5 rule.
- [P2] (confidence: 8/10) Fail-open risk (Confío's dominant defect class). month_insights must let `SummaryUnavailable` propagate. The resolver maps it to a GraphQLError and the app hides C/D. It must never return `recurring: []` / `pace: null` on bad monetary rows, because "no fixed payments" and "Vas bien" would be confident claims made from data we couldn't read. Required correctness.
- [P3] (confidence: 8/10) Holding snapshots reuse cusd_plus/gm_holdings.py's Multicall3 batching (250 balanceOf calls per eth_call), pinned to the snapshot block. No new RPC helper.

### Section 3: Tests
Framework: Django test runner (`AWS_PROFILE=Julian CONFIO_ENV=testnet myvenv/bin/python manage.py test <labels> --keepdb`) and jest (`npx jest --config jest.config.js` in apps/).

```
CODE PATHS                                              USER FLOWS
[+] users/cashflow.py month_insights()                  [+] Open Tu mes (current month)
  ├── [GAP] 2-of-3 months, ±25%, ≤6-day spread            ├── [GAP] A + B + C + D render in order
  ├── [GAP] wrap at month end (28→2), 31→Feb clamp        ├── [GAP] B hidden → B' fills slot (VE)
  ├── [GAP] split payment in one month summed             └── [GAP] all of B/B' hidden → no gap/shell
  ├── [GAP] exclusions (Recarga/Retiro/Ahorro/<US$1)    [+] Switch to a past month
  ├── [GAP] raw keys: 4 unknown wallets ≠ 1 payee         ├── [GAP] no D, no B/B', C shows paid dates
  ├── [GAP] SummaryUnavailable propagates (no [] )        └── [GAP] stale cards cleared on switch
  └── [GAP] projection = linear pace only (R24)        [+] Tap a fixed-payment row
[+] users/protection.py (T4)                              └── [GAP] opens MonthMovements filtered
  ├── [GAP] R13 replay (Codex counterexample → $0)      [+] "¿Cómo lo calculamos?"
  ├── [GAP] quote timeout/error → null                    └── [GAP] sheet shows rates + quote time
  ├── [GAP] ≤ threshold → null; non-personal → null     [+] Error states
  └── [GAP] flag off → null                               ├── [GAP] insights error → C/D hidden, A ok
[+] cusd_plus snapshots + earned_month_usd                ├── [GAP] protection error → B' shown
  ├── [GAP] pinned block, failed read → no row            └── [GAP] old server (unknown field) → A ok
  ├── [GAP] missing day → null (never 0.0)              [+] Masked balance
  └── [GAP] mid-month deposit accrues from next day       └── [GAP] all amounts MASK, bars/dots stay
[+] cashflow_schema resolvers
  ├── [GAP] employee → empty/None (all 3 new queries)
  └── [GAP] business owner → A, B' (if savings), C
[+] apps tuMes cards + useMonthInsights
  ├── [GAP] pace verdict boundaries 0.9 / 1.1, day<5 hidden, day<7 no projection
  ├── [GAP] Card A result states >0 / =0 / <0 (never red)
  └── [GAP] 320pt layout, a11y labels per card
[+] Empty month (R25): [GAP] B/B'/C render, A/D hidden, empty message below
COVERAGE: 0/37 paths tested (all new)  |  QUALITY target ★★★ for detection, replay, snapshots, slot rule
```

Regression contract (IRON RULE): existing MonthSummaryScreen behavior must keep its tests green:
summary card, Clasifica CTA, chips, Con quién, Entre tus cuentas and month switching
(apps/src/screens/__tests__ MonthSummary tests) plus users.test_cashflow. This is carried as required
proof of the approved R10-style contract. New cards are additive; no existing assertion changes.

### Section 4: Performance
- [P3] (confidence: 7/10) month_insights reads 4 months of the account's UnifiedTransactionTable rows on each Tu mes open. The scope is per account via `account_unified_queryset`, and indexes exist on (sender_user|counterparty_user, -created_at) (users/models_unified.py:295-302). Typical per-account volume is tens of rows/month (prod: 26 user→user sends in 90d platform-wide), so this is cheap. Scale beyond that is unknown; no cache needed now.
- [P3] (confidence: 8/10) Holding snapshots: one daily Multicall3 batch per 250 holders at a pinned block. Holder count is unknown here (verify in prod before deploy); a failed batch writes no rows for that day, so earnings go null instead of wrong.
- Protection quote: R7's 10-min cache per fiat currency already bounds quote traffic. No new finding.

Dispositions: Section 1 → R21 approved (D3), R22 approved (D4), JWT reuse + D26 carried. Section 2 → 4 required-correctness items carried (no questions). Section 3 → test gaps carried as required proof of approved behavior. Section 4 → no change.

### Outside voice (Codex, gpt-6-astra, completed)
1. [P1] Daily accrual misattributes a transfer/burn day's accrual (contracts/cusd_plus/CusdPlusVault.sol:764 `_update` allows transfers). → R23.
2. [P1] "Pagado" and "remaining expected payments" have no settlement rule (partial, unrelated transfers, overdue). → R24.
3. [P2] Wrap-aware detection vs ordinary median (28th and 2nd → 15th); installment date undefined. **Correction applied** (circular median, first payment day per month).
4. [P2] users/cashflow.py:71 `previous` is the comparable period only; the caption and eligibility need the full previous month, and a zero denominator is undefined. **Correction applied** (`previousMonthSpendingUsd`, zero rules).
5. [P2] apps/src/screens/MonthSummaryScreen.tsx:302 early-returns the empty state, hiding B/B'/C for movement-less months. → R25.

### R23: How exact is "Tu ahorro ganó" (reopens R19 on new evidence)
Finding: Outside voice #1, P1, confidence 8/10, contracts/cusd_plus/CusdPlusVault.sol:764 (`_update` permits transfer/mint/burn with no accrual hook). Reviewer Codex (outside voice), verified by Claude.
Plan baseline: R19 (D4 2nd pass) + R20 (D2): earned = Σ days shares_held(day−1) × (pps(day) − pps(day−1)); copy "Tu ahorro ganó US$X en {mes}" (exact).
Runtime evidence: a withdrawal or transfer during day d is still credited with day d's price change; a deposit during day d gets none. Error per move ≤ one day's yield on the moved amount (≈0.014% at 5% APY). Reason for reopening: new evidence, not a preference change.
Comparison grid:
| Choice | Current | A | B | C |
|---|---|---|---|---|
| R23 earnings exactness | R19 daily accrual, exact wording | Keep R19 math; copy says "~US$X" (approximate) | Switch to balance-difference: shares_now×pps_now − shares_open×pps_open − net savings flows from the unified ledger (null if flows unknown); exact wording | Keep R19 math and exact wording |
| R20 snapshots, R21 slot | approved | unchanged | unchanged (snapshots still needed for opening shares/price) | unchanged |
Question D5:
D5 — Is "Tu ahorro ganó US$X" an exact number or an estimate?
Project/branch/task: main, Tu mes insights eng review; snapshots and the slot fallback are settled.
ELI10: We planned to compute savings earnings from one daily photo of each user's savings. If someone withdraws or deposits during a day, that day's tiny gain lands on the wrong side, about a cent per US$100 moved. Small, but the card says "ganó" as a fact, and Confío's rule is that money numbers are exact.
Stakes if we pick wrong: either a number that is slightly off but presented as exact, or a heavier calculation that can fail more often.
Recommendation: A because the error is at most one day's yield on moved money, and "~" tells the truth with no new machinery.
Completeness: A=8/10, B=10/10, C=5/10
Pros / cons:
A) Keep math, show "~US$X" (recommended)
  ✅ No new computation, and the copy is honest that it's an estimate
  ✅ Keeps the earlier R19 choice to avoid matching deposits and withdrawals
  ❌ "~" on a money number is slightly less satisfying than an exact figure
B) Exact via ledger flows
  ✅ An exact figure: start value plus deposits minus withdrawals, compared with today's value
  ❌ Depends on every savings move being in the ledger; any gap hides the card (human: ~1d / CC: ~1h)
C) Keep as approved
  ✅ No change at all to the approved plan
  ❌ Shows an estimate as an exact fact, which breaks the exact-numbers rule
Net: an honest estimate today vs. an exact figure that depends on complete savings-flow records.
Header: Earnings
Options:
A) Keep math, show "~US$X" (recommended)
R19 daily-accrual formula unchanged; copy "Tu ahorro ganó ~US$X en {mes}" and a11y "alrededor de X dólares". Snapshots (R20) and slot rule (R21) unchanged.
B) Exact via ledger flows
earned = shares_now×pps_now − shares_at_month_start×pps_first_snapshot − net savings deposits in month from UnifiedTransactionTable; null when any flow or snapshot is missing; exact copy. Supersedes R19's formula; snapshots kept.
C) Keep as approved
R19 formula with exact "ganó US$X" copy, unchanged.

State: approved
Actual answer: A) Keep math, show "~US$X" (recommended), D5 answer 2026-10-04
Accepted scope: R19 daily-accrual formula unchanged; Card B' copy "Tu ahorro ganó ~US$X en {mes}", a11y "alrededor de X dólares". R20 snapshots and R21 slot rule unchanged.
History: R19 approved daily accrual (D4 2nd pass); R20 approved building it (D2).

### R24: When a fixed payment counts as paid, and what the projection adds
Finding: Outside voice #2, P1, confidence 9/10, tu-mes-insights.md §5 ("Pagado ✓", "remaining expected Pagos fijos") with no settlement rule. Reviewer Codex (outside voice), verified by Claude.
Plan baseline: §5/§6 as approved 2026-10-04 (paid pill; projection adds remaining expected fixed payments), rule undefined.
Runtime evidence: n/a (unbuilt). Per-payee monthly sums are already how occurrences are defined (§5 correction #3).
Comparison grid:
| Choice | Current | A | B |
|---|---|---|---|
| R24 settlement rule | undefined | This month's sum to the payee ≥ 75% of expected → "Pagado ✓"; projection adds max(expected − paid so far, 0) for every detected payee (partial payments count, nothing double-counted); past the expected day unpaid → pill keeps the date in neutral gray (no "late" wording) | Remove "Pagado" and fixed-payment forecasting; projection = linear pace only; pill always shows the expected date |
| Detection rule (§5) | approved + correction #3 | unchanged | unchanged |
Question D6:
D6 — How does a fixed payment count as "paid" this month?
Project/branch/task: main, Tu mes insights eng review; the detection rule is settled.
ELI10: If Karen's rent is ~US$100 and you've sent her US$40 so far this month, is the rent paid? The plan shows "Pagado ✓" and adds unpaid rent to the month forecast, but never said how partial payments work. Without a rule, the forecast either forgets the remaining US$60 or counts the US$40 twice.
Stakes if we pick wrong: a wrong forecast ("A este ritmo ~US$440") or a "Pagado" badge on rent that isn't fully paid.
Recommendation: A because it uses the same monthly totals the detector already computes, and counting what's left (US$60) can't double-count.
Completeness: A=9/10, B=6/10
Pros / cons:
A) Paid at 75%, count the rest (recommended)
  ✅ US$40 of US$100 sent → forecast adds the remaining US$60, never US$100 again
  ✅ Rent paid in two parts still turns "Pagado ✓" once 75% has gone out
  ❌ Unrelated transfers to the same person also count toward "paid"
B) Drop paid status and forecasting
  ✅ No settlement rules to get wrong; the card only shows dates and amounts
  ❌ Forecast ignores known rent, so it swings wildly around big payments
Net: a smarter forecast with one simple threshold vs. a dumber but rule-free card.
Header: Paid rule
Options:
A) Paid at 75%, count the rest (recommended)
Paid when this month's sum to the payee ≥ 75% of expected; projection adds max(expected − paid so far, 0) per detected payee; unpaid past the expected day keeps the date pill in neutral gray (no "late" copy).
B) Drop paid status and forecasting
No "Pagado" pill and no fixed-payment term in the projection (linear pace only); the pill always shows the expected date.

State: approved
Actual answer: B) Drop paid status and forecasting, D6 answer 2026-10-04
Accepted scope: No "Pagado" pill; the pill always shows the expected date (current month: next expected date; past months: that month's expected date). Card D projection = linear pace only: Salió to date ÷ days elapsed × days in month, shown from day 7, whole dollars with "~". No fixed-payment term anywhere.
History: none

### R25: Insight cards on a month with no movements
Finding: Outside voice #5, P2, confidence 9/10, apps/src/screens/MonthSummaryScreen.tsx:302 `if (isEmpty) { return (<View ... testID="month-summary-empty">` early-returns before any card; spec §7 "Month with no movements → existing empty state; no insight cards". Reviewer Codex (outside voice), verified by Claude.
Plan baseline: §7 as approved 2026-10-04: no insight cards when the month has no movements.
Runtime evidence: the early return exists today. Savings earnings (B'), protection (B) and expected fixed payments (C, current month) don't depend on this month's movements.
Comparison grid:
| Choice | Current | A | B |
|---|---|---|---|
| R25 empty-month behavior | whole screen = empty state | Cards B/B' and C (current month) render independently of movements; the empty message + Enviar/Recibir pills move into the movements area; Card A and D hidden when there are no movements | Keep the early return: no cards on empty months |
| R21 slot rule, R24 pill rule | approved | unchanged | unchanged |
Question D7:
D7 — Should a month with no movements still show protection, savings and fixed payments?
Project/branch/task: main, Tu mes insights eng review; card rules are settled.
ELI10: Today, if you haven't moved money this month, Tu mes shows only "Todavía no hay movimientos". But someone who just holds savings still earned something, a dollar holder is still protected, and rent due on the 5th is still coming. Hiding those cards hides the reasons to open Tu mes for quiet users.
Stakes if we pick wrong: early in the month (days 1-5) and for passive savers, Tu mes looks empty even though we have something real to show.
Recommendation: A because those three cards don't depend on this month's movements, and quiet savers are the users most likely to churn.
Completeness: A=9/10, B=6/10
Pros / cons:
A) Show cards, empty state below (recommended)
  ✅ A saver opening Tu mes on the 2nd still sees "Tu ahorro ganó ~US$X" and upcoming rent
  ✅ The empty message and Enviar/Recibir stay, just lower on the screen
  ❌ One more screen layout to test (empty movements with cards above)
B) Keep the empty screen
  ✅ No change to today's empty state or its tests
  ❌ Quiet users and the first days of each month always see an empty Tu mes
Net: show what we know even without movements vs. keep the simpler empty screen.
Header: Empty month
Options:
A) Show cards, empty state below (recommended)
Cards B/B' and C (current month) render regardless of movements; Card A and D are hidden when the month has no movements; the "Todavía no hay movimientos" message and Enviar/Recibir pills move below the cards.
B) Keep the empty screen
Keep the early return; no insight cards on months without movements.

State: approved
Actual answer: A) Show cards, empty state below (recommended), D7 answer 2026-10-04
Accepted scope: Remove the MonthSummaryScreen early return as the whole screen; Cards B/B' and C (current month) render regardless of movements; Cards A and D are hidden when the month has no movements; "Todavía no hay movimientos en {mes}." + Enviar/Recibir pills render below the cards. Tests: empty month with savings → B' + empty message; empty month without anything → only the empty message (unchanged look).
History: none

Approval readiness: PASS. Checked R20 (D2), R21 (D3), R22 (D4), R23 (D5), R24 (D6), R25 (D7), TODO (D8); scope record D1. Carried without new questions: prior R7/R13/R14 (T4), R17/R19 (snapshot storage, via R20), D25 sheet (via R22), D26 business title, R10-style regression contract.

## Eng Review Output

### NOT in scope
- "Ingresos fijos" (recurring income): deferred to TODOS.md (D8); needs a design pass.
- Paid status and fixed-payment forecasting: dropped (D6, R24). The projection is linear pace only.
- Month-end protection snapshots for past months: Card B is current-month only (§4). No snapshot of protection is kept.
- A bolívar on-ramp: VE protection needs one. Out of scope; VE users get B' via R21.

### What already exists
- `users/cashflow.py`: `summarize()`, `classify()`, `comparison_window()` (same-day previous period, clamped) and `_merge_unknown_wallets()`. Reused: Card D's verdict uses `summarize`'s `previous`; detection runs on raw keys before the merge.
- `users/cashflow_schema.py:87` `_summary_context()`: JWT, owner-only, employees → None. Reused by all three new resolvers.
- `cusd_plus/gm_holdings.py`: Multicall3 batching (250 calls). Reused for holding snapshots.
- `ramps/koywe_client.py:489` `create_preview_quote(... executable False, auth=False)`: the protection quote (R7/R14).
- `apps/src/hooks/useMonthHeroLine.ts`: no-cache, request counter and month-switch guard pattern for `useMonthInsights`.
- Rebuilt: nothing. New: month_insights(), protection module (T4), cUSD+ snapshots, 4 card components + hook + utils.

### Failure modes
| Path | Realistic failure | Handling | User sees | Test |
|---|---|---|---|---|
| monthInsights | a bad monetary row → SummaryUnavailable | propagates → GraphQLError; C/D hidden | Card A + sections, no C/D (no wrong claim) | yes (§Tests) |
| protectionValue | Koywe quote timeout (2s) | null (R7 fail closed) → B' fallback (R21) | savings card instead | yes |
| savingsEarned | BSC RPC down at snapshot time | no row that day → null | card hidden (never US$0) | yes |
| holding snapshots | a Multicall batch reverts | 3 retries at the pinned block; still failing → those account ids recorded on the day row → only they get null for the month (R28) | card hidden for those accounts only | yes |
| app isolated queries | old server: unknown field | per-query try/catch | Card A unaffected | yes |
| recurring detection | 4 unknown wallets merged | detection on raw keys | no false "fixed payment" | yes |
Critical gaps (no test + no handling + silent): 0.

### Worktree parallelization strategy
| Step | Modules touched | Depends on |
|---|---|---|
| S1 month_insights + monthInsights query | users/ | — |
| S2 protection (T4) + protectionValue query | users/, ramps/, config/ | — |
| S3 cUSD+ snapshots + savingsEarned query | cusd_plus/, config/ (celery beat) | — |
| S4 app cards + hook + utils | apps/ | S1–S3 GraphQL contracts (field names only) |
Lane A: S1. Lane B: S2. Lane C: S3. Lane D: S4 against the agreed schema; integrate last.
Execution order: launch A + B + C; D can start from the schema contract; merge A–C, then D.
Conflict flags: `users/cashflow_schema.py` (S1, S2, S3 all add resolvers) and `config/settings.py` (S2 flags, S3 beat). Sequence those edits or give them one owner. Per "Always main", run lanes sequentially in one tree when concurrent sessions share the index.

## Implementation Tasks
Synthesized from this review's findings. Each task derives from a specific finding above. Run with Claude Code or Codex; checkbox as you ship.

- [ ] **T1 (P1, human: ~2d / CC: ~2h)** — users — month_insights() + monthInsights isolated query
  - Surfaced by: §5 detection; Section 2 (raw keys, fail-open); outside voice #3/#4 corrections
  - Files: users/cashflow.py, users/cashflow_schema.py, users/test_cashflow.py
  - Verify: `AWS_PROFILE=Julian CONFIO_ENV=testnet myvenv/bin/python manage.py test users.test_cashflow --keepdb` (2-of-3, ±25%, ≤6-day circular spread, 28→2 wrap, split month sum, exclusions, 4 wallets ≠ 1 payee, SummaryUnavailable propagates, previousMonthSpendingUsd, employee → empty)
- [ ] **T2 (P1, human: ~3d / CC: ~4h)** — protection — T4 (R7/R13/R14) + protectionValue query + D25 sheet fields
  - Surfaced by: Scope #3; R22 (D4)
  - Files: users/protection.py (new), users/cashflow_schema.py, config/settings.py (TU_MES_PROTECTION_BO/VE ON)
  - Verify: Codex counterexample replay → $0; quote timeout → null; ≤ threshold → null; flag off → null; sheet fields present
- [ ] **T3 (P1, human: ~1.5d / CC: ~1.5h)** — cusd_plus — R20 snapshots + savingsEarned query (R23 "~" copy)
  - Surfaced by: R20 (D2), R23 (D5), Section 4
  - Files: cusd_plus/models.py (+migration), cusd_plus/tasks.py, config/settings.py (beat), config/admin_dashboard.py, users/cashflow_schema.py
  - Verify: pinned block (no `latest`), failed read → no row, missing day → null, deposit mid-month; check prod cUSD+ holder count before deploy
- [ ] **T4 (P1, human: ~3d / CC: ~3h)** — apps — tuMes cards A, B, B', C, D + slot rule + sheet + empty month
  - Surfaced by: §1–§9; R21 (D3), R22 (D4), R24 (D6), R25 (D7)
  - Files: apps/src/components/tuMes/{SummaryCard,ProtectionCard,RecurringCard,PaceCard}.tsx, apps/src/hooks/useMonthInsights.ts, apps/src/utils/monthInsights.ts, apps/src/apollo/monthSummary.ts, apps/src/screens/MonthSummaryScreen.tsx
  - Verify: `npx jest --config jest.config.js` (visibility matrix, slot fallback, pace 0.9/1.1 + zero rules, day<5/<7, masked, past vs current, empty month, isolated query failure, a11y, 320pt) + existing MonthSummary tests unchanged
- [ ] **T5 (P2, human: ~30m / CC: ~5m)** — docs — DESIGN.md decisions-log entry for Tu mes insights (card system, slot rule, no-red rule)
  - Surfaced by: R21/R22/R24 design-visible decisions
  - Files: DESIGN.md
  - Verify: entry present, tokens match theme.ts

_No new tasks from Performance review._

### Suppressed findings (appendix)
- none below confidence 5.

### Unresolved decisions that may bite you later
- none in this review.

### Completion summary
- Step 0: Scope Challenge — scope accepted as-is (no cuts; D1 Original arrangement; F2 → R20 restores approved D24)
- Architecture Review: 4 issues found
- Code Quality Review: 4 issues found
- Test Review: diagram produced, 37 gaps identified (all new code; regression contract carried)
- Performance Review: 2 issues found (no change)
- NOT in scope: written
- What already exists: written
- TODOS.md updates: 1 item proposed to user (added, D8)
- Failure modes: 0 critical gaps flagged
- Unresolved decisions: 0 in this review
- Outside voice: codex (gpt-6-astra), completed (5 findings: 2 corrections applied, 3 decided via D5–D7)
- Parallelization: 4 lanes, 3 parallel / 1 sequential
- Lake Score: 2/6 = answers picking a 10/10 option / answers scored for Completeness (D2, D3 yes; D4, D5, D6, D7 no)

## Design Review (/plan-design-review, 2026-10-04)

Target: this file. DESIGN.md calibrated; classification OPERATE (app UI). Outside voices: Codex (gpt-6-astra) + Claude subagent, both completed.

### Approved Mockups

| Screen/Section | Mockup Path | Direction | Notes |
|----------------|-------------|-----------|-------|
| Tu mes, current month + quiet month (build reference) | /Users/julian/.gstack/projects/caesar4321-Confio/designs/tu-mes-new-states-20261004/final-spec.png | Hero card with pace line, dollar slot, Pagos habituales, empty month | Spec wins on track labels (ends only, 15A) |
| Savings card B' + explainer sheet + empty month | /Users/julian/.gstack/projects/caesar4321-Confio/designs/tu-mes-new-states-20261004/variant-A.png | Big ~US$ number + daily bars; sheet = 3 rows + sentence + Entendido | Caption "en {mes}" (no "protegido"); number 28pt (3A) |
| Earlier approval (four cards) | /Users/julian/.gstack/projects/caesar4321-Confio/designs/tu-mes-insights-20261004/spec-A.png | Superseded where the decisions below differ | Card D folded into A (2A) |

### Design decisions (this review)
| # | Decision | Answer |
|---|---|---|
| 1 | Hero label | 1A keep "Te quedaron" + restore "Sin contar recargas, retiros ni ahorro." |
| 2 | Pace card | 2A fold into Card A (no calendar bar) |
| 3 | B' size | 3A 28pt; only the hero is 34pt |
| 4 | Business B' | 4A same slot rule |
| 5 | Sparkline | 5A dailyUsd[], <3 days number only, masked bars stay |
| 6 | Precision | 6A cents on B' only |
| 7 | Pill date | 7A viewed month's day, past days grey (supersedes R24 next-date) |
| 8 | Loading | 8A reveal together ≤800ms, silent refocus |
| 9 | Sheet | 9A snapshot of the card's quote |
| 10 | Summary error | 10B full-screen retry unchanged |
| 11 | More rows | 11A expand in place |
| 12 | Pace copy | 12B warm personal, plain business (accepted contradiction risk) |
| 13 | Icon chips | 13A bare glyph |
| 14 | Card chrome | 14A hairline only |
| 15 | Day track | 15A keep, end labels only |
| 16 | Card name | 16B "Pagos habituales" / "casi cada mes" |
| 17 | Header contrast | 17A keep app convention; app-wide TODO added |
| 18 | Tokens | 18A map to real tokens (+ colors.compareNeutral) |
| 19 | Motion | 19A tick-settle on hero only |
| 20 | Screen reader | 20A group text, expose every action, masked "oculto" |
| 21 | Font scale | 21A grow and wrap to 1.6×, hero min 0.85, 44pt hit areas |
| 22 | Narrow rows | 22A truncate name, amount never shrinks |
| 23 | Past months | 23A B' on past months with full snapshots |

Not adopted: Codex P3 "brand identifier in the header". Every app screen shares this header, so it isn't a Tu mes gap.

### Journey storyboard
```
STEP | USER DOES                     | USER FEELS                 | PLAN SPECIFIES
1    | Opens Tu mes (5 sec)          | "How did my month go?"     | A: one 34pt result + honest caption
2    | Reads the dollar slot         | Reassured / rewarded       | B (protection + sheet) or B' (~US$0,42 + bars)
3    | Scans habitual payments       | "What's coming?"           | C: track + day pills, past days grey
4    | Reads the pace line (5 min)   | Informed (personal: encouraged) | A's pace line (12B)
5    | Optional: classifies payments | Low-stakes homework        | existing CTA
6    | Over months (5 years)         | "Confío keeps my dollars safe" | protection + monthly savings history (23A)
```

### NOT in scope (design)
- App-wide header contrast: TODOS.md (17A).
- Past-month protection: needs month-end snapshots; Card B stays current-month only.

### What already exists
DESIGN.md (hero field, money in/out tokens, tick-settle), theme.ts (`surface`, `border`, `flowIn`/`flowOut`, `onHeroField`), the shared Header (`isLight`, 47 screens), MonthSummaryScreen's "Con quién" truncation, MASK handling and `money()` whole-dollar rule (B' is the one recorded exception, 6A).

### TODOS.md updates
1 item added: app-wide header contrast (from approved decision 17A). No other deferred design debt.

## Design Implementation Tasks
- [ ] **DT1 (P1, human: ~1d / CC: ~1h)** — apps — Card A: result, "Sin contar" caption, pace line (12B copy), tick-settle (1A, 2A, 12B, 19A)
  - Files: apps/src/components/tuMes/SummaryCard.tsx (PaceCard folded in), apps/src/screens/MonthSummaryScreen.tsx
  - Verify: jest (personal vs business copy, day <5 / <7, masked)
- [ ] **DT2 (P1, human: ~1d / CC: ~1h)** — apps — B' anatomy: 28pt cents number, daily bars, <3-day rule, past months (3A, 5A, 6A, 23A) + server dailyUsd[]
  - Files: apps/src/components/tuMes/ProtectionCard.tsx (B'), users/cashflow_schema.py savingsEarned, cusd_plus snapshots
  - Verify: jest + Django test (dailyUsd length, missing day → null)
- [ ] **DT3 (P1, human: ~4h / CC: ~30m)** — apps — Pagos habituales: rename, day-of-month pills, grey past days, end-only track labels, expand in place, narrow rows (7A, 11A, 15A, 16B, 22A)
  - Files: apps/src/components/tuMes/RecurringCard.tsx
  - Verify: jest (pill = viewed month, sort by day, +N más / Ver menos, 320pt)
- [ ] **DT4 (P1, human: ~4h / CC: ~30m)** — apps — Reveal-together loading, silent refocus, full-screen error kept (8A, 10B)
  - Files: apps/src/hooks/useMonthInsights.ts, MonthSummaryScreen.tsx
  - Verify: jest (late query dropped, sections below never move, refocus no re-fade)
- [ ] **DT5 (P1, human: ~3h / CC: ~20m)** — apps — Card chrome + tokens (13A, 14A, 18A) and colors.compareNeutral in theme.ts
  - Files: apps/src/config/theme.ts, tuMes cards
  - Verify: grep for raw hex in tuMes = 0
- [ ] **DT6 (P1, human: ~1d / CC: ~1h)** — apps — Accessibility + font scale (20A, 21A)
  - Files: tuMes cards, MonthSummaryScreen month buttons
  - Verify: jest a11y labels (separate buttons, masked "oculto"), fontScale 1.6 stacked layout
- [ ] **DT7 (P2, human: ~2h / CC: ~15m)** — apps — Explainer sheet as a snapshot of the card's quote (9A)
  - Files: apps/src/components/tuMes/ProtectionCard.tsx
  - Verify: jest (no fetch on open, masked rows)

### Design completion summary
```
  +====================================================================+
  |         DESIGN PLAN REVIEW — COMPLETION SUMMARY                    |
  +====================================================================+
  | System Audit         | DESIGN.md present; UI scope: Tu mes cards   |
  | Step 0               | 7/10 initial impression; all 7 dimensions   |
  | Pass 1  (Info Arch)  | 6/10 → 9/10 after fixes                     |
  | Pass 2  (States)     | 5/10 → 9/10 after fixes                     |
  | Pass 3  (Journey)    | 6/10 → 8/10 (12B accepted risk)             |
  | Pass 4  (AI Slop)    | 6/10 → 8/10 after fixes                     |
  | Pass 5  (Design Sys) | 6/10 → 8/10 (header contrast app-wide TODO) |
  | Pass 6  (Responsive) | 6/10 → 9/10 after fixes                     |
  | Pass 7  (Decisions)  | 1 resolved, 0 deferred                      |
  +--------------------------------------------------------------------+
  | NOT in scope         | written (2 items)                           |
  | What already exists  | written                                     |
  | TODOS.md updates     | 1 item (from approved 17A)                  |
  | Approved Mockups     | 5 generated, 2 approved                     |
  | Decisions made       | 23 added to plan                            |
  | Decisions deferred   | 0                                           |
  | Overall design score | 5/10 → 8/10                                 |
  +====================================================================+
```
Plan is design-complete. Run /design-review after implementation for visual QA.

### Unresolved Decisions
- none.

## Eng Review, delta pass (/plan-eng-review, 2026-10-04)

Target: this file. Delta: design decisions 2A, 5A, 7A, 8A, 23A. Scope: D1 Original arrangement still holds, minus PaceCard.tsx (folded into SummaryCard.tsx by 2A); no new services.

### Delta findings
1. [P1] (confidence: 9/10) R20 + 23A: holding rows exist only for current holders, so any zero-share day reads as "missing" and hides the card for the month. → R26 (D1 delta) approved A.
2. [P2] (confidence: 9/10) 8A (≤800ms reveal) vs R7 (2s cold quote): protection flickers with B' after each 10-min cache expiry. → R27 (D2 delta) approved A.
3. [P2] (confidence: 9/10) 2A + 8A: Card A's pace line needs `previousMonthSpendingUsd` from monthInsights. **Required correction:** the pace line belongs to the 8A reveal group. Card A renders its result first and the pace line is revealed with the cards, so nothing moves.
4. [P3] (confidence: 9/10) Contract corrections: `savingsEarned(year, month)` → `{earnedUsd, dailyUsd: [{date, usd}]}` (days sum to the total; null under the R26 rule) for 5A/23A. monthInsights recurring items return `expectedDay` + `expectedAmountUsd`; the app derives 7A's pill text and past-day grey state from the account timezone.
5. R24's pill rule ("next expected date") is superseded by design 7A (history kept in R24).

### R26: Zero-share days vs missing snapshots
State: approved
Actual answer: A) Run-complete marker (recommended), D1 (delta) answer 2026-10-04
Accepted scope: CusdPlusPriceSnapshot gains `complete` (bool), set true only after every holder batch for that pinned block succeeded. On a complete day, no holding row = 0 shares; an incomplete or absent day → earned null → card hidden. Tests: partial batch failure leaves complete=false; a zero-share day mid-month still yields a number.

### R27: Protection quote freshness vs the 800ms reveal
State: approved
Actual answer: A) Warm quotes in background (recommended), D2 (delta) answer 2026-10-04
Accepted scope: Celery beat refreshes the R14 $100 buy quote for each enabled protection currency every 8 min into the R7 cache (TTL 10 min); the protectionValue resolver only reads the cache; a miss = hidden (fail closed) → B' per R21. Currencies without an on-ramp quote (e.g. VES today) simply stay empty. Test: cache miss → B hidden, B' shown; warm task failure leaves the previous value until TTL.

### Delta tasks (amend T2, T3, T4)
- T2 += R27 warm-quote beat task (protection lane; settings beat entry).
- T3 += R26 `complete` flag + dailyUsd[] + savingsEarned(year, month) for past months (23A).
- T4 += pace line in the reveal group; pill/grey derivation from expectedDay (7A); PaceCard.tsx removed (2A).

Approval readiness (delta): PASS. R26 (D1 delta), R27 (D2 delta); corrections 3-5 carry approved behavior.

### Outside voice, delta (Codex gpt-6-astra, completed)
1. [P1→P3 after verification] R27 needs a shared cache. Prod has `USE_REDIS_CACHE=True` (.env.mainnet:114); testnet/local default to LocMem (config/settings.py:511). **Correction:** the warm task runs only when the cache backend is Redis; otherwise the resolver does a bounded live fetch (dev only). T2 asserts this.
2. [P2] Snapshot boundaries. **Correction:** day d's accrual = shares(d−1) × (pps(d) − pps(d−1)) and is labeled date d; the first day of a month needs the previous day's snapshot (so the first eligible month is the first full month after deploy); `dailyUsd` contains completed days only (today appears after its snapshot completes).
3. [P2] One failed batch hides everyone. → R28 (D3 delta) approved A.
4. [P2] 800ms timer vs monthSummary. **Correction:** the 800ms window starts when monthSummary has rendered Card A; until then the screen shows today's loading state. The pace line, cards and lower sections reveal together at the end of the window.
5. [P2] Refocus vs frozen layout. **Correction:** a refocus refetch updates values inside cards already shown but never adds, removes or swaps a card or row; structural changes wait for the next view (month switch or screen re-entry).
6. [P2] Past empty months. **Correction:** 23A wins over R25's current-month wording. A past month with no movements still shows B' when that month's snapshots are complete; the test expectation "past month: no B/B'" becomes "past month: B' if complete, never B".
7. [P2] 7A on past months. **Correction:** a pill is grey when its full expected date is before today in the query's resolved timezone (the same `tz` as monthSummary), so every pill on a past month is grey.

### R28: Blast radius of a failed snapshot batch (amends R26)
State: approved
Actual answer: A) Retry + mark failed accounts (recommended), D3 (delta) answer 2026-10-04
Accepted scope: Each holder batch retries 3× at the same pinned block within the run; account ids still failing are stored on the day's CusdPlusPriceSnapshot row (`failed_account_ids`). Those accounts get earned = null for that month; everyone else computes normally. A day with no price snapshot at all stays null for everyone. Tests: one batch failing after retries → only its accounts null; retry success → no ids recorded.

Approval readiness (delta, final): PASS. R26 (D1), R27 (D2), R28 (D3); corrections 1-7 carry approved behavior.
Delta completion: scope unchanged (D1 arrangement minus PaceCard.tsx); 5 delta findings + 7 outside-voice findings (6 corrections, 1 decision); 0 critical gaps; 0 unresolved.

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 1 | not run for this plan | — |
| Outside Review | codex-plan-review (eng ×2) + design-outside-voices (codex) | Independent 2nd opinion | 5 + 1 | completed, issues_found | eng: 5 + 7 findings (8 corrections, 4 decisions); design: 10 findings folded into design decisions 1–23 |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 8 | clean (delta: 0 unresolved, 0 critical gaps) | 12 issues, 0 critical gaps |
| Design Review | `/plan-design-review` | UI/UX gaps | 3 | clean | score: 5/10 → 8/10, 23 decisions |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | — | — |

- **OUTSIDE COVERAGE:** codex plan-review completed twice (full + delta), codex design phase completed; all findings resolved by corrections or decisions.
- **CROSS-MODEL:** Codex caught the snapshot-boundary, cache-sharing and reveal-lifecycle gaps; Claude caught the zero-share/missing-day ambiguity and the quote-vs-reveal flicker. Both agreed the reveal needs a defined start and a frozen structure.
- **VERDICT:** ENG + DESIGN CLEARED — ready to implement (T1–T5 + DT1–DT7, with delta amendments).

NO UNRESOLVED DECISIONS
