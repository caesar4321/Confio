# VEXPay integration for Venezuela (design)

**Status**: on-ramp and off-ramp built (2026-10-24); off-ramp dark behind
`VEXPAY_OFFRAMP_ENABLED` and `VEXPAY_SEND_MIN_APP_VERSION`.
**Scope**: Venezuelan on-ramp (bolívares → USDT on BSC in the user's wallet) and
off-ramp (USDT on BSC → bolívares by Pago Móvil to the user or a third party),
both through VEXPay as the first provider. Built so a later provider (Pago
ASAP, Bolívar Connect) can replace either direction without app changes.

## Why `ramps/`, not `payment_accounts/`

VEXPay is a ramp: money moves between a local rail and the user's wallet, with
no virtual account in the user's name. `ramps/` already does exactly that for
Koywe's `cusd_plus` rail:

- `RampTransaction(destination='cusd_plus')` delivers USDT BEP20 to
  `Account.bsc_address`, locked at order creation.
- Arrival is detected on-chain (`cusd_plus/tasks.monitor_bridge_arrivals` →
  `ramps/signals.attribute_bsc_ramp_arrival`) and auto-converts into the
  user's dollar balance. A VEXPay payout to `bsc_address` is attributed by the
  same code, with no new delivery path.
- Off-ramp funding is a user-signed, sponsored 7702 batch to a
  server-vouched deposit address (`annotate_koywe_deposit_address`,
  `koyweOffRampService.fundUsdtDestination`). VEXPay reuses that path.

`payment_accounts/local_money.py` stays Infinia-only for now; generalizing it is
the routing-design follow-up, not this change.

## On-ramp (Recargar, VE) — built, dark

Venezuelan users never see the generic top-up: the local-money row
`ve_pagomovil_receive` ("Pago Móvil") opens `VePagoMovilReceiveScreen`, which
lets the user (or a third party) pay bolívares into a per-order flow. Code:
`ramps/vexpay_client.py`, `ramps/vexpay.py`, `ramps/vexpay_schema.py`.

1. **Order** — `createVexpayOnRamp` reserves a
   `RampTransaction(provider='vexpay', direction='on_ramp',
   destination='cusd_plus')` under a limits lock, then claims a Confío Face
   step-up (the order is dynamic, like Koywe's top-up). The estimate uses
   VEXPay's market rate and is labelled *estimado*.
2. **Pay-in**, two methods, each carrying
   `onwardPayout {network: BEP20, address: bsc_address}` so VEXPay converts the
   net bolívares to USDT and pays the user's wallet itself (no separate
   conversion or payout call from us):
   - **Pago Móvil** (default): show the receiving account and exact Bs amount;
     the user pays from their bank app and enters the reference and date;
     `POST /v1/payments/pago-movil/verify` (fresh idempotency key per try).
     `MOVEMENT_NOT_FOUND` / `AMOUNT_MISMATCH` leave the transfer claimable, so
     the order returns to the form.
   - **C2P** (Clave de pago): `POST /v1/payments/c2p/request`, the user types
     the bank key, `POST /v1/payments/c2p` with the `intentId`.
3. **Arrival** — existing BSC arrival attribution (`bsc_provider_hash`, by the
   txHash VEXPay reports) proves the delivery, links the conversion and runs
   the auto-conversion into the user's balance.

**Unknown outcomes.** A transport error or 5xx on any write is ambiguous: the
order is never released. Only the direct answer to our own request settles a
Pago Móvil order whose submission is in doubt; a looked-up failure is recorded,
then a bounded replay (row-locked, fresh key) decides, and an unresolved order
escalates to `needs_review` with an ops alert.

**Reconciliation.** Webhooks are single-attempt, so a 60 s Celery poll
(`poll_vexpay_ramp_transactions`) is the source of truth; the webhook only
enqueues a re-read. Completed orders stay polled for reversals (7 days) and
for a missing conversion link (30 days).

## Off-ramp (Enviar por Pago Móvil, VE) — built, dark

VEXPay has no USDT → VES API, so VEXPay converts by hand and ops releases each
payout. Code: `ramps/vexpay_offramp.py`, `ramps/vexpay_offramp_schema.py`,
`ramps/vexpay_admin.py` (admin → Ramp transactions → `vexpay-envios/`), app
`VePagoMovilSendScreen` (row `ve_pagomovil_send`).

1. **Order** — `createVexpayOffRamp` (personal owner, KYC, peeks the
   withdrawal Face) reserves `RampTransaction(direction='off_ramp')` under a
   limits lock and fetches the order's OWN BEP20 deposit address
   (`customerRef = cfo-<order>`), so equal amounts never collide.
2. **Funding** — `startVexpayOffRampFunding` is a single-use claim that
   answers the vouched address once. The app pins the personal wallet, checks
   it against the order, and pays with the Retiro batch (redeem with fee +
   exact transfer); the sponsor spends the Face approval. The hash is
   reported; a lost one is fine.
3. **Proof** — the chain decides: one USDT Transfer from the order's wallet to
   its address for exactly the vouched amount, by receipt or an incremental
   log scan (micro-chunk fallback) watched for 3 days. VEXPay's webhook only
   triggers a re-check.
4. **Conversion** — ops is notified, asks VEXPay to convert that deposit and
   marks it converted with the bolívares credited (±25% of the estimate).
5. **Payout** — `POST /v1/payments/credit` only when the free VES balance
   covers it after other in-flight payouts. Body and key are committed first;
   every dispatch holds a lease. VEXPay's idempotency lasts 24 h, so a lost
   answer is replayed with the same key for 20 h at most, then ops review.
   Definite bank rejections can be retried with a new key (after correcting
   the destination); anything unknown needs ops to confirm "NO PAGADO".

The estimate's processor fee (USDT deposit fee, conversion spread) comes from
`VEXPAY_OFFRAMP_*` settings until VEXPay exposes them.

## Cross-cutting

- **Secrets**: Parameter Store `/confio/secrets/<prefix>/vexpay-api-key` and
  `/confio/secrets/<prefix>/vexpay-webhook-secret` (`VEXPAY_AWS_SECRET_PREFIX`
  = `prod` / `sandbox`). Never in the repo.
- **Webhook**: `api/vexpay/webhook/`, verify `VexPay-Signature` (HMAC over the
  exact raw body) and de-duplicate on `VexPay-Event-Id` via `RampWebhookEvent`;
  fail closed outside DEBUG, like Koywe.
- **Polling fallback**: Celery task re-reads open orders (by id / `by-ref`)
  so a lost webhook never strands an order.
- **Model**: add `'vexpay'` to `RampTransaction` and `RampWebhookEvent`
  provider choices (migration). Status mapping into the existing
  PENDING/PROCESSING/COMPLETED/FAILED.
- **Eligibility**: Confío does the KYC. VEXPay does not refuse Venezuelan
  nationals, so the VE rows use our identity status, not Infinia's policy.
- **Limits**: flags `VEXPAY_RAMP_ENABLED`, per-order and per-user-daily caps,
  and a global daily cap per direction, so the most that can be in flight at
  VEXPay is bounded. No prefunding in either direction.
- **App**: the receive row is served only to builds at or above
  `VEXPAY_RECEIVE_MIN_APP_VERSION` (empty = nobody), to personal owners, while
  the flag is on or the user has an open order. Older builds never see it.
- **Switching providers later**: the order stores `provider`; adding Pago ASAP
  or Bolívar Connect is a new adapter plus a routing change, not an app change.

## Open points with VEXPay (before production)

1. **Off-ramp protocol**: how we request each manual USDT → VES conversion
   (API call, webhook, or they act on `payment.completed` automatically), the
   SLA and hours, and how the VES credit is tagged with our order reference.
2. **Off-ramp deposit fee**: USDT received carries the standard crypto pay-in
   fee; the off-ramp needs its own agreed price (deposit + FX + Pago Móvil
   payout), all-in vs the market rate.
3. **Agreed on-ramp terms applied in production** (pay-in, spread, conversion
   minimum, BEP20 payout fee lowered to cost after the BSC production test).
4. **Live conversion time**: written maximum for VES → USDT.
5. **Webhook registration** on the live tenant and the signing secret.

## Rollout

1. Backend behind `VEXPAY_RAMP_ENABLED=False`; sandbox end-to-end tests
   (C2P → conversion → BEP20 payout; USDT deposit → payout simulation).
2. Production smoke with Julian's own account: one small on-ramp and one small
   off-ramp, verified on-chain and in the beneficiary's bank.
3. Flag on for VE users with low caps; raise caps after a week of clean
   reconciliation.
