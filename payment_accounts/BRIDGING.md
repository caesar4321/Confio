# Implicit provider bridging with Allbridge NEXT

This integration executes BSC USDT → a verified provider's Polygon USDC address,
and Polygon USDC already in the customer's wallet → that customer's BSC USDT
wallet. The app presents dollar movements rather than a separate bridge tool.
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

## Configuration and rollout

Apply `payment_accounts` migrations 0005–0007 **before** deploying callers of
`reserved_usdt_wei`, which now reserves wallet USDT for pending bridges.

```env
PAYMENT_BRIDGE_QUOTES_ENABLED=False
PAYMENT_BRIDGE_BSC_ENABLED=False
PAYMENT_BRIDGE_POLYGON_ENABLED=False
PAYMENT_BRIDGE_MAX_USDT=100
PAYMENT_BRIDGE_VERIFIED_INSTRUCTIONS={}
PAYMENT_BRIDGE_POLYGON_RPC_URL=https://polygon-bor-rpc.publicnode.com
PAYMENT_BRIDGE_POLYGON_MAX_GAS_PRICE_WEI=500000000000
```

Existing provider flags and verified identity/eligibility must also be enabled.
For outbound, configure only a provider-confirmed, active reusable native
Polygon USDC instruction that accepts bridge-originated funds:

```json
{
  "<funding-instruction-UUID>": {
    "token_id": "POL:USDC",
    "address": "<provider-issued Polygon address>"
  }
}
```

The mapping attests to the exact instruction and address. Address rotation
requires reverification. Provider webhook metadata cannot enable execution.

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
