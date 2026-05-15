# TODOs

Project-level deferred work captured by /plan-eng-review. Each entry includes context so it can be picked up cold.

## Open

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
