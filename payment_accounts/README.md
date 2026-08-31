# Payment accounts

`payment_accounts` owns persistent provider accounts and the money operations
performed through them. It does not replace `ramps`: legacy quoted/order-based
providers remain in `ramps`, while a customer-facing fiat/crypto journey can
link to one or more `MoneyOperation` rows through `MoneyFlow`.

## Provider mapping

| Confío concept | Cobre | Infinia |
| --- | --- | --- |
| Provider profile | Local verified holder profile | Account Owner |
| Financial account | Cobre Balance / omnibus subledger | Named Virtual Account |
| Funding instruction | Separately provisioned Bre-B Key | Instructions returned by Account |
| Unsolicited receipt | Balance credit webhook | Deposit/movement webhook |
| External send | Counterparty + Money Movement | Payout with inline destination |
| Conversion / prefunding | StableFX for `usd_stable` ↔ `copco` balances only | Internal Transfer |

The `ownership_structure` field must remain truthful. A Cobre balance with the
end user's name displayed on its Bre-B key is still an `omnibus_subledger`, not
a provider-named bank account.

## Safety invariants

- GraphQL resolves the active `users.Account` from the JWT. Provider IDs are
  never accepted from the client.
- Eligibility uses verified KYC nationality and residence, not phone country
  or IP-country guesses.
- Account opening and payout destination eligibility are evaluated separately.
- Missing provider/scope policy fails closed. Unconfirmed seeded cohorts return
  `review`; they are not provisioned automatically.
- Money operations and idempotency keys are stored before provider submission.
- Webhooks are signature-verified, stored uniquely by `(provider, event_id)`,
  and processed asynchronously.
- Ledger entries are immutable provider facts and are not inferred from a
  customer flow merely reaching a submitted state.
- Cobre resources without reliable API idempotency use the local UUID as a
  stable alias and are searched by that alias before retries create anything.
- Infinia never uses hosted KYC. Provisioning requires explicit data-sharing
  consent and an approved Didit session scoped to the active personal account
  or exact business ID.
- Didit media URLs are treated as short-lived credentials: they are fetched
  only during provisioning, never persisted, capped at 10 MB, hashed for the
  audit trail, and uploaded directly to Infinia's presigned URLs.

## Provisioning lifecycle

1. Resolve the JWT-bound Confío account and its correctly scoped Didit result.
2. Evaluate and record the active `account_opening` policy.
3. Provision or synchronize `ProviderProfile`.
4. Once the profile is active, provision or synchronize `FinancialAccount`.
5. Snapshot provider capabilities.
6. Create or ingest funding instructions.

For Infinia, step 3 uses `SELF_DECLARED`. Individual KYC uploads the approved
identity document and liveness reference image before creating the Account
Owner. Business KYB additionally requires an approved business-scoped Didit
session, certificate of incorporation, source-of-funds evidence, proof of
address, and a completed child Didit KYC for every natural-person UBO. Missing
evidence fails closed. The public mutation requires `shareComplianceData=true`.

## Operation lifecycle

`MoneyFlow` represents customer intent; each provider call is a
`MoneyOperation`. Canonical statuses retain the original provider status
alongside them. A documented Cobre StableFX operation is supported only when
both sides are existing `usd_stable`/`copco` balances. The adapter deliberately
rejects an end-user Bre-B `COP` balance: Cobre must contract and document the
bridge from that balance before Confío can compose receive → convert → crypto
delivery. Infinia account-to-account conversion uses Internal Transfer and
remains `settling` until the destination movement credit arrives.

Non-terminal operations older than 30 minutes are reconciled every ten minutes
using their persisted idempotency keys. Provider webhooks remain the primary
settlement signal.

## GraphQL surface

- `myPaymentAccounts`, `myMoneyFlows`, `myPayoutDestinations`
- `paymentAccountEligibility`
- `provisionPaymentAccount`, `createReceivingInstruction`
- `createPayoutDestination`, `createPaymentPayout`
- `createPaymentTransfer`

Destination details are a typed input union represented as a validated
superset because GraphQL input unions are not available. Provider-owned IDs are
always resolved from JWT-owned database rows. Money-moving mutations require a
client-generated `requestId` UUID; retries with the same UUID return the
original operation, while reuse with different immutable details is rejected.

## Fee boundary

`payment_accounts` never calculates or deducts a Confío platform fee. Amounts
sent to any payment-account provider are face-value amounts for that provider
leg. A provider's own fee, when returned by the provider, remains recorded as
`provider_fee` / `provider_cost`.

The Confío conversion fee is assessed once at the USDT <-> cUSD on-chain
perimeter and recorded in the canonical conversion ledger. Depending on flow
direction, that on-chain boundary may occur before or after a provider leg. Its
fee must not be copied into provider payloads or duplicated in payment-account
records.

## Configuration

Required settings are loaded from environment/Secrets Manager:

- `COBRE_USER_ID`, `COBRE_SECRET`, `COBRE_WEBHOOK_SECRET`
- `COBRE_PAYMENT_ACCOUNTS_ENABLED` (default `False`)
- `COBRE_API_URL`, `COBRE_COLOMBIA_PROVIDER_ID`
- `INFINIA_SECRET_ID`, `INFINIA_SECRET_PASSWORD`, optional `INFINIA_COMPANY_ID`
- `INFINIA_API_URL`
- `INFINIA_PAYMENT_ACCOUNTS_ENABLED` (default `False`)
- `INFINIA_KYC_MODE=SELF_DECLARED`
- `DIDIT_API_KEY`, `DIDIT_MEDIA_ALLOWED_HOSTS`
- `PAYMENT_ACCOUNTS_CALLBACK_BASE_URL`

Do not enable provisioning until the full written eligibility matrix, webhook
subscriptions, account products/capabilities, and contract-specific Cobre
document mapping have been verified in sandbox.

Infinia's Compliance team must approve Confío's Didit-backed SELF_DECLARED
integration before the Infinia feature flag is enabled. The Didit personal and
business workflows must expose the fields and document groups listed above;
the configuration check also requires an explicit allowlist for Didit's media
hosts.

The public Cobre schema confirms `DIE`, `CE`, `PPT`, `PA`, and `CC` as accepted
holder ID enum values, but does not define which one Cobre has contracted for a
Venezuelan cédula in this program. The initial mapping uses `DIE`; confirm that
semantic mapping with Cobre before production activation.
