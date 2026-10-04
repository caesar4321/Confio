# Stereum sandbox integration

The backend includes an administrator-only sandbox console and CLI for Bolivia bank discovery, balances, BOB↔USDT/USDC quotes and orders, QR collection, recipient decoding, QR payouts, charge simulation, and status reconciliation. Records live in separate Stereum test tables; they do not change customer balances or create RampTransaction records.

This is a provider test integration, not a customer-facing ramp. The existing mobile ramp continues to use its existing provider. Customer onboarding/KYC and authenticated customer quotes are implemented below. Polygon liquidity and settlement into Confío wallets, automatic settlement reconciliation, and production mobile routing are not implemented here. Operator-only mobile QR routing is described below. Production cannot be enabled by changing a key: the adapter rejects `STEREUM_ENV=production`.

## Configuration

Use `CONFIO_ENV=testnet` to load the ignored local `.env.stereum-test.local`. The supplied credentials have been placed there; no credential is committed. The application also supports the existing Secrets Manager helper with `sandbox/stereum-api-key` and `sandbox/stereum-secret-key` when enabled and environment values are absent.

```dotenv
STEREUM_ENV=sandbox
STEREUM_TEST_ENABLED=True
STEREUM_CUSTOMER_TEST_ENABLED=True
STEREUM_MOBILE_QR_TEST_ENABLED=True
STEREUM_TEST_WRITES_ENABLED=False
STEREUM_API_KEY=<test API key>
STEREUM_SECRET_KEY=<test signing secret>
STEREUM_COMPANY_ID=<Stereum test company ID>
STEREUM_BOB_ACCOUNT_ID=<corporate BOB account ID>
```

Both environments use `https://api.stereum.tech`; Stereum selects the network from the credential. A local sandbox setting cannot independently prove that a credential is a test credential. The supplied key was described as a test key by its owner. Responses explicitly marked mainnet are rejected, but this check occurs after the request. Only install provider-confirmed test credentials.

Apply migration `0022_stereum_test_integration` to the intended development database using the normal migration workflow. No application database migration has been executed as part of this change.

Open Django admin → Stereum test operations → **Open Stereum test console**, using an active superuser. Read-only quotes and bank queries work with mutations disabled. Set `STEREUM_TEST_WRITES_ENABLED=True` to exercise test charge/order/payout creation. Use synthetic test identities.

The CLI uses the same durable records and permissions:

```sh
# quote.json: {"side":"BUY","amount":"1000.00","currency":"USDT"}
CONFIO_ENV=testnet ./myvenv/bin/python manage.py stereum_test quote \
  --actor <superuser> --payload-file /tmp/quote.json

CONFIO_ENV=testnet ./myvenv/bin/python manage.py stereum_test refresh \
  --actor <superuser> --request-id <saved-request-UUID>
```

Every new action needs a new request UUID. Reuse a UUID only for the identical action and payload: it returns the existing record and never resubmits. References such as `quote_request_id` are local request UUIDs, not provider resource IDs. References are limited to the same administrator and API credential. The `quote` action uses the corporate `SELF` identity. The `customer_quote` action uses the signed-in user’s registered Stereum identity and never falls back to SELF. Staff orders can reference either type of quote belonging to that same user.

## Test sequence

1. Fetch banks and BUY/SELL quotes. BUY input is BOB; SELL input is USDT/USDC. Fiat rail is `CSL`, crypto rail `POLYGON`. Use the returned `expireAt` in milliseconds; observed quotes expire after approximately 60 seconds.
2. Create a charge and inspect its QR/payment link and explicit `on_main_net=false`. Once the company ID is configured, use `confirm_charge` referencing that local charge and refresh its status.
3. Create an FX order referencing a fresh quote. BUY requires a controlled Polygon destination. SELL requires destination bank type, account, holder name and document. The order response supplies the next payment instructions. No crypto funding or bridge is initiated by this integration.
4. Decode a provider-supplied sandbox QR. Review recipient, amount, currency and expiry. `pay_qr` uses only that decoded recipient and maps its bank code through the bank catalog. It requires the corporate BOB account and sender test identity. Decoding does **not** independently verify bank account ownership.
5. Refresh the provider resource. A timeout or uncertain server response remains `unknown`; do not create a fresh UUID to retry it. Reconcile against Stereum using the saved idempotency UUID first. A crashed `submitting` attempt also stays reserved. `SALDO_VERIFICADO` is not treated as final payment success.

A request UUID is committed before submission; callers must not wrap execution in another database transaction. Database uniqueness also reserves FX quotes, single-use QR payloads and charge confirmations across request UUIDs. Reservations remain consumed after uncertain outcomes. Status polling locks each operation and refuses to overwrite a terminal result with a conflicting response. There are no automatic POST retries. PostgreSQL row locking serializes attempts by administrator; the same quote is reserved after its first order attempt, even if the attempt fails or is uncertain. Test data can include identity/account information, so use synthetic identities and restrict admin/database access.

## Webhooks

Configure the test API key's callback to `/api/stereum/test/webhook/` on a reachable test backend. HMAC-SHA256 validates the exact raw body using the signing secret string and `x-signature`. Duplicate bodies are deduplicated per API credential. Events are stored for inspection; they do not drive settlement or credit wallets. Use provider polling to reconcile resources. Live webhook delivery and the precise event envelope remain unverified.

## Verification and remaining work

The supplied key successfully fetched 58 banks and both quote directions through this adapter. Focused tests cover signing, timeouts, mutation controls, duplicate-submission handling, QR recipient constraints, quote expiry, resource matching, and webhook authentication/deduplication. The suite includes mocked contract/service tests and real isolated SQLite migration, persistence, rollback and uniqueness checks. PostgreSQL concurrency and live payment certification remain unverified. Run the offline suite without loading application secrets or touching an application database:

```sh
./myvenv/bin/python -m ramps.tests.run_stereum
```

Before an end-to-end sandbox run, obtain the test company ID, corporate BOB account ID, a sandbox QR and any required test liquidity. Then verify charge simulation, QR payment, FX order completion and webhook delivery. Before customer rollout, certify the KYC identity mapping against Stereum, and implement/verify wallet funding and settlement, Confío's fee application, background reconciliation and production mobile provider routing. Confío's 0.9% fee is not added to sandbox provider quotes; its existing mint/redeem charging must not be duplicated.

Provider reference: https://stereum.tech/developers


## Customer identity handoff

Migration `0023_stereum_customer` adds a per-user, per-credential registration with a stable external UUID, source verification reference, consent time, request snapshot and stage status. Enable `STEREUM_CUSTOMER_TEST_ENABLED` for this sandbox feature. Writes still require `STEREUM_TEST_WRITES_ENABLED=True`.

The backend selects the authenticated user’s current verified **personal** identity. Names, document number/type and birthdate come from that record; callers cannot supply another user ID or replace the legal identity. Expired, unverified and business-context identities are rejected. This initial integration supports Bolivia residents with Bolivian CI/CE documents or passports. Economic activity and other profile details must follow Stereum’s accepted catalog; production certification of those values remains necessary.

For CI/CE, the user supplies the surname split (which must match the verified full surname) and optional document complement. `POST /api/v1/segip/validate` is signed; only `VERIFIED` with a usable `validationId` advances. `POST /api/v1/customers/create` receives that reference as `doc_provider_id`, plus residence department, economic activity, income bracket and source/destination of funds. Passports skip SEGIP. No document images, hosted document URLs or another provider’s approval token are sent.

Customer registration uses our stable UUID as `idempotency_key`. Customer quotes use the same UUID as `externalUserId`, matching the endpoint field documentation. The provider-generated customer ID is stored separately and cannot be linked to two users in the same credential scope. `registered` means the customer record exists, not that Stereum has granted every FX service; customer quotes must still pass provider eligibility checks. Live confirmation of this identity linkage remains outstanding.

Stages are `validating → validated → registering → registered`, with `rejected` for definitive failure and `unknown` for uncertain outcomes. Each network stage is committed before submission. A saved `validated` stage can safely resume registration. In-flight, rejected and uncertain attempts are not automatically repeated; reconcile those with Stereum before changing data or retrying. No endpoint for retrieving customer/SEGIP status has been verified, so there is no automatic KYC reconciliation. Changed identities are blocked from quoting until reconciled.

### Interfaces

* Django admin → Stereum customers → **Onboard my test customer** previews the signed-in administrator’s verified identity and collects the additional fields and explicit consent. Use a designated test account with provider-approved test identity data. Existing ramp economic activity is prefilled when available.
* Authenticated personal-account GraphQL exposes `onboardStereumCustomer(details, consent)`, `stereumCustomerStatus`, and `createStereumCustomerQuote(requestId, side, amount, currency)`. User ownership comes from the authenticated context; business contexts are rejected. Provider credentials and customer IDs are not exposed by the status API.
* The quote console and CLI support `customer_quote` with the same side/amount/currency fields as `quote`.

Example request (only additional profile information is supplied):

```graphql
mutation {
  onboardStereumCustomer(consent: true, details: {
    stateOfResidence: "BO_L"
    economicActivity: "Tecnología y software (desarrollo, soporte, ciberseguridad)"
    sourceOfFunds: "Trabajo"
    destinationOfFunds: "Servicios"
    incomeLevel: "500 - 1000"
    surname1: "PEREZ"
    surname2: "MEDINA"
  }) { status error }
}
```

No live end-user identity has been submitted during development. Automated tests use synthetic records and mock provider responses. The admin UI and backend API are implemented; mobile onboarding/navigation has not been connected to these new APIs.

## Bolivia QR in the mobile app

`STEREUM_MOBILE_QR_TEST_ENABLED=True` enables the `bo_qr` send method for active superusers in their own personal account context, while Stereum is configured for sandbox. This operator restriction is intentional: QR payouts still use the corporate test BOB account, without debiting customer wallets. Regular customer payments must not be enabled until wallet funding, fees and settlement are connected. The Enviar entry and screen explicitly say they are tests.

The backend's existing `localMoneyMethods` query advertises the Bolivia entry to eligible operators. Enviar routes that entry through `LocalSend` to `BoliviaQrSendScreen`. `ScanScreen` recognizes BO EMV country hints and the documented encrypted `ciphertext|16-hex` envelope, then checks server availability before routing. Recognition is not verification; all payloads are decoded by Stereum on the server. For other Bolivia QR encodings, the dedicated Enviar scanner accepts the raw payload without a client format restriction. The scanner modal supports both camera and gallery imports.

The app calls `decodeStereumQr`, displays recipient, bank, last four account digits, expiration and BOB amount, and explains that these are QR contents rather than independently verified account ownership. A fixed amount cannot be edited; open QR amounts accept 1–69,000 BOB with two decimal places. Scanning does not submit payment. The review screen and explicit payment confirmation are separate, with the existing critical-action authentication flow before submission.

`payStereumQr` derives the sender name/document from the operator's verified identity. It accepts only the local decode reference, amount and stable request UUID; recipient fields cannot be overridden. Existing provider expiry, fixed-amount, ownership and single-use guards remain authoritative. `stereumQrPayment` exposes only the owning operator's payout status and polls the provider when a resource ID exists.

Before submission, the app saves the request UUID in account-scoped secure storage. Lost responses remain locked for status checking, and a restarted screen recovers either that local reference or a pending server operation. Unreadable storage fails closed. Terminal results clear the journal; unknown/not-yet-found results must be reconciled rather than creating another payment. There is no automatic retry of a payment POST.

This change has automated scanner/screen/backend coverage, but camera behavior and real provider payment completion still require a device and provider-approved sandbox QR, corporate account ID and test balance. No live payments were submitted during implementation. The customer KYC onboarding screen remains separate from this operator QR flow.
