<!-- /autoplan restore point: /Users/julian/.gstack/projects/Confio/main-autoplan-restore-20260903-201014.md -->
# Confío Institutional Collections: CIP-First Obligations, Payments, and Public API

Status: APPROVED — full CEO, design, engineering, security, and developer-experience review complete  
Scope: Business-created one-time and recurring payment requests paid by personal or business Confío accounts  
First institution: Colegio de Ingenieros del Perú (CIP)  
Settlement: Existing BSC `ConfioPayContract`, sponsored EIP-7702 flow, 0.9% payment fee

## 1. Executive decision

Build a thin, reusable institutional-collections kernel above the existing `Invoice` and `PaymentTransaction` settlement path, and prove it through a bounded CIP pilot before expanding it into a broad self-service platform.

The core product object is an `Obligation`: a one-time or periodically issued amount that a subject owes and any authorized payer may pay. A schedule may create obligations, but it cannot debit a non-custodial wallet. Confío presents the bill, reminds reachable payers, prepares the existing sponsored Pay-contract transaction, and requires an explicit signature every time.

The pilot kernel contains only the reusable primitives needed to collect and reconcile money safely:

- institution/business and obligation subject;
- obligation, immutable line items, adjustments, and allocation;
- payer and funding account, which may differ from the obligation subject;
- short-lived payment attempt and existing on-chain settlement;
- institution application/status acknowledgement;
- settlement reporting, event outbox, restricted API, and signed webhooks;
- operator holds, corrections, disputes, and manual refund reconciliation.

CIP is the first adapter, not a special-purpose fork. Generic product catalogs, SDKs, self-service developer onboarding, arbitrary identity-sharing workflows, and broad subscription-management features remain designed but are promoted to product scope only after the CIP pilot meets its gates and a second institution validates the same abstractions.

The promised outcome is not “automatic subscriptions.” It is lower-friction institutional dues collection with reliable reconciliation: a member sees what is owed, uses the existing Recarga flow when funding is needed, signs in a few taps, receives proof, and can see whether CIP applied the payment to `habilidad`.

### First-party member checkout and Recarga boundary

Linked members see obligations in the Confío mobile app and explicitly sign every payment. The app requests a short-lived server quote, creates a BSC `CUSD_PLUS` legacy invoice, and settles through the existing Pay contract and finalizer.

If the wallet balance is insufficient, the payment screen links to the existing `TopUp`/Recarga flow with `destination=cusd_plus`. Yape may be one of the methods selected inside that existing flow, but billing has no Yape-specific model, endpoint, status, webhook, or reconciliation path. After Recarga, returning to payment refreshes the wallet balance and the user signs normally.

Institution membership linking accepts only a short-lived, audience-bound, single-use identity-session token. The member API never accepts or returns raw DNI, email, or phone data; the dues UI receives only an institution name and masked member reference.

## 2. Product principles

1. No silent debit. Every payment requires an explicit wallet signature from the payer.
2. One settlement path. One-time and recurring invoices use the same BSC Pay contract and confirmation pipeline.
3. Billing is off-chain; settlement is on-chain. Schedules, memberships, reminders, metadata, and webhook delivery belong in the backend. Final payment proof belongs on-chain and is mirrored in the database.
4. Institutions own their domain state. Confío reports payment facts; CIP decides how those facts affect `habilidad` unless CIP explicitly delegates that calculation.
5. API-first and app-native. Anything the business portal can do should use the same service layer exposed by the public API.
6. At-least-once events, idempotent effects. API writes and webhook consumers must be safe to retry.
7. Never overload legacy `Invoice`. Existing invoices remain immutable payment attempts with a 24-hour ceiling. Recurring obligations create fresh invoices for individual collection attempts.
8. Privacy by design. Store only the institution identifiers and attributes needed for eligibility, reconciliation, and support.
9. Billing access never implies identity access. Creating an obligation, viewing a payment, or managing a schedule grants no right to see a subject's DNI, email, phone, KYC record, or documents.
10. Prefer verified claims over raw identity. A business normally receives facts such as `member_match=true` or `contact_verified=true`; raw attributes are released only when a separately approved integration purpose requires them.
11. The commercial obligation keeps its institution currency. CIP dues are denominated and receipted in PEN even when the signed settlement amount is a quoted cUSD/cUSD+ equivalent.
12. Chain confirmation is not the whole institutional outcome. Confío separately records institution application and, when contracted, bank/fiat settlement.
13. Generalization is earned. Pilot-only infrastructure must demonstrate repeat use before it becomes a self-service platform surface.

## 3. Vocabulary

| Term | Meaning |
| --- | --- |
| Obligation subject | The member, person, or organization whose status/debt the payment affects |
| Payer | The authenticated personal or business account that authorizes payment; may differ from the subject |
| Funding account | The payer wallet/account from which the signed transaction is executed |
| Obligation | The durable amount due, denominated in the institution's commercial currency, with immutable line items and external reference |
| Schedule | Optional rule that produces recurring obligations; it is not an automatic-debit mandate |
| Collection invoice | The payer-facing presentation of one or more obligation balances |
| Payment intent | A short-lived, payable attempt bound to one billing invoice and one payer |
| Payment transaction | The existing record of the sponsored on-chain execution |
| Payment link | Shareable URL/deep link for one obligation or a recurring-bill enrollment flow |
| Event | Immutable business event placed in the outbox and exposed through webhooks |
| Institution application | CIP's acknowledgement that a confirmed payment was allocated and the member status recalculated |
| Settlement report | The gross, 0.9% fee, receiver net, asset/FX, payout, and accounting evidence owed to the institution |

Public API naming should use `obligation` for the institution debt, `invoice` for its payer-facing presentation, and `payment_intent` for a short-lived attempt. Internally, the current `payments.Invoice` remains a payment attempt and is wrapped by the new domain service without a risky table rename in V1.

## 4. User journeys

### 4.1 CIP member enrollment

1. Member opens the CIP entry in Confío or scans a CIP link/QR.
2. The preferred pilot link contains a short-lived CIP-signed token with an opaque member reference and obligation references. Confío verifies the signature and does not receive DNI, email, or phone for a successful match.
3. Only when the opaque-token/member-number path cannot resolve the member does Confío show CIP's approved identity request: required fields, optional fields, purpose, recipient, retention period, and CIP privacy notice.
4. The member explicitly authorizes any required transfer. Optional fields use separate controls and cannot be preselected.
5. The CIP connector sends approved attributes directly to CIP; the generic business dashboard never receives them.
6. CIP returns a stable opaque member ID, chapter, status, PEN obligations, and source version. Confío records the provenance and links an obligation subject without using phone, email, or DNI as its public key.
7. If the member is current, Confío shows the next due date and no payment CTA.
8. If payment is due, Confío shows the amount, period, institution, fee disclosure, and two steps: `Recargar` then `Pagar`.
9. If balance is insufficient, `Recargar con Yape` opens the existing local ramp flow with a Yape-readable QR and a recommended amount that covers the exact gross payment plus any independently disclosed top-up conversion cost.
10. After the top-up confirms, the app returns to the same invoice rather than Home.
11. The member reviews and signs the sponsored transaction.
12. After chain confirmation, Confío records `payment_confirmed`, shows a receipt with the subject, period, PEN obligation, token/FX quote, payer gross, 0.9% receiver fee, receiver net, and transaction hash, then asynchronously asks CIP to apply the payment.
13. The receipt shows `CIP actualizando estado` until CIP acknowledges allocation. It then shows `Aplicado por CIP`, the returned `habilidad`, and last-sync time; a delay never disguises a confirmed payment as unpaid.

### 4.2 Periodic monthly obligation

1. CIP supplies an obligation or an approved schedule creates the next period using CIP's timezone and calendar rules.
2. The billing invoice becomes `open` and the user receives an in-app/push reminder.
3. The user can pay now, snooze, or view details. There is no "autopay" toggle.
4. Additional reminders are sent according to the institution reminder policy, payer reachability, and user communication preferences.
5. When the user pays, the same one-time Pay-contract flow settles the invoice.
6. If the due date passes, the invoice becomes `past_due`; it is still payable unless the business voids it or policy closes it.
7. The business and institution receive webhook events for payment confirmation and institution application as separate transitions.

### 4.3 Pay on behalf

1. A member shares a signed/unguessable obligation link with a relative, employer, or business payer.
2. The payer sees the institution, masked subject, covered periods, amount, and an explicit statement that payment affects another person's membership.
3. The payer authenticates, chooses a funding account, tops up if needed, and signs.
4. The receipt records both payer and obligation subject; CIP receives only the subject/member reference and payment facts it needs.
5. Paying creates no durable right for the payer to inspect the subject's identity, history, or future obligations.

### 4.4 Business API integration

1. A business owner creates a restricted API key in test mode.
2. During the pilot the developer imports obligation subjects and obligations, queries payments/application state, and consumes events. Catalogs and generic schedules are exposed later only if validated.
3. Confío returns stable opaque IDs, request IDs, and idempotent responses.
4. The developer registers a webhook endpoint and completes a signed test-event handshake.
5. The integration consumes events and periodically reconciles using list endpoints and cursors.
6. The developer promotes the integration to live mode with a separate key and webhook secret.

## 5. Information architecture in the mobile app

### Personal and business payers

- Home shows a contextual `Pago pendiente de CIP` item only when actionable; `Recargar` never becomes a Home action-row shortcut.
- Pilot navigation enters a lightly CIP-branded relationship hub: `Estado`, `Cuotas`, and `Comprobantes`. A future generic `Membresías` area is a taste decision deferred to the approval gate.
- Member-facing language uses `Cuotas y pagos`, `Pago programado`, or `Recordatorio mensual; tú confirmas cada pago`; never imply automatic debit with `Suscripción`.
- Shared links are entry mechanisms, not a permanent top-level `Enlaces` destination.
- One persistent obligation/invoice detail is the task screen across balance checking, Yape top-up, return, signing, confirmation, and CIP application. It shows institution, masked subject, covered periods, due date, authoritative PEN amount, quoted settlement equivalent, balance/shortfall, support path, and one sticky primary action.
- The durable receipt is reachable from the CIP hub and activity/history even when CIP synchronization fails.

### Business operators

- Business Home: collections snapshot, application lag, settlement status, and exceptions requiring action.
- Pilot operations: Obligation subjects, Obligations, Payments, Settlements, and Exceptions. Catalogs, generic schedules, and Developers become visible only with their rollout flags.
- The Exceptions workspace is a dense task queue, not a card grid. Categories: `Payment unknown`, `CIP pending/mismatch/rejected`, `Wrong member/allocation`, and `Refund pending`.
- Queue rows show severity, age/SLA, masked subject, period, amount, payment proof, CIP response, settlement state, and assigned owner. Filters are shareable/saved and source timestamps are visible.
- Case detail includes an immutable timeline, source snapshots, evidence/attachments, notes, owner, support communications, and separate integration, financial, and support actions.
- Financial corrections require reason code, preview of resulting balances, step-up authentication, and two-person approval where policy requires it. Operators append adjustments; they never edit the original payment.
- Desktop/tablet support dense table + detail split view. Narrow screens collapse rows into cards and permit review/escalation, but not complex financial corrections.
- Developer area: test/live keys, webhook endpoints, recent deliveries, signing secret rotation, logs, and API docs after the public-platform gate.

### Screen-level payment contract

The obligation detail owns a server-side resumable payment context keyed to obligation/invoice, payer, funding account, ramp order, expected shortfall, and quote expiry. On launch, authentication return, deep link, or process restart it resolves to exactly one visible state:

| State | Persistent content | Sticky primary action / copy |
| --- | --- | --- |
| Balance checking | Known obligation and last balance remain visible | `Verificando saldo…` disabled |
| Insufficient | PEN total, token quote, balance, shortfall, provider cost | `Recargar S/… con Yape` |
| Awaiting ramp | QR, amount, manual copy/share alternative, expiry | `Esperando tu recarga` plus cancel/help |
| Delayed/partial funding | Amount received, amount still missing, last check | `Faltan …` or retry/status action |
| Funded | Confirmation that funds reached Confío, not CIP | `Saldo recibido · Confirmar pago` |
| Quote changed/expired | Old/new amount comparison and reason | `Aceptar nuevo monto` before pay |
| Ready | Subject, period, total authorized, selected funding account | `Firmar y pagar` |
| Signature rejected | No money moved; input preserved | `Intentar de nuevo` |
| Chain processing/unknown | Transaction reference and durable polling state | `Confirmando pago…`; no second attempt |
| Payment confirmed | Immutable proof and next milestone | `Ver comprobante` |
| CIP pending/delayed | Confirmed payment stays green; CIP step neutral/amber | `CIP está actualizando tu estado` / support |
| CIP mismatch/rejected | Confirmed payment remains intact | `No vuelvas a pagar`; tracked support case |

Every ramp screen repeats: `Esta recarga agrega saldo a Confío; todavía debes confirmar el pago a CIP.` A funded-but-not-returned user sees the resumable payment on the next app open.

### Receipt and application timeline

```text
✓ Pago confirmado por Confío             [fecha/hora]
• CIP está aplicando tu pago              [ETA / última actualización]
○ Habilidad actualizada por CIP           [pendiente]
```

When CIP acknowledges, the last step becomes complete and shows the CIP-returned status/version. When delayed, mismatched, or rejected, show expected resolution, last attempt, case reference, and support action. Never make the confirmed-payment milestone red and never tell the member to pay again. Transaction hash, chain, quote provenance, fee, and receiver net live under `Detalles técnicos`/`Cómo se calculó`, not in the primary success message.

### Pay-on-behalf trust contract

- Before authentication show only institution, masked subject, covered periods, total, link expiry, and `Este pago actualizará la membresía de otra persona`.
- After authentication revalidate link, amount, subject, hold/dispute state, and concurrent payment state; show payer/funding account separately from the subject.
- Define terminal states for expired, revoked, already paid, payment in progress, amount changed, subject mismatch, and unavailable obligation.
- A payer receipt may show the masked subject and periods paid, but offers no route to subject history, profile, contact data, or future obligations.

### Loading, offline, and accessibility contract

- Initial structural loads may use skeletons; refreshes preserve known financial data and label `Actualizado hace…` or stale/offline state.
- Every empty state states what it means and one truthful next action. Every retry preserves entered data. Financial processing never becomes an indefinite spinner.
- Meet WCAG 2.2 AA contrast, 44×44 targets, Dynamic Type/200% text scaling, semantic headings, visible focus, logical focus restoration, reduced motion, and non-color status labels/icons.
- Announce balance, funding, confirmation, and CIP application changes to assistive technology. Money is read with explicit currency; masked identities and QR actions have descriptive labels.
- QR always has copy/share/manual-code alternatives. Layouts cover small phone, landscape, tablet, long Spanish strings, and long institution/member names without clipping amounts.
- Use the existing 4-point spacing, type, radius, `SuccessHero`, `ReceiptCard`, `InlineBanner`, and button grammar. Emerald is reserved for completed/primary money actions, blue for information, amber for delay/review, red for actionable mismatch, and violet only for `$CONFIO`.
- Avoid decorative crypto imagery, gradients/blobs, invented activity, generic KPI-card mosaics, excessive icon circles, and celebratory effects around unresolved institutional state.

New negative-check permissions:

- `manage_billing` for subjects, obligations, and approved schedules;
- `view_billing` for customer/invoice/payment views;
- `manage_api_keys` owner-only;
- `manage_webhooks` owner/admin;
- `configure_identity_requests` is never role-derived; it is enabled only for a reviewed institution connection and requires Confío approval;
- `view_shared_identity` is granted per connection and field class, never to cashiers and never merely because someone owns the business account;
- `export_shared_identity` is disabled by default and requires a separate institutional contract, scope, and audit policy;
- `issue_refunds` reserved for a future refund workflow and not granted in V1.

Access matrix:

| Actor/capability | Billing and payment data | Masked customer hints | Raw email/phone | DNI | KYC documents |
| --- | --- | --- | --- | --- | --- |
| Ordinary business owner/admin | According to billing role | Yes | No | No | No |
| Cashier | Current collection flows only | Minimum needed for service | No | No | No |
| Standard public API key | Scope-limited billing objects | Yes | No | No | No |
| Approved institution connection | Yes | Yes | Only fields granted for an approved purpose | Only when explicitly required and granted | No by default |
| Confío restricted identity service | Transfer/verification references | Yes | Policy-controlled | Policy-controlled | Existing KYC controls only |
| Support operator | Case-specific metadata | Masked by default | Break-glass only | Break-glass only | Separate KYC-admin boundary |

Every break-glass access requires a case ID, reason, short expiry, immutable audit event, and subsequent review.

## 6. State machines

### Optional schedule

```text
incomplete -> active -> paused -> active
                 |         |
                 +-------> canceled
                 |
                 +-------> completed   (fixed number of periods)
```

`past_due` is not a schedule status. It belongs to an obligation. A schedule can remain active while one or more obligations are past due.

### Obligation

```text
draft -> open -> payment_pending -> paid
          |  |         |          |
          |  +-> held/disputed     +-> correction/refund reconciliation
          |            +------> open          (failed/reverted before settlement)
          +----------> past_due -> paid
          +----------> void/uncollectible     (explicit authorized action)
```

`payment_pending` is outcome-unknown until the chain confirmer resolves it. The UI and API must never invite an immediate second payment while an attempt may have landed.

### Payment intent

```text
requires_payment_method -> requires_confirmation -> processing -> succeeded
                                  |                    |
                                  +-> canceled         +-> failed
```

A payment intent expires independently of the billing invoice. Retrying creates or refreshes an attempt without duplicating the obligation.

### Institution application

```text
payment_confirmed -> application_pending -> acknowledged
                              |          -> mismatch -> manual_review -> acknowledged
                              +----------> rejected  -> manual_review
```

Chain confirmation is immutable payment evidence; CIP application is an independently retryable business outcome. A failure or delay in CIP never rolls the payment back to unpaid.

## 7. Data model

Use UUID/ULID-style public IDs with resource prefixes (`subj_`, `obl_`, `inv_`, `pi_`, `pay_`, `set_`, `app_`, `evt_`, `we_`). Database primary keys remain private.

### `ObligationSubject`

- `business_id`, `public_id`, institution-scoped opaque `external_id`
- optional `confio_user_id` only after a verified link
- subject type: `person`, `business`, `membership`, or future institution-defined type
- display-safe label and masked reference; no raw DNI/email/phone
- `status`, `locale`, `timezone`, bounded metadata
- unique `(business_id, external_id)`

### `BillingObligation`

- `business_id`, `subject_id`, `public_id`, unique institution `external_reference`
- authoritative commercial `currency` and `original_amount` (`PEN` for CIP)
- immutable line items: base dues, chapter assessment, penalty, credit, waiver, or adjustment
- `period_start`, `period_end`, `issued_at`, `due_at`
- `status`: `draft`, `open`, `held`, `payment_pending`, `paid`, `past_due`, `disputed`, `void`, `uncollectible`; `partially_paid` is reserved for the future partial-tender feature
- source version, allocation policy, bounded metadata
- `amount_paid` and `amount_remaining` may be locked projections only; the append-only allocation journal is authoritative
- optional `schedule_id`; imported obligations do not require a subscription

### `ObligationAdjustment` and `Correction`

- append-only amount/status correction linked to an obligation or allocation
- reason code, operator, approval/audit reference, before/after snapshot
- supports holds, releases, waivers, reallocations, and manual refund records without rewriting settled history

### `BillingInvoiceObligation`

- invoice, obligation, immutable selected commercial amount, deterministic allocation order
- unique `(invoice, obligation)`; a bundled invoice may cover whole periods but cannot silently change them after signing

### Immutable payment journal

- `PaymentEffect`: one economic payment, reversal, reallocation, or refund; unique semantic effect ID and immutable type/status/provenance.
- `PaymentAllocationEntry`: effect, obligation, signed commercial-currency minor-unit delta, allocation order, quote reference, and allocation revision.
- Corrections append inverse and replacement effects. No service edits or deletes an original allocation.
- Commercial amounts use integer minor units (PEN céntimos); chain amounts use exact integer token/share base units.
- Enforced reconciliation: allocation deltas equal the accepted commercial effect; collectible balance cannot go below zero without an explicit credit policy; settlement gross units equal fee plus receiver net for the actual event units.
- Pilot policy is exact full-balance payment only. Whole periods may be bundled with deterministic oldest-first allocation and an explicit rounding-remainder rule. Partial tender is modeled for later but not exposed unless CIP proves it is necessary.

### `PayerAuthorization`

- obligation/invoice, authenticated payer user or business account, selected funding account
- short-lived link/token provenance and authorization time
- grants payment authority only; never subject-profile or future-obligation access

### `BillingCustomer`

Post-pilot compatibility resource for merchant-style APIs. It projects an `ObligationSubject` plus merchant-safe metadata; it is not the identity or payer model.

- `business_id`
- `public_id`
- `external_id` unique per business
- `confio_user_id` nullable
- `confio_account_id` nullable and bound only after verified linking
- display-safe `name` and masked contact hints only; raw shared identity does not live in this table
- `tax_id_last4` or institution-specific masked reference only when needed
- `locale`, `timezone`
- `status`: `active`, `archived`, `blocked`
- `metadata` bounded JSON
- unique `(business_id, external_id)` for live rows

### `BillingProduct`

Post-pilot catalog extension, promoted only after repeated institution demand.

- `business_id`, `public_id`, `name`, `description`, `active`, bounded `metadata`

### `BillingPrice`

Post-pilot catalog extension. CIP pilot obligations remain PEN-denominated imports or institution-approved schedule outputs.

- `business_id`, `product_id`, `public_id`
- `amount`, commercial `currency`; any settlement-asset quote is recorded on the payment attempt, not baked into the price
- `type`: `one_time`, `recurring`
- recurrence: `interval`, `interval_count`, `anchor_rule`
- `active`; prices are immutable after first use and replaced rather than edited

### `BillingSubscription`

Post-pilot schedule extension. API and UI terminology should prefer `schedule` or `recurring bill`; it never implies automatic debit.

- `business_id`, `customer_id`, `price_id`, `public_id`
- `status`, `starts_at`, `current_period_start`, `current_period_end`
- `billing_anchor_day`, `timezone`
- `collection_method = send_invoice` fixed in V1
- `days_until_due`
- `reminder_policy_id`
- `cancel_at_period_end`, `canceled_at`, `ended_at`
- `external_reference`, bounded `metadata`
- optional `period_limit`

### `BillingInvoice`

- `business_id`, `subject_id`, one or more obligation/allocation references, optional `schedule_id`
- `public_id`, `number` (business-scoped human identifier)
- `status`: `draft`, `open`, `payment_pending`, `paid`, `past_due`, `void`, `uncollectible`
- commercial `currency`, `subtotal`, `amount_paid`, `amount_remaining`; payment presentation separately exposes quoted settlement asset, FX, gross, fee, and net
- `period_start`, `period_end`, `due_at`, `paid_at`, `voided_at`
- `description`, immutable line-item snapshot, bounded `metadata`
- `source`: `api`, `dashboard`, `schedule`, `import`
- unique `(schedule_id, period_start, period_end)` where schedule-produced, plus unique institution obligation references for imports

The obligation amount remains authoritative in its commercial currency. At payment time Confío creates an expiring quote with the PEN obligation amount, rate/source/time, settlement asset amount signed by the payer, 0.9% fee, receiver net, rounding, and the party bearing any movement. The Pay contract always deducts 0.9% from receiver gross: `receiver_net = gross - ceil(gross * 90 / 10_000)`. API responses expose every amount by role; never overload `amount`.

Prices therefore declare one of two presentation modes while settlement stays identical:

- `payer_amount`: the configured amount is what the payer signs; the business receives that amount minus the 0.9% fee.
- `receiver_net_target`: the configured amount is the desired receiver net; Confío grosses up the payer amount and discloses it before enrollment and payment. At token precision, the minimal gross is `ceil(target_net * 10_000 / 9_910)` and the contract still deducts its normal fee from the receiver side.

This is not a different fee payer at the contract level. In both modes the contract subtracts the fee from gross. The second mode only lets the business set a high enough sticker price to reach its desired net.

Example: if CIP sets a payer amount of US$50.00, the member signs US$50.00 and CIP receives US$49.55. If CIP instead targets a US$50.00 net receipt, Confío calculates the smallest supported gross above roughly US$50.4541, rounds it to the invoice's supported display precision, and shows that final payer amount before the member enrolls or signs.

### `BillingPaymentIntent`

- `billing_invoice_id`, `public_id`
- optional `payer_user_id`, `payer_business_id`, `payer_account_id`
- `status`, `amount`, `currency`
- `expires_at`, `last_payment_error`
- one-to-one or foreign-key reference to current `payments.Invoice`
- `idempotency_key`, `client_secret_hash` if a public web handoff needs one
- unique active intent per billing invoice and exactly one successful economic effect; retries create a fresh legacy `payments.Invoice` attempt only after the prior attempt is terminal

### `FundingSession`

- payment intent, payer, ramp transaction, target asset/base units, expected shortfall, accepted quote, return target, status, expiry
- at most one active funding session per payer/intent
- ramp success means funds are available; it never changes obligation, invoice, or payment processing state

### `BillingPayment`

- `billing_invoice_id`, `payment_intent_id`, one-to-one existing `PaymentTransaction_id`
- `public_id`, `status`, `gross`, `fee`, `net`, `currency`
- `chain`, `transaction_hash`, `confirmed_at`
- immutable settlement snapshot and reversal/refund placeholders

### `InstitutionApplication`

- payment/allocation, institution connection, opaque subject/member reference
- status: `pending`, `acknowledged`, `rejected`, `mismatch`, `manual_review`
- idempotency/event ID, attempts, last error, CIP acknowledgement and returned status/version
- `payment_confirmed_at`, `institution_applied_at`; these milestones are never collapsed

### `SettlementQuote`

- commercial PEN minor units; pair/direction; provider/source quote ID; fetched, locked, accepted, and expiry times
- rate/spread, rounding rule, settlement asset/address/decimals, and exact payer base units
- commercial/FX terms shown to and accepted by the payer are immutable

### `SettlementLeg`

- payment/quote, chain ID, contract version, receiver address
- input token/address/decimals and exact gross units; fee token/units; merchant output token/units, including routed cUSD output when applicable
- transaction hash plus finalized block, transaction, and log coordinates
- values are verified from the finalized `PaymentMade` event, not recomputed from display decimals

### `PayoutBatch` and `PayoutEntry`

- exist only if Confío contractually owes fiat settlement
- group reconciled payment settlement legs into a bank/provider payout with currency, FX, amount, reference, status, and accounting export
- a payment settlement record is never mistaken for proof of a later bank payout

### `RefundRecord`

- original payment/allocation, requested and executed amounts/assets, reason, operator approvals
- status: `requested`, `approved`, `awaiting_institution_signature`, `submitted`, `confirmed`, `failed`
- signer/funding authority, treatment of the original 0.9% fee, asset/FX rule, partial allocation effects, and manual/on-chain/off-chain evidence
- `confirmed` requires a reconciled chain receipt or bank/provider payout reference; a database record alone is not execution proof
- V1 may execute refunds operationally, but must record them and emit compensating CIP effects before the pilot handles real value

All financial journal, payment, settlement, application, event, consent, and audit foreign keys use `PROTECT` or nullable pseudonymized actor references with immutable snapshots. Account deletion erases identity where legally appropriate; it never cascades away accounting evidence.

### API and event infrastructure

- `BusinessApiKey`: business, mode, prefix, secret hash, scopes, last_used_at, expires_at, revoked_at.
- `WebhookEndpoint`: business, mode, URL, encrypted signing secret, enabled events, status, failure counters.
- `BillingEvent`: immutable type, tenant, aggregate type/ID/version, transition idempotency key, correlation/causation IDs, API version, payload snapshot, created_at; unique per semantic aggregate transition.
- `WebhookDelivery`: event, endpoint snapshot, attempt count, lease/status, next_attempt_at, response code, bounded response excerpt; unique `(event, endpoint)`.
- `IdempotencyRecord`: business/key/mode/endpoint fingerprint, request hash, status code, response body, expiry.
- `InstitutionConnection`: business, provider, credentials reference, configuration, status.
- `InstitutionIdentity`: connection, customer, opaque external member ID, verification state, last verification result/provenance, and masked display hints only.
- `InstitutionDataRequirement`: reviewed connection, field code, required/optional, purpose code, source requirement (`user_entered` or `confio_verified`), retention, and policy version.
- `InstitutionDataGrant`: customer/user, connection, policy version, granted field set, purpose, granted/revoked timestamps, and receipt hash.
- `InstitutionDataTransfer`: grant, exact field set, destination, request/event ID, delivery state, timestamps, and audit metadata. Values are not copied into logs or webhook payload snapshots.
- `SharedIdentityValue`: encrypted, connection-scoped values only when Confío must retain a copy for retry or reconciliation; otherwise transmit from the identity vault and retain only the transfer receipt.
- `IntegrationJob`: bulk import/export/reconciliation job with progress and row-level error artifact.

## 8. Service boundaries

```text
Mobile app / Business portal / External REST clients
                    |
              Billing API layer
                    |
     +--------------+----------------+
     |              |                |
Billing domain   Institution      Event outbox
services         connectors            |
     |              |             Webhook dispatcher
     |              |
Payment-attempt     +---- CIP API (future)
adapter
     |
existing payments.Invoice + PaymentTransaction
     |
prepareBscInvoicePayment / submitBscInvoicePayment
     |
Sponsored EIP-7702 batch -> ConfioPayContract
     |
BSC receipt confirmer -> atomic billing finalizer -> events
```

### Existing-rail prerequisite

Before billing reuses the BSC rail, add `pay_cusd` to the database constraint that permits only one active sponsored batch per payment source. Today `payments/bsc_flow.py` emits `pay_cusd`, while `blockchain.models.SponsoredBatch.cpsb_unique_active_payment` covers only `pay_cusd_plus`, `pay_usdt`, and `pay_confio`. The migration must preflight ambiguous active rows, centralize the canonical payment-kind set, adopt and validate the winning batch on submit races, and include a real PostgreSQL concurrent-submit regression test. The newest-300 stranded-payment scan must also become starvation-free oldest-first/keyset claiming with oldest-age monitoring.

### Locked finalization seam

Receipt resolution calls one idempotent `finalize_billing_payment(batch_id)` service. It must not extend the current confirmer by saving stale, pre-transaction objects. Within one database transaction it locks and re-reads, in stable order:

```text
SponsoredBatch -> PaymentTransaction -> legacy payments.Invoice
               -> BillingPaymentIntent -> BillingInvoice -> obligations by PK
```

It then verifies batch ownership/kind/hash/finality, returns idempotently if the unique finalization key already exists, and atomically:

1. marks legacy transaction/invoice and the current intent confirmed;
2. creates one immutable billing payment/effect linked one-to-one to the legacy transaction;
3. persists exact finalized contract-event settlement legs;
4. appends deterministic commercial-currency allocations;
5. reconciles and updates validated obligation/invoice projections;
6. creates institution-application rows per allocation;
7. creates versioned business events and endpoint delivery rows for the endpoint snapshot active at transition time.

Only after commit may `transaction.on_commit` enqueue notifications, webhook delivery, CIP delivery, and reconciliation. Failure finalization uses the same locking discipline and reopens collection only when no other attempt is live.

Dispatchers claim bounded delivery batches with `select_for_update(skip_locked)`, commit the lease, and perform network I/O outside locks. Ordering is preserved per aggregate/version while different aggregates run concurrently. Replay creates a new delivery attempt for the same immutable event, never a new business transition.

## 9. Public REST API V1

Base: `https://api.confio.lat/v1`  
Auth: `Authorization: Bearer sk_test_...` or `sk_live_...`  
Content type: JSON  
Mutation retries: `Idempotency-Key` required for POST requests that create or change billable resources  
Versioning: URL major version plus event `api_version`

### Core endpoints

The committed `/v1` pilot contract exposes only the institutional collection surface. Deferred catalog/schedule operations do not appear in its OpenAPI document, SDK artifacts, or examples until the generalization gate approves them.

```text
POST   /subjects
GET    /subjects/{id}
GET    /subjects?external_id=&limit=&starting_after=
PATCH  /subjects/{id}

POST   /obligations
GET    /obligations/{id}
GET    /obligations?subject=&external_id=&status=&updated_after=&limit=&starting_after=
POST   /obligations/{id}/hold
POST   /obligations/{id}/release
POST   /obligations/{id}/adjustments

POST   /payment_links
GET    /payment_links/{id}
PATCH  /payment_links/{id}

GET    /payment_intents/{id}
GET    /payments/{id}
GET    /payments?obligation=&subject=&status=&updated_after=&limit=&starting_after=
GET    /applications/{id}
GET    /applications?payment=&obligation=&status=&updated_after=&limit=&starting_after=
GET    /settlements?payment=&status=&updated_after=&limit=&starting_after=
POST   /corrections
POST   /refunds

POST   /webhook_endpoints
GET    /webhook_endpoints
PATCH  /webhook_endpoints/{id}
DELETE /webhook_endpoints/{id}
POST   /webhook_endpoints/{id}/rotate_secret
POST   /webhook_endpoints/{id}/test
GET    /webhook_deliveries?event=&status=&limit=&starting_after=
GET    /webhook_deliveries/{id}
POST   /webhook_deliveries/{id}/retry

POST   /imports
GET    /jobs/{id}
GET    /events?type=&created[gte]=&limit=&starting_after=
GET    /events/{id}
POST   /reconciliation_runs
GET    /reconciliation_runs/{id}
```

External clients create or import subjects and authoritative obligations. Confío creates payer-facing invoices/intents and finalized payment/application/settlement resources. `customer`, `product`, `price`, and `schedule/subscription` remain future merchant compatibility projections, not aliases in pilot V1.

The app continues using GraphQL for first-party screens. Both REST and GraphQL call the same Python domain services; neither contains billing rules directly.

### API behavior

- Cursor pagination only; deterministic descending creation order with a public-ID tiebreaker.
- Consistent envelope: `{ "id": ..., "object": ..., ... }`; lists use `{data, has_more, next_cursor}`.
- Errors use stable machine codes plus human message, parameter, request ID, and docs URL.
- Unknown fields are rejected on writes to catch integration mistakes.
- Metadata is limited in key count, key/value size, nesting, and total bytes.
- API keys are mode-separated and scoped. Secrets are displayed once and stored only as a hash.
- Use a dedicated REST authentication layer. Pilot recommendation is Django REST Framework plus generated OpenAPI because the repository has Graphene but no DRF; do not independently hand-build authentication, serializers, throttling, pagination, and error normalization.
- Hash generated 256-bit API secrets with prefix lookup plus keyed HMAC and a rotated KMS-held pepper; password-style work factors are unnecessary for high-entropy generated keys.
- All reads and writes are hard-filtered by authenticated `business_id`; no client-supplied business selector is trusted.
- Standard billing keys cannot request raw identity fields. Identity operations require a separately provisioned institution credential with field-level scopes and a reviewed `InstitutionConnection`.
- `GET /subjects` and billing webhooks return masked display data and opaque IDs only, even to business owners.
- Per-business and per-key rate limits return standard headers and `429` with retry guidance.
- Idempotency covers every retryable POST/PATCH/action/DELETE mutation with body fingerprint, an in-progress lease, retained terminal response, and `409` for same-key/different-body.
- Institutional surfaces never serialize legacy `payments.Invoice` or `PaymentTransaction` wholesale. Explicit anonymous-preview, authenticated-payer, institution, and operator DTOs use field allowlists and object authorization; legacy payer/contact/account fields cannot leak through shared links.

Resource identity is frozen in one schema dictionary: prefix, owner, lifecycle enum, canonical object schema, relationships, expandable fields, aggregate version, and owning event. Pilot prefixes are `subj_`, `obl_`, `plink_`, `pi_`, `pay_`, `app_`, `set_`, `evt_`, `we_`, `wd_`, `job_`, and `rec_`. Every event `data.object` includes its own `object` discriminator and matching ID prefix.

Pilot machine scopes are separate from dashboard permissions: `subjects:read/write`, `obligations:read/write`, `payments:read`, `applications:read`, `settlements:read`, `events:read`, `webhook_endpoints:read/write`, and `reconciliation:read`. Unknown scopes deny by default. CIP connector mTLS/request-signing credentials are a different principal class and cannot call the public billing API merely by adding scopes.

Idempotency keys are namespaced by API principal, mode, method, and canonical route; maximum length is 255 bytes and pilot retention is at least seven days. Exact replay returns the original status/body/resource plus `Idempotent-Replayed: true`; a body mismatch returns `409 idempotency_key_reused`; an in-progress duplicate returns `409 idempotency_in_progress` with `Retry-After`. Mutable resources expose monotonic `version` and require `If-Match` for conflict-prone updates. Every response includes `Confio-Request-Id`.

Canonical error envelope:

```json
{
  "error": {
    "type": "invalid_request",
    "code": "obligation_external_id_conflict",
    "message": "An obligation with this external_id already exists.",
    "param": "external_id",
    "request_id": "req_...",
    "retryable": false,
    "doc_url": "https://docs.confio.lat/errors/obligation_external_id_conflict"
  }
}
```

Freeze mappings for `400` syntax/validation, `401` invalid or wrong-mode key, `403` missing scope, tenant-safe `404`, `409` idempotency/state/version conflict, `422` semantically invalid transition, `429` with `Retry-After`, and retryable `5xx`. Connector errors classify as permanent, retryable, or manual review.

V1 compatibility forbids removing/reusing fields, changing semantics, or adding required request fields. Additive response fields are allowed and consumers must ignore unknown fields. Webhook endpoints pin an event schema version and receive an upgrade preview/test. Deprecation/Sunset headers, changelog entries, migration guides, and a stated support window precede removals; CI fails on breaking OpenAPI diffs.

### Institution identity endpoints

These endpoints exist only for approved institution connections. They are not part of ordinary merchant billing access.

```text
GET  /institution/identity_requirements
POST /institution/identity_sessions
GET  /institution/identity_sessions/{id}
POST /institution/identity_sessions/{id}/submit
GET  /institution/data_transfers/{id}
```

An identity session returns a short-lived app handoff URL. The user reviews and authorizes sharing inside Confío. The institution API client receives the verification outcome and its own member identifier, not a reusable Confío KYC profile. Direct bulk lookup by DNI, email, or phone is not supported.

### Representative request

```json
POST /v1/obligations
Idempotency-Key: cip-obligation-2026-09-102938

{
  "external_id": "cip:102938:2026-09",
  "subject": "subj_...",
  "commercial_amount": {"value": "50.00", "currency": "PEN"},
  "period": {"start": "2026-09-01", "end": "2026-09-30"},
  "due_at": "2026-09-10T23:59:59-05:00",
  "description": "Cuota CIP · septiembre 2026"
}
```

### Sandbox developer journey

Primary persona is a CIP/vendor backend engineer maintaining the membership database. Secondary personas are CIP finance/reconciliation, member support, security/privacy administration, and Confío's connector engineer. Human permissions, public API scopes, and connector credentials are documented in separate RACI tables.

A provisioned engineer must complete the production-shaped golden path without blockchain knowledge, a mobile install, or a meeting:

```text
T+0:00  Open hosted test webhook inbox with a test key
T+1:00  Create/import one seeded subject and PEN obligation
T+2:00  Receive IDs and a payer test link
T+3:00  Trigger a test-only synthetic finalized payment through the real finalizer/outbox
T+3:05  Verify signed payment.confirmed (including an intentional duplicate)
T+4:00  Trigger a CIP acknowledgement scenario
T+4:05  Verify institution.application_applied
T+5:00  Fetch a checksummed reconciliation report whose counts/totals balance
```

Target time-to-first-hello-world is under ten minutes after credential provisioning; five minutes is the stretch benchmark. Test-only scenario helpers reject live keys. A separate, slower BSC testnet certification exercises wallet signing and real receipt parsing before live approval.

Source-controlled developer kit:

- committed pilot OpenAPI as the API source of truth;
- copy-paste cURL quickstart and one complete Python integration example;
- generated Python/TypeScript clients used as CI smoke-test artifacts, not supported public SDKs;
- hosted webhook inbox, signed fixtures, Postman collection, and scenario controls;
- CIP connector mock plus golden active/inactive/past-due/already-paid/mismatch/timeout/rejection/duplicate/correction/refund fixtures;
- versioned UTF-8 batch manifest/files with `schema_version`, `batch_id`, `generated_at`, row count, SHA-256, minor-unit/date rules, formula-injection protection, dry-run validation, stable row errors, amendments, acknowledgements, and daily reconciliation manifest.

Documentation order is outcome-first: Overview; Quickstart; Sandbox; Core concepts; obligation/import, webhook, reconciliation, correction/refund, batch, and go-live guides; generated API reference; event decision table; errors/retries/idempotency/pagination/rate limits; CIP contract; privacy/security; operations/SLOs; changelog/migrations. Internal journal/finalizer architecture lives in engineering documentation, not before the quickstart.

Partner onboarding has four separate checklists, each naming owner, artifact, pass condition, escalation contact, and rollback action:

1. Institution approval: legal/data roles, identity manifest, settlement/refund authority, support, incidents, and commercial sign-off.
2. Technical sandbox: credential, OpenAPI, mock/fixtures, webhook verification, batch/API conformance, and reconciliation drill.
3. Live readiness: endpoint and credential-rotation verification, rate/batch limits, outage exercise, finance totals, cutover contacts, and rollback drill.
4. Post-live: status page, delivery/application SLO review, reconciliation sign-off, monthly access review, and incident cadence.

Measure developer outcomes separately from approval lead time: credential-to-first-success, first obligation creation, first verified webhook, first confirmed-payment event, reconciliation-drill completion, repeated error codes/docs searches, support contacts per integration, and sandbox-to-live conversion.

## 10. Webhooks

### Event catalog V1

- `subject.created`, `subject.updated`, `subject.linked`
- `invoice.created`, `invoice.payment_pending`, `invoice.paid`, `invoice.past_due`, `invoice.voided` are workflow notifications, not CIP ledger-booking facts
- `payment_intent.created`, `payment_intent.processing`, `payment_intent.succeeded`, `payment_intent.failed`
- `payment.confirmed` is the financially authoritative finalized-chain event; `payment.failed` is a terminal failed attempt, while `payment_intent.processing` is not financial success
- `institution.application_pending`, `institution.application_applied`, `institution.application_mismatch`
- `obligation.created`, `obligation.updated`, `obligation.held`, `obligation.paid`, `obligation.disputed`, `obligation.adjusted`
- `refund.recorded`, `refund.completed`, `refund.failed`
- `institution.member.verified`, `institution.member.verification_failed`
- `institution.data_transfer.completed`, `institution.data_transfer.failed`, containing field names and receipt IDs but not raw identity values
- `job.completed`, `job.failed`

### Delivery contract

- HTTPS only in live mode; reject localhost, link-local, private network, cloud metadata, embedded credentials, and unsafe redirects to prevent SSRF.
- Sign `timestamp.raw_body` with HMAC-SHA256. Header: `Confio-Signature: t=...,v1=...`.
- Include `Confio-Event-Id`, `Confio-Delivery-Id`, and `Confio-Api-Version`.
- Receiver tolerance: five minutes, constant-time compare, raw bytes before JSON parsing.
- Timeout: 10 seconds. No redirect following.
- Retry with jittered exponential backoff for up to 72 hours; stop on most permanent 4xx responses except 408/409/425/429.
- Delivery is at least once and may be out of order. Each event has a stable ID and resource version.
- General billing webhooks never contain DNI, full email, full phone, KYC documents, or raw institution-verification inputs. An institution receives approved identity values only through the dedicated consented transfer request, not through replayable billing events.
- Endpoint auto-disables after the retry horizon and alerts business owners/admins.
- Dashboard supports inspect, replay, secret rotation with overlap, and test events.
- Test mode provides a hosted webhook inbox, deterministic signed fixture payloads, and Python/Node/cURL-OpenSSL verification examples. Standard HTTPS tunnels are documented for local receivers; a custom relay CLI waits until generalization.
- Delivery inspection/retry is available through the API. Replay preserves event ID/body/schema version, creates a new delivery ID, and supports duplicate/out-of-order certification scenarios.
- Endpoints move to `failing` then explicitly resumable `paused` with owner alerts after the retry horizon; they are not silently and permanently disabled.
- `GET /events` repairs notification delivery but is not financial reconciliation. Snapshot reconciliation resources/reports are authoritative for period close.

### Reconciliation contract

`POST /reconciliation_runs` freezes a requested window and watermark/snapshot cursor. Its immutable downloadable manifest contains counts, PEN commercial totals, allocation/effect totals, exact settlement-leg totals by asset, CIP application totals, optional payout totals, exceptions, schema version, and SHA-256 checksum. Rerunning the same frozen snapshot yields the same report. Events prompt CIP to fetch; list endpoints and checksummed reports prove completeness.

Example event:

```json
{
  "id": "evt_...",
  "object": "event",
  "api_version": "2026-09-01",
  "created": 1788393600,
  "type": "payment.confirmed",
  "livemode": true,
  "data": {
    "object": {
      "id": "inv_...",
      "subject": "subj_...",
      "obligations": ["obl_..."],
      "status": "confirmed",
      "period_start": "2026-09-01T00:00:00-05:00",
      "period_end": "2026-10-01T00:00:00-05:00",
      "commercial_amount": {"value": "50.00", "currency": "PEN"},
      "settlement": {
        "gross": "13.42",
        "fee": "0.13",
        "net": "13.29",
        "asset": "CUSD_PLUS"
      },
      "payment": "pay_..."
    }
  }
}
```

## 11. CIP connector

Define a provider interface rather than embedding CIP calls in billing code:

```text
verify_member(lookup, consent_context) -> MemberVerification
get_obligations(member_id) -> list[ExternalObligation]
apply_effect(effect_id, effect_kind, allocation_revision, facts) -> acknowledgement
reconcile_member(member_id, since) -> InstitutionSnapshot
```

`apply_effect` covers payment, reversal, reallocation, and refund. Its idempotency key is the stable economic effect/revision, not a transport delivery ID. CIP acknowledges every affected allocation and authoritative status version.

Signed CIP tokens define issuer, audience, algorithm allowlist, key ID/rotation, environment, expiry/max lifetime, nonce/JTI replay protection, revocation, and clock skew. They authorize only an opaque subject and obligation references; amount and current status are reloaded from authority. Outbound calls require TLS validation, credential rotation, timeout budgets, retry classification, request signing or mTLS, schema/version negotiation, replay protection, and idempotent response semantics.

### Source-of-truth contract

- CIP owns member identity, chapter, dues policy, and legal `habilidad` status.
- Confío owns obligation mirror/payment/application state and on-chain evidence; CIP remains authoritative for the original obligation and legal membership status.
- Confío should not call a CIP endpoint synchronously inside BSC confirmation. It commits `payment.confirmed` first and lets an outbound connector worker notify CIP.
- CIP effect notification carries the semantic effect/revision as its idempotency key, opaque member ID, covered allocation/period, commercial amount, settlement facts, confirmation time, and transaction hash.
- A failed CIP acknowledgement never changes a confirmed payment back to unpaid. It leaves `application_pending`, creates an integration alert, and retries.
- A reconciliation job compares paid periods with CIP status and exposes mismatches to operators.

### CIP identity exchange

CIP should identify the normal pilot flow with a signed, short-lived token containing an opaque member reference and obligation references. CIP may legitimately require DNI, email, phone, or other fields only for documented fallback matching or a separately approved record-maintenance purpose. That does not make those fields ordinary merchant data.

The CIP connection must define a versioned data-requirement manifest before production:

| Field | Example purpose | Default treatment |
| --- | --- | --- |
| CIP member number | Locate the member record | Required, user-entered or CIP-issued; retained as an opaque external reference |
| DNI | Strong record match and duplicate prevention | Required only if CIP proves necessity; encrypted transfer, masked in Confío, never shown in the business dashboard |
| Verified email | Member contact or record recovery | Share verified claim/value only with explicit required-purpose disclosure |
| Verified phone | Member contact or step-up verification | Share normalized verified value only with explicit required-purpose disclosure |
| KYC status/name match | Confirm the Confío user matches the CIP member | Prefer boolean or signed claims over raw documents or full KYC records |
| Document images/selfie | Exceptional manual review | Not shared in the normal integration; requires a separate high-risk review and user action |

The user-facing receipt records who received which field categories, for what purpose, under which policy version, and when. Revocation stops future transfers but does not pretend to delete data already lawfully delivered to CIP; the UI instead points to CIP's deletion/contact process. A changed manifest or new purpose requires fresh authorization.

The fallback consent interaction is a dedicated CIP verification sheet, not a generic form checkbox. It identifies the recipient, places purpose/retention and required/optional status beside every field, leaves optional controls unchecked, offers `Continuar sin compartir` where possible, previews the exact transfer, and requires step-up authentication before DNI transfer. Success, partial failure, timeout, and interrupted-session states all produce a recoverable outcome. Privacy > Shared data shows the human-readable transfer receipt and CIP contact/deletion route.

Ordinary businesses get none of this capability. Eligibility requires verified institutional identity, an approved use case and privacy notice, named data controller/processor roles, field necessity, retention limits, incident contacts, and a manual Confío enablement. Billing API keys alone can never be upgraded into identity keys by changing a scope string.

Until CIP publishes an API, build against an OpenAPI mock and support encrypted CSV/SFTP-style batch exchange only if CIP operationally requires it. Do not make CSV semantics the core domain contract.

### CIP settlement contract — pilot go/no-go

Before real-value pilot payments, CIP and Confío must sign off on:

- the legally authoritative PEN obligation and receipt amount;
- settlement asset accepted by CIP (`cUSD`/`cUSD+`) and whether CIP can legally and operationally hold it;
- quote source, expiry, rounding, and who bears FX movement;
- 0.9% receiver deduction and any independent on-ramp/off-ramp/provider costs;
- whether Confío owes a PEN bank payout, including cadence, rate, liquidity owner, reference, and failure ownership;
- accounting export, reconciliation format, refund/correction treatment, and named treasury operators.

The pilot cannot launch merely because chain payment works. If CIP requires PEN bank settlement, completion for treasury reporting includes that payout milestone; member-facing payment proof and CIP application remain visible separately.

### CIP scale

400,000 members imply up to 4.8 million monthly obligations per year before reminders, events, and delivery attempts. Capacity planning covers three years, not only roster import:

- immutable import batches with source checksum/schema version, encrypted object-storage input/error artifacts, staging tables, set-based validation, chunked promotion, and stable row error IDs;
- no roster rows or PII in Celery arguments;
- indexes on `(business_id, external_id)`, schedule keys, due status/date, and event delivery status;
- tenant-aware partial indexes for due obligations, active schedules, pending deliveries, and reminder claims;
- scheduler uses deterministic period keys and keyset partitions, claims due rows with `select_for_update(skip_locked)` in bounded batches, and performs no network I/O while locked;
- pre-aggregate dashboard read models; define the launch-time event/delivery partition strategy from projected three-year row counts rather than deferring it until tables are large;
- never generate all monthly invoices in one transaction;
- spread reminders across local-time windows and enforce global/provider send limits;
- dashboards use aggregates/read models, not live scans of all invoices.

## 12. Reminder policy

Default CIP policy in `America/Lima`:

- invoice available: immediately;
- pre-due: 7 days and 2 days before;
- due date: morning local time;
- overdue: 3, 10, and 20 days after;
- stop immediately when paid, voided, or disputed;
- never send duplicate reminders for the same policy step;
- quiet hours and user notification preferences apply, except legally required in-app notices;
- expose business-configurable templates only within approved transaction-message constraints to prevent spam/phishing.
- every reminder deep-links to the exact obligation and revalidates already-paid/account-mismatch state on open;
- lock-screen copy defaults to `Tienes un pago pendiente de CIP` without amount, debt period, or membership status; richer detail requires an explicit notification preference;
- define dismissed, snoozed, expired-link, already-paid-on-open, and wrong-account behavior without creating duplicate reminders.

Store a `ReminderDelivery` keyed by `(billing_invoice, policy_step, channel, recipient)` so scheduler retries cannot duplicate a reminder.

## 13. Yape top-up handoff

The payment and ramp are separate state machines. The invoice must never be marked processing merely because the user started a top-up.

Required UX contract:

1. calculate shortfall from fresh spendable cUSD/cUSD+ value;
2. show the exact payment amount and top-up quote separately;
3. create the ramp order through the existing provider path;
4. render/copy a Yape-interpretable QR using provider-issued data;
5. persist `return_to=confio://billing/invoices/{id}`;
6. wait for provider webhook/reconciliation to confirm funds;
7. return to invoice detail and require an explicit `Pagar` signature;
8. if the quote expires or funding is partial, refresh without losing the invoice context.

No screen may imply that scanning the Yape QR pays CIP directly. It funds the user's Confío wallet; the subsequent signed transaction pays CIP.

## 14. Security and compliance

- API keys: 256-bit random secrets, prefix lookup plus Argon2/HMAC-backed verification, one-time reveal, scope and mode binding, rotation, expiry, revocation, audit log.
- Separate the KYC identity vault from billing storage. Billing code receives typed claims or an authorized transfer handle, not unrestricted ORM access to `IdentityVerification`.
- Encrypt retained DNI, email, and phone values with connection-specific envelope keys. Use keyed blind indexes only for exact matching where strictly necessary; never expose those indexes externally.
- Enforce field-level authorization in the identity service, not only in REST serializers or the dashboard. Business ownership and `manage_billing` are insufficient.
- Require a versioned, explicit user grant before each new institution/purpose/field-set combination. Store the consent receipt and show it to the user under Privacy > Shared data.
- Distinguish required and optional data. Refusal of an optional field cannot block payment or enrollment; refusal of a genuinely required field explains why CIP cannot verify the membership.
- Minimize retention: prefer direct server-to-server delivery and retain the value only as long as needed for retry/reconciliation. Keep long-lived audit receipts without raw values.
- Never place raw identity values in events, Celery arguments, URLs, analytics, support screenshots, or application logs.
- Never accept `business_id`, settlement address, merchant address, fee, net, or chain from an untrusted API caller as settlement authority. Resolve them from the authenticated business and server configuration.
- Public payment links use unguessable tokens and expose the minimum invoice data before authentication.
- Link an obligation subject to a wallet only after authenticated proof and institution identity matching; prevent account-link takeover.
- Webhook endpoint validation protects against SSRF on registration and every delivery after DNS resolution.
- Outbound payloads exclude raw KYC documents, full national IDs, wallet private data, API credentials, and unnecessary phone/email fields.
- Immutable audit records cover API key operations, schedule/obligation changes, invoice voiding, event replay, and institution overrides.
- All financial mutations use database transactions and row locks around state transitions.
- Separate test/live data logically and cryptographically. Test events can never call live CIP endpoints.
- Define retention and deletion rules with institutional contracts and Peruvian data-protection counsel before production.
- Provide disputes and support escalation in V1 even though automated refunds are deferred.

## 15. Failure modes and rescue

| Failure | User/business impact | System response |
| --- | --- | --- |
| CIP API unavailable during enrollment | Member cannot be verified | Show retryable status, retain entered member number securely, no subject/obligation linkage |
| CIP API unavailable after payment | Payment succeeds but CIP status lags | Keep invoice paid, retry connector, alert operators, expose sync state |
| Chain outcome unknown | User could pay twice | Lock invoice in `payment_pending`; reconcile receipt/batch before allowing retry |
| Webhook endpoint down | Institution misses real-time event | Retry 72h, show logs, alert, permit replay and `/events` reconciliation |
| Scheduler reruns | Duplicate monthly invoices | Unique period constraint plus idempotent generation |
| Reminder worker reruns | Duplicate push spam | Unique reminder-step delivery key |
| Price changes mid-period | Incorrect charge | Immutable price and invoice line snapshot; change applies next period unless explicit proration policy |
| Member linked to wrong Confío user | Privacy loss or wrong payer prompts | Verified linking flow, unlink audit, support hold, never key by phone, email, or DNI alone |
| Ordinary merchant requests identity scopes | Customer data exposure | Deny structurally; only reviewed institution connections can create identity sessions |
| CIP changes required fields or purpose | Stale consent used for new processing | Version the manifest and require a fresh user grant |
| Identity transfer succeeds but response is lost | Duplicate values or member mutation | Transfer ID as idempotency key; retry same request, retain receipt state |
| Shared-data worker/log leaks payload | High-impact privacy incident | Pass encrypted handles, redact centrally, alert and follow incident runbook |
| User lacks funds | Payment blocked | Show shortfall and Yape top-up handoff; obligation remains open |
| User ignores reminders | Membership may lapse | Past-due state, business policy/webhook; no wallet action without signature |
| API client retries mutation | Duplicate subject/obligation/effect | Required idempotency key with request-body fingerprint |
| Payment event duplicated/out of order | CIP double-applies dues | Stable event/payment IDs, resource versions, idempotent CIP handler contract |
| Business key compromised | Unauthorized billing operations/data read | Scopes, rate limits, rotation/revoke, anomaly alerts; keys cannot move wallet funds |

## 16. Observability and operations

Metrics:

- reachable-member rate by CIP-owned link/channel;
- obligation view -> authenticated payer -> funded wallet -> signature -> confirmation conversion;
- completion, total landed cost, and time-to-paid versus CIP's current collection rail;
- median/p95 payment-confirmed -> CIP-applied time and mismatch rate;
- incremental net collections, contribution margin, and total take rate;
- support contacts and manual interventions per 100 successful payments;
- invoice generation lag and failures;
- open/past-due/paid counts and amount by business;
- reminder delivery success and opt-out rates;
- payment prepare-to-confirm latency and outcome-unknown backlog;
- webhook success, latency, retry queue depth, disabled endpoints;
- institution verification/notification latency and reconciliation mismatch count;
- API latency/error/rate-limit metrics by endpoint and mode;
- import throughput and rejected-row reasons.

Every request carries a public request ID across API logs, domain commands, events, webhook deliveries, and institution calls. Never log secrets, full auth headers, raw identity documents, or full sensitive identifiers.

Runbooks must cover chain congestion, sponsor failure, webhook backlog, notification provider failure, CIP outage, compromised business key, and reconciliation mismatches.

Before pilot, convert operational metrics into owned warning/critical SLOs for confirmation-finalization lag, oldest outcome-unknown payment, oldest stranded sponsored batch, oldest outbox delivery, oldest CIP application, reconciliation imbalance, import failure/lag, and payout breaks. Each alert declares pager versus ticket behavior, cardinality budget, owner, dashboard, and runbook; numeric thresholds are set from sandbox/load baselines and CIP's contracted application SLA.

## 17. Testing strategy

### Domain tests

- calendar anchors including February, leap years, month-end, timezone/DST behavior;
- exactly-once period creation under concurrent schedulers;
- status transition table, cancellation, pause/resume, and late payment;
- immutable price/invoice snapshots and fee ceiling parity;
- partial/duplicate/out-of-order event handling;
- customer linking and business isolation.
- institution manifest versioning, required/optional field behavior, consent and revocation;
- field-level authorization proving billing owners and standard API keys cannot read identity;
- encryption/blind-index behavior and log/event redaction;
- direct-transfer retry/idempotency without durable plaintext duplication.
- subject/payer/funding-account separation and pay-on-behalf privacy;
- PEN obligation plus expiring settlement quote, rounding, FX provenance, and receiver-fee arithmetic;
- obligation allocation, holds, disputes, adjustments, reallocation, and refund records;
- payment confirmation and institution application never collapse or roll each other back.
- property tests prove conservation of PEN minor units and exact token/share base units across randomized payments, allocations, inverse corrections, reallocation, fee rounding, routed settlement, and refunds;
- every aggregate transition table is tested for allowed actor, precondition, effect, emitted event/version, idempotent replay, and terminality.

### Database, migration, and fault-injection tests

- PostgreSQL `TransactionTestCase` races for duplicate prepare/submit, two direct-cUSD batches, duplicate confirmer workers, scheduler/import claims, allocation/correction conflicts, outbox leases, and API idempotency leases;
- kill the finalizer after every persistence boundary and prove retry converges to one journal effect, projection, settlement, application set, and outbox set;
- rehearse expand/shadow/canary/rollback migrations against legacy invoice/payment fixtures and preflight ambiguous sponsored batches;
- verify new financial evidence survives actor/account erasure without cascading deletion.

### API contract tests

- auth scopes and test/live separation;
- idempotency replay and same-key/different-body rejection;
- cursor pagination stability;
- stable error objects and request IDs;
- bulk import partial failures;
- OpenAPI schema compatibility and generated SDK smoke tests.

### Webhook tests

- raw-body signature vectors, timestamp tolerance, secret overlap rotation;
- retry classification/backoff, duplicate delivery, replay, endpoint disable;
- SSRF cases including redirects, DNS rebinding, IPv6, and cloud metadata ranges.

### Payment integration tests

- billing invoice -> current `Invoice` attempt -> BSC prepare/submit -> confirmation -> atomic billing finalization;
- insufficient balance -> Yape top-up return -> pay;
- reverted, dropped, reorged, and outcome-unknown batches;
- one billing invoice cannot produce two successful payments;
- Pay-contract fee and replay protection remain unchanged.
- finalized `PaymentMade` log values, cUSD/cUSD+ routing output, token decimals/base units, contract version, and log coordinates exactly match persisted settlement legs;
- existing public GraphQL invoice access is restricted/deprecated before institutional payment links; negative tests cover anonymous, unrelated payer, cashier, ordinary API key, and cross-business access.

### CIP contract and correction tests

- token issuer/audience/environment/key rotation/expiry/JTI/revocation/clock skew;
- duplicate, delayed, lost, rejected, mismatched, and schema-versioned `apply_effect` acknowledgements per allocation revision;
- payment, inverse correction, reallocation, and refund effects converge under out-of-order delivery;
- no raw PII appears in DTOs, events, Celery arguments, logs, artifacts, exports, notifications, or support screens.

### Scale tests

- 400,000-customer import;
- monthly invoice generation in partitioned batches;
- reminder burst smoothing;
- webhook backlog and recovery;
- list/dashboard query plans on production-shaped data.
- one-day webhook/CIP outage and backlog recovery within SLO without starving old rows;
- three-year event/delivery/reminder volume and partition/index maintenance budgets.

### End-to-end test flow

```text
CIP API/import/schedule -> obligation/invoice -> quote/intent/funding session
  -> legacy Invoice -> prepare/submit -> SponsoredBatch -> finalized receipt
  -> locked finalizer -> effect + allocations + settlement legs + outbox
  -> webhook / CIP application / optional payout
  -> correction/refund/reconciliation until every ledger balances
```

At every arrow test duplicate/concurrent input, authorization failure, stale terms, process crash, retry, timeout, out-of-order delivery, and recovery. Mobile E2E additionally covers process death, second-device return, quote expiry/change, double tap, already-paid link, confirmed-payment/CIP-pending, and `No vuelvas a pagar` rescue.

## 18. Rollout plan

### Gate 0: commercial and operational proof (weeks 0–2)

- Obtain a named CIP pilot owner, bounded chapter/cohort, representative obligation/roster sample, current-rail funnel and cost baseline, support/treasury owners, and written pilot intent.
- Agree authoritative PEN amounts, fee presentation, settlement asset/payout, FX responsibility, receipts, correction/refund ownership, and landed-cost ceiling.
- Agree signed opaque-member link/token, API or batch schemas, status semantics, covered-period/allocation rules, idempotency, availability, incident contacts, and data-controller responsibilities.
- **Kill/no-launch gate:** no real-value build-out without an operable settlement agreement, usable source data, and named CIP counterparties.

### Deployment sequence across phases

1. Add a new `billing` Django app and additive nullable tables/constraints; preflight and fix BSC active-batch uniqueness first.
2. Deploy a dual-compatible, billing-aware finalizer dark by default. Do not backfill ordinary historical invoices into obligations.
3. Run shadow finalization for sandbox/test rows and reconcile its journal/events against legacy payment truth.
4. Enable creation and dispatch for one internal institution, then a bounded CIP cohort behind separate flags.
5. Add/validate large indexes concurrently when volume justifies them; tighten constraints and cut reads only after shadow comparison passes.
6. Rollback disables new obligation/payment creation but continues confirmation, outbox, CIP, payout, and reconciliation workers until every in-flight row is terminal. Real-value financial rows are never reverse-migrated or deleted.

### Phase 1: thin kernel and sandbox (weeks 2–4)

- Introduce obligation subjects, obligations, allocations, payment intents, payments, application state, settlements, corrections, and event outbox.
- Wrap the existing BSC invoice settlement without changing the Pay contract.
- Build the CIP OpenAPI mock/batch adapter, signed-token verifier, test-mode API/webhooks, and operator exception queue.
- **Kill/redesign gate:** prove idempotent end-to-end sandbox reconciliation, corrections, and refunds before member UX scale work.

Implementation note (2026-09-04): the disabled-by-default CIP simulator now
persists synthetic member status and application receipts, exposes protected
verification/application contract endpoints, issues opaque one-use mobile links,
and includes idempotent pilot seeding plus operator admin actions. Automated
PostgreSQL coverage proves privacy, replay/mismatch handling, and confirmed
payment-to-`habilidad` application. Physical-device signing, BSC certification,
correction/refund drills, and production-shaped load remain release evidence,
not simulated launch approval.

### Phase 2: concierge cohort pilot (weeks 4–6)

- Pilot one CIP chapter or bounded cohort with CIP-owned invitation links, obligation import, PEN display, Yape-compatible top-up return, explicit signature, receipts, CIP application status, and daily human reconciliation.
- Support pay-on-behalf, operator holds/corrections, and manual refund recording before increasing limits.
- Benchmark the full wallet funnel against CIP's current rail; if contractually possible, compare a direct local-payment route rather than assuming wallet exclusivity wins.
- **Expansion gate:** thresholds are agreed before launch for reachability, completion, time-to-application, landed cost, mismatch rate, contribution margin, and support burden.

### Phase 3: operational hardening (weeks 6–10)

- Add approved recurring schedules only where CIP rules are uniform; otherwise continue importing authoritative obligations.
- Add reminder-channel orchestration, reconciliation reports, settlement exports, retry/runbooks, and progressive cohort limits.
- **Scale gate:** no nationwide roster fan-out until the bounded cohort meets all thresholds for two consecutive obligation cycles.

### Phase 4: selective generalization

- Onboard a second institution through the same kernel and record every abstraction that fails or requires institution-specific branching.
- Only after repeated demand, promote products/prices/schedules, self-service keys/webhooks, public docs, SDKs, CLI helpers, usage limits, and generic dashboards.
- A 400,000-member CIP rollout and broad platform GA are separate decisions; neither follows automatically from a successful small pilot.

## 19. Explicitly not in V1

- Automatic or pre-authorized wallet debit.
- Changing the Pay contract solely for subscriptions.
- Voting or CIP election functionality.
- Automated self-service refunds, chargebacks, proration, metered billing, usage billing, coupons, trials, or tax calculation. Operator corrections and auditable manual refund reconciliation are required.
- General-purpose email/SMS marketing.
- Confío deciding CIP legal membership status independently of CIP.
- Direct Yape-to-CIP payment masquerading as a Confío wallet transaction.

These can be added later without changing the thin-kernel resource model.

## 20. Open decisions requiring confirmation

1. Price presentation per product: `payer_amount` or `receiver_net_target`. In both cases the contract subtracts 0.9% from gross; net-target mode simply grosses up the disclosed payer price.
2. CIP identity manifest: CIP must specify which of DNI, verified email, verified phone, or other attributes are required versus optional, with a purpose and retention period for each, before implementation can be finalized.
3. Enrollment authority: the recommended default is that CIP verification is required before a member is linked to CIP obligations, with no manual self-attestation fallback.
4. Membership authority: the recommended default is that CIP computes `habilidad`; Confío sends immutable payment facts and displays CIP's returned status plus last-sync time.
5. Past-due policy: the recommended default is to keep old periods individually payable and never silently roll debt into the current month.
6. Channel scope: start with in-app plus push. Add email/SMS only if CIP supplies verified contact authority, consent, templates, and delivery ownership.
7. Pilot success thresholds: CIP and Confío must set numeric minimums for reachability, completion versus current rails, time-to-application, landed cost, mismatch, contribution margin, and support burden before inviting members.
8. Settlement: CIP must choose accepted token settlement or contracted PEN payout and assign FX/liquidity/accounting ownership before real-value launch.

## 21. Review scorecards and implementation tasks

### Dream-state delta and existing leverage

The dream state is not generic Stripe parity. It is an institution-neutral collection kernel where a person can open an exact obligation, fund and sign safely, obtain immutable payment proof, see the institution apply it, and let both sides close a period with zero unexplained balance. The CIP pilot now validates that outcome before self-service platform breadth.

Existing code reused rather than replaced:

- `payments.Invoice` and `PaymentTransaction` as short-lived payment-attempt records;
- BSC prepare/submit, sponsored EIP-7702 execution, Pay-contract fee/replay behavior, and finalized receipt pipeline;
- current Yape-compatible ramp provider/order flow and React Native payment/ramp service patterns;
- existing notification/Celery infrastructure, provided new side effects are durable and queued after commit;
- existing JWT/dashboard permission concepts, while public API and identity principals remain separately enforced.

Explicit gaps fixed before reuse are the missing `pay_cusd` active-batch uniqueness, newest-300 reconciliation starvation, unlocked/stale confirmation seam, and overly broad legacy invoice DTO/resolver access.

### Dual-voice consensus

| Phase | Shared conclusions | Material disagreement | Resolution |
| --- | --- | --- | --- |
| CEO | CIP-first outcome, obligation over subscription, settlement/economics gate, opaque identity token, distinct application state, corrections, payer/subject split | How long to wait before generalizing | User chose thin kernel + CIP-first; second-institution evidence gates broad surface |
| Design | Persistent task screen, two-stage receipt, exact top-up recovery, consent fallback, pay-on-behalf, operator queue, accessibility | `Cuotas` vs `Cuotas y pagos`; dedicated CIP hub vs generic area | Copy defaults to `Cuotas y pagos`; hub choice remains the one taste gate |
| Engineering | Rail prerequisite, append-only journal, locked finalizer/outbox, exact settlement legs, full-balance pilot, expand/contract rollout | No material architecture disagreement | All incorporated; settlement/refund authority remains a CIP contract input |
| DX | Pilot-only API, deterministic sandbox, canonical event semantics, snapshot reconciliation, scopes/errors/versioning, CIP contract kit | Five-minute promise vs under-ten target; custom relay vs hosted inbox | Under ten is acceptance with five-minute stretch; hosted inbox + standard tunnels, custom CLI deferred |

### Cross-phase themes

- **Outcome over platform breadth:** CEO, engineering, and DX independently rejected exposing generic catalog/subscription breadth before the CIP outcome is proven.
- **Truthful multi-stage state:** CEO, design, engineering, and DX require payment confirmation, CIP application, and optional payout to remain separate.
- **Recovery is part of the product:** CEO, design, and engineering require correction/refund, exception ownership, and `do not repay` rescue before real value.
- **Identity minimization:** CEO, design, engineering, and DX prefer CIP-signed opaque references; sensitive fallback sharing is purpose-scoped and separately authorized.
- **Reconciliation over notification:** CEO, engineering, and DX treat webhooks as prompts and checksummed resource snapshots/journal evidence as accounting authority.

### Review completion summary

The plan is implementation-ready for Gate 0 commercial work and sandbox architecture after final approval. It is deliberately not approved for real-value launch: CIP settlement/FX, refund authority, accounting convention, API/batch capability, identity necessity, application SLA, and numeric pilot thresholds must be resolved in Gate 0. All four reviews produced build-actionable tasks and acceptance evidence; the standalone test artifact is `docs/payments/RECURRING_PAYMENT_PLATFORM_TEST_PLAN.md`.

### Design review scorecard

| Dimension | Before | Planned | Acceptance evidence |
| --- | ---: | ---: | --- |
| Information architecture | 6/10 | 9/10 | CIP-first hub/task entry and no premature platform navigation |
| Interaction-state coverage | 4/10 | 9/10 | Executable state matrix for top-up, pay, application, links, and exceptions |
| User journey and trust | 7/10 | 9/10 | Two-stage receipt and `No vuelvas a pagar` rescue flow tested |
| Specificity / AI-slop resistance | 6/10 | 9/10 | Evidence-driven operator queue; no generic card-grid dashboard |
| Design-system alignment | 6/10 | 9/10 | Existing tokens/components and semantic status palette in mockups |
| Responsive and accessibility | 3/10 | 9/10 | Small-phone, tablet, 200% text, screen-reader, offline, and QR-alternative QA |
| Unresolved design decisions | 6/10 | 9/10 | CIP hub versus generic memberships choice approved before build |

### Design implementation tasks

- **DES-01 — Member task flow:** Produce linked mockups/specs for every screen-level payment state, including app termination and another-device return. Acceptance: no transition requires an engineer to invent copy, CTA, preserved data, or retry behavior.
- **DES-02 — Two-stage receipt:** Extend existing success/receipt components for Confío confirmation and CIP application. Acceptance: delayed/rejected CIP never changes confirmed-payment truth or invites repayment.
- **DES-03 — Consent fallback:** Design opaque-token success and sensitive fallback transfer, including step-up, decline, partial failure, receipt, and revocation entry. Acceptance: optional fields are never preselected and values never appear in generic surfaces.
- **DES-04 — Pay on behalf:** Cover link preview, revalidation, terminal states, payer/subject separation, and constrained receipt. Acceptance: payer cannot navigate to subject history or identity.
- **DES-05 — Operator exceptions:** Design desktop/tablet queue + case timeline, actions, previews, dual approval, and narrow-screen review-only layout. Acceptance: every failure-mode row maps to an owned queue/action or documented automated recovery.
- **DES-06 — Inclusive QA:** Verify contrast, focus, screen-reader announcements/order, reduced motion, large text, long Spanish strings, offline/stale timestamps, and QR alternatives on target devices.

### Engineering workstreams

| Stream | Depends on | Deliverable and acceptance |
| --- | --- | --- |
| ENG-A Existing rail | — | Fix `pay_cusd` active-batch uniqueness/adoption and starvation-free reconciliation; adversarial races produce one broadcast owner and one finalization for every payment kind |
| ENG-B Journal/schema | A for live linkage | Obligations, invoice joins, effects, allocations, quotes, settlement legs, payout/refund evidence, DB invariants, and additive migrations; conservation properties pass |
| ENG-C Finalizer/outbox | A + B | Locked idempotent finalizer with immutable events/deliveries; crash at every boundary converges with no duplicate effects or missing events |
| ENG-D API/auth | B | REST/OpenAPI, dedicated principals, tenant/scopes, DTO allowlists, rate limits, and mutation idempotency; full negative-access matrix passes |
| ENG-E Webhooks/CIP | B + C | Durable fan-out, semantic `apply_effect`, signing, retries, replay, SSRF/rebinding defense, connector versions; duplicate/delayed/mismatched effects converge |
| ENG-F Mobile/funding | B + D contracts | Resumable top-up/sign/confirmation/application state machine; process-death and second-device E2E pass |
| ENG-G Import/operations | B + C + E | Staging import, deterministic generation/reminders, SLOs, reconciliation, exceptions, and runbooks; agreed load/backlog budgets pass |

### Engineering build tasks

- **ENG-01 P1:** Fix canonical active sponsored-batch uniqueness for `pay_cusd` and all payment kinds; add migration preflight, race adoption, and concurrent tests.
- **ENG-02 P1:** Replace newest-300 stranded-payment reconciliation with oldest-first/keyset claims and oldest-age alerting.
- **ENG-03 P1:** Freeze journal schema, transition tables, full-balance pilot rule, exact unit/rounding equations, and database constraints.
- **ENG-04 P1:** Refactor confirmation into the locked finalizer and durable outbox, with `transaction.on_commit` side effects only.
- **ENG-05 P1:** Persist finalized contract event evidence and reconcile routed/multi-leg settlement exactly.
- **ENG-06 P1:** Resolve CIP settlement/refund/signing authority and encode payout/refund milestones before real value.
- **ENG-07 P1:** Implement dedicated REST principals, tenant-safe DTOs, scopes, mutation idempotency, and restricted legacy GraphQL access.
- **ENG-08 P1:** Implement event fan-out, webhook/CIP delivery, aggregate ordering/versioning, replay, SSRF/rebinding defenses, and reconciliation.
- **ENG-09 P1:** Implement signed CIP tokens, connector compatibility/security, per-allocation effects, and PII leakage tests.
- **ENG-10 P2:** Implement staging imports, deterministic schedule/reminder claims, and capacity/partition plan.
- **ENG-11 P2:** Bind the resumable mobile payment experience to frozen API contracts.
- **ENG-12 P2:** Rehearse expand/shadow/canary/rollback; add SLO dashboards, alerts, exception operations, and runbooks.

### Partner personas and authority

| Persona | Primary job | Human permission / machine scope boundary |
| --- | --- | --- |
| CIP integration engineer/vendor | Exchange obligations, receive events, reconcile | Test/live API scopes granted explicitly; no dashboard owner or identity rights implied |
| CIP finance/reconciliation operator | Close totals, settlement/payout, approve financial corrections | Read settlement/reconciliation; correction/refund approval is separate and step-up protected |
| CIP member-support operator | Resolve member cases without moving value | Masked case data, notes/escalation; no raw identity export or financial approval |
| CIP security/privacy administrator | Credentials, identity manifest, access review | Connector/identity configuration; cannot create payments or approve refunds by default |
| Confío connector operator | Operate adapter, retries, version compatibility | Infrastructure/application actions; cannot view raw transferred identity without break-glass |

The codebase's human permission registries must be centralized or mechanically checked for drift. Human permissions, public API scopes, and connector principals all deny unknown capabilities by default.

### Developer-experience scorecard

| Dimension | Before | Planned | Acceptance evidence |
| --- | ---: | ---: | --- |
| Institution personas | 4/10 | 9/10 | Persona/RACI and separate principal classes tested |
| Time to first sandbox payment | 2/10 | 9/10 | Provisioned newcomer finishes golden path in <10 minutes; stretch <5 |
| API/resource design | 4/10 | 9/10 | Pilot-only OpenAPI and resource/event dictionary pass consistency tests |
| Errors/debugging | 3/10 | 9/10 | Stable examples/codes, request IDs, retry guidance, delivery inspection |
| Documentation | 2/10 | 9/10 | Outcome-first quickstart and partner kit complete without a meeting |
| Upgrade/versioning | 3/10 | 8/10 | Breaking-diff CI, pinned webhooks, changelog/migration policy |
| Developer tooling | 4/10 | 8/10 | Hosted inbox, fixtures, temporary generated clients, batch mock |
| Reconciliation/handoff | 5/10 | 9/10 | Frozen checksummed report and certification drill |
| DX measurement | 4/10 | 8/10 | Funnel and frequent failure telemetry visible by test/live mode |

### Developer-experience build tasks

- **DX-01 P0 — Freeze pilot API:** Source-controlled OpenAPI exposes only subjects, obligations, payment links/intents/payments, applications, settlements, events/webhooks, imports/jobs, corrections/refunds, and reconciliation. No example calls a deferred resource.
- **DX-02 P0 — Golden sandbox:** One documented script completes subject/obligation → synthetic real-finalizer payment → signed duplicate webhook → CIP application → balanced report in under ten minutes; helpers reject live keys. Separate BSC certification proves the real rail.
- **DX-03 P0 — Event/resource dictionary:** Every prefix, enum, object discriminator, relationship, aggregate version, and event owner is consistent across database, OpenAPI, fixtures, and webhooks; consumer decision table identifies ledger-booking facts.
- **DX-04 P0 — Snapshot reconciliation:** Closed-window report reproduces identical counts/totals/checksum and lists every exception.
- **DX-05 P1 — Principals/scopes:** Negative tests cover every persona, scope, mode, tenant, revoked/expired key, identity boundary, and connector credential.
- **DX-06 P1 — Idempotency/errors/concurrency:** Contract tests cover exact replay, body mismatch, in-progress retry, retention, stale `If-Match`, bulk row IDs, HTTP mappings, request IDs, and retryability.
- **DX-07 P1 — Webhook tooling:** Hosted inbox, signature vectors and Python/Node/cURL examples, delivery inspection/retry, duplicate/out-of-order fixtures, secret overlap, paused/resume behavior, and retention policy work in test mode.
- **DX-08 P1 — CIP contract kit:** API and versioned batch transports pass the same provider suite with golden scenarios, checksums, dry-run validation, amendments, stable errors, acknowledgements, corrections, and PII redaction.
- **DX-09 P1 — Compatibility CI:** OpenAPI lint/breaking diff, generated-client smoke tests, webhook-version upgrade preview, changelog, support window, and migration template are release-blocking.
- **DX-10 P2 — Partner operations:** Approval, sandbox, live-readiness, post-live, outage, credential-rotation, reconciliation, and rollback checklists have owners and pass conditions; developer funnel instrumentation is live.

## Decision Audit Trail

| # | Phase | Decision | Classification | Principle | Rationale | Rejected |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Intake | Model recurring payments as recurring obligations requiring explicit signatures | Mechanical | Non-custodial correctness | Matches the wallet security model and the stated product constraint | Merchant-initiated automatic debit |
| 2 | Intake | Reuse the existing BSC invoice settlement and Pay contract | Mechanical | DRY | Existing fee, sponsor, replay, and confirmation invariants already solve settlement | New subscription contract/rail |
| 3 | Intake | Separate durable billing invoices from short-lived current `Invoice` attempts | Architectural | Explicit over clever | The current 24-hour invoice cannot represent a monthly obligation safely | Extending legacy invoice lifetime/state indefinitely |
| 4 | Intake | Build CIP through a generic institution connector | Architectural | Completeness | Keeps billing reusable and isolates an API that does not exist yet | CIP-specific billing tables and endpoints |
| 5 | Clarification | Always deduct the 0.9% fee from receiver gross | Settled product rule | User direction | Matches the Pay contract and current payment economics | A separate payer-side contract fee |
| 6 | Clarification | Support receiver-net pricing by grossing up the advertised payer amount | Architectural | Explicit over clever | Preserves one settlement rule while allowing a business to target its desired net | Hidden fee switching or a second contract path |
| 7 | Privacy | Separate billing permissions from institution identity sharing | Security boundary | Least privilege | A merchant's right to collect payment does not imply a right to customer identity | Exposing KYC/contact fields through customer objects |
| 8 | Privacy | Use consented, purpose-scoped direct transfers with verified claims by default | Security boundary | Data minimization | Supports CIP's legitimate verification needs without creating a general customer-data product | Bulk merchant access to raw Confío identity records |
| 9 | CEO review | Adopt thin generic kernel plus CIP-first pilot | User challenge | User decision: option C | Preserves the reusable domain while making broad platform scope contingent on evidence | Full Stripe-like platform before pilot; CIP-only fork |
| 10 | CEO review | Use obligation as the core object and treat schedules as optional issuers | Architectural | Explicit over clever | Institutional debt has externally sourced amounts, adjustments, and allocations that a uniform subscription cannot represent | Subscription as universal source of truth |
| 11 | CEO review | Separate subject, payer, and funding account | Architectural | Completeness | Enables relatives, employers, or businesses to pay without receiving member identity access | One customer equals one payer |
| 12 | CEO review | Prefer CIP-signed opaque member tokens before identity transfer | Security boundary | Data minimization | Avoids a speculative identity-sharing platform and reduces regulatory exposure | DNI/email/phone as normal enrollment keys |
| 13 | CEO review | Separate chain confirmation, institution application, and optional fiat payout | Architectural | Explicit over clever | Users, CIP operations, and treasury need distinct truthful milestones | One `paid` flag for every outcome |
| 14 | CEO review | Require corrections and manual refund reconciliation before real-value pilot | Scope correction | Completeness | Irreversible payments need a safe operator rescue path | Deferring all refund/correction mechanics |
| 15 | Design review | Use one persistent obligation task screen with resumable server state | Interaction architecture | Completeness | Top-up, return, signing, and asynchronous confirmation must survive restarts without losing context | Separate disposable success/loading screens |
| 16 | Design review | Present payment confirmation and CIP application as a two-stage timeline | Interaction architecture | Explicit over clever | Prevents a successful chain payment from being confused with institutional status update | One generic success state |
| 17 | Design review | Build an exception task queue with append-only corrective actions | Operational UX | Completeness | Operators need evidence, ownership, SLA, preview, and auditability | Generic dashboard cards or editing source payments |
| 18 | Design review | Use a lightly branded CIP hub for the pilot | Taste, user approved | Narrowest useful wedge | Makes the first institution legible without prematurely teaching generic platform nouns | Generic memberships destination from day one |
| 19 | Engineering review | Treat active-batch uniqueness and reconciliation starvation as prerequisite rail fixes | Correctness | Fix the root invariant | Existing `pay_cusd` and newest-window behavior are unsafe at higher volume | Assuming the current rail needs no hardening |
| 20 | Engineering review | Use an append-only minor/base-unit payment journal and exact event-derived settlement legs | Architecture | Explicit over clever | Proves conservation across PEN, token/share units, allocations, corrections, routing, and refunds | Mutable balances as accounting authority |
| 21 | Engineering review | Pilot exact full-balance payments only | Scope reduction | Simplicity | Avoids reservation and concurrent partial-tender complexity while leaving the journal extensible | Partial payment in the pilot |
| 22 | Engineering review | Add a locked idempotent finalizer and transactional fan-out | Correctness | Completeness | Closes stale-object, double-finalization, crash, and missing-event windows | Adding billing saves to the current confirmer |
| 23 | Engineering review | Keep financial evidence immutable across account erasure and rollback | Data durability | Explicit over clever | Accounting truth must survive lifecycle operations and deployment reversal | Cascade deletion or reverse-migrating real-value rows |
| 24 | DX review | Publish only institutional thin-kernel resources in pilot `/v1` | Scope reduction | User-selected option C | Makes the copy-paste contract match the roadmap instead of advertising deferred Stripe-like breadth | Feature-flagged future resources in public V1 |
| 25 | DX review | Use fast synthetic finalizer sandbox plus separate BSC certification | Developer journey | Action beats abstraction | Delivers a quick deterministic first success without weakening real-rail assurance | Mobile/testnet required for hello world; simulation as sole certification |
| 26 | DX review | Make checksummed resource snapshots—not event history—the reconciliation authority | API architecture | Explicit over clever | Webhooks notify; accounting closure needs stable complete resources and totals | Treating `/events` as the financial ledger |
| 27 | DX review | Use hosted webhook inbox and standard tunnels in the pilot | Scope reduction | Simplicity | Gives zero-install/local paths without building a custom CLI before demand | Custom relay CLI in pilot; dashboard-only testing |
