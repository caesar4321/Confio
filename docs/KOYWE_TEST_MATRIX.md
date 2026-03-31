# Koywe Test Matrix

Last updated: 2026-03-31

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

## Practical Conclusions

1. Production is healthier and broader than sandbox behavior suggests.
2. Sandbox is sufficient for delegated-KYC contract validation.
3. Brazil sandbox payout remains unreliable even with a valid CPF.
4. Mexico is currently best tested with `RFC`, not `CURP`.
5. For clean sandbox retests, use:
   - fresh emails
   - unused valid documents
   - country-consistent address payloads

## Next Recommended Tests

1. Ask Koywe about:
   - `BankAccountBRA::save::error:getBankListByCountry problem`
   - valid Mexico sandbox `STP` bank/account examples
2. Keep using fresh sandbox emails for repeatability.
3. Prefer `RFC` for Mexico QA unless Koywe confirms a known-good `CURP` sample.
4. Use production for:
   - provider availability
   - redirect behavior
   - quote behavior
   - merchant enablement checks
