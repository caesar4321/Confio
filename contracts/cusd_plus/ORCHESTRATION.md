# cUSD ↔ cUSD+ conversion orchestration (Algorand ↔ BSC)

The layer between the app's ConvertAhorro/RetirarAhorro screens and the two
contracts (`cusd.py` on Algorand, `CusdPlusVault.sol` on BSC). Implementation
lands in the `cusd_plus` Django app (models + celery) behind the existing
GraphQL seam (`cusdPlusQuote` → execute mutation later).

**Scope note:** this path exists ONLY for money already inside Confío.
New money never bridges — direct ramps (Koywe → USDT-BSC → vault, and the
reverse) are separate, simpler flows with no Allbridge leg.

## 1. The legs

### Ahorrar (cUSD → cUSD+)
```
leg A (Algorand, atomic):  user cUSD burn → USDC released to treasury.algo
                           (sponsored group; user signs, sponsor pays fees)
leg B (Allbridge Core):    USDC-ALG → USDT-BSC to treasury.bsc
leg C (BSC, atomic):       vault.subscribeAndMint(usdtIn, minUsdyOut, user.bsc)
                           → IM subscribe → USDY into vault → shares to user
```

### Retirar (cUSD+ → cUSD)
```
leg A' (BSC, atomic):      vault.redeemToUsdt(shares, minUsdtOut, treasury.bsc)
leg B' (Allbridge Core):   USDT-BSC → USDC-ALG to treasury.algo
leg C' (Algorand, atomic): cUSD mint_with_collateral (sponsored) → user
```

Cross-chain atomicity does not exist; what we guarantee instead:
**each leg is atomic on its chain, and the saga is exactly-once, resumable,
and can only halt in states where the user's value is parked in a treasury
account with a recorded owner — never lost, never double-spent.**
This is the honest version of the per-conversion chain (decision: the
conversion drives the legs mechanically; no discretionary treasury
management in the hot path).

Addresses: `user.bsc` is derived from the same Web3Auth seed as the user's
Algorand key (non-custodial); the relayer pays all BSC gas. User signs leg
A/C' (their Algorand side); the relayer executes B and the BSC legs.

## 2. Saga state machine

One `ConversionSaga` row per conversion. `conversion_id` (UUIDv7) is the
idempotency key end-to-end: it goes in the Algorand group note, the
Allbridge transfer memo lookup table, and the BSC tx metadata table.

```
QUOTED ─▶ LEG_A_PENDING ─▶ LEG_A_DONE ─▶ LEG_B_PENDING ─▶ LEG_B_DONE
   │            │                              │
   ▼            ▼ (never confirmed)            ▼ (stuck > T_bridge)
 EXPIRED      ABORTED                     BRIDGE_STUCK ──(support/retry)──▶
                                               
LEG_B_DONE ─▶ LEG_C_PENDING ─▶ COMPLETED
                   │
                   ▼ (vault paused / frozen / IM down)
              PARKED_DEST ──(retry loop)──▶ COMPLETED
                   │
                   ▼ (operator decision only)
              REFUNDING ─▶ REFUNDED  (reverse the done legs)
```

Rules:
- Every leg executor is idempotent: before submitting, check for an existing
  on-chain tx tagged with `conversion_id` (the pending-transfer check that
  already hardened the cUSD↔USDC conversion flow). Crash + resume never
  double-submits.
- Transitions are monotonic; a celery beat sweeper re-drives any saga not in
  a terminal state (COMPLETED / REFUNDED / EXPIRED / ABORTED-clean).
- Value location is explicit per state: user wallet → treasury.algo →
  bridge in flight → treasury.bsc → vault. Reconciliation (§6) audits it.

## 3. Quote & guard (before leg A commits anything)

Leg A is the point of no return (burn). Everything is validated before it:

1. **Compose the quote** server-side (`cusdPlusQuote`):
   - Allbridge `getAmountToBeReceived` for USDC-ALG → USDT-BSC (real pool
     math, includes their fee + price impact),
   - IM leg at oracle price (no spread; slippage floor = minUsdyOut),
   - our conversion fee if any (server-config).
2. **Spread guard** (remote config, ~0.5%): if total cost exceeds the
   threshold, run `maxFillUnderThreshold` (binary search on
   getAmountToBeReceived) and return a PARTIAL quote: "convertimos hasta
   $X ahora" — the amber paused/partial state ConvertAhorroScreen already
   renders. Never reject outright when a partial fill fits.
3. **Quote TTL ~60s**, foreground-triggered only (mobile constraint: the app
   must be open; no background auto-conversions). Executing re-checks the
   quote; drift beyond guard → back to step 1, user re-confirms. Only then
   leg A.

Pool reality check (measured 2026-07): the Allbridge Algorand USDC pool held
~$43.5K — 2%+ impact around $20–25K. Consequences:
- per-conversion cap = maxFillUnderThreshold result;
- large conversions become **client-visible partial fills**, not silent
  tranching — the user re-taps to continue once the pool re-arbs (tranches
  need time between them; an auto-tranche loop would race the arbs and is
  the infinite-loop bug we explicitly rejected);
- pool liquidity is polled (token-info endpoint) and alerts fire under
  $30K / $15K so we hear about droughts before users do.

## 4. Allbridge leg specifics

- Integration = Allbridge Core SDK (server-side) — quotes via
  `getAmountToBeReceived`, transfer build + submit, then **poll transfer
  status by tx id** until destination delivery; typical minutes, timeout
  T_bridge (config, ~30 min) → BRIDGE_STUCK + ops alert (their transfers
  don't silently die; stuck ones resolve via retry or support).
- Destination gas: relayer keeps BNB float; Allbridge's destination-gas
  feature optional, not load-bearing.
- **Treasury-inventory fast path (optional v1.5, feature-flagged):** when
  treasury.bsc already holds USDT float ≥ amount, skip leg B for the user's
  saga (settle C immediately) and let a treasury-rebalance saga run leg B in
  the background. Same mechanics, order swapped; the user-facing conversion
  drops from minutes to seconds. The invariant audit (§6) treats owed-value
  identically in both orders. This is float management, not discretion — the
  rebalance saga is triggered mechanically by the float threshold.
- Allbridge **Deposit Addresses** stays backlogged (no slippage protection,
  no programmatic API yet); revisit when their partner reply lands.

## 5. Failure & refund matrix

| Failure point | Value sits in | Action |
| --- | --- | --- |
| Quote/guard fails | user wallet | nothing committed; show paused/partial state |
| Leg A never confirms | user wallet | Algorand groups are atomic; ABORTED, clean |
| After A, bridge quote now over guard | treasury.algo | hold ≤ T_park (1h) re-checking; then operator choice: proceed anyway (we eat the delta), keep holding, or refund-mint cUSD back to user (leg C' machinery) |
| Bridge stuck | in flight | poll → retry/support; never re-send without status resolution (idempotency) |
| Arrival shortfall vs quote | treasury.bsc | within guard: proceed (user got quoted net); beyond guard: ops review — the quote is the contract with the user |
| IM down / vault paused | treasury.bsc | PARKED_DEST, retry loop; USDY mint price is oracle-time so parking costs the user nothing in USD terms |
| User address frozen (vault) | treasury.bsc | compliance hold — value parked with recorded owner, resolved by the freeze process, not the saga |
| Retirar mirror failures | symmetric | same table, reversed; leg A' is the point of no return |

Refunds reuse the opposite direction's leg executors — no bespoke refund
code paths (fewer paths, fewer bugs).

## 6. Reconciliation & monitoring

- Hourly + daily invariant audit across chains:
  `Σ cUSD burned − Σ cUSD re-minted == Σ value delivered to vault ± recorded
  costs/fees` per saga and in aggregate; any unexplained residual pages ops.
- Vault-side public invariant is monitored independently:
  `backingRatioBps() ≥ 10000` (also feeds ProtectedSavings).
- Dashboards: sagas by state + age, Allbridge pool depth, treasury floats
  (algo USDC / bsc USDT / BNB gas), guard-trip rate, partial-fill rate.
- Every state transition emits a websocket event → the app's processing
  screen shows real progression, and a stuck saga shows an honest "tardando
  más de lo normal" instead of a fake spinner.

## 7. UX honesty contract

- ConvertAhorro's processing phase maps to real states (A confirmed →
  "asegurando tu tasa" → C done → success with actual received amount).
- "Al instante" is only promised where it's true: Retirar → cUSD is instant
  ONLY under the fast path (§4) or once C' lands; copy for the slow path is
  "en unos minutos". No resting-order fictions (same rule as GM).
- Partial fills are first-class UI, not an error.

## 8. Open decisions

1. Fast path float sizes + thresholds (treasury.bsc USDT, treasury.algo
   USDC) — determines how often users see minutes vs seconds.
2. T_park operator policy for guard-trips after burn (auto-refund vs hold).
3. v1 caller restriction on the vault (README open question 6) interacts
   here: if mint/redeem are relayer-only at launch, the saga executor set is
   the allowlist.
4. Whether Retirar-to-bank (direct off-ramp) shares leg A'/B' with this saga
   or goes vault → USDT → Koywe without touching Algorand at all (it
   should — that's the whole point of the direct rail).
