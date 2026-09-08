# Confío Institutional Collections — Test Plan

Status: Acceptance matrix; implemented-scope regression audit completed separately  
Source: `docs/payments/RECURRING_PAYMENT_PLATFORM_PLAN.md`  
Scope: CIP-first thin kernel, existing BSC Pay rail, external API/webhooks, mobile funding/payment, CIP application, settlement, and operations

See `PAYMENT_PLATFORM_AUDIT.md` for executed checks and implementation boundaries.
The matrix below is a release target, not a claim that every scenario has run.
Refund/correction execution, dedicated identity-field consent UX, physical-device
and BSC certification, and 400,000-member load testing remain outstanding.

## First-party member checkout

- A linked member lists only their own obligations; another authenticated user receives an empty list and cannot create an intent for the opaque obligation id.
- Member responses contain the masked institution reference and no subject external id or identity values.
- PEN-to-cUSD+ checkout fails closed when the official PEN/USD rate is absent or stale.
- `payer_amount` leaves the 0.9% fee inside the quoted gross and subtracts it from the receiver; `receiver_net_target` grosses up to protect the requested receiver net.
- Repeated taps reuse the unexpired payment intent. An expired quote is canceled before a replacement is created.
- Preparing the legacy BSC invoice creates a `BillingPayment` with the actual funding asset/units and moves its invoice, intent, and obligation to payment-pending atomically.
- Insufficient balance offers the existing Recarga route. No test fixture or state machine introduces Yape-specific billing behavior.

## Release gates

No real-value pilot until:

1. every P1 rail, journal, finalizer, privacy, connector, correction, and reconciliation suite passes on PostgreSQL;
2. CIP's commercial PEN obligation, token/fiat settlement, FX, refund authority, and application semantics are signed off;
3. the end-to-end sandbox and BSC certification paths pass;
4. the bounded cohort load, outage recovery, accessibility, and operator drills meet agreed thresholds;
5. reconciliation produces zero unexplained balance across obligation, payment, chain settlement, CIP application, and optional payout.

## Invariants

- A non-custodial payment is never created without an explicit payer signature outside test-only simulation.
- One legacy `Invoice`/`PaymentTransaction` produces at most one successful economic effect and one live sponsored batch.
- `pay_cusd`, `pay_cusd_plus`, `pay_usdt`, and `pay_confio` share the canonical active-batch constraint.
- PEN amounts are integer minor units; chain amounts are exact integer token/share base units.
- Allocation deltas equal the accepted commercial effect; finalized gross units equal fee plus receiver net for actual contract-event units.
- Corrections/refunds append compensating effects; original payment/allocation evidence is immutable.
- Payment confirmation, CIP application, and optional fiat payout are distinct milestones.
- Events and outbox rows are atomic with the financial transition; delivery rows are created idempotently by the outbox worker, and network side effects start only after commit.
- Billing/API access never grants raw identity access; ordinary merchants and billing keys cannot read DNI/email/phone/KYC.
- Account erasure, rollback, replay, or worker retry cannot delete or duplicate financial evidence.

## Test matrix

| Layer | Required cases | Pass condition |
| --- | --- | --- |
| Contract/fee | Fee ceiling vectors, global invoice replay, supported assets/routing | Existing Pay behavior unchanged; event units match expected gross/fee/net |
| Rail concurrency | Two prepares/submits with different nonces/funding kinds, winner adoption | One active batch, one broadcast owner, one finalized payment |
| Reconciliation worker | More than 300 stranded rows, steady new traffic, oldest-first claiming | No starvation; oldest-age SLO returns to zero |
| Journal/property | Random payment/allocation/correction/reallocation/refund sequences | Conservation equations always hold; projections equal journal |
| Finalizer | Duplicate workers, stale objects, crash after each write, reordered tasks | Retry converges to one effect/allocation/settlement/application/event set |
| Quote/settlement | Expiry, rounding, share units, routed output, log parsing, FX change | Accepted quote and finalized event evidence reconcile exactly |
| API auth | Tenant/mode/scope matrix, revoked/expired keys, unknown scope | Default deny; no cross-tenant or identity leakage |
| API idempotency | Exact replay, body mismatch, in-progress request, retention, `If-Match` | Original response replayed; stable documented 409 conflicts |
| Event/webhook | Raw signing, version pin, duplicates, order, replay, secret overlap, 4xx/429/timeout | One semantic event; durable inspectable deliveries converge or pause visibly |
| SSRF | Redirects, DNS rebinding, IPv4/IPv6 private/link-local/metadata targets | Every unsafe target rejected on registration and retry |
| CIP connector | Token rotation/expiry/JTI, lost/duplicate/rejected/mismatched effects, versions | Idempotent per-allocation revisions converge with full audit trail |
| Identity | Consent versions, required/optional fields, interruption, redaction | No PII in generic DTOs/events/tasks/logs/artifacts/screens |
| Refund/correction | Wrong member/period, inverse/replacement, signer delay, failed payout | Original remains; compensation and CIP acknowledgement reconcile |
| Imports | Checksum/schema, duplicates, partial errors, amendments, formula injection | Dry run is deterministic; promotion is idempotent; errors stable |
| Scale | 400k import, monthly generation, six reminders, multi-day outage/backlog | Agreed latency/throughput/SLO budgets pass without full-table scans |
| Mobile | Top-up cancel/delay/partial, process death, second device, quote change, double tap | Same obligation resumes; ramp never implies CIP payment; no double pay |
| Application UX | CIP pending/delayed/mismatch/reject after confirmed payment | Receipt preserves proof, says not to repay, creates tracked resolution |
| Pay on behalf | Expired/revoked/already-paid/changed/held links, subject mismatch | Minimum disclosure; payer cannot access subject profile/future bills |
| Accessibility | Screen reader, focus return, 200% text, contrast, reduced motion, QR alternative | WCAG 2.2 AA and target-device checks pass |
| Migration/rollback | Legacy fixtures, constraint preflight, shadow diff, in-flight rollback | Creation can stop while confirmation/reconciliation safely drain |

## End-to-end scenarios

### A. Five-to-ten-minute sandbox golden path

1. Set `BILLING_CIP_SANDBOX_ENABLED=True` and a sandbox-only bearer token.
2. Run `setup_cip_sandbox_pilot` twice for the same synthetic member and prove
   it creates one subject, schedule, obligation, and member while issuing a new
   one-use device link.
3. Call the protected verification contract and prove its response/link contain
   neither the raw member number nor identity fields.
4. Open the link on a test device, use Recarga if required, explicitly sign Pay,
   and wait for real finalization. No Yape-specific billing state is permitted.
5. Verify `payment.confirmed`, then `institution.application_applied`, including
   an intentional duplicate application delivery.
6. Reuse the same idempotency key with a changed body and require `409`; confirm
   the original payment and CIP receipt remain unchanged.
7. Disable the sandbox flag and require both simulator endpoints to return `404`.
8. Freeze/download reconciliation; assert counts, totals, and checksum.

Test-only helpers must reject live credentials and run through the real finalizer/outbox.

### B. BSC certification

1. Create obligation, quote, intent, and legacy payment attempt.
2. Fund/sign through the test wallet and submit the sponsored batch.
3. Exercise confirmed, reverted, dropped, no-op, RPC-loss, and reorg outcomes.
4. Parse finalized `PaymentMade` logs and compare exact settlement legs.
5. Confirm one journal effect/outbox set after duplicate/crashed confirmers.

### C. Yape top-up and payment

1. Open an insufficient-balance obligation and start the ramp.
2. Exercise cancel, delayed webhook, partial funding, app termination, and another-device return.
3. Confirm funding only changes the funding session.
4. Refresh changed/expired quote with old/new comparison.
5. Sign explicitly, confirm payment, then hold CIP acknowledgement pending.
6. Verify durable two-stage receipt, notification privacy, and later application update.

### D. Correction and refund

1. Confirm/apply a payment to the wrong period or subject in the sandbox.
2. Open the operator exception, require reason/evidence/preview and configured dual approval.
3. Append inverse and replacement effects; deliver out of order and with lost responses.
4. Record refund signer/funding path and only mark confirmed after external evidence.
5. Reconcile Confío journal, CIP revisions, chain/provider evidence, and receipt history.

### E. Outage and scale recovery

1. Stage a production-shaped 400k roster/obligation cycle.
2. Disable webhook/CIP endpoints for one day while payments/reminders continue.
3. Restore service and drain with bounded leases and per-aggregate ordering.
4. Prove old rows do not starve, SLO alerts fire/clear, and reconciliation reaches zero.

## Contract artifacts required in CI

- committed/linted pilot OpenAPI and breaking-change diff;
- resource/event dictionary and JSON fixtures;
- generated temporary Python/TypeScript client smoke tests;
- Postman/cURL quickstart and complete Python sample;
- webhook signing vectors and duplicate/out-of-order fixtures;
- CIP API mock, batch schemas, golden scenario files, and checksum manifests;
- migration rehearsal fixtures and query-plan/load baselines;
- redaction snapshots proving sensitive values never enter forbidden channels.

## Evidence retained for each release candidate

- test command, commit, environment, database/chain configuration, start/end time;
- pass/fail counts and quarantined-test justification;
- invariant reconciliation report and checksum;
- load percentiles, queue oldest-age graphs, and alert/runbook drill results;
- mobile/accessibility device matrix;
- named approvals from engineering, product/design, security/privacy, CIP integration, and CIP finance.
