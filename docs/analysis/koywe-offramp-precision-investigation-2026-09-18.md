# Koywe off-ramp funding refusal — 2026-09-18

Status: root cause reproduced and backend fix implemented; deployment validation recorded below.

## Confirmed cause

Production database reads and Daphne journals confirm that orders 1588, 1625,
1630, and 1632 were blocked by Confío's amount validation before automatic
funding. Closing the app is not needed to explain any of these failures.

The 90-bps fee preview produces a net amount with nine decimal places for
these six-decimal gross inputs. `_provider_amount_matches` floors the
provider amount to six decimals, then compares it to the unquantized fee
preview. All four comparisons fail.

| Order | Creation UTC | Gross | Preview net | Provider amount / comparison LHS |
| --- | --- | --- | --- | --- |
| 1588 | Sep 14 09:56:27 | 55.294678 | 54.797025898 | 54.797025 |
| 1625 | Sep 16 20:58:33 | 55.303787 | 54.806052917 | 54.806052 |
| 1630 | Sep 17 15:03:46 | 55.308343 | 54.810567913 | 54.810567 |
| 1632 | Sep 18 03:23:49 | 55.312898 | 54.815081918 | 54.815081 |

Persisted `provider_payload_created` confirms each gross, net, 90-bps fee,
and provider `amountIn`. The records remain PENDING / waiting as inspected
around 07:14 UTC on September 18.

Exact production log for order 1625 at September 16 20:58:36.137 UTC:

```text
Koywe amount_in 54.806052 != requested 54.806052917; refusing to auto-fund this order
```

Equivalent logs exist for 1588 at September 14 09:56:29.514 UTC, 1630 at
September 17 15:03:51.474 UTC, and 1632 at September 18 03:23:51.415 UTC.

The false validation result removes the server-validated deposit address.
The mobile funding service returns `skipped / missing_bsc_destination`
before invoking the wallet funding function. The order has already been
created and remains pending. The client navigates to the instructions screen
and displays an alert; the persistent order state does not distinguish this
funding refusal from ordinary waiting.

## Supporting production evidence

- No SponsoredBatch entries exist for this customer's user ID after September
  14 09:56 UTC. Their latest batch was a confirmed stock sale at 09:43 that day.
- Their earlier August 30 withdrawal has a confirmed redeem batch and a
  completed provider order, providing a working historical comparison.
- Repeated order-status validation logs continue after creation, including
  more than a minute after order 1625. App-exit timing is not established,
  but waiting longer cannot bypass the deterministic creation-time refusal.
- Production HEAD reported `038dcb985`; the deployed validator was read
  directly and has the same asymmetric precision comparison.

## Additional confirmed status-validation defect

`resolve_ramp_order_status` reads `getattr(result, 'amount_in', None)`, but
`KoyweOrderStatusResult` has no `amount_in` field. The actual amount exists in
`result.raw_response['amountIn']`. Status polling therefore logs:

```text
Koywe returned an unreadable amount_in (None); refusing to auto-fund
```

This prevents status responses from supplying validated funding details. It
is distinct from the initial precision error and does not itself prove that
the current instructions screen attempts to resume funding.

## Local reproduction

Extracted the actual `_provider_amount_matches` AST from `ramps/schema.py`
and executed it with Decimal, ROUND_DOWN, InvalidOperation, and a logger;
no Django initialization, database mutation, provider request, or chain
transaction was needed. All four production amount pairs returned False.
A same-precision control (`54.815081` versus `54.815081`) returned True.

## Repair requirements

1. Define one provider-supported amount precision before quote/order creation;
   preserve the exact gross debit and fee separately, and use the same provider
   amount for the quote, verification, and on-chain USDT payment. Merely relaxing
   the comparison would leave the payment amount different from the order.
2. Read and validate the real status-response amount; preserve creation-time
   gross/net fee metadata across provider polling.
3. Represent an unfunded/refused order accurately instead of ordinary pending
   payout, and prevent repeated attempts from obscuring that state.
4. Reconcile existing orders before recovery; do not automatically fund all
   duplicate attempts. This investigation did not execute any withdrawal,
   cancel any order, or independently audit all chain transfers/balances.

## Code references

- `ramps/schema.py`: fee preview/provider amount around 1040; response
  validation around 1429; status validation around 1952; validator at 2216.
- `ramps/koywe_client.py`: KoyweOrderStatusResult at 103; status construction
  at 822.
- `apps/src/services/koyweOffRampService.ts`: missing BSC destination at 286.
- `apps/src/screens/SellScreen.tsx`: funding outcome handling around 499–535.

Production access was read-only: database queries used PostgreSQL
`SET TRANSACTION READ ONLY`; journals and deployed source were read via SSH.
No production state was changed during the investigation.

## Implemented correction and audit loop

- Quote, order creation, and USDT funding now share a six-decimal provider
  amount. The exact contract gross, fee and net remain separately recorded;
  less than one micro-USDT of rounding remainder stays in the wallet.
- Status validation reads the provider's real `amountIn` and reconciles it
  against immutable creation metadata, never the mutable estimate updated
  by polling. Records without an immutable amount remain unfundable.
- Off-ramp status responses recognize `destinationAddress` and reject
  conflicting deposit addresses.
- Fee metadata must contain valid positive gross/net amounts, net <= gross,
  and a provider amount consistent with the order. Malformed fee metadata
  cannot downgrade funding to a legacy raw-USDT transfer.
- Independent review found and prompted fixes for validation after mutable
  status sync, missing/malformed gross vouchers, and repeat-poll acceptance
  through a mutable fallback. Regression coverage includes each case.
- Core regressions were run against the original committed schema in an
  isolated process and failed, then passed against the repaired schema.

Existing pending attempts are not automatically funded by this deployment.
The app signs funding only during order creation. No customer payment is
authorized or broadcast by the deployment verification.
