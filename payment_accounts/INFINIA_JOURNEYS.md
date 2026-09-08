# Infinia payment journeys

An `InfiniaJourney` is an owner-authorized parent MoneyFlow with durable
conversion and payout legs. Its worker continues after the app closes.
`INFINIA_JOURNEYS_ENABLED` defaults to false and is separate from the bridge flags.

## Confirmed API contracts

Read the **OpenAPI definitions** in Infinia's Markdown pages, not just the
rendered examples. Verified on 2026-09-05:

- [Movement created](https://docs.infiniaweb.com/reference/v1_webhook_movement_created.md):
  `ThirdPartyCryptoMovement` has `type=CRYPTO`, `crypto_network`, `crypto_address`,
  and **`transaction_hash`**. This closes the previously unidentified bridge
  credit reference. `crypto_address` is third-party data, not assumed to be the
  beneficiary; the owned financial account and verified bridge receipt bind
  the beneficiary.
- [FX quote](https://docs.infiniaweb.com/reference/v1_7_create_quote.md):
  `POST /v1/accounts/internal-transfer/quote/`, source/target account IDs,
  source amount and requested lock time. Validate `ACTIVE`, `expire_at`, account
  IDs, source amount and target amount. Offsetless example timestamps are treated
  as UTC; an expired/invalid quote fails closed. Numeric values must round-trip
  through the provider's JSON number representation without changing value.
- [Internal transfer](https://docs.infiniaweb.com/reference/v1_10_create_internal_transfer.md):
  use the quoted `quote_id` and the same persisted `idempotency_key`. COMPLETED
  means sent, **not necessarily credited**.
- [Developer handbook](https://docs.infiniaweb.com/reference/introduction):
  create/retrieve/webhook schemas are shared and repeated money operation keys
  return the original result.
- [Fund flows](https://docs.infiniaweb.com/docs/fund-flows): conversions use
  Internal Transfer; payouts originate from the user's provider account.

## Outbound: dollars → local bank

1. Prepare a NEXT bridge to the user's verified Infinia USDC_POL account.
2. On confirmation, persist the local account, bank destination snapshot,
   minimum acceptable FX output and bridge ID in a journey; then sign the
   source bridge. A retry uses the same request UUID and cannot change terms.
3. Wait for on-chain delivery **and** Infinia's matching crypto credit.
4. Obtain a fresh FX quote for the actual credited amount. Refuse any quote
   below the user's authorized minimum or for different accounts/amounts.
5. Persist the conversion before submitting it. Wait for destination movements
   with that provider operation ID and the expected target currency/amount.
6. Persist and submit the bank payout from the user's local account. Only its
   confirmed success completes the parent flow.

The FX minimum is before payout costs, not a guaranteed net bank receipt.
Payout amounts are rounded down to two fiat decimal places; any fractional
remainder remains in the user's provider account. No Confío fee is calculated
inside provider legs: the existing on-chain dollar perimeter owns that fee.

## Inbound: local deposit → wallet → Confío

1. The user selects an authenticated, unused deposit credit and authorizes its
   conversion to USDC_POL with a minimum FX output. Each credit can fund one
   journey only.
2. After the matching conversion credit, withdraw to the JWT account's EVM
   address, snapshotted at authorization. No client-supplied crypto address is
   accepted.
3. A payout success status is not wallet delivery. Require the corresponding
   crypto movement hash and a finalized Polygon USDC receipt to the wallet.
4. When the user opens the app, prepare a return bridge for the **actual received
   amount**, attach it to the journey, and let the user review and sign once.
5. Source submission and bridge delivery continue without the foreground app.
   Finalized BSC USDT delivery completes this USDT-targeted journey. The existing
   dollar conversion remains a subsequent wallet operation.

The app never signs on a webhook or on opening history. An inbound journey
intentionally pauses for wallet authorization; the server does not hold user
keys or invent an authorization for an unknown future amount.

## Recovery and accounting

- `createInfiniaJourney` and `attachInfiniaReturnBridge` are JWT owner-scoped.
  Provider IDs, calls, and withdrawal addresses are resolved server-side.
- The journey row serializes stage advancement. Child operation UUIDs are
  deterministic per journey/leg, and submission happens after the DB commit.
- Unknown submissions stay attached to their original operation. The existing
  provider reconciler retries/retrieves using that same idempotency key.
- FX quote binding is stored on the journey, surviving replacement of provider
  response/error payloads on the child operation.
- A conversion credit can arrive before the create response or status webhook:
  lookup uses its provider operation ID directly, without relying on webhook
  order or a preexisting ledger-to-operation foreign key.
- A child success cannot prematurely complete its parent. Late failures,
  reversals, and posted refunds move the journey to review rather than starting
  another payment.
- One unsettled journey per owner reserves its two provider accounts against
  competing provider submissions. Existing pending provider operations prevent
  opening another journey.
- A changed wallet, insufficient FX output, ambiguous credit, refund, failed
  payout, or failed return bridge requires review. No automatic replacement
  economic leg is created. Funds already delivered to a provider remain there;
  a failed later leg does not imply that the original bridge was refunded.

## App and deployment

`Pagos con cuenta local`, accessible from the dollar/local-account screen,
provides bank selection, deposit selection, minimum-output authorization,
review-before-signing and paginated journey history. Existing destinations and
provider accounts must be provisioned first.

Apply payment_accounts migrations **0008 and 0009** before enabling callers.
Run Celery beat/worker; `payment_accounts.reconcile_infinia_journeys` runs every
30 seconds. The custom admin shows immutable journey evidence and failure codes.

Enable only after provider sandbox certification, account capabilities,
webhook delivery and both bridge directions have been validated for the
contracted program. Disabling the journey flag prevents advancing into new
legs; already submitted provider/bridge operations retain their existing
reconciliation paths.

Cobre has its own separately gated [COP/COPco orchestration](COBRE_JOURNEYS.md). No live provider transfers or deployment were performed.

See the [orchestration audit](ORCHESTRATION_AUDIT.md) for recovery and concurrency validation.
