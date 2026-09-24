# Infinia payment journeys

An `InfiniaJourney` is an owner-authorized parent MoneyFlow with durable
conversion and payout legs. Its worker continues after the app closes.
`INFINIA_JOURNEYS_ENABLED` defaults to false and is separate from the bridge flags.

## Automatic incoming deposits

Product policy: automatic conversion applies to newly received deposits on all
eligible Infinia receiving accounts, including accounts opened before rollout.
There is no per-account opt-in. Existing country/rail/user admission switches,
identity checks, account-opening payment requirements and global enablement
remain mandatory. Cobre behavior is unchanged.

Under the confirmed program policy (2026-09-16), missing Infinia third-party
capability data defaults to enabled: Confío owns country/rail/recipient approval.
Explicit provider restrictions still override that default. Capability sync does
not create or enable any Confío recipient grants.

First-party admission for individual owners compares the incoming FIAT
`third_party.full_name` with the provisioned owner's verified identity snapshot.
Comparison ignores case, accents, punctuation, whitespace, and complete-component
order, but requires every name component with its original repetition count.
Initials, omitted components, and fuzzy spelling are not matches. Document number,
type, and issuing country are not admission evidence; provider identifiers can
differ from KYC identifiers or be absent. The legacy `payin_document_country`
field is retained but no longer gates admission.

A name match bypasses third-party grants, while verified identity, active profile,
known receiving rail, and enabled `receive_same_name` capability remain required.
Different names are allowed by default outside Brazil, unless an explicit country,
rail, or recipient stop applies. Brazil still requires all three approval scopes.
Provider capability and a nonempty sender name remain required; document fields
are optional. The receiving account country determines the Brazil exception. Business
representative names never establish first-party business ownership. Name matching
cannot distinguish unrelated people with identical names. These rules do not add
automatic refunds or a historical sweep. Existing pending automatic-pay-in jobs
are re-evaluated by the worker and may proceed under the new name policy; jobs
already marked for review are not automatically restarted.

Conversion settlement may reference a bank `voucher_id` or, for USDC on Polygon,
a crypto credit's `transaction_hash`. Match the completed conversion's exact
voucher set, account identities and amount; never infer settlement from amount alone.

Migration `0023` introduces `AutomaticPayin`, one durable job per ledger credit.
Authenticated new external-fiat movements enqueue it in the webhook transaction.
The existing journey worker processes the queue and creates a direct-to-wallet
journey using `deposit_quote`'s FX and bridge minimums and existing cost caps.
The deposit's deterministic request ID and unique journey funding credit prevent
duplicate conversion, including a race with the manual flow. Failed quotes and
busy accounts remain pending. Eligibility is rechecked before creation/execution.

Receiving detection covers every configured fiat country/currency pair. Explicit
account funding instructions verify SPEI (checksum-valid CLABE), Pix, Bre-B,
CBU/CVU, TED (`ted_brl`) and FPS (`fps_gbp`). Multiple rails on one account are
ambiguous: the account-level switch must not silently choose one for a deposit.
`provider_data.receiving_rail_detection` records status, candidate rails, reason,
and field names without copying banking PII. Generic bank/IBAN/QR details produce
inferred candidates only (including CL, BO, PE, PY, UY, US and EUR accounts).
Only `payin_rail`, populated by unambiguous evidence, is used for admission.
Country/currency, payout schemas, and the coverage table never authorize a rail.
Unknown shapes remain pending and are reclassified when the authenticated account
snapshot is refreshed. Sender document jurisdiction is not inferred. Sources:
[account schema](https://docs.infiniaweb.com/reference/v1_2_get_account_.md) and
[coverage table](https://docs.infiniaweb.com/docs/virtual-accounts.md), read 2026-09-16.

Historical ledger credits are deliberately not swept: an unlinked credit may
already have been spent. An operator can inspect a specific deposit with
`manage.py recover_automatic_payin --provider-entry-id ID` and authorize it with
`--apply`. A subsequent debit places it in review rather than replaying it.
Run `migrate` before restarting workers. The rollout does not change existing
in-flight journeys or send funds to a Confío treasury. USDT is delivered directly
to the user's wallet; the final cUSD mint still uses the app's signing flow.

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

1. Prepare a bridge through the configured provider (currently Relay) to the user's verified Infinia USDC_POL account.
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

## Inbound: local deposit → bridge deposit → BSC wallet

1. The user selects an authenticated, unused deposit credit and authorizes its
   conversion to USDC_POL with a minimum FX output and a separate minimum net
   BSC USDT receipt (`minimumWalletOutput`). Both are immutable on request retries.
   Each credit can fund one journey only. Check bridge feature flags, an active
   crypto instruction, and the quoted FX output against the bridge cap before
   submitting FX; repeat these checks before subsequent submissions.
2. After the matching conversion credit, prepare a deposit-address bridge route for
   that amount of native Polygon USDC, rounded down to six decimals. Persist the
   bridge and Infinia payout in the same transaction. The bridge's BSC recipient and
   Polygon refund address are the user's EVM address snapshotted at authorization.
   The built minimum output must meet the user's wallet minimum before creating
   the payout. An unacceptable minimum or unavailable prerequisite requires review;
   the rejected quote/bridge rolls back without an orphan transfer.
3. Submit the payout from the user's Infinia crypto account directly to the
   generated deposit address. The v2 destination is `country=GLOBAL`,
   `currency=USDC`, `destinationType={type: POLYGON, address: deposit}`. Infinia's
   acceptance of this destination was confirmed by Julian on 2026-09-14.
4. Bind the source transaction using the authenticated Polygon CRYPTO movement
   for this exact payout and account. Verify the exact native USDC receipt at
   the deposit address; the sender may be Infinia's hot wallet. An amount mismatch
   requires manual review, never a top-up or replacement payout.
5. Reconcile bridge status and finalized BSC USDT receipts to the pinned user
   wallet. On-chain delivery can complete the journey before the payout status
   webhook arrives. The existing dollar conversion remains a subsequent operation.

No user bridge signature, Polygon wallet balance, or Confío Polygon gas sponsor
is required for this path. A wallet signing endpoint rejects provider-funded
bridges. The app may close after the user authorizes conversion and payout.

The [Infinia v2 payout schema](https://docs.infiniaweb.com/reference/v2_create_payout__post)
was checked on 2026-09-14: it specifies `amount` but exposes no fee/net-amount quote
or documented deduction formula. The same exact amount funds the payout and bridge
quote; absence of a fee field is **not** proof of zero provider fees. Actual
on-chain funding is checked before recognizing bridge completion.

Use the returned deposit deadline, not an assumed 30-second lifetime. Submission
and retries stop when fewer than 60 seconds remain; an unresolved submitted
payout keeps its original operation and deposit. Late authenticated transaction
hashes remain reconcilable. Delayed-deposit review can clear after verified BSC
delivery, without submitting more funds. Other review reasons, refunds and
mismatched deposits require manual review; no automatic refund recovery is implemented.

Existing payouts already addressed to the user's Polygon wallet keep their old
delivery → review/sign → bridge flow. Migration 0012 defaults existing bridges
to wallet funding, preserving their execution semantics. Migration 0013 leaves
the wallet minimum null for pre-upgrade journeys; those retain their wallet payout
and review/sign flow even if their payout has not yet been created. New inbound
journeys require the separate wallet minimum; older clients must update.

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

`Recibir por cuenta local` shows receiving details and incoming fiat receipts,
without manual conversion selection or a summary step. Outgoing transfers retain
bank selection, minimum-output authorization and review-before-signing.
Transfer status supports pull-to-refresh. Existing destinations and provider
accounts must be provisioned first.

Apply payment_accounts migrations through **0023** before restarting workers.
Run Celery beat/worker; `payment_accounts.reconcile_infinia_journeys` runs every
30 seconds. The custom admin shows immutable journey evidence and failure codes.

Enable only after provider sandbox certification, account capabilities,
webhook delivery and both bridge directions have been validated for the
contracted program. Disabling the journey flag prevents advancing into new
legs; already submitted provider/bridge operations retain their existing
reconciliation paths.

Cobre has its own separately gated [COP/COPco orchestration](COBRE_JOURNEYS.md). No live provider transfers or deployment were performed.

See the [orchestration audit](ORCHESTRATION_AUDIT.md) for recovery and concurrency validation.
