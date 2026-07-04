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
leg AB (Algorand, ONE atomic group,    [sponsor fee pay, cUSD axfer → app,
        user signs):                    burn app call (inner tx: USDC → user),
                                        USDC axfer → Allbridge, Allbridge
                                        app call, destination = user.bsc]
leg C  (BSC, user signs, gas-dusted):  approve + vault.subscribeAndMint(
                                        usdtIn, minUsdyOut, user.bsc)
                                        → USDY into vault → shares to user.bsc
```

Leg AB is ONE group by design (Julian's correction — and VERIFIED against
the deployed contract: `burn_for_collateral` uses relative indexing with no
group-size cap, its own comment says "so burn can be embedded in larger
atomic groups"; no contract change needed). Consequences:
- USDC never rests at user.algo — it exists only inside group execution, so
  there is no auto-swap race and no suppression flag;
- the Allbridge receive floor sits in the same group, so an adverse pool
  move fails the WHOLE group and the user still holds cUSD untouched —
  "burned but not bridged" is not a reachable state;
- the point of no return is the group commit, after which the value is
  already in bridge flight toward the user's own BSC address.

### Retirar (cUSD+ → cUSD)
```
leg A' (BSC, user signs, gas-dusted):  vault.redeemToUsdt(shares, minUsdtOut,
                                       user.bsc) → USDT at user's address
leg B' (BSC→bridge, user signs):       Allbridge deposit, destination =
                                       user.algo → USDC-ALG arrives at user
leg C' (Algorand):                     THE EXISTING USDC→cUSD auto-swap —
                                       already in production, unchanged
```

EVM has no native tx grouping, so A' and B' are two signatures in the same
foreground session; if interrupted between them, USDT rests at the user's
own address and resume continues. (A v2 periphery "redeem-and-bridge"
router contract could fuse them into one tx — transient in-contract flow,
not custody — optional, not load-bearing.) USDC arriving at user.algo is
leg C' doing its normal job: on Retirar the auto-swap IS the last leg.

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
  the fresh number and decides: continue at today's cost or wait. Confío
  never eats a delta silently and never proceeds on a stale quote.
- Server-side celery only does what needs no keys: watching OUR chains
  for bridge arrivals (chain-first: a USDT Transfer to user.bsc on BNB, or
  the USDC credit the existing inbound scanner already sees on Algorand —
  the Allbridge indexer API is a support diagnostic only, never the truth;
  a vendor outage must not fake a STUCK state), topping BNB gas dust when
  leg C is next, websocket events, reconciliation (§6 monitoring), and
  nudging via push if a conversion sits half-done for days.

## 3. Server's role (quotes, guard, observation — never custody)

1. **Quote** — decision (b), IMPLEMENTED 2026-07-04: the client prices the
   Allbridge leg itself with dependency-free ported pool math
   (`apps/src/services/allbridgeQuote.ts`, validated to ≤ $1e-5 against the
   official SDK — `apps/scripts/validate-allbridge-port.mts`); the server's
   `cusdPlusConvertParams` supplies threshold/fee/kill-switch only. IM leg
   is oracle-priced (no spread). TTL 30s snapshot cache, foreground-only.
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
| Leg AB group fails (incl. Allbridge floor breached) | cUSD (group atomic — nothing happened) | clean retry at a fresh quote |
| Bridge in flight / stuck | in-flight (Allbridge) | server watches the DESTINATION CHAIN for the arrival; > ~30 min of chain silence → STUCK + ops alert + honest "tardando más de lo normal" (Allbridge indexer consulted only as a support diagnostic); value not lost |
| USDT arrived, app closed | USDT-BSC at user.bsc | next foreground: gas dust + leg C; push nudge after days |
| Vault paused / IM down | USDT-BSC at user.bsc | retry on later foregrounds; oracle-time mint means waiting costs ~nothing in USD |
| user.bsc frozen (vault) | USDT-BSC at user.bsc | compliance process, not the conversion's problem |
| Retirar legs | mirror of the above | leg C' is the existing auto-swap |

No REFUNDING machinery exists because there is nothing to refund FROM — the
"refund" of every Ahorrar halt is that the user already holds the asset, and
the swap-back-to-cUSD offer reuses the existing 1:1 conversion.

## 5. BSC inbound: three sources, one scanner

USDT arriving at user.bsc has three producers, all watched by the same
batched scanner (one eth_getLogs per 30s over the whole watch set):

1. **Conversion** (leg B delivery) — matches an in-flight row; advances it.
2. **Koywe ramp** with destination=cusd_plus — matches a pending ramp
   order once the destination param ships.
3. **External deposit** (Julian, 2026-07-04): crypto-native users and
   no-Koywe countries onramp by sending USDT (BEP-20) straight to their
   address — WITHOUT this rail they would be forced through USDC-ALG and
   the thin Allbridge pool for no reason. Semantics: user.bsc is the
   savings-chain address, so an external arrival IS a savings deposit —
   the client auto-mint prompt on foreground is the auto-swap pattern
   generalized (gas-dusted, user signs subscribeAndMint). Needs user.bsc
   registration on the Account at savings activation + deposit records.

Consequence: user.bsc is a PUBLIC receive address, so the watcher is a
standing scanner over all registered savings addresses (like the Algorand
inbound scanner) — the address-array topic filter keeps it one RPC call
regardless of watch-set size.

The same single call extends to GM: every ERC-20 shares one Transfer
event signature, and eth_getLogs' `address` field takes a CONTRACT array
— so USDT plus 200+ tokenized stocks are one radar sweep (contract list =
GM metadata, data not code). Contrast Algorand, where the inbound scan is
per-asset; the unified EVM event log is a structural win for the stocks
product. If public-node array limits ever bind, chunk the arrays or move
to a keyed provider — no architecture change.

## 6. Build inventory — new vs reused

**New builds** (the bulk is BSC-side client infrastructure):
- EVM key derivation from the Web3Auth seed + BSC tx signing in the app
- BNB gas-dust service (server: meter, top up user.bsc when a BSC leg is next)
- Vault deployment + client calls: `subscribeAndMint` (Ahorrar leg C),
  `redeemToUsdt` (Retirar leg A' — burns cUSD+, delivers USDT to the user)
- Allbridge Core SDK integration, BOTH directions (Ahorrar's group-embedded
  Algorand deposit; Retirar leg B': user-signed BSC deposit → user.algo)
- Leg-AB group composer on Algorand (new group shape; the burn contract
  itself is unchanged — relative indexing already supports embedding)
- Real `cusdPlusQuote` (Allbridge pool math + IM + guard), conversion state
  tracking, resume-on-foreground logic, websocket progress events

**Reused unchanged:**
- cusd.py burn/mint contracts and the sponsored-group infrastructure
- The USDC→cUSD auto-swap — Retirar leg C' ONLY; the rest of Retirar is new
- Push notification + websocket plumbing, Koywe ramps (separate direct flows)

## 7. Reconciliation & monitoring

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

## 8. UX honesty contract

- Processing screens map to real leg states via websocket; a stuck bridge
  shows "tardando más de lo normal", never a fake spinner.
- "Al instante" is only promised where true (leg C' auto-swap is instant
  once USDC lands; the full Ahorrar is "en unos minutos").
- Partial fills and cost changes are always stated with numbers, before the
  user signs the affected leg. We don't cover anything — and we don't hide
  anything either.

## 9. Resolved (formerly "open") decisions

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
