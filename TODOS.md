# TODOs

Project-level deferred work captured by /plan-eng-review. Each entry includes context so it can be picked up cold.

## Open

### App-wide header contrast (white title on mint)
**Source:** plan-design-review on 2026-10-04 (Tu mes insights, design review 17A)

**What:** Switch the shared Header's `isLight` title and back icon on `colors.heroField` (#34D399) from white to `colors.onHeroField` (#064E3B) across all 47 screens that use it.

**Why:** White on #34D399 is 1.9:1 (DESIGN.md "Hero field"), below the 3:1 large-text minimum. Hard to read outdoors and for low-vision users.

**Pros:**
- One change fixes every mint header consistently
- Matches the status-bar rule already in DESIGN.md (dark icons on the field)

**Cons:**
- Visible change on 47 screens; needs a quick visual pass (screenshots) before release
- Website screenshots showing the header may need refreshing

**Context:** Tu mes kept the convention on purpose so it doesn't differ from the other screens. Start in `apps/src/components/` Header (`isLight` prop) and grep `isLight` under `apps/src/screens`.

**Depends on / blocked by:** nothing; a /design-review screenshot pass after the change.

### "Ingresos fijos": detect recurring income in Tu mes
**Source:** plan-eng-review on 2026-10-04 (Tu mes insights, D8)

**What:** Run the Pagos fijos detector (`month_insights()` in `users/cashflow.py`: ≥2 of the 3 previous months, ±25% amount, ≤6-day circular spread) on inbound Entró rows to find a salary or a family remittance ("Tu sueldo llega cada día 1").

**Why:** Pagos fijos answers "when does money leave". The matching question, "when does my money arrive", matters most to remittance receivers in VE/BO.

**Pros:**
- Reuses the detector and its tests; small server change
- Pairs with Card A ("Entró") naturally

**Cons:**
- Needs its own small design pass (where it lives: Card A line vs. a Card C section)
- Same partial-transfer ambiguity Pagos fijos avoided by dropping "paid" status (R24)

**Context:** Spec `docs/designs/tu-mes-insights.md` open question 2. Start from the detector's test table and add inbound cases.

**Depends on / blocked by:** Tu mes insights (month_insights detector) shipped; a /plan-design-review pass for placement.

### Negative-feedback Slack alert (admin notification)
**Source:** plan-eng-review on 2026-05-15 (ICP + Rating modal feature)

**What:** When a user submits the Confío Rating modal with `stars <= 3` AND non-empty `confio_rating_feedback_text`, post a Slack message (or send email) to Julian with the user identifier (id, country, last activity), star count, and feedback text.

**Why:** At Confío's current stage (~3 deposits/day, 3 whales = 95% of MX volume), a single dissatisfied whale's complaint matters more than aggregate dashboards. Time-to-response is the lever. Reading admin manually means a 1-3 day delay; Slack push means sub-hour response time. Whale-grade users explicitly indicated they want personal Julian relationship (Luis: "¿Cuándo vienes a Cancún?").

**Pros:**
- Sub-hour response on negative feedback
- Catches whale-grade issues before they spread
- Trivial implementation (~30 min): add to the same `post_save(User)` or `submitConfioRating` mutation handler that already persists the rating
- Reuses existing Slack/email infra if present (check `notifications/` or `config/`)

**Cons:**
- Noise risk if many low-star ratings arrive
- Requires Slack webhook URL or email config
- Adds external dependency to the request path (defer behind Celery task to avoid blocking)

**Context:**
- Implement in: same module as `submitConfioRating` resolver (probably `users/schema.py`)
- Fire condition: `action != SKIP AND stars IN (1,2,3) AND feedbackText IS NOT NULL`
- Send via existing Slack/email service if it exists; otherwise simple `requests.post()` to a webhook URL stored in `settings.NEGATIVE_FEEDBACK_WEBHOOK_URL`
- Always fire async (Celery task) so mutation response is not blocked
- Include in payload: user_id (anonymized for privacy if needed), country, stars, first ~200 chars of feedback, link to admin user detail

**Depends on / blocked by:**
- ICP + Rating modal PR must ship first (this is the source of `confio_rating_*` fields)
- Slack webhook or email destination must be configured in env vars

**Estimated effort:** 30 min dev + test

### Data-triggered whale and institutional conversion pricing
**Source:** plan-eng-review on 2026-08-29 (cUSD conversion fee system)

**What:** Revisit volume tiers, capped fees, or negotiated institutional conversion pricing only after real high-volume usage demonstrates that the symmetric 0.9% entry/exit fee blocks valuable customers.

**Why:** At 0.9%, a $100,000 conversion costs $900 in each direction. That may become commercially unattractive for institutional or whale users, but V1 has no confirmed requirement and adding exemptions now would weaken the universal fee perimeter.

**Pros:**
- Lets pricing respond to observed customer behavior instead of speculation.
- Preserves a simple retail message and contract surface for V1.
- Avoids provenance heuristics, waiver attestations, and premature per-address policy.

**Cons:**
- A large early customer may require a manual commercial response before productized tiering exists.
- Any later on-chain pricing change requires a reviewed cUSD implementation upgrade or a separately approved mechanism.

**Context:**
- V1 uses one symmetric `feeBps` initialized to 90 with `MAX_FEE_BPS = 90`.
- The Safe may lower the universal fee, but there are no per-user exceptions.
- Revisit when a concrete customer or cohort crosses an agreed monthly conversion-volume threshold and fee sensitivity is evidenced in conversion abandonment or direct feedback.
- Do not treat asset provenance, ramp provider, or wallet origin as a tier signal.

**Depends on / blocked by:**
- Production conversion-volume and funnel data after the cUSD fee system ships.
- A concrete pricing decision and legal review for differentiated customer treatment.

**Estimated effort:** product decision first; implementation depends on the selected pricing model
