# Cobre payment journeys

`CobreJourney` persists an owner's payment intent across NEXT and three Cobre
operations. The feature defaults off (`COBRE_JOURNEYS_ENABLED=false`). Cobre
balances are provider ledgers; their existing ownership classification remains
unchanged. This implementation does not create a new wallet custody model.

## Confirmed contracts

Public Cobre documentation checked on 2026-09-05:

- [StableFX](https://docs.cobre.com/stablefx-2262883m0): static FX quotes and
  cross-border money movements convert `usd_stable` ↔ `copco`. COP cannot be
  passed directly to StableFX. Destination credits wait for mint/burn confirmation.
- [On/off-ramp](https://docs.cobre.com/stablecoin-funding-onoff-ramp-2262882m0):
  ordinary Money Movements convert the client's own COP ↔ COPco balances.
  The COP corridor uses manual conversion. Off-ramp `standard` settlement follows
  settlement windows and has no settlement fee; `instant` has an additional cost.
- [Static quote schema](https://docs.cobre.com/fx-quote-static-create-response-11817891d0):
  `id`, `type`, `currency_pair`, `source_amount`, `destination_amount`, `valid_until`.
  Quotes must match the authorized pair, exact source amount and minimum output,
  and have an unexpired timezone-aware deadline before creating the FX leg.
- [Stable payout](https://docs.cobre.com/stablecoin-payouts-2262880m0): payouts from
  `usd_stable` use a verified global beneficiary. COPco cannot pay external wallets.
- [Global payouts](https://docs.cobre.com/global-payouts-in-stable-2053445m0): Polygon
  supports USDC; amounts use cents, with a one-dollar minimum. Money Movement
  idempotency keys last 24 hours. This implementation pins Polygon/native USDC.
- [StableFX credit](https://docs.cobre.com/transaction-metadata-cbmm-credit-stablefx-16622702d0),
  [on-ramp credit](https://docs.cobre.com/transaction-metadata-onramp-credit-16622696d0),
  [off-ramp credit](https://docs.cobre.com/transaction-metadata-offramp-credit-16622698d0):
  `metadata.money_movement_id` binds credits to their original operation.
- [Stable payout debit](https://docs.cobre.com/transaction-metadata-stable-payout-debit-16622695d0):
  beneficiary chain, token, wallet, money movement ID and `tracking_key` provide
  the evidence for a finalized Polygon receipt.

## Payment paths

**Dollars to Bre-B:** owner reviews and authorizes NEXT BSC USDT → their verified
Cobre Polygon funding address. After bridge delivery and its matching
`global_credit` to USD_STABLE, the worker executes StableFX → COPco, waits for
`cbmm_credit`, submits standard off-ramp → COP, waits for `offramp_credit`, then
pays the saved Bre-B beneficiary. The app can close after source submission.
The payout must succeed before the parent completes. Net bank proceeds are
reported only if the provider supplies them; the payout face amount is not a
net-receipt guarantee.

**COP deposit to dollars:** owner chooses an unused local deposit and authorizes
conversion with a minimum FX output. The worker executes COP → COPco, waits for
`onramp_credit`, quotes and executes COPco → USD_STABLE, waits for `cbmm_credit`,
then pays the owner's verified Polygon beneficiary. Payout success alone does
not enable bridging: the exact native USDC receipt must finalize. The user
opens the app, reviews the actual received amount and signs the Polygon → BSC
return bridge. The worker completes on finalized BSC USDT delivery. The existing
wallet dollar conversion remains subsequent to this USDT-targeted journey.

Standard settlement may wait for Cobre's windows. The minimum applies to FX,
before payout costs. If inbound FX falls below the minimum, COP may already be
in COPco: the journey stops for review, without inventing a compensating transfer.
No server-held user key or automatic signature is introduced.

## Persistence and recovery

- JWT owner checks bind all financial account, deposit, bridge and destination
  UUIDs. All three Cobre balances must belong to the same active owned profile.
- Bank destinations are snapshotted at authorization. Wallet payouts use the
  owner's current wallet, never a client-supplied arbitrary address. Cobre's
  beneficiary is re-fetched and checked for verified status, Polygon and the
  exact authorized wallet immediately before submitting the payout.
- One unresolved journey reserves all three balances against other provider
  submissions. Each deposit and bridge can be attached once. Reusing a request
  UUID with different authorization details fails.
- Every leg is persisted before its POST. Deterministic idempotency keys and the
  original FX quote survive timeouts, HTTP response replacement and worker restarts.
  A retry never silently requotes or creates a replacement economic leg.
- Credits must match the owned destination, asset, transaction type, direction,
  provider operation ID and exact expected amount. Equal amounts and timestamps
  never establish ownership. Rewards and refunds cannot fund another leg.
- Ledger matching does not depend on webhook/create-response order or a ledger
  foreign key. A source credit posted before its operation ID becomes known is
  also detected before advancement. Late failures/refunds reopen completed
  journeys for review. Queued legs cannot submit after the journey enters review.
- Unknown Cobre operations are retrieved/retried under the original key only
  within the existing conservative 23-hour window. Unresolved older operations
  enter review instead of risking reuse after Cobre's 24-hour expiry.
- Failed/expired bridges, refunds, changed wallets and mismatched credits require
  review. A later failure does not imply that earlier delivered funds were refunded.

## Setup and activation

The integration operates on **already provisioned, contracted Cobre resources**.
It does not automatically open stable balances or submit beneficiary KYC.
Before enabling the feature, operators must register and verify:

1. Three active `FinancialAccount` records under the same owned Cobre profile:
   COL/COP, USD_STABLE, COPCO, with their correct remote account IDs. Preserve
   `omnibus_subledger` where applicable; do not reuse a shared treasury balance
   as if it were several users' separately owned balances.
2. Approved `convert` capabilities for COP, COPco and USD_STABLE,
   `send_third_party` for COP and `crypto_payout` for USD_STABLE. Stable capabilities
   are never inferred from the existence of a Bre-B account.
3. A verified active Polygon USDC funding instruction on USD_STABLE, attested in
   `PAYMENT_BRIDGE_VERIFIED_INSTRUCTIONS`. Confirm bridge-origin deposit acceptance
   with Cobre for the contracted program.
4. For outbound payments, an active owned Bre-B `PayoutDestination` with its
   provisioned `provider_destination_id`.
5. For inbound payments, an active owned `crypto_wallet` destination, asset
   `USDC_POL`, `details.address` equal to the lowercase current account wallet,
   and the verified Cobre `global_deposit_np` counterparty ID. Provision this
   beneficiary through Cobre's approved onboarding process, then register it
   locally. The money path independently revalidates it through GET before payout.

Apply migration **0010** after the bridge/Infinia migrations. Run Celery
beat/worker: `payment_accounts.reconcile_cobre_journeys` runs every 30 seconds;
existing provider and bridge reconcilers remain required. The custom admin
shows immutable journey evidence. The mobile `Pagos en Colombia` screen shares
payment review, explicit authorization and paginated history with Infinia.

Certify each leg, both bridge directions, fees, transaction notifications and
standard settlement timing in the provider sandbox before activation. Then set
`COBRE_JOURNEYS_ENABLED` along with the approved provider and bridge flags.
Disabling the journey flag stops new advancement; existing submitted operations
retain their reconciliation paths. No live transfers or deployment were performed.

See the [orchestration audit](ORCHESTRATION_AUDIT.md) for recovery and concurrency validation.
