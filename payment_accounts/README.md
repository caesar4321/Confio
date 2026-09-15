# Payment accounts

## Didit identity handoff to Infinia

SELF_DECLARED uses the same verified identity number as Koywe: shared Didit
normalization stores CPF (Brazil), CURP (Mexico), RUN/RUT (Chile), and personal
identity number (Colombia), not card serials. Infinia validates CPF, checks
CURP/RUN formats, and formats RUN with a check-digit separator. This does not
establish provider nationality or document eligibility.

Argentina requires a separate CUIL from the approved ID check's
`additional_tax_id`, `extra_fields.additional_tax_id`, or `extra_fields.cuil`.
Missing, conflicting, invalid-checksum, or DNI-mismatched values block onboarding.
The Didit workflow must collect this value; the adapter never generates it.

Approved individual `document_verifications.items` of exact type
`source_of_funds`, `financial_statements`, or `proof_of_address` are uploaded and
referenced in the owner payload. Approved evidence must have a `file_url`.
The trusted decision's optional `expected_monthly_volume_usd` is forwarded after
finite, nonnegative validation. Absent values are not invented. This is backend
handoff support, not a new questionnaire or a replacement for EDD approval.

Unknown ID types fail closed rather than being relabeled NATIONAL_ID. Every
individual, including a UBO, requires an approved decision, ID check and liveness.
The first ID check must be approved because shared Didit normalization uses that
same check; another check's evidence must not be substituted. Missing UBO contact
details cannot fall back to the Confío account owner's contact. Business registry
checks must themselves be approved, and KYB requires an explicit `tax_number`,
not an untyped company registration reference. Placeholder/blank addresses and
missing personal contact data are rejected before identity uploads start.

The [implicit bridging implementation](BRIDGING.md) adds disabled-by-default
NEXT execution between BSC USDT and native Polygon USDC, source sponsorship,
background recovery and app history. Provider credit and fiat payout remain
separate from on-chain bridge delivery; see its rollout and settlement limits.
[Infinia journeys](INFINIA_JOURNEYS.md) now compose provider conversion and payout
with durable parent state and an explicit owner-approved minimum FX output.

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
rejects an end-user Bre-B `COP` balance. The separate COP/COPco on/off-ramp and verified-credit payment sequence is now
implemented in [Cobre journeys](COBRE_JOURNEYS.md), behind its own disabled-by-default
flag. NEXT bridge flags alone do not enable it. Infinia account-to-account conversion uses Internal Transfer and
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

Production Infinia credentials are stored in AWS Secrets Manager in `eu-central-2`:
`prod/infinia-secret-id`, `prod/infinia-secret-password`,
and `prod/infinia-webhook-signing-key`. Explicit environment
overrides take precedence. Sandbox credentials use the `sandbox/` prefix.
`INFINIA_ENV=production|sandbox` selects the API URL and all three secret names
independently of `CONFIO_ENV`. The checked-in `.env.testnet` uses production
Infinia to look up real recipients: the sandbox only resolves its documented
test values and otherwise leaves bank validations pending (see
[sandbox testing](https://docs.infiniaweb.com/docs/sandbox-testing.md)). This makes Infinia
operations live even while the wallet uses testnet. Existing sandbox provider
IDs do not work in production; pending recipient lookups must be run again.
`INFINIA_WEBHOOK_SIGNING_KEY` is independent of the API user; missing signing
configuration rejects webhooks. Production `INFINIA_API_URL` defaults to
`https://app2.infiniaweb.com/infinia_api`, as specified in Infinia's
[official Postman collection](https://infiniaweb.github.io/readme_docs/infinia-api.postman_collection.json).

Required settings are loaded from environment/Secrets Manager:

- `COBRE_USER_ID`, `COBRE_SECRET`, `COBRE_WEBHOOK_SECRET`
- `COBRE_PAYMENT_ACCOUNTS_ENABLED` (default `False`)
- `COBRE_API_URL`, `COBRE_COLOMBIA_PROVIDER_ID`
- `INFINIA_SECRET_ID`, `INFINIA_SECRET_PASSWORD`, optional `INFINIA_COMPANY_ID`
- `INFINIA_WEBHOOK_SIGNING_KEY`
- `INFINIA_API_URL`
- `INFINIA_ENV` (defaults to the stage derived from `CONFIO_ENV`)
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
# Third-party pay-in admission (Infinia)

Confío's controls are independent of Infinia's capabilities. All third-party
receiving is **off by default** (no switch rows are seeded). In Django admin,
create three enabled `ThirdPartyPayinSwitch` rows to permit a recipient:

| Scope | Country | Rail | Confío account |
| --- | --- | --- | --- |
| Country | ISO-2 receiving country | blank | blank |
| Rail | same country | verified rail code, e.g. `SPEI` | blank |
| Recipient | same country | same rail | recipient account |

All three must allow and Infinia's `receive_third_party` capability must be
enabled. Approval evidence is required; user grants must reference completed
enhanced KYC/KYB and compliance approval. This is an operator approval, not an
automatic determination that a Didit session qualifies as enhanced KYC.
Personal/business accounts are isolated. Country here is the receiving account's
country, **not** phone country (which remains the home-country fee signal).

An operator may use rail `*` for an all-verified-rails rollout or recipient grant
within one country, including before account issuance. An exact rail row takes
precedence, including a disabled row or one without evidence. Country switches
remain mandatory; a wildcard never authorizes a blank/ambiguous account rail,
missing sender identity, or a missing provider capability. Recipient rollout
authorization must not be described as proof of enhanced KYC or provider approval.

Configure `FinancialAccount.payin_rail` only after verifying the issued rail.
Do not assign a single rail to an account with ambiguous/multiple receiving
rails: leave blank and hold deposits until event-level rail evidence is supported.
`payin_document_country` must identify the verified jurisdiction of sender
document numbers on that rail. It is deliberately blank by default. Never infer
it from phone country or a depositor's nationality.

Same-owner admission requires verified personal identity, exact normalized name,
document number and document type, comparable document jurisdiction, and an
enabled provider same-name capability. Names alone never authorize a deposit.
Business representatives cannot be matched as business owners. Type aliases and
truncated/missing identities require review; third-party grants do not bypass
missing sender identity. Provider data must come from authenticated movements.

`PayinAdmission` in admin records the latest decision per deposit without copying
sender PII. Webhooks retain the accounting fact even when processing is held.
Admission is rechecked at journey creation, worker advancement, and submission.
Generic fiat balance spending is blocked while an unconsumed deposit fails
admission. Completed journeys are excluded from that balance guard. Unknown
submissions remain subject to normal reconciliation; revocation cannot undo a
provider operation already submitted. These controls do not reject an external
bank transfer or issue automatic refunds. Review/return and resumption of held
journeys require an operator workflow; changing a switch does not automatically
resume `needs_review` journeys.

Internal-transfer and refund labels alone do not bypass admission. Exemption
requires correlation to Confío's recorded provider operation and the correct
same-owner destination (or refund source). Switches are read in one database
snapshot. Name matching preserves word boundaries and rejects non-string
identity values. Both controls are registered on the custom Confío admin site;
the reassessment action updates decisions only and never moves funds.
Customer fiat submissions must belong to a payment journey: a provider balance
without a screened funding credit is not spend authorization. Standalone
customer fiat operations are rejected, including when their ledger is empty
because a webhook has not arrived. Platform-liquidity operations retain their
separate path and remain subject to the source-deposit guard.

Deploy migration `0011` before the code. No production switches or accounts are
enabled by this migration. Cobre enforcement is unchanged; the switch model
is provider-scoped for future adapters.

# Identity documents, residence, and EDD (local money)

**Primary vs additional documents.** The primary verification stays the
phone-country, rail-enforced Didit workflow; Koywe and every existing reader
keep using it. A person may add documents for local-money rails the primary
one does not satisfy (any country's national ID — DNI/cédula — or passport
opens COP, MXN, BRL and ARS accounts, plus the CNH for BRL; Venezuelan
documents are never accepted; `local_money.accepts_identity`). Additional
documents are `IdentityVerification` rows with `is_additional_document=True`,
and `IdentityVerification.objects` hides them by default, so no existing
query can pick one up; `all_documents` sees everything (admin uses it).
They come from one Didit workflow (`DIDIT_ADDITIONAL_DOCUMENT_WORKFLOW_ID`,
every document allowed; each session sets `expected_details.id_country` and
`expected_document_types`, mismatch = DECLINE). On approval the server
requires the requested country/type and the same date of birth and names as
the primary document. `local_money.rail_status` checks eligibility first,
then returns `needs_document` with the requirement when no verified document
fits; the Infinia account owner's document is fixed once created.

**Residence.** Eligibility residence is the majority IP country of the last
90 days of `IPDeviceUser` sessions (VPN/Tor/datacenter excluded), falling back
to the document country (`security.geo.residence_country_for`). Infinia's
owner address and National/Foreign domicile use the self-declared ramp address
(the same one Koywe uses), because many LATAM IDs print no address.

**EDD** (monthly volume above the provider default). The app asks income type,
occupation, expected monthly volume and funding source. One Didit session
collects proof of address and source-of-funds evidence. The webhook routes EDD
sessions to `payment_accounts.edd`, never to `IdentityVerification`.

Submitted sessions (`Approved` or `In Review`) are automatically dispatched to
`payment_accounts.forward_edd` after commit. There is no Confío manual-review
gate: complete evidence awaiting Didit review can be sent to Infinia for its
own decision. Incomplete, declined, or unfinished sessions are not forwarded.
The handoff uploads proof of address and bundles **all** income-proof and bank
statement files into one source-of-funds PDF, then links both document IDs with
`PATCH /v1/accounts/owners/{owner_id}/`. SELF_DECLARED owners also receive
`expected_monthly_volume_usd`; occupation and income/source categories remain
local because the owner update schema has no matching fields.

Dispatch retries use Celery backoff; `payment_accounts.reconcile_edd` runs every
five minutes to recover missed webhooks, queue failures, and owners activated
later. A successful handoff becomes `forwarded`, never locally `approved`.
Repeated completed jobs do not relink documents. `forwarded` is a completed
handoff, not a provider approval: users may send new evidence without staff
closing the earlier request. Each request has a distinct Didit vendor reference,
so updating evidence cannot resume an earlier session awaiting review. Apply
migration `0022_edd_forwarded_terminal` before deploying worker and beat.
A rollback to the previous uniqueness rule requires resolving multiple forwarded
requests per owner first. Task logs omit underlying HTTP exception chains because
they can contain temporary document credentials.

The [owner update API](https://docs.infiniaweb.com/reference/v1_5_update_account_owner)
supports these document links. The published
[limit increase process](https://docs.infiniaweb.com/docs/transaction-limits)
still specifies an account-manager request; uploading evidence alone is not
documented to initiate that review. Confirm that routing with Infinia.
Monthly limits are informational in Confío; Infinia enforces them on execution.
Provider rejection after bridging can leave funds at Infinia for recovery;
this change does not add automatic refunds.

Deploy `security` migration `0011` and `payment_accounts` migration `0014`
(after the direct-bridge migrations `0012`–`0013`).


## US$10 local account activation

One opening fee applies per Confío owner/country/currency, shared by sending and
receiving methods. Supporting `XXX / USDC_POL` accounts do not incur another fee.

### Open first, collect when ready

1. `prepareLocalActivation(methodId)` returns `consent_required` and the US$10
   price without opening an account or preparing a payment.
2. After explicit consent, the app repeats the mutation with `acceptedFee: 10`.
   KYC and address checks must pass. A durable activation records the consent,
   fixed collector, amount, and country/currency before requesting Infinia accounts.
3. The provider must confirm both accounts and their owner profile active and provide non-empty, unexpired receiving
   instructions before the activation becomes `awaiting_payment`. A failed opening
   never produces a payment. Unknown outcomes retain their IDs for reconciliation.
4. Only then can the server prepare a signed payment of exactly 10 cUSD to the
   collector. The user confirms this separate payment. Any savings conversion
   rounding surplus remains in the user's own wallet.
   Savings conversion still obeys Ondo's US$1 minimum: a split balance such as
   9.50 cUSD plus 0.50 cUSD+ needs a top-up before it can pay. The app explains
   this condition without charging or recreating the account.
5. Only server confirmation of that linked payment marks the activation `active`.
   Until then, account lists and receiving instructions are hidden, and quotes,
   bridges, conversions, and payouts using the unpaid account are blocked server-side.
   Inbound provider credits may still be recorded; they do not bypass these gates.

Opening records commit before payment preparation. Insufficient balance, leaving
the app, or payment failure cannot roll back provider IDs and create another
account on retry. Payment retries reuse the same send unless it definitively failed.
Readiness and the snapshotted token/network are checked again when returning an
existing payment and immediately before submission. Unready unpaid accounts can
resync their existing provider resources. Terminal openings release the unfinished
opening allowance only when no payment could still execute; prepared or uncertain
payments retain their original record until their outcome is established.
Celery beat runs `payment_accounts.reconcile_activations` every 30 seconds to finish
opening, reconcile unpaid accounts, and confirm payments even when the app is closed.

There is one unfinished opening per verified user's customer identity in Confío
(`user_id`), across their personal/business accounts. This is serialized on the user
row. An abandoned ready account consumes that allowance until paid. Confío bears
the provider creation cost on abandoned or failed openings; these costs are separate
from the customer's opening fee. A failed country/currency request cannot silently
restart or incur a repeated fee.

### Collection contract

Deployed on BSC mainnet on 2026-09-15 at
`0x45f302BC7a81b74631Af2341f367D5Cddb754471`. See the
[deployment record](../contracts/cusd_plus/DEPLOYMENT.md#accountactivationcollector--deployed-2026-09-15)
for its transaction, immutable values, and verification evidence.

`contracts/cusd_plus/AccountActivationCollector.sol` receives cUSD transfers and
has one permissionless `sweep()` function. It can send its cUSD balance only to the
immutable secure treasury Safe. There is no refund, owner, signer, upgrade method,
recipient setter, or arbitrary withdrawal function. No extra KMS key is needed.
Anyone can pay gas to sweep; no routine Safe signature is required to receive it.

The backend records opening/payment state and verifies signed transfers; the
collector holds only collected revenue. It is not escrow and does not track account
eligibility. The sponsor remains the existing gas payer and holds no fee revenue.

### Rollout

- Build and test the collector with the existing Foundry project. The script
  `script/DeployAccountActivationCollector.s.sol` dry-runs creation with the current
  cUSD token and documented secure 3-of-5 Safe. It does not start a broadcast.
- Deploy its creation bytecode using the existing KMS deployment workflow; verify
  its immutable `token()` and `treasury()` before configuring the backend.
- Set `INFINIA_ACTIVATION_COLLECTOR_ADDRESS` to the deployed collector and
  `INFINIA_ACTIVATION_SAFE_ADDRESS` to that secure Safe. Opening fails closed if
  the collector is missing, is an EOA, or its token/treasury getters disagree.
- Apply the unreleased `0015_accountactivation` migration. It preserves existing
  provider accounts as `legacy`, with no retroactive fee. This migration replaces
  the earlier, undeployed charge-before-opening draft; do not apply it over a
  deployment of that draft without a forward data migration.
- Deploy the backend before the mobile bundle. Run Celery workers and beat.

No activation refund endpoint, command, or signing permission exists. A provider
opening failure leaves the user uncharged. Normal later account restrictions are
separate from whether the account was successfully opened.

Tests: `payment_accounts.tests.test_activation`, the local-money/bridge/journey
regressions, mobile `localActivation.test.ts`, and `AccountActivationCollectorTest`.
