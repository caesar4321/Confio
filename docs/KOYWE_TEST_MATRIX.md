# Koywe Test Matrix

Last updated: 2026-04-01

## Scope

This document tracks what has been validated against:

- Koywe sandbox: contract behavior
- Koywe production: real provider availability and executable quote behavior

It is not a generic product document. It is the current engineering truth for Confio's integration work.

## Key Rules

- Treat sandbox as contract validation only.
- Treat production as the source of truth for real provider behavior.
- Do not assume sandbox redirect/provider behavior matches production.

## Confirmed Contract Findings

### `/rest/accounts`

Confirmed in sandbox:

- `address.addressCountry` must be ISO alpha-3:
  - `ARG`, `BOL`, `BRA`, `CHL`, `COL`, `MEX`, `PER`
- `POST /rest/accounts` can update an existing account for the same email.
- Document uniqueness is still enforced.
- Updating a profile with a different valid document can succeed for the same email.

### `/rest/bank-accounts`

Confirmed in sandbox:

- Koywe requires `email` in the payload.
- Koywe requires `documentNumber` in the payload.

This is implemented in:

- [ramps/koywe_client.py](/Users/julian/Confio/ramps/koywe_client.py)

## Sandbox Delegated-KYC Results

### `/rest/accounts`

Validated successfully:

- `AR` with `DNI`
- `BO` with `CI`
- `CL` with `RUT`
- `CO` with `CED_CIU`
- `MX` with `RFC`
- `PE` with `DNI`
- `BR` with valid `CPF`

Notes:

- Brazil failed with invalid sample CPF until a checksum-valid CPF was used.
- Mexico `CURP` was not validated successfully with the sample used.

### Document-type results

- `BR`
  - `CPF`: validated
- `MX`
  - `RFC`: validated
  - `CURP`: not validated with sample `GODE561231HDFRRN04`

## Sandbox Bank-Account Results

### After fixing `email` + `documentNumber` payload

`CO / NEQUI`
- result: `422 Document already exists for this client`
- meaning: payload moved past missing-field validation; duplicate identity/account state is now the blocker

`CO / BANCOLOMBIA`
- result: `422 Document already exists for this client`

`PE / LIGO`
- result: `422 Document already exists for this client`

`BO / SIP_QR`
- result: `422 Document already exists for this client`

`MX / STP`
- initial result with old sample: `documentNumber is not valid for MEX`
- with valid `RFC`, `/rest/accounts` succeeds
- bank-account creation then fails on account routing semantics, not document validation

### Fresh-email targeted retests

`BR / CPF`
- `/rest/accounts`: `200 OK`
- `/rest/bank-accounts`: `500 BankAccountBRA::save::error:getBankListByCountry problem`
- interpretation: Brazil sandbox payout failure is on Koywe's side

`MX / RFC`
- `/rest/accounts`: `200 OK`
- `/rest/bank-accounts`: `400 Error creating bankAccount, accountNumber belongs to another bank`
- interpretation: document path is valid; remaining issue is bank/account pairing

`MX / CURP`
- `/rest/accounts`: `400 Document number format is invalid`
- interpretation: current CURP sample is not accepted

## Production Provider and Quote Results

Production authentication with Confio's merchant credentials is working.

Confirmed executable provider lists and quotes:

`CO / COP`
- providers: `PSE`, `NEQUI`, `BANCOLOMBIA`
- `NEQUI` quote works

`PE / PEN`
- providers: `WIREPE`, `QRI-PE`, `RECAUDO-PE`
- `QRI-PE` quote works

`BO / BOB`
- providers: `QRI-BO`
- `QRI-BO` quote works

`AR / ARS`
- providers: `KHIPU`, `WIREAR`, `QRI-AR`
- `WIREAR` quote works

`BR / BRL`
- providers: `SULPAYMENTS`, `PIX_QR`
- `PIX_QR` quote works

`CL / CLP`
- providers: `WIRECL`, `KHIPU`
- `WIRECL` quote works

`MX / MXN`
- providers: `WIREMX`, `STP`
- `STP` quote works

## Production `duende-*` Account Results

These tests were run against Koywe production using the pre-existing `duende-*` accounts Koywe provided.

### `CO / duende-colombia`

- auth: `200`
- providers: `PSE`, `NEQUI`, `BANCOLOMBIA`
- executable quote: works
- `NEQUI` bank-account creation: `200`
- `BANCOLOMBIA` bank-account creation: `200`

Interpretation:

- `CO` is strongly production-validated for both on-ramp provider behavior and off-ramp payout-account setup.

### `PE / duende-peru`

- auth: `200`
- providers: `WIREPE`, `QRI-PE`, `RECAUDO-PE`
- executable quote: works
- `QRI-PE` payout-account creation: `200`
- `WIREPE` payout-account creation: `200`

Interpretation:

- `PE` is strongly production-validated for both on-ramp provider behavior and off-ramp payout-account setup.

### `CL / duende-chile`

- auth: `200`
- providers: `WIRECL`, `KHIPU`
- executable quote: works
- `WIRECL` payout-account creation: `200`

Interpretation:

- `CL` is strongly production-validated for both on-ramp provider behavior and off-ramp payout-account setup.

### `AR / duende-argentina`

- auth: `200`
- providers: `KHIPU`, `WIREAR`, `QRI-AR`
- executable quote: works
- bank-info: works
- payout-account creation: `400 Failed to validate if bank account ... belongs to ...`

Interpretation:

- `AR` on-ramp is production-validated at quote level.
- `AR` off-ramp is not yet validated end to end because payout-account ownership validation failed with the sample data used.

### `BO / duende-bolivia`

- auth: `200`
- providers: `QRI-BO`
- executable quote: works
- payout-account creation: `400 bank account not found`

Interpretation:

- `BO` on-ramp is production-validated at quote level.
- `BO` off-ramp is not yet validated because payout-account semantics remain unclear in production.

### `BR / duende-brazil`

- auth: `200`
- providers: `SULPAYMENTS`, `PIX_QR`
- executable quote: works
- payout-account creation: `400 BankCode not valid PIX_QR`

Interpretation:

- `BR` on-ramp is production-validated at quote level.
- `BR` off-ramp is not yet validated because the tested PIX `bankCode` is not accepted for payout-account creation.

### `MX / duende-mexico`

- auth: `200`
- providers: `WIREMX`, `STP`
- executable quote: works
- payout-account creation: `400 documentNumber is not valid for MEX`

Interpretation:

- `MX` on-ramp is production-validated at quote level.
- `MX` off-ramp is not yet validated because the production test identity/payout data is still not accepted.

## Directional Validation Summary

| Country | On-ramp validated | Off-ramp validated | Notes |
|---|---|---|---|
| `CO` | Yes | Yes, account setup validated | `NEQUI` and `BANCOLOMBIA` payout-account creation succeeded |
| `PE` | Yes | Yes, account setup validated | `QRI-PE` and `WIREPE` payout-account creation succeeded |
| `CL` | Yes | Yes, account setup validated | `WIRECL` payout-account creation succeeded |
| `AR` | Yes, quote/provider level | No | payout-account ownership validation failed with sample data |
| `BO` | Yes, quote/provider level | No | payout-account creation returned `bank account not found` |
| `BR` | Yes, quote/provider level | No | tested PIX `bankCode` rejected for payout-account creation |
| `MX` | Yes, quote/provider level | No | production payout-account creation still rejects tested document/data |

Important:

- `Off-ramp validated` here means payout-account setup is production-validated.
- It does not yet mean full fiat settlement has been certified end to end for every country.
- Full off-ramp certification still requires:
  - order creation
  - funding
  - provider settlement
  - final status reconciliation

## Practical Conclusions

1. Production is healthier and broader than sandbox behavior suggests.
2. Sandbox is sufficient for delegated-KYC contract validation.
3. On-ramp is much more validated than off-ramp across the full country matrix.
4. `CO`, `PE`, and `CL` currently have the strongest production readiness because both quote behavior and payout-account setup were validated.
5. Brazil sandbox payout remains unreliable even with a valid CPF.
6. Mexico is currently best tested with `RFC`, not `CURP`.
7. For clean sandbox retests, use:
   - fresh emails
   - unused valid documents
   - country-consistent address payloads

## Next Recommended Tests

1. Ask Koywe about:
   - `BankAccountBRA::save::error:getBankListByCountry problem`
   - valid Mexico sandbox and production `STP` bank/account examples
   - Bolivia production payout-account expectations for `QRI-BO`
   - Brazil production payout `bankCode` for PIX off-ramp
2. Keep using fresh sandbox emails for repeatability.
3. Prefer `RFC` for Mexico QA unless Koywe confirms a known-good `CURP` sample.
4. Use production for:
   - provider availability
   - redirect behavior
   - quote behavior
   - merchant enablement checks
5. For full off-ramp certification, run controlled production end-to-end tests in:
   - `CO`
   - `PE`
   - `CL`
