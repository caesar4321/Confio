# Design: Perpetual futures on Hyperliquid

Status: DRAFT (spec only, nothing built)
Date: 2026-10-25
Prior art reused: `cusd_plus/crypto_*` (catalog, policy, risk ack, holdings, history,
`CryptoTrade`), `cusd_plus/sponsor_7702.py` (sponsored EIP-7702 batches + relay policy),
`payment_accounts/relay.py` (Relay quote binding and validation), `cusd_plus/fee_ledger.py`,
`inbox/member_portfolio.py`, `users/cashflow.py`, `security/geo.py` (`GeoPolicy`).

## 1. What this is

A member opens a leveraged long or short on a Hyperliquid perpetual market (core perps
such as BTC/ETH/SOL, and HIP-3 markets such as `xyz:GOLD` or `xyz:NVDA`) from inside the
Confío app, signed by their own in-app key. Margin leaves Confío Dollar through the
ordinary exit, crosses to Hyperliquid through Relay, backs exactly one isolated position,
and on close comes back through Relay into Confío Dollar through the ordinary entry.

Fixed inputs (not reopened by this spec):

- Venue: Hyperliquid (HyperCore perps + HIP-3).
- Bridge: Relay (`api.relay.link`), BSC ⇄ HyperCore.
- No builder fee and no perps-specific fee. Each open pays the ordinary cUSD exit fee
  (0.9%) on the margin; each return pays the ordinary entry fee (0.9%) on what comes back.

## 2. Measured facts (2026-10-25)

All quotes are live `POST /quote/v2` responses, `EXACT_INPUT`, user = recipient (same EVM
address on both sides). Raw responses kept outside the repo.

### 2.1 Relay delivers straight into the HyperCore account

Relay lists Hyperliquid as chain `1337` (`vmType: hypevm`), currency "USDC (Perps)",
address `0x0000…0000`, 8 decimals. A quote from BSC USDT to `1337` credits the user's
**HyperCore perps balance directly** (the solver transfers inside HyperCore). It does not
touch Arbitrum and does not use Hyperliquid's Bridge2:

- Hyperliquid's 5 USDC Bridge2 minimum deposit **does not apply**. Relay quoted $1, $2 and
  $3 into an existing HyperCore account.
- The user **never needs ETH on Arbitrum**, and never needs HYPE (HyperCore has no gas).

Steps Relay returns:

| Direction | Steps | Who signs what |
|---|---|---|
| BSC → HyperCore | `approve` USDT to the Relay depository `0x4cd0…bc31`, then `deposit` (`0xe8017952`: depositor, token, amount, orderId) | Two plain BSC calls, so they fit in one sponsored 7702 batch |
| HyperCore → BSC | `authorize`: EIP-712 `RelayNonceMapping` (posted to Relay `/authorize`); `deposit`: a Hyperliquid **user-signed `sendAsset`** to Relay's HyperCore depository `0x66cf…2224` (token `USDC:0x6d1e…e054`, `sourceDex: ""`) | Two EIP-712 signatures, no transaction, no gas |

Withdrawing through Relay therefore **avoids the $1 Bridge2 withdrawal fee**. It is an
internal HyperCore `sendAsset`, not a `withdraw3`.

### 2.2 Quotes

| Margin | BSC USDT → HyperCore (credited) | Cost | HyperCore → BSC USDT (received) | Cost |
|---:|---:|---:|---:|---:|
| $5 | 4.9686 | $0.031 (0.63%) | 4.9657 | $0.034 (0.69%) |
| $10 | 9.9571 | $0.043 (0.43%) | 9.9541 | $0.046 (0.46%) |
| $20 | 19.9342 | $0.066 (0.33%) | 19.9309 | $0.069 (0.35%) |
| $100 | 99.7511 | $0.249 (0.25%) | 99.7453 | $0.255 (0.25%) |

`timeEstimate` is 1 s in both directions. Relay's `minimumAmount` sits ~2% under the
expected output, which is its default tolerance. The app binds a tighter floor, using the
same dollar-and-bps rule as `payment_accounts/relay.py`.

### 2.3 First deposit into a new HyperCore account costs $1.20 once

Relay quoted the same BSC → HyperCore route to an address with `userRole: missing` at
**$1.20 less** at every size ($5 → 3.77 instead of 4.97). $1 would not quote at all
(`AMOUNT_TOO_LOW`). This is Hyperliquid's new-account transfer charge, passed through by
Relay. Every member pays it on their first open only, shown up front (§3.3).

### 2.4 Hyperliquid venue facts

- Markets listed today: 178 core perps (56 more are delisted), with $2.6B of 24h
  notional. HIP-3 dexes:

  | Dex | Collateral | Listed markets | 24h notional |
  |---|---|---:|---:|
  | `xyz` (trade.xyz) | USDC | 116 (stocks, indices, metals, energy, FX) | $582M |
  | `io` | USDC | 11 | $26M |
  | `para` | USDC | 32 | $2.1M |
  | `mkts` | USDC | 5 | $1.1M |
  | `flx`, `vntl`, `km` | USDH | — | — |
  | `hyna` | USDE | — | — |
  | `cash` | USDT0 | — | — |

- Only USDC-collateral dexes can use the Relay route as-is.
- **Account mode decides whether HIP-3 needs extra transfers.** Hyperliquid has three
  modes, set with the user-signed `userSetAbstraction`:
  - **standard**: separate core, spot and per-dex balances. Each HIP-3 market needs
    `sendAsset` core → dex before the open, and dex → core before the return.
  - **`unifiedAccount`**: one balance per asset, shared across core, HIP-3 and spot.
    Hyperliquid recommends it for most users. It is capped at 50k actions/day. Balances and
    holds are reported in the spot clearinghouse state, so per-dex user states are no
    longer meaningful.
  - **`portfolioMargin`**: margins eligible assets together. Not used here.

  The older HIP-3 "DEX abstraction" (`userDexAbstraction`, auto-transfer from the USDC
  perps balance) is deprecated and discontinued in favor of these modes.
  `userAbstraction` reads `default` for both an existing and a fresh address
  (2026-10-25). Which concrete mode `default` means is not documented and must be checked
  on mainnet (§9).
- Max leverage from `meta`: BTC 40x, ETH 25x, SOL 20x, PAXG 10x, `xyz:GOLD` 25x,
  `xyz:SILVER` 25x, `xyz:` stocks 20x.
- Taker / maker at tier 0: 0.045% / 0.015% on core. HIP-3 `xyz` has
  `deployerFeeScale` 1.0, which doubles taker fees (≈0.09%). Markets in growth mode
  (e.g. `xyz:TSLA`, `xyz:NVDA`, `xyz:AAPL`, `xyz:SILVER`) get a ≥90% discount (≈0.009%).
  `xyz:GOLD` is not in growth mode.
- Minimum order value: $10 notional.
- Liquidation: a book liquidation leaves any remaining collateral with the trader. A
  backstop liquidation forfeits the isolated margin. There is no liquidation fee.

### 2.5 All-in round trip (flat price, open + close, no funding)

| Margin | Core 1x | Core 5x | HIP-3 5x (no growth mode) |
|---:|---:|---:|---:|
| $5 | — (below $10 notional) | $0.18 (3.5%) | $0.20 (4.0%) |
| $10 | — (below $10 notional) | $0.31 (3.1%) | $0.35 (3.5%) |
| $20 | $0.51 (2.5%) | $0.58 (2.9%) | $0.67 (3.3%) |
| $100 | $2.37 (2.4%) | $2.73 (2.7%) | $3.17 (3.2%) |

Breakdown at $100, core 5x: perimeter $1.78 (0.9% each way), Relay $0.50, Hyperliquid
taker $0.45. Add $1.20 on the member's first open (§2.3). Funding accrues on top, in
either direction.

## 3. Margin model

### 3.1 Isolated, one live position per member

Every position is **isolated** (`updateLeverage` with `isCross: false` before the order).
Each open funds exactly one position, so its margin is never shared with another one.

**A member holds one live position at a time** (database constraint
`perp_one_live_position_per_wallet`; a second open is refused with
`one_position_at_a_time`, a second open on the same market with `position_exists`, which
points to adding margin instead). Everything free on the member's HyperCore account then
belongs to exactly one position, so attribution needs no per-position arithmetic and a
lost answer can never be credited to the wrong position. Several simultaneous positions
would need one HyperCore sub-account per position; the data model already keys
everything by position, so lifting the limit is a contained change.

The **return rule** follows from isolation: the HyperCore *withdrawable* balance never
includes the isolated margin of positions that are still open. So the amount a close
returns is **the whole withdrawable balance**. In unified mode that is the free USDC in
the spot clearinghouse state; in standard mode it is core plus each HIP-3 dex. That one
rule
covers four cases with no per-position arithmetic:

- the closed position's margin and P&L, after fees and funding;
- residual collateral after a book liquidation;
- deposit dust (the order is sized from the credited amount, rounded to `szDecimals`);
- anything stranded by an earlier failure.

The target balance on Hyperliquid between flows is zero idle USDC.

**Account mode: standard at launch, unified if the mainnet canary confirms it.**
- **Built today:** the first open's plan starts with a user-signed
  `userSetAbstraction("disabled")` when Hyperliquid reports any other mode, so every
  account runs in standard mode, with explicit `sendAsset` steps for HIP-3 markets. The
  server re-plans after that step (`replan`).
- **Turning unified on:** the same step with `"unifiedAccount"`. After that, HIP-3 markets need no per-position
  `sendAsset` in or out: one less signature and one less failure step on every HIP-3 open
  and close.
- **Must be proven first (§9):**
  - a Relay credit lands in the unified balance;
  - Relay's return `sendAsset` (`sourceDex: ""`) can spend it;
  - isolated orders on `xyz:` work in unified mode;
  - an isolated position's margin is excluded from the free balance.
- **Fallback:** if any of these fails, the design stays in standard mode with the explicit
  `sendAsset` steps described below. Both paths are specified, and the reconciler reads
  whichever mode `userAbstraction` reports.

### 3.2 Sizing

The order is sized **after** the deposit lands: notional = credited × leverage, minus a
taker-fee buffer, rounded down to `szDecimals`. The member chooses margin in dollars, and
the confirmation shows margin, leverage, notional, estimated liquidation price and every
cost from §2.5.

### 3.3 Minimums

- **Minimum notional: $12** after the deposit. That keeps Hyperliquid's $10 floor with
  room for a small price move between quote and fill.
- **Minimum margin: $10.** At $10 a 1x position cannot reach $12 notional ($10 → 9.91 USDT
  after exit → 9.87 credited), so the app requires margin × leverage ≥ $12 and offers
  leverage from 2x at $10. Below $10, Relay's fixed cost goes above 0.6% per leg.
- **First open:** the member pays the one-time $1.20 activation. The first-open
  confirmation shows it as its own line ("Activación de tu cuenta en Hyperliquid (solo la
  primera vez): $1,20"), next to the other costs. The market screen explains it in one
  sentence before the member starts. Minimum first margin is **$12**, so the activation
  does not leave the position under the floor. Whether an address is new comes from
  `userRole` (`missing`) at quote time, and the Relay quote already prices it.
- **Return leg minimum:** $2. A smaller withdrawable balance stays on Hyperliquid, shown as
  "saldo pendiente", and rides along with the next return.

### 3.4 Margin changes

- **Adding margin** to an open position is an **open leg**: exit (0.9%) → Relay →
  `updateIsolatedMargin(+)`. The confirmation calls it "Agregar margen".
- **Removing margin** (`updateIsolatedMargin(−)`, down to Hyperliquid's allowed level) is a
  **return leg** (§5.2 from the withdraw step).
- **Every dollar of new margin crosses the perimeter.** Opening, adding margin and
  closing each go through the 0.9% exit or entry, with no exceptions. Idle withdrawable
  USDC on Hyperliquid is never used as margin for a new position or a top-up: it is
  returned home (or, under $2, waits for the next return). Dollars on Hyperliquid back
  exactly one position or are on their way home.

## 4. Signing and submission

### 4.1 One key, no agent wallet

The member's in-app EVM key is the same address on BSC and on HyperCore. It signs:

| Action | Hyperliquid type | EIP-712 domain |
|---|---|---|
| `updateLeverage`, `order`, `cancel`, `updateIsolatedMargin` | L1 action (phantom agent: `connectionId = keccak(msgpack(action) ‖ nonce ‖ vault)`) | `Exchange`, v1, chainId 1337 |
| `sendAsset` (to Relay; core ⇄ HIP-3 dex in standard mode only) | user-signed action | `HyperliquidSignTransaction`, `signatureChainId` set by the client |
| `userSetAbstraction` (`unifiedAccount`, once per account) | user-signed action | `HyperliquidSignTransaction` |
| Relay `NonceMapping` | Relay authorization | `RelayNonceMapping`, v2, chainId 1 |

**No agent wallet.** An agent key held by the server could trade the member's account,
which makes it a custody key. An agent key held on the device adds nothing over the main
key, which is already on the device. Nonces are millisecond timestamps (Hyperliquid keeps
the 100 highest per signer), which also works across a member's devices.

Automation that would need a key, such as stop-loss, take-profit and liquidation, runs
**on the venue**. Take-profit and stop-loss are native Hyperliquid trigger orders, signed
at open time. What no venue order can do is the *return*: after a trigger closes a
position, the money waits on Hyperliquid until the member opens the app (§5.4).

### 4.2 Server-forwarded, policy-checked

The app signs, then posts the signed action to Confío. The server checks it against the
perps policy and forwards it to `api.hyperliquid.xyz/exchange`. This mirrors the 7702
relay: the server records each signed action before it goes out, and enforces the policy
on its side too (the UI and the API both enforce it).

The policy checks (`cusd_plus/perps_flow.py`: `validate_batch` for the BSC legs,
`submit_action` / `submit_return` for Hyperliquid):

- `order` / `updateLeverage`: market is openable in the perps catalog; leverage ≤ the
  market's Hyperliquid `maxLeverage`; margin mode isolated; no builder field; `vaultAddress` absent.
  Opens need `PERPS_POLICY` + risk ack + the open flags; reduce-only closes and cancels are
  **never** gated.
- `sendAsset`: destination is Relay's HyperCore depository for a quote the server issued
  to this member, or (standard mode only) the member's own HIP-3 dex balance; token is
  USDC.
- Each signed action must equal, field for field, the step the server issued for this
  position (only the nonce is the app's). Steps are claimed atomically in order, sent once,
  and expire after 10 minutes. An order whose answer was lost is found again by its client
  order id, never re-sent blindly.
- Opens and returns exclude each other under the position's row lock: no open step is
  sent while a return is quoted, and no return is signed while an open step is on the wire.
- `userSetAbstraction`: only `disabled` or `unifiedAccount`. `portfolioMargin` is refused, because it
  margins positions together and breaks the one-position-per-open isolation (§3.1).
- Anything else (`withdraw3`, `usdSend` to third parties, `approveAgent`, vault and
  staking actions) is refused.

The policy only binds the Confío app. The key can always talk to Hyperliquid directly,
which is also the member's exit if Confío is ever unavailable.

### 4.2.1 What the app checks before it signs

The server issues every plan; the app re-checks it and refuses to sign anything else
(`apps/src/services/perps.ts`):

- **BSC batches:** only Confío-dollar exits to the member, USDT approvals to Relay's
  depository (outbound) or to Confío's dollar contracts (the entry), mints to the member,
  and exactly one Relay deposit whose depositor is the member. Every amount is capped at
  what the member reviewed. Confío's dollar contract addresses are compiled into the app;
  the server's values must match them.
- **Hyperliquid actions:** the purpose must belong to the stage the member started; orders
  must be on the position's market, side and leverage, opens no larger than its margin
  allows, closes and protections reduce-only; `sendAsset` only between the member's own
  balances on that market's dex (or to Relay's HyperCore depository on the return);
  margin changes may only add.
- **Price impact:** an open past the warning level needs a second confirmation; past the
  maximum the server refuses it.

- **Signature lifetime:** Hyperliquid accepts any unused nonce up to two days old, so
  a signature that never reached the venue stays valid. The app records every nonce it
  signs under before signing. A retried order, protection or leverage change reuses the
  previous unresolved signature's nonce, so at most one of them can ever execute. Before
  any new money moves (an open, a top-up, a bridge retry), the app spends every recorded
  nonce with Hyperliquid's `noop` action, posted directly to Hyperliquid. Only a
  "used" or "too old" answer counts; anything else stops the flow.
- **TP/SL:** replacing protection places the new triggers first and cancels the old ones
  only after Hyperliquid shows the new ones live, at full size and at the prices
  entered.

- **The Relay order:** Relay decides where a deposit or a return pays out from the order
  its quote creates. The server fetches the quote and passes Relay's raw signed quote with
  the plan. The app proves the order itself:
  - the order ID must equal Relay's EIP-712 hash of the order terms (its `getOrderId`,
    verified against recorded quotes in both directions);
  - the order signature must come from Relay's solver, whose address is pinned in the app
    and in settings (`RELAY_PERPS_SOLVERS`).
  So the payout recipient, the refund recipients, the amounts and the deadline are the
  terms Relay will execute. The app then requires the member as sender, payout recipient
  and refund recipient; the amount within what the member reviewed; the guaranteed
  minimum within the same slippage and cost bounds the server uses; and the order not
  expired. It signs only the deposit call for that order, or the nonce mapping and
  `sendAsset` for that order. A compromised server can't redirect the payout.

Rate limits: Hyperliquid limits per IP (1200 weight/min, 1 per exchange action) and per
address. One server IP covers about 1,200 actions a minute. A second egress, or
client-direct submission with server reconciliation, is the fallback if that ever binds.

### 4.3 The BSC legs reuse the 7702 batch

Two new batch kinds go in `sponsor_7702.py`, validated like `crypto_buy` / `crypto_sell`:

- **`perps_open`**: `[exit, approve(USDT → Relay depository), depository.deposit]`.
  - The exit is the existing cUSD `redeem` or cUSD+ `redeemToUsdt` with the recipient
    pinned to the signer.
  - The policy decodes the deposit (`0xe8017952`) and checks: depositor = signer; token =
    BSC USDT; amount ≤ the exit's net preview; `orderId` = the Relay quote the server
    fetched and validated for this member, recipient = the same address on `1337`, refund
    to the signer on BSC.
  - One signature and atomic: the exit and the bridge deposit succeed or revert together,
    so dollars never sit idle as USDT after a revert.
- **`perps_return`**: `[approve, mint]` into cUSD, or into cUSD+ when the member is
  eligible. This is the ordinary entry: the same calls as `mint_cusd` / `subscribe`, under
  a kind that ties it to a position. The cUSD+ path keeps `check_savings_mint_eligibility`
  and `is_safe_mint_amount`; otherwise it lands in cUSD, as crypto sells do.
- **`perps_bridge_retry`**: `[approve, depository.deposit]` alone, for USDT that Relay
  refunded (§5.3). No exit, so no second fee.

`send_sponsored_batch` skips `outgoing_identity_restriction` for `crypto_buy` /
`crypto_sell`. `perps_return` belongs on that list, because it brings money home. Whether
`perps_open` does is a policy call: the money leaves BSC, but only for the member's own
HyperCore account. This spec proposes the same treatment as `crypto_buy`.

The Relay quote binding reuses `RelayClient.validate_quote`, extended with the
`BSC:USDT ⇄ HL:USDC` pair: exact sender/recipient/currency, a deterioration bound and a
total-cost cap. Refunds to the signer are always on the origin chain.

## 5. State machine

One `PerpPosition` row per position. Each step's external id (batch hash, Relay request
id, Hyperliquid oid) is stored before the next step starts. A reconciler task (every 2 min
while any position is in flight, plus on app open) moves states from **observed facts
only**: the BSC receipt, Relay `/intents/status/v3`, and Hyperliquid `info`
(`userAbstraction`; `spotClearinghouseState` in unified mode or `clearinghouseState` per
dex in standard mode; `userFills`; `userNonFundingLedgerUpdates`). The server
never signs for the member. A stuck step shows the member where it stopped and a retry
button. Following the house rule, a needs-review flag never blocks the member's next
action.

### 5.1 Open

```
quoted ──(perps_open batch)──► bridging ──(Relay success, credit seen)──► funded
   │                              │                                          │
   │ batch reverts                │ Relay refund                             │ updateLeverage + IOC order
   ▼                              ▼                                          ▼
failed (nothing moved)        refunded (USDT on BSC)                      open
                                │ retry: perps_bridge_retry → bridging        (fill seen in userFills)
                                │ cancel: perps_return entry (0.9%) → cancelled
```

- **quoted**: the server fetches and binds the Relay quote; the app shows every cost. A
  quote expires after 60 s, then the app requotes.
- **bridging**: the batch has confirmed and Relay is in flight (1 s typical). Past 10 min
  it shows "Transferencia demorada" while the reconciler keeps polling Relay.
- **funded**: USDC is on HyperCore. In unified mode a HIP-3 order draws on that balance
  directly. In standard mode the app first signs the `sendAsset` into the dex. The app signs `updateLeverage` and an IOC market order with a
  slippage bound, plus optional TP/SL triggers.
  - If the order is rejected or does not fill, the position stays **funded**. The member
    sees "Tu margen está en Hyperliquid" with two buttons: "Reintentar orden", or "Traer de
    vuelta", which runs the return leg (§5.2). Nothing is lost; the money sits in the
    member's own account.
- **refunded**: rare. Relay could not deliver and returned the USDT, minus its refund
  gas, to the member's BSC address. The open's exit fee has already been charged.
  - "Reintentar" bridges the same USDT again (`perps_bridge_retry`). It is the same open,
    so there is no second exit.
  - "Volver a dólares" means the money comes back in without a position. Like any
    return, it runs the ordinary entry (0.9%).

### 5.2 Close and return

```
open ──(reduce-only IOC)──► closed ──([standard mode, HIP-3: sendAsset dex→core]; Relay authorize + sendAsset)──► returning
                                                                                                │
                                         Relay success: USDT on member's BSC address ◄──────────┘
                                                   │
                                     (perps_return batch) ──► done
```

- **closed**: reduce-only close filled (or TP/SL filled, or liquidation, §5.5).
- **returning**: the withdrawable sweep (§3.1) is signed and posted. Relay failure →
  `return_failed`: the USDC is still on HyperCore, and "Reintentar" requotes.
- **landed** (implicit): USDT is on the member's BSC address. The app immediately signs
  `perps_return`. If the app was closed, the next app open finds `landed` and asks for
  that one signature. A `perps_return` revert keeps the USDT on the member's address with
  a retry; nothing is lost.
- **done**: the history row is written from the receipts and fills.

### 5.3 Where the money is, per state

| State | Money is | Member action |
|---|---|---|
| failed | still cUSD / cUSD+ | none |
| bridging | inside Relay | wait; Relay refunds to BSC if it fails |
| refunded | USDT, member's BSC address | retry bridge, or back to dollars |
| funded | USDC, member's HyperCore account | retry order, or return |
| open | isolated margin on Hyperliquid | close, add or remove margin |
| closed / return_failed | USDC, member's HyperCore account | return (retry) |
| returning | inside Relay | wait; Relay refunds to HyperCore if it fails |
| landed | USDT, member's BSC address | one signature to enter |

At every point the money sits on the member's own addresses or inside a Relay order that
refunds to them. Confío never holds it.

### 5.4 Positions closed while the app is closed

A take-profit, stop-loss or liquidation can close a position on the venue at any time.
The reconciler sees it and sends a push notification ("Tu posición en BTC se cerró:
+$3,10. Abre Confío para traerlo a tus dólares."). The return runs the next time the
member opens the app. Until then the Invertir card shows "Listo para traer".

### 5.5 Liquidation

The reconciler detects the position gone with a liquidation fill. The state becomes
`liquidated`.

- **Book liquidation:** whatever is withdrawable is returned through the normal return
  leg, if it is ≥ $2.
- **Backstop liquidation:** nothing returns.

History shows the loss as margin in − amount returned, with "Liquidada" and the
liquidation price. No fee is involved.

## 6. Data model

- `PerpPosition`: user, wallet, dex (`""` or `xyz`), coin, side, leverage, margin
  requested (USD), state, step error, `open_batch` (SponsoredBatch), `relay_out_id`,
  credited USDC, entry oid + average price + size, TP/SL oids, close oid + average price,
  realized P&L, funding, venue fees, `relay_back_id`, `return_batch`, returned USD,
  liquidated (book/backstop), timestamps per transition.
- `PerpMarginChange`: position, direction, amount, its own open or return leg ids.
- `PerpsRiskAcknowledgement`: user, version, acknowledged_at (same shape as
  `CryptoRiskAcknowledgement`).
- `cusd_plus/perps_catalog.py`: the market list is **synced from Hyperliquid**, not
  hand-picked, the way onchain.cc (Bitso) lists every Hyperliquid crypto perp plus
  builder-deployed stocks, commodities, FX and indices.
  - A Celery task reads `meta` for core and for each USDC-collateral HIP-3 dex (§2.4) and
    stores dex, coin, `szDecimals`, `maxLeverage` and `onlyIsolated`.
  - A market is **openable** when all of these hold: listed on Hyperliquid; USDC
    collateral; not in `PERPS_EXCLUDED_MARKETS` (ops removes a broken market without a
    deploy).
  - There is **no volume floor**. Measured 2026-10-25, a $1M 24h-notional floor would hide
    125 of 178 core markets and 71 of 116 `xyz` markets, NFLX, COST, LLY and TSM among
    them. Yet the median impact spread among those markets is ~21 bps. Thin books are
    handled per order instead (§6.1).
  - Display metadata (Spanish name, asset class, logo) is a small overlay JSON, and
    unknown markets fall back to the ticker. Asset class is crypto, stock, index,
    commodity or FX, from the dex and the overlay.
  - Markets that drop out stay closeable.
- All models registered in `config/admin_dashboard.py`.

### 6.1 Price impact, per order

A market's liquidity matters only at the size being traded, so the check runs on each
order:

- **Shown before confirming.** The app walks the live `l2Book` for the order's real size
  and shows the estimated average fill and its price impact vs mid ("Impacto en el
  precio: 0,4%").
- **Opens and margin adds:**
  - above `PERPS_IMPACT_WARN_BPS` (100), a second confirmation explains that the market is
    thin at this size and suggests a smaller one;
  - above `PERPS_IMPACT_MAX_BPS` (300), the open is refused.

  The server policy re-walks the book before forwarding the order, so an old or buggy
  client cannot skip the check.
- **Closes are never refused** for impact, because a holder can always leave. Above the
  warning level, the app shows the impact and offers to close in parts.
- **Slippage bound on every order.** Each IOC order is a limit at the quoted average fill
  ± `PERPS_SLIPPAGE_BPS` (50). A market order can never fill worse than the price the
  member saw plus that bound. If the book moved, the order does not fill and the app
  requotes. The policy refuses an order whose limit price is outside that bound around
  the live mid.

## 7. Where it shows up

- **Invertir**: a card named **«Futuros»** (subtitle "Largo o corto, con apalancamiento ·
  24/7").
  - **Position:** below "Acciones de EE.UU." and "Oro y Bitcoin", above "$CONFIO". The
    cards are ordered by risk, and most members use Confío for daily money, so the
    riskiest product sits low. Members who want leverage will scroll to it.
  - **Not promoted:** "Futuros" has no row or shortcut of its own on Home. Its value
    still counts in the Home total's existing investments term, because it is the
    member's money. It gets no push notifications, banners or assistant suggestions. The only push
    notifications are about the member's own positions (§5.4).
  - **The card itself:** it follows the hub rules. The big number on the right is the
    member's own money in positions (margin ± P&L). Each open position is a row ("BTC ·
    Largo 10x", P&L on the small line), with "Listo para traer" and stuck-step badges.
  - **The market list:** tabs Cripto · Acciones · Índices · Materias primas · Divisas,
    with search.
  - **The market page:** the chart (Hyperliquid candles), the funding rate, and Abrir
    largo / Abrir corto.
  - **Wording:** "futuros perpetuos" is used in full in the disclosure and the
    explanation screen.
- **Activity history** (`cusd_plus/unified.py`):
  - one row per open ("Abriste largo BTC 5x · −$20,00"), per margin change, and per
    return ("Cerraste BTC · +$23,10");
  - liquidation shows "Liquidada · −$20,00", or the partial return;
  - stuck steps show on the row.
- **Tu mes** (`users/cashflow.py`): `perps_open` and margin-add legs count as investment
  outflow, `perps_return` as inflow, the same classification as `stock_buy` / `stock_sell`.
  Investment net = returns − margin in.
- **Comunidad (unified from launch)**: perps are positions like stocks, Bitcoin and gold.
  - **Investor profile:** perps appear in the same portfolio and position lists, with
    side and leverage shown on each row. The all-time Total counts perps:
    returned − margin in, plus unrealized P&L on open positions.
  - **Activity shares:** the same opt-in share card on open and on close. The card shows
    market, side, leverage, margin, and on close the exact P&L.
  - **Liga:** a position's return is P&L ÷ margin, so a liquidation counts as the loss of
    its margin (−100% after a backstop liquidation). `inbox/member_portfolio.py` reads
    `PerpPosition` beside `CryptoTrade` and the stock trades.
- **Fee ledger**: new source `('perps', 'Perps (Hyperliquid)')`; `classify` maps
  `perps_open`, `perps_bridge_retry` (no fee event) and `perps_return` to it. Hyperliquid
  taker fees and Relay costs are the member's market costs and stay out of the ledger.

## 8. Risk surfaces

- **Leverage**: no Confío cap. The limit is each market's Hyperliquid `maxLeverage`
  (read live from `meta`, e.g. BTC 40x, `xyz:` stocks 20x), together with Hyperliquid's
  own margin tables at larger sizes. The policy only checks leverage ≤ the venue maximum,
  so a stale client gets a readable refusal before Hyperliquid rejects the order. The
  confirmation shows the liquidation price at every leverage.
- **Disclosure / ack** (`cusd_plus/perps_risk.py`, the `crypto_risk` pattern):
  - Server-served text, versioned. The relay refuses an open without the ack, so old
    builds get a readable refusal. Closing and returning never ask.
  - The points cover: leverage multiplies losses; liquidation can take the whole margin;
    funding is charged or paid every hour; Hyperliquid is a third-party venue Confío does
    not operate; each open and close crosses chains through Relay and pays the
    exit/entry fee; prices move 24/7; not financial advice.
- **Country policy**: `PERPS_POLICY = GeoPolicy(name='perps', …)`, phone and IP, missing
  phone fails closed.
  - Baseline is the venue's restricted list: `US`, the sanctioned set `CU IR KP SY`, and
    `CA` (Ontario cannot be told apart from the rest of Canada by phone or IP country).
  - Also in the baseline: `GB` and `BE`, the extra countries MetaMask's Hyperliquid perps
    exclude.
  - `PERPS_BLOCKED_COUNTRIES` adds codes without a deploy.
  - `PERPS_PROMOTION_BLOCKED_COUNTRIES` keeps the feature available in a country but
    removes every promotion there: no push notifications, banners, Home placement or
    assistant suggestions about perps. The member finds it in Invertir and turns it on
    themselves.
  - Only **opens** are gated. A holder can always close and return.
- **Flags**: `PERPS_ENABLED` (discovery), `PERPS_TRADING_ENABLED`, `PERPS_OPEN_ENABLED`,
  `PERPS_ALLOWED_USER_IDS` (canary), and `PERPS_IOS_ENABLED`. All default on since
  2026-10-26 (builds without Futuros never query it), so they are emergency levers only. A min app version
  gates every new field, which goes in its own isolated GraphQL query until it is live
  everywhere.
- **Store guidelines** (read 2026-10-25):
  - Apple 3.2.2(viii): apps that facilitate trading in CFDs or other derivatives "must be
    properly licensed in all jurisdictions where the service is available".
  - Apple 3.1.5(iv): apps facilitating cryptocurrency futures trading "must come from
    established banks, securities firms, futures commission merchants (FCM), or other
    approved financial institutions".
  - Perpetual futures fall under both.
  - Google Play's Financial Services policy names no rule for derivatives. It does require
    the Financial features declaration. Its crypto exchange/wallet licensing table
    excludes non-custodial wallets.
- **iOS precedent** (2026-10-25): Apple does approve non-custodial interfaces to
  Hyperliquid perps.

  | App (seller) | What it is on iOS | Key model | Region notes |
  |---|---|---|---|
  | MetaMask Mobile (Consensys) | perps tab since 2025-10, 150+ markets, up to 40x, US stocks | user key, exportable | excludes US, GB, Ontario, BE, US-sanctioned |
  | Phantom | Hyperliquid perps on mobile since 2025-07 | user key, exportable | launched EU first |
  | fomo (FOMO Labs, Inc.) | social trading app with Hyperliquid perps | Privy wallet, exportable | excludes US persons from perps |
  | Lootbase | Hyperliquid-only iOS app | non-custodial, exportable | listing says "not an exchange", no advice |
  | Dexly (Hyper Lion LTD) | "non-custodial wallet interface that connects to Hyperliquid"; Finance, 4+; releases since Feb, latest Oct 5 | connected wallet signs | none stated |
  | Splash, Based | Hyperliquid trading apps listed on the App Store | self-custody | — |

  Counter-signal: Hyperliquid itself ships Android only, and iPhone users go to its PWA.

  The approved apps share four traits:
  - a company submits them (5.1.1(ix));
  - the user's key signs every action;
  - they say they are an interface, not an exchange or broker;
  - they exclude US persons.

  Confío has all four, except that its key is not exportable. That makes the "the user
  controls the funds" argument rest on the Salida de emergencia, which today covers BSC
  only.

  Confío's iOS 5.2.6 review on 2026-10-21 already raised 3.1.5 and 3.2.1, so the
  submission needs to be prepared:
  1. **Salida de emergencia covers HyperCore** (§8.1).
  2. A visible "Confío no es un exchange ni un bróker; las órdenes se ejecutan en
     Hyperliquid" line on the perps screens and in the risk ack.
  3. The US block, plus the baseline above.
  4. Review notes that describe the interface model, name Hyperliquid, and show a demo
     account with a small position.

  The platform flag `PERPS_IOS_ENABLED` stays as a kill switch. If review rejects perps,
  iOS keeps spot stocks, Bitcoin and gold.

### 8.1 Salida de emergencia for HyperCore funds

The emergency exit is already client-side and signs with the member's key. A HyperCore
leg fits that model, because Hyperliquid actions are signed fresh at exit time. Nothing
is pre-signed: Hyperliquid nonces must fall within a few days of the current time.

When the exit is open, it does the following:
1. Lists open positions from `clearinghouseState` (read straight from
   `api.hyperliquid.xyz`, no Confío server).
2. Signs reduce-only market closes for each one.
3. In standard mode, moves each HIP-3 dex balance to core (`sendAsset`). Unified mode
   needs no step here.
4. Sends the whole withdrawable USDC to the destination the member enters, by a Bridge2
   `withdraw3` to the same address on Arbitrum: gasless for the member, $1 Hyperliquid fee.

A close is an IOC order, which can fill partly or not at all. The exit re-reads the account
after each round, retries wider (5%, 8%, 12% from the mark), and never withdraws while a
position is still open. If one cannot be closed, it says so and moves nothing.

Relay is not used here, so the exit depends on nothing but Hyperliquid. The exit follows
the same gate as the BSC exit (14 days of heartbeat silence). Hyperliquid has no on-chain
hook for that gate, so the app enforces it and the key itself is never limited. The steps
have resumable checkpoints, like the BSC legs.

## 9. Build order

1. Perps catalog, policy, risk ack, GeoPolicy, flags, models (server). No money moves.
2. Relay `BSC:USDT ⇄ HL:USDC` quote binding, extending `payment_accounts/relay.py`.
3. 7702 kinds `perps_open` / `perps_return` / `perps_bridge_retry` + fee-ledger source.
4. Hyperliquid signing in the app (EIP-712 L1 phantom agent + user-signed actions,
   msgpack), plus the server forwarder with the policy.
5. Reconciler + push notifications + stuck-step UI + the HyperCore leg of the Salida de
   emergencia (§8.1).
6. Invertir section, history rows, Tu mes, investor profile.
7. Canary on mainnet with real small positions:
   - first-deposit activation charge;
   - reduce-only close of a position under $10 notional;
   - book vs backstop liquidation residue;
   - Relay refund path on both sides;
   - unified account: the four checks in §3.1 (Relay credit, Relay return, isolated `xyz:`
     orders, free balance excludes isolated margin), and what `userAbstraction: default`
     means for a new address.

## 10. Decisions

Settled 2026-10-25:

- **Leverage:** no Confío cap; each market's Hyperliquid maximum applies (§8).
- **First-deposit activation ($1.20):** the member pays, shown up front (§3.3).
- **Fees:** every open, every margin add and every return crosses the perimeter at 0.9%.
  A Relay refund retry is the same open (§5.1).
- **Comunidad:** unified at launch: profile, Total, shares and Liga (§7).
- **Markets:** synced from Hyperliquid core + USDC HIP-3 dexes, no volume floor; thin
  books are handled by the per-order price-impact check (§6, §6.1).
- **iOS:** precedent exists (§8). iOS ships after the four submission items in §8 are in
  place, with `PERPS_IOS_ENABLED` as a kill switch.

- **Memecoins:** included, like the rest of Hyperliquid core.
- **One live position per member** at launch (§3.1).
- **Account mode:** standard at launch; unified after the canary (§3.1).

Open:

- **Relay API key:** Relay's docs say `/quote/v2` needs an `x-api-key`. Keyless quotes
  still worked on 2026-10-26. The client sends `RELAY_API_KEY` whenever it's configured;
  creating the key is an ops step (dashboard.relay.link → Apps).

The impact and slippage thresholds above are starting values in settings, so they can be
tuned without a deploy.
