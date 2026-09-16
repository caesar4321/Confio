# Implicit provider bridging with Relay (legacy NEXT retained)

## Relay rollout — September 15, 2026

New estimates and durable quotes use Relay `/quote/v2` deposit addresses in
both directions. Existing NEXT quotes/transfers continue with NEXT/NEAR Intents;
never change an in-flight transfer's provider or deposit address.

`relay.py` validates canonical tokens, base-unit amounts, recipient, refund
terms, protocol output, the authorized deterioration ceiling, and exactly one
ERC20 transfer with zero native value. No router calldata, approvals, app fee, or arbitrary URLs are
accepted. The deposit-address fee is included in the displayed quote. Confío's
0.9% remains at cUSD mint/redeem; no second fee is added through Relay.

Julian explicitly selected the API-trusted deposit-address model. Relay does
not yet expose independent derivation of a deposit address from order terms.
Also, `/quote/v2` ignores `strict`; EXACT_INPUT addresses can reprice on deposit.
(`strict` is documented as ignored, but it is still what unlocks `EXACT_OUTPUT`:
without it `/quote/v2` returns 400 `INVALID_REQUEST_PARAMS`. We stay on
`EXACT_INPUT` regardless — see the slippage section below.)
Do not claim that our local minimum is independently enforced on chain. We
retain the reviewed minimum and hold any shortfall for review after checking
finalized destination receipts. We cap local authorization at ten minutes.

Relay's status locates transaction hashes; it cannot alone mark delivery or
refund. Reconciliation checks source-hash inclusion, chain IDs, finalized
receipts, exact token/recipient, and the reviewed minimum. Split provider
deliveries and partial refunds require review. Full refunds require a receipt
back to the source wallet. An API timeout never triggers a second deposit.
Unresolved status lookups or destination receipts escalate to review one hour
after the deposit deadline. Receive estimates price the actual reverse Relay
route at the authorized FX lower bound, then apply the existing repricing
cushion; fixed bridge costs are not approximated as a percentage.

Sources: [quotes](https://docs.relay.link/references/api/get-quote-v2),
[deposit addresses](https://docs.relay.link/features/deposit-addresses),
[validation limitations](https://docs.relay.link/references/api/api_core_concepts/input-validation),
[status](https://docs.relay.link/references/api/get-intents-status-v3).

The NEXT-specific sections below document retained legacy execution.

This integration executes BSC USDT → a verified provider's Polygon USDC address,
and Polygon USDC already in the customer's wallet → that customer's BSC USDT
wallet. Infinia inbound journeys also fund a bridge Polygon deposit directly from
the user's provider account, with BSC USDT delivered to their wallet (see
[Infinia journeys](INFINIA_JOURNEYS.md)). The app presents dollar movements rather than a separate bridge tool.
The feature defaults off. It does not turn a bridge receipt into a fiat payout.

## Verified NEXT contract

Checked against the official Allbridge MCP source and live NEXT API on
2026-09-05. NEXT **does support a distinct recipient**: `/tx/create` takes
`sourceAddress` and `destinationAddress`. Core's `toAccountAddress` is not the
NEXT field name. Both directions currently quote the `near-intents` messenger.

- `GET https://api.next.allbridge.io/tokens`: verify chain, contract, decimals.
- `POST /quote`: `sourceTokenId`, `destinationTokenId`, integer-string `amount`.
- `POST /tx/create`: selected route, source/destination, `refundTo=source`.
- Live response: `amountOut`, `amountOutMin`, and `tx` with source ERC20
  `contractAddress`, `value: "0"`, and transfer calldata (sometimes without `0x`).
- Verify the unique deposit through NEAR's `/v0/status?depositAddress=...` and
  `/v0/tokens`: exact input, source/refund/recipient, chain/token contracts,
  output minimum, no memo/virtual recipient, unused deposit and deadlines.

The current bridge route uses an ordinary ERC20 transfer to a unique NEAR
Intents deposit address. Execution rejects other messengers and arbitrary
calldata. This is intentionally stricter than the general NEXT quote client.
No Core assumptions about relayer fees, approval requirements, or BNB-free
transactions are carried over. Source gas is sponsored by Confío.
For `funding_mode=infinia`, Infinia submits the source transfer and pays its gas;
Confío binds that hash to the authenticated payout movement instead of signing.

Sources:

- [Allbridge NEXT API client](https://github.com/allbridge-io/allbridge-mcp/blob/master/src/next-api-client.ts)
- [Allbridge NEXT tools](https://github.com/allbridge-io/allbridge-mcp/blob/master/src/next-tools.ts)
- [NEAR execution status](https://docs.near-intents.org/api-reference/oneclick/check-swap-execution-status)
- [Cobre stablecoin payins](https://docs.cobre.com/stablecoin-payins-2262879m0)
- [Cobre global credit metadata](https://docs.cobre.com/transaction-metadata-global-credit-16622693d0)
- [Infinia fund flows](https://docs.infiniaweb.com/docs/fund-flows)

## Execution

1. `quotePaymentBridge(fundingInstructionId, amount, requestId, direction)`
   resolves ownership from the JWT, checks eligibility and provider state,
   creates a durable quote and MoneyFlow. The request UUID is idempotent;
   different details cannot reuse it. Quote lifetime is 60 seconds, not a price
   guarantee. Amounts remain integer strings across API, database and app.
2. `preparePaymentBridge(quoteId)` validates the deposit binding and creates one
   transfer per quote. One pending preparation/transfer per wallet prevents
   duplicate spending and repeated sponsor attempts. An existing preparation
   can be retrieved again without building another deposit.
3. For BSC, the batch spends unreserved wallet USDT first. If needed, it unwraps
   cUSD+ to cUSD and redeems only the missing USDT through the existing conversion
   perimeter. The existing fee is quoted and recorded from canonical events;
   there is no additional Confío bridge fee. A minimum-sized savings redemption
   may leave unused cUSD in the wallet. The last call transfers the exact bridge
   input to the validated deposit. EIP-7702 authorization is collected up front
   if the wallet is not yet delegated.
4. For Polygon, native USDC must already be in the customer wallet. The app signs
   one EIP-3009 `TransferWithAuthorization` with a unique nonce, exact amount,
   deposit address and bounded expiry. The server checks the token's EIP-712
   domain and signature, simulates, sponsors and broadcasts that transfer.
   No Polygon private key is sent to the server.
5. Both paths persist signed source bytes and transaction hash **before**
   broadcast. Retries adopt that transfer. The worker rebroadcasts only those
   same bytes; it never signs a new user authorization. BSC rebroadcast ends
   at expiry. Polygon can rebroadcast an expired authorization to consume the
   sponsor nonce through a revert rather than block later transactions. Polygon
   sponsor nonces are serialized in PostgreSQL.
6. The worker requires finalized, canonical source receipts and exact token
   transfers. It binds NEXT success to the submitted source hash, then verifies
   finalized destination receipts for the pinned token, recipient and output.
   Unsupported finality RPCs fail closed. Refund status alone goes to review.

After signing and submission, the app can close. The Celery worker continues;
reopening the dollar/account screen retrieves history without signing again.
An ambiguous submit result is a status-check situation, not a new transfer.

## Settlement boundary

`delivered` means on-chain delivery only. Inbound MoneyFlow succeeds when its
USDT target arrives in the customer's BSC wallet. The existing foreground dollar
conversion can subsequently handle that USDT; this bridge does not claim that
cUSD was minted while the app was closed.

For outbound Cobre, an authenticated `global_credit` ledger entry must match
the exact financial account, Polygon, USDC, beneficiary address and destination
transaction hash (`metadata.tracking_key`). Only then does the funding MoneyFlow
succeed. The credited currency/amount remains Cobre's ledger value, separately
from bridge output. This works whether the approved Cobre balance credits
`USD_STABLE` or automatically off-ramps to `USD`.

Infinia crypto credits now match the owned USDC_POL account and the documented
`third_party.transaction_hash`, `type=CRYPTO`, and `crypto_network=POLYGON`.
Its [payment journeys](INFINIA_JOURNEYS.md) compose conversion and payout under
a separate owner authorization. They require posted conversion credits and
finalized wallet receipts before advancing. Cobre COP on/off-ramp remains a
separate provider integration.

Cobre's public docs now describe stablecoin balances and COPco on/off-ramp, but
its existing adapter still does not compose an end-user Bre-B COP balance into
that path. A COP/Bre-B key is never accepted as a Polygon deposit address.

## Slippage and small transfers

Rolled back the hard-coded `slippageTolerance: '50'` on 2026-09-15. Relay's cost
is roughly fixed per crossing, so a flat 0.5% band is far tighter than the route
can hold at small sizes and refuses the transfers this product exists to serve.
Measured live that day, BSC USDT -> Polygon USDC:

| Size | $0.50 | $1 | $2 | $5 | $50 | $1000 |
|---|---:|---:|---:|---:|---:|---:|
| Relay auto tier | 452bps | 409bps | 335bps | 200bps | 200bps | 200bps |
| All-in cost | 9.96% | 5.08% | 2.63% | 0.97% | 0.28% | 0.19% |

Cost is ~$0.043 fixed + ~0.19%. Sampling one $2 quote every 5s for a minute, the
quoted output moved 3.80% between the median and the worst sample, so the band
must absorb an absolute swing, not a proportional one.

We now omit `slippageTolerance` and take Relay's amount-aware tier as a proposal,
bounded by `allowed_deterioration()`: `min(max(250bps, $0.15), 1000bps)`. The
dollar floor is what keeps sub-$5 sends alive; a flat 200bps ceiling would have
been a $5 minimum in disguise. The 1000bps cap exists because the floor alone
left no ceiling where it applies -- $0.15 is 15.7% of a $1 output and 75% of a
$0.75 one. Observed tiers peak at 495bps, so the cap keeps ~2x headroom.

A separate backstop caps total cost at 2500bps. Relay prices tiny routes it
cannot serve rather than returning `AMOUNT_TOO_LOW`: on 2026-09-15 it quoted
$0.05 USDT to $0.0031 USDC, destroying 94%, and we would have accepted it. This
is a cost rule, not a size floor -- it bites on value destroyed, so it moves with
gas instead of blocking an amount. Legitimate small sends measured 11.5% at
$0.75 and 8.68% at $1. Its message is Spanish because `NextError` text reaches
the user verbatim through `_public_error`. There is no minimum transfer size — small QR/Alias/Pix sends are the
product, so the cost is disclosed rather than blocked. `payout_quote` returns
`expected_source_amount`, `expected_target` and `total_cost_percent` alongside the
minimum, and `target_amount` is still priced off `amount_out_min`.

Not established: whether an EXACT_INPUT deposit-address order can deliver anywhere
between `minimumAmount` and the quoted amount, and who keeps the improvement when
execution beats the quote. One observed transfer delivered exactly the quoted
amount; that is not proof. Until Relay confirms, assume the user receives only the
minimum and display it that way. A wider tier authorizes a worse result even if
most fills land at the expected amount.

`EXACT_OUTPUT` was evaluated and rejected: it inverts this pipeline, which derives
the USDT input from the user's budget after the cUSD redemption fee, and under
strict semantics the leftover returns as an excess refund on every transfer --
manufacturing the exact event whose handling needs a contract redeploy.

## Configuration and rollout

Apply `payment_accounts` migrations 0005–0007 **before** deploying callers of
`reserved_usdt_wei`, which now reserves wallet USDT for pending bridges.

```env
PAYMENT_BRIDGE_QUOTES_ENABLED=False
PAYMENT_BRIDGE_BSC_ENABLED=False
PAYMENT_BRIDGE_POLYGON_ENABLED=False
# Empty = no per-transfer cap (NEXT prices every size at the same rate).
# Set a positive amount only as an emergency brake.
PAYMENT_BRIDGE_MAX_USDT=
PAYMENT_BRIDGE_POLYGON_RPC_URL=https://polygon-bor-rpc.publicnode.com
PAYMENT_BRIDGE_POLYGON_MAX_GAS_PRICE_WEI=500000000000
```

Existing provider flags and verified identity/eligibility must also be enabled.
Outbound requires an owned, active reusable crypto instruction on a canonical
`USDC_POL` account. Infinia acknowledged the Allbridge-origin settlement flow
in the September 5, 2026 conversation supplied by Julian. No per-instruction
operator allowlist is required. Quotes bind the current provider-issued address;
rotation invalidates existing quotes at execution. Generic `USDC` or
`USD_STABLE` balances cannot establish the required network.

BSC also requires `CUSD_PLUS_7702_ENABLED` and uses the existing 7702 sponsor; Polygon uses the same configured KMS signer
on chain 137, funded separately with native POL. Reserve that signer's Polygon
nonce stream for this integration; unrelated senders must not share it without
coordinating nonce allocation. Monitor sponsor gas and unresolved nonce gaps.

Run Celery beat and worker: `payment_accounts.reconcile_bridges` runs every
30 seconds. New-transfer flags can be disabled while reconciliation continues.
The custom admin displays quotes, transfers and failure codes, but hides signed
raw transactions and does not allow deleting or editing financial evidence.
Delayed source confirmations and refund/amount mismatches require review.
Never reset the source hash and resubmit an unresolved transfer.

`needs_review` is an operator flag, never a gate on the user. Preparation blocks
only on genuinely in-flight transfers (`submitted`, `bridging`, unexpired
`prepared`); funds are protected by `reserved_usdt_wei`, which reserves for
`submitted`/`prepared` only, because by `bridging` the USDT has already left the
wallet. Gating on `needs_review` meant one unresolved row denied that wallet
every future bridge indefinitely -- a Relay outage alone sets
`relay_settlement_delayed`. Observed in production 2026-09-15.

A refund net of gas is a complete refund, not an anomaly. Relay documents that
refunds are paid "minus the cost of gas", so the previous exact-equality check
could never hold and sent every refund to review. `refund_gas_allowance()`
accepts a shortfall up to $0.25 once the receipts prove the funds returned to
the user's own source wallet; a genuinely short return still goes to review.

## Validation

Tests cover quote idempotency/concurrency, ownership and recipient isolation,
route/token/deposit binding, source reservations, expiry, canonical finality,
wrong amounts, uncertain broadcasts, persist-before-broadcast rollback,
Polygon signing parity between Python and TypeScript, Cobre credit correlation,
and app reopen behavior without automatic signing. App GraphQL documents are
validated against the server schema. Tests use dummy keys and mocked external
services; live documentation/quote/domain checks do not move funds.

A real-money sandbox/canary with each contracted provider is still needed before
enabling production execution. No live funds were transferred by this change.

Cobre provider legs are orchestrated separately in [Cobre journeys](COBRE_JOURNEYS.md).
