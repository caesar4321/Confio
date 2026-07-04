# cUSD ↔ cUSD+ conversion orchestration (Algorand ↔ BSC)

The layer between ConvertAhorro/RetirarAhorro and the two contracts
(`cusd.py` on Algorand, `CusdPlusVault.sol` on BSC).

**Philosophy (= cUSD's, non-negotiable): every leg is user-driven and
user-signed. Funds only ever sit at the user's own addresses, inside the
contracts, or in flight on the bridge. There is NO company treasury in the
flow — Confío sponsors fees and observes, it never custodies.** An earlier
draft routed value through treasury accounts; Julian rejected it.

**Scope note:** this path exists ONLY for money already inside Confío.
New money never bridges — direct ramps (Koywe ↔ USDT-BSC ↔ vault) are
separate flows with no Allbridge leg.

## 1. The legs — all from/to the USER's addresses

`user.algo` and `user.bsc` derive from the same Web3Auth seed
(non-custodial). Confío's only financial role per leg: fee sponsorship
(Algorand fee-pooled groups; on BSC, metered BNB gas dust sent to user.bsc —
the same sponsorship philosophy, different mechanism).

### Ahorrar (cUSD → cUSD+)
```
leg A (Algorand, atomic, user signs):  burn cUSD → USDC lands at user.algo
                                       (sponsored group, as today)
leg B (Algorand→bridge, user signs):   user.algo deposits USDC into Allbridge
                                       Core, destination = user.bsc → USDT-BSC
                                       arrives AT THE USER'S BSC ADDRESS
leg C (BSC, user signs, gas-dusted):   approve + vault.subscribeAndMint(
                                       usdtIn, minUsdyOut, user.bsc)
                                       → USDY into vault → shares to user.bsc
```

### Retirar (cUSD+ → cUSD)
```
leg A' (BSC, user signs, gas-dusted):  vault.redeemToUsdt(shares, minUsdtOut,
                                       user.bsc) → USDT at user's address
leg B' (BSC→bridge, user signs):       Allbridge deposit, destination =
                                       user.algo → USDC-ALG arrives at user
leg C' (Algorand):                     THE EXISTING USDC→cUSD auto-swap —
                                       already in production, unchanged
```

Cross-chain atomicity doesn't exist; the guarantee is the honest version:
**each leg is atomic on its chain, every halt state leaves the value in the
user's own wallet as a real asset (cUSD, USDC-ALG, USDT-BSC or cUSD+), and
the client can always resume or the user can simply keep what they hold.**
Worst case of an abandoned Ahorrar is the user owning USDC/USDT — never a
limbo balance, never an IOU on Confío.

## 2. Client-driven resume (the auto-swap pattern, generalized)

No server-side executor drives user funds — it can't; it doesn't hold keys.
Progress happens exactly like the existing USDC-ALG → cUSD auto-swap:

- On every app **re-foreground**, the client asks the server "any conversion
  in flight?" and executes the next leg it can sign, after a fresh quote
  check for that leg.
- **The modal always says why**: "Continuando tu ahorro: tu dinero cruzó a
  la red de ahorro, falta el último paso" — never a silent spinner, never
  an unexplained popup. If a leg partially filled, the modal states plainly
  what portion is through and what remains ("Convertimos $X de $Y; el resto
  sigue en tu billetera como cUSD").
- **We don't cover anything.** If costs moved between legs, the user sees
  the fresh number and decides: continue at today's cost, wait, or (Ahorrar
  leg-B halt) swap the USDC back to cUSD 1:1 via the existing conversion and
  forget the whole thing. Confío never eats a delta silently and never
  proceeds on a stale quote.
- **Auto-swap suppression flag**: during an Ahorrar in flight, USDC at
  user.algo is leg-A output, NOT idle dust — the existing auto-swap must
  check the in-flight conversion state or it will "helpfully" convert the
  user's savings deposit back into cUSD. (Symmetrically, leg C' of Retirar
  IS the auto-swap doing its normal job — no suppression there.)
- Server-side celery only does what needs no keys: polling Allbridge
  transfer status, topping BNB gas dust when leg C is next, websocket
  events, reconciliation (§6), and nudging via push notification if a
  conversion sits half-done for days ("te falta un paso para que tu ahorro
  gane rendimiento").

## 3. Server's role (quotes, guard, observation — never custody)

1. **Quote** (`cusdPlusQuote`): Allbridge `getAmountToBeReceived`
   (USDC-ALG → USDT-BSC, real pool math) + IM leg at oracle price + any
   server-config Confío fee. TTL ~60s, foreground-only.
2. **Spread guard** (remote config, ~0.5%): over threshold →
   `maxFillUnderThreshold` binary search → PARTIAL quote ("convertimos
   hasta $X ahora"), the amber state ConvertAhorroScreen renders. Partial
   fills are first-class, not errors; the user re-taps later for the rest —
   no auto-tranche loop racing the arbitrageurs.
3. **Contract-side floors** are the real protection: `minUsdyOut` /
   `minUsdtOut` on the vault, Allbridge's receive minimum on the bridge.
   The client never signs a leg whose floor is below the quote the user
   accepted.

Pool reality (measured 2026-07): Allbridge's Algorand USDC pool ~$43.5K;
2%+ impact near $20–25K. Liquidity is polled (token-info) with alerts at
$30K/$15K. Large conversions = visible partial fills by design.

## 4. Failure map — value is always the user's, somewhere concrete

| Halt point | User now holds | Path forward (client modal offers it) |
| --- | --- | --- |
| Guard trips at quote | cUSD (untouched) | partial now, or wait |
| Leg A unconfirmed | cUSD (group atomic) | clean retry |
| After A, bridge cost jumped | USDC-ALG in own wallet | continue at fresh cost / wait / swap back to cUSD 1:1 |
| Bridge in flight / stuck | in-flight (Allbridge) | server polls status; > ~30 min → ops alert + honest "tardando más de lo normal"; Allbridge transfers resolve by retry/support, value not lost |
| USDT arrived, app closed | USDT-BSC at user.bsc | next foreground: gas dust + leg C; push nudge after days |
| Vault paused / IM down | USDT-BSC at user.bsc | retry on later foregrounds; oracle-time mint means waiting costs ~nothing in USD |
| user.bsc frozen (vault) | USDT-BSC at user.bsc | compliance process, not the conversion's problem |
| Retirar legs | mirror of the above | leg C' is the existing auto-swap |

No REFUNDING machinery exists because there is nothing to refund FROM — the
"refund" of every Ahorrar halt is that the user already holds the asset, and
the swap-back-to-cUSD offer reuses the existing 1:1 conversion.

## 5. Reconciliation & monitoring

- Per-conversion ledger (server, observational): leg tx ids keyed by
  `conversion_id` (UUIDv7, stamped in tx notes/metadata) — powers the
  resume logic, the Movimientos history, and support.
- Invariant audits: vault `backingRatioBps() ≥ 10000` (public, monitored);
  per-conversion "value in vs shares out at oracle price" within quoted
  costs — any residual pages ops.
- Dashboards: conversions by state + age, Allbridge pool depth, gas-dust
  spend, guard-trip and partial-fill rates.
- Sponsorship accounting: BNB dust + Algorand fee pooling are Confío's only
  costs in the flow, tracked like existing sponsored-tx accounting.

## 6. UX honesty contract

- Processing screens map to real leg states via websocket; a stuck bridge
  shows "tardando más de lo normal", never a fake spinner.
- "Al instante" is only promised where true (leg C' auto-swap is instant
  once USDC lands; the full Ahorrar is "en unos minutos").
- Partial fills and cost changes are always stated with numbers, before the
  user signs the affected leg. We don't cover anything — and we don't hide
  anything either.

## 7. Resolved (formerly "open") decisions

1. ~~Treasury float sizing~~ — **dead: there is no treasury in the flow.**
   (A user-visible "instant mode" would require custody; rejected.)
2. ~~Post-burn cost-absorption policy~~ — **dead: we don't cover anything.**
   Cost changes are re-presented to the user, who decides.
3. ~~Relayer-only vault v1~~ — **dead: permissionless, like cusd.py.** The
   user IS the caller (msg.sender = user.bsc, gas-dusted); locking the vault
   to relayers would contradict the user-driven flow. README question 6
   resolved accordingly.
4. Route clarification (Julian): the full saga to cUSD is for users who
   want cUSD **to use in-app** (send, pay, guardar) — it ends at cUSD.
   Bank withdrawals from savings never ride it: that is
   vault.redeemToUsdt → USDT-BSC → Koywe, the direct rail that leads the
   Retirar sheet ("A mi banco" first).

Remaining genuinely open: none at the orchestration level. Blockers are the
Ondo onboarding answers (vault README) and Allbridge's partner reply.
