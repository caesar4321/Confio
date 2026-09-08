# Institutional billing operations runbook

## Launch status

The code is sandbox-ready and deliberately not real-value ready by default.
`BILLING_LIVE_API_KEYS_ENABLED` is false unless explicitly configured. A live
institution connector also requires `status=active`, `live_approved=true`, an
application URL, and named settlement and refund authorities. Missing any gate
prevents the CIP effect worker from sending a live request.

`billing_readiness` checks configuration and queue ages; it does not certify
the full release. Correction/refund execution workflows, physical-device/BSC
certification, and the 400,000-member load exercise are still outstanding.
The journal has compensating-effect types, but there is no supported operator
correction/refund command or API yet. Do not modify journal rows to simulate one.

## CIP sandbox pilot

### App entry points

There is no global membership promotion or new tab. Home shows one linked
member's actionable bill or unresolved institution acknowledgment, with the
institution name and a review action. Settled, acknowledged dues disappear from
Home. The existing test/live launch flags also gate Home entries.

Profile shows `Mis instituciones` only for linked personal accounts. Home and
reminder taps open the selected obligation; members can return to all institutions.
The scanner accepts first-party `confio://memberships?provider=cip` and
`https://confio.lat/memberships?provider=cip` public QR links. Public links do not
claim identity: they explain how to request a personalized verification link.
Actual self-service enrollment still depends on the institution's verification
integration. Never put a personal one-use token on public signage. Personalized
links may include the existing short-lived `token` parameter.

Deploy the backend GraphQL `myBillingSummary.entry` addition before releasing
the app querying it. No database migration is required for this entry-point change.
Recarga and the tab bar are unchanged. Device-level visual/accessibility QA is
still required before enabling the pilot for real members.

The in-process CIP contract simulator is disabled by default and accepts only
test/sandbox connections. Enable it only in a local or isolated staging
environment:

```dotenv
BILLING_CIP_SANDBOX_ENABLED=True
BILLING_CIP_SANDBOX_TOKEN=<random sandbox-only bearer token>
```

Seed or refresh one member journey with an existing merchant user and its test
BSC receiver address:

```bash
python manage.py setup_cip_sandbox_pilot \
  --merchant-username <username> \
  --merchant-bsc-address <0x-address> \
  --member-number <synthetic-member-number> \
  --amount-pen 50.00 \
  --period 2026-09
```

The command is idempotent for the same member, amount, and period. It prints a
short-lived, one-use `confio://memberships?...` link that can be opened on a
test device. The link contains opaque Confío identifiers, not the member number.
The command also prints a connection ID. When several sandbox connections exist,
send it in `X-CIP-Sandbox-Connection` on both simulator endpoints; ambiguous
requests fail instead of choosing another institution's connection.

The future CIP contract can be exercised independently with:

```text
POST /v1/sandbox/cip/verify
Authorization: Bearer <sandbox token>
{"member_number":"<synthetic-member-number>"}

POST /v1/sandbox/cip/payments/apply
Authorization: Bearer <sandbox token>
Idempotency-Key: <stable-effect-key>
{"subject_reference":"cip:<member>","period_end":"2026-09-30","payment_id":"pay_..."}
```

Application receipts are durable. Replaying the same key and body returns the
original response; reusing the key with a different body returns `409`. Disable
the feature flag to make both endpoints return `404`.

Operators use the institutional collections section in Django admin to inspect
subjects, schedules, obligations, immutable payments, CIP application state,
and sandbox receipts. `Apply selected institution updates now` retries a
selected application synchronously. `Queue selected failed/mismatched updates
for retry` accepts terminal exceptions without active worker leases. Both actions
require change permission and produce an admin audit entry. Financial records,
subject bindings, schedules, and application evidence are read-only here.

### Device acceptance path

1. Open the command's deep link on a signed-in test device.
2. Confirm that the screen shows only the masked CIP reference and PEN due.
3. If funds are insufficient, use the existing Recarga flow and return. Yape is
   only a Recarga method; it has no billing-specific state or endpoint.
4. Re-open the obligation, review the current quote, and explicitly sign Pay.
5. Confirm the receipt first shows Confío payment status separately from CIP
   application status.
6. In admin, verify exactly one payment effect/allocation, one institution
   application, and one acknowledged sandbox receipt; the member must be
   `active` through the obligation period end.
7. Re-run the application action and confirm the receipt/version do not advance.

Never use real DNI, email, phone, or member records in this simulator. A real
CIP identity manifest and field-specific consent remain launch prerequisites.

Run `python manage.py billing_readiness` in the target environment. Every
`BLOCK` must have an accountable owner and evidence before enabling live keys.

## Expand and rollback

Migration `0013` introduces explicit test/live boundaries for subjects,
obligations, schedules, and imports. Existing unclassified rows default to live;
review any old sandbox fixtures before migrating a populated staging database
and recreate synthetic records using the updated seed command. Never infer a
real member's environment from an external ID or business name.

1. Apply migrations while the old application remains compatible. They only
   add tables, indexes, constraints, or nullable/defaulted columns.
2. Deploy code with live API keys disabled. Run existing payment reconciliation
   and compare payment, settlement, fee, and journal totals in shadow mode.
3. Provision test keys and a test webhook. Exercise duplicate delivery,
   timeout, rejection, and replay. Confirm test events never reach live endpoints.
4. Configure one reviewed live institution connection, but keep the API gate
   disabled. Run `billing_readiness` and obtain finance/privacy/security signoff.
5. Enable one canary business and monitor the queues below. Expand only after a
   complete payment-to-acknowledgement reconciliation.
6. To roll back, disable the webhook endpoint/institution connection and live
   key gate. Do not reverse migrations or delete journal/events. Existing payment
   confirmation remains available through the legacy path.

## Queue and SLO checks

- Outbox: alert if oldest due message exceeds 60 seconds.
- Webhook: alert if oldest due delivery exceeds 5 minutes or terminal failures rise.
- Institution application: alert after 5 minutes; payment stays confirmed while
  the application remains pending.
- Payment reconciliation: alert on oldest submitted payment age, not only count.
- Scheduler: alert when an active schedule's `next_period_start` is in the past
  after two generation cycles.
- Import: never promote a batch with invalid rows or a checksum mismatch.

## Incident rules

- Never edit or delete payment effects, allocations, settlements, or events;
  append a compensating effect after approval.
- Never mark a payment unpaid because CIP is unavailable.
- Rotate an endpoint secret through the API; existing deliveries retain their
  original secret snapshot and replays use the current secret.
- Disable a compromised API key immediately. Idempotency records and accounting
  evidence remain tenant-scoped and intact.
- Identity data may only travel through an active, unexpired, field-specific
  grant. Revocation stops future transfers; it does not claim deletion by CIP.

## External decisions required for real value

CIP and Confío must record: accepted settlement asset, PEN conversion and payout
responsibility, who funds refunds, signer/approval authority, accounting export,
privacy purposes and retention per identity field, CIP endpoint/API version,
credentials, retry semantics, and incident contacts. Until then, use the sandbox
connector only.
