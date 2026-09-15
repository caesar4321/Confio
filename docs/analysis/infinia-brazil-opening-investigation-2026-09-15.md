# Brazilian Infinia opening investigation

## Confirmed findings

Read-only production inspection on 2026-09-15. No provider POSTs, database updates, payments, or deployments were performed during this investigation.

1. From 19:49:05 through at least 19:59:23 UTC, account creation repeatedly returned `Infinia POST /v1/accounts/ failed: An internal server error occurred.` The journal does not include the HTTP status or full response payload, so the provider's internal cause remains unknown.
2. The original request subsequently succeeded: the provider account was created at 19:59:31 UTC and is ACTIVE. A GET filtered by the original idempotency key found it. Confio also persisted its active state.
3. At 20:01 UTC the activation remained `provisioning`, with no payment transaction. Direct evaluation of `opening_ready()` returned false.
4. The BRL funding response has `type: fiat`, a nonempty `br_code`, and `br_code_brl.br_code`. It has no Pix key or account number. The stored instruction is `bank_details`, active, with an empty display value. The companion crypto instruction is active and nonempty.

## Current root cause

`payment_accounts/services.py:328` does not normalize `br_code` or `br_code_brl.br_code`. It classifies this real Pix QR response as bank details and discards the usable display value.

`payment_accounts/activation.py:125` requires an active, nonempty instruction matching the country's receive method. Brazil's receive method in `payment_accounts/local_money.py` only accepts `pix_key`. Thus adding QR parsing alone would still leave the activation stuck.

`receive_account()` also filters by that single kind. The receive screen labels Brazil's returned value as a Pix key. QR support needs consistent parsing, readiness, receive selection, and presentation; a QR payment payload should not be labeled as a Pix key.

## Why failures appear silent

`activation.reconcile()` catches all provisioning exceptions and returns the unchanged activation after logging. The application opening loop has ten polling attempts and no explicit exhausted-loop error. An active account with an unrecognized funding instruction similarly remains provisioning without an error.

## Ruled out / limits

- Provider owner is COMPLETED, SELF_DECLARED, with no failure reason.
- PAYINS, PAYOUTS, and INTERNAL_TRANSFER are APPROVED for BR for company 1921.
- The request fields match the current documented creation schema.
- Provider recovery under the original key rules out a permanently invalid request as the explanation for the current blockage. It does not explain the earlier internal provider failure.
- Repository state changed concurrently during the investigation. Relevant parsing code was also read directly from production to verify the deployed behavior.

## Recommended fix and verification

Normalize the two BR Code response shapes, accept usable Pix QR instructions in activation readiness and receive lookup, and render accurate copy/QR UI. Keep payment gated on genuinely usable instructions. Regression coverage should use the production response shape and prove that an active local/crypto pair transitions to awaiting_payment without creating or charging a payment during reconciliation. Add explicit pending/error feedback when polling is exhausted and preserve safe retries with the existing request key.

## References

- https://docs.infiniaweb.com/reference/v1_0_create_account_.md
- https://docs.infiniaweb.com/reference/v1_1_list_accounts_.md
- https://docs.infiniaweb.com/docs/account-capabilities.md
- https://docs.infiniaweb.com/docs/required-documents.md

## Fix and audit outcome

Implemented locally after the investigation:

- Normalize flat/nested Pix QR and Pix key responses, preserving existing generic QR values.
- Share unexpired receiving-instruction selection between readiness and receiving; return the actual kind through GraphQL.
- Retire superseded Brazilian QR/key instructions atomically so missing or malformed replacement data cannot leave an old payment destination usable.
- Store full QR payloads with a TextField (`0019_fundinginstruction_display_value`).
- Render the Pix QR and copy/share its exact payload; use neutral Pix wording before issuance and key wording only for an issued key.
- Explain when opening polling is exhausted and leave the user free to exit or retry.

Audit loop: three native reviewer passes. Pass one found stale QR reuse and misleading pre-opening copy; both were fixed. The parent review also found the 255-character storage limit and preserved the legacy generic QR value fallback. Pass two and the final pass found no unresolved actionable issues in this scope.

Verification:

- 455 payment-account tests passed on isolated PostgreSQL. The offline harness disables unrelated historical migrations and explicitly loads the current eligibility policy seeds.
- 39 mobile tests passed, covering receive rendering/copy/share, existing key presentation, unpaid gating, opening timeout/retry, activation services, and send activation behavior.
- The new regression suite run against the original parsing/readiness/receiving functions produced six failures and four errors, confirming it detects the original defects.
- The actual storage migration preserved an existing value and allowed a 600-character value to round-trip on isolated PostgreSQL. Model/migration consistency and whitespace checks passed.
- Whole-project TypeScript checking reports 377 diagnostics outside the changed Pix screens/tests; it is not a clean project-wide type check.

The optional external Claude review was rejected by automatic approval review because it would export private repository source. No external payload was sent. Native independent reviews completed; external coverage is unavailable.

No deployment, production migration, payment, or production record edit was performed. Rollout requires migration 0019 plus backend and mobile release. Existing unpaid activations are retried by the current reconciliation job, which can normalize the provider's stored/live QR data after deployment without recreating the provider account.
