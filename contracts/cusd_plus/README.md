# cUSD+ Vault (BSC) — design draft

Solidity port of the trust architecture proven in [`contracts/cusd/cusd.py`](../cusd/cusd.py)
(Algorand), for Confío Dollar+ (cUSD+): the USDY-backed savings token.

**Status: COMPILED + TESTED** (build ungated by founder decision,
2026-07-04). Foundry scaffold in this directory: solc 0.8.26, OZ 5.6.1
(via npm; `npm install && npm run setup:forge-std`), 17 tests green
including a fuzz over random op sequences asserting
`backingRatioBps() ≥ 10000`. Mocks stand in for USDY/USDT/IM/oracle until
Ondo onboarding answers land — the Solidity surface those answers touch is
isolated in `_imSubscribe`/`_imRedeem`. Note: OZ 5.6 dropped
ReentrancyGuardUpgradeable; the vault uses ReentrancyGuardTransient
(stateless, proxy-safe; needs Cancun opcodes — BSC has them).

## Concept map: cusd.py → CusdPlusVault.sol

| cusd.py (Algorand)                                    | CusdPlusVault.sol (BSC)                                   |
| ----------------------------------------------------- | --------------------------------------------------------- |
| Mint only inside atomic group; contract verifies the USDC axfer at a fixed group index | Mint only inside `subscribeAndMint`/`depositAndMint`, which take custody of the collateral in the same tx (single revert scope) |
| ASA manager permanently zero (nobody can mint outside the contract) | No admin/owner mint exists in the bytecode |
| Clawback = app (contract controls reserve)            | Vault holds the USDY; shares burn to release it            |
| 1 cUSD : 1 USDC fixed                                 | Invariant: vault USDY ≥ `usdyOwed()` — checked with `_assertFullyBacked` after **every** state change |
| Sponsored group (user never pays fees)                | Relayer/treasury is `msg.sender`; `recipient` gets the shares (user never needs BNB) |
| `pause`/`unpause` (admin)                             | OZ `Pausable` gating mint/redeem paths                     |
| `freeze_address`/`unfreeze_address` (ASA freeze bit)  | `freezeAddress`/`unfreezeAddress` + `_update` hook: frozen addresses cannot transfer, receive, mint or redeem; yield still accrues (detain, not confiscate) |
| `@app.update`: admin updates allowed during maturation, "change to Reject() when stable" (and cUSD **has** been updated several times in production) | UUPS upgrade gated to owner + irreversible `lockUpgrades()` — the recompile-to-Reject milestone as a one-way on-chain switch |
| `@app.delete`: permanently `Reject()`                 | No selfdestruct/delete path exists                         |
| Explicit state init in `@app.create` (the empty-bytes lesson) | All proxy state set in `initialize()`: `pPlus = 1e18`, `lastOraclePrice` from a live oracle read; implementation locks itself with `_disableInitializers()` |

## Token & fee mechanics

- **Accumulating share (decision A).** `pPlus` (USD per share, 1e18) starts at
  $1.00 and compounds at `1 − CONFIO_YIELD_SHARE_BPS` (85%) of USDY's oracle
  growth, lazily on every interaction (Compound-style `accrue()`). Share
  counts never surface in any Confío UI — USD value only.
- **Fee = surplus, never a mint (decision B).** Confío's 15% slice is not
  minted or transferred at accrual time; it appears as the gap between vault
  USDY and `usdyOwed()`. `collectFees` can withdraw **only** that surplus, so
  backing is ≥ 100% by construction, before and after every fee withdrawal.
- **Soft transfer policy (decision C), one hard control.** Plain ERC-20
  on-chain; the app UI doesn't surface transfers. The single hard hook is
  per-address freeze — beyond cUSD parity, it's self-defense: USDY is a
  permissioned asset, and a sanctioned actor moving through the vault could
  get the vault address itself blacklisted by Ondo, stranding every honest
  holder. Surgical freeze protects the pool.
- **Contract-automatic mint (decision D).** Two mint paths, both atomic with
  collateral custody: USDT → InstantManager `subscribe` → USDY → shares
  (primary), or direct USDY deposit (treasury bridge leg / IM outage
  fallback). Both honor a caller-supplied slippage floor.

## Upgradeability posture (corrected after review)

The first draft claimed day-one immutability; Julian's review corrected it:
cUSD itself ships admin-updatable and has needed several production updates.
The vault mirrors the real cUSD lifecycle, not the idealized one:

1. **Maturation**: UUPS upgrades gated to the treasury multisig (add a
   timelock before scale). Early versions integrate a not-yet-final Instant
   Manager ABI — a bug escape hatch is a user protection here, not a rug
   vector, and it's the same authority users already accept on cUSD.
2. **Lock**: `lockUpgrades()` is a one-way switch; after it, upgrades are
   impossible forever and publicly verifiable as such — strictly better than
   cUSD's "recompile update() to Reject()" which itself requires an update.

Wiring (USDY/USDT/IM/oracle) lives in implementation immutables, so an
upgrade can re-wire if Ondo migrates its BNB contracts — the concrete
scenario most likely to force an update.

## Price updates: none needed (vs the Solana design)

The Solana-era design required Confío to PUSH the USDY price on-chain (no
readable oracle exists there), making us the price authority — ops burden
plus a trust burden. On BSC the vault reads Ondo's RWADynamicOracle
synchronously inside every interaction; `accrue()` is lazy and catches up
the whole elapsed window in one step, so mints/redeems always settle at the
live oracle price with no keeper required for correctness.

Two footnotes:
- **Optional keeper, recommended**: a daily cron calling `accrue()` keeps
  the jump-guard window small (a >1-year dead period could make a legitimate
  catch-up trip the 2% guard) and keeps server-side netApy/earnedToday
  displays fresh. Hygiene, not correctness.
- **If BNB has no RWADynamicOracle deployment** (open question 3), the
  design regresses to a pushed-price model — confirm early in onboarding.

## Defensive details

- **Oracle jump guard**: USDY's RWADynamicOracle is a deterministic accreting
  curve; a decreasing or > 2%-per-step read is a fault. Accrual freezes
  (mints/redeems keep working at the frozen `pPlus`) until the owner
  investigates and `resetOracleBaseline()`. Yield during a frozen window goes
  to surplus, not holders — conservative on purpose.
- **Rounding always favors backing**: mints and redeems floor; `usdyOwed`
  ceils.
- **`sweep` can rescue anything except USDY** — the backing is not sweepable,
  not even by the owner.
- **Public verifiability** (feeds the ProtectedSavings BscScan links):
  `totalOwedUsd()` (cUSD+ in circulation), `backingRatioBps()` (must never
  read < 10000), `surplusUsdy()`, plus the USDY balance of the vault address
  directly on BscScan.

## ConfioStockRouter — GM trades with an explicit fee

`ConfioStockRouter.sol` is the sweep-model trade path: `buyWithSavings`
(pull cUSD+ shares → vault.redeemToUsdt → fee slice to treasury → GM
settle → stock to user) and `sellToSavings` (stock → GM settle → fee →
vault.subscribeAndMint back to the user — proceeds literally keep
earning). Confío's fee is an EXPLICIT on-chain USDT transfer, never a
price markup, so "Sin comisiones ocultas" is contract-enforced; the rate
is owner-settable under a 1% hard cap (launch config after Ondo's GM fee
schedule — no number is anchored in code, default 0). The router never
holds funds at rest and is replace-by-redeploy (stateless, unlike the
vault). GM touchpoints are provisional and isolated in `_gmBuy/_gmSell`.
7 tests cover fee exactness, reinvest round trip, cap/authz, zero-fee
pass-through, slippage floors, pause, and frozen-user rejection — the
vault backing invariant holds through trades.

## Open questions (blockers before implementation)

> **Investigation 2026-07-05** (docs.ondo.finance + BSC on-chain reads),
> **superseded on 2026-07-06 by Ondo first-party reply**: the Instant
> Manager goes LIVE ON BNB ~end of week of 2026-07-06, deposit currency
> **USDT only on BNB** (USDC on ETH), single atomic transaction, $1
> minimum for instant mint/redeem, gated on Primary Purchaser approval.
> The public docs were simply behind reality — the original architecture
> hypothesis (USDT ↔ USDY on BSC) is CONFIRMED.

1. **Instant Manager ABI on BNB** — **RESOLVED (Daniel, 2026-07-07 +
   on-chain verification).** BNB IM:
   `0x9bA360087075A4Cef548eeD71Eed197bf4cFA4E2` (deployed, 12,351 bytes;
   `rwaToken()` == the BSC USDY below). ABI == Ethereum's minus the rUSDY
   surface (rUSDY doesn't exist on BNB; we never used it):
   `subscribe(depositToken, depositAmount, minimumRwaReceived)` selector
   `0x22d4a175`, `redeem(rwaAmount, receivingToken, minimumReceived)`
   selector `0xd8780161` — both selectors re-derived and matched. Deposit
   token on BNB is USDT (Binance-Peg BSC-USD
   `0x55d398326f99059fF775485246999027B3197955`). `IOndoInstantManager`
   is now the official interface; `_imSubscribe/_imRedeem` wired
   (2026-07-07), 33/33 tests green.
2. **USDY flavor on BSC** — **CONFIRMED accumulating, 18 decimals**
   (on-chain read of `0x608593d17a2decbbc4399e4185be4922f97ed32e`,
   "Ondo U.S. Dollar Yield"), and confirmed as the IM's `rwaToken()`.
3. **USDY price oracle on BSC** — **RESOLVED:**
   `0x8aaa843b848c2E3c83956Bc09aFBE4D9Dcf297b7` (from Daniel).
   `getPrice()` verified on-chain 2026-07-07: 1.13863392 × 1e18 — 1e18
   semantics match our `IRWADynamicOracle`.
4. **USDT-BSC decimals** — **RESOLVED: 18**, verified on-chain against
   canonical BSC-USD `0x55d398...7955`. Constants assume 1e18 — correct.
5. **OndoIDRegistry whitelisting** — **PARTIALLY RESOLVED (Daniel,
   2026-07-07): contracts CAN be whitelisted; whitelisting gates
   mint/redeem only, so token-level USDY transfers to non-whitelisted
   addresses are not blocked.** NOTE (2026-07-13): technically permitted
   ≠ legally permitted — the PP representations state USDY is never
   transferred to cUSD+ holders, so `redeem`/`depositAndMint` are
   owner-gated (raw USDY moves only vault↔IM↔treasury Safe; the sole
   holder exit is `redeemToUsdt`). External framing discipline: the
   vault (Duende) is the Purchaser that subscribes for USDY and issues
   cUSD+ — never "users mint/redeem USDY through our contract".
   REMAINING: complete PP onboarding and whitelist the vault PROXY
   address (read-only API key already issued — 1Password link expires
   7 days from 2026-07-07).
6. ~~Relayer authz~~ — **RESOLVED: permissionless, like cusd.py.** The
   conversion flow is user-driven end to end (see ORCHESTRATION.md): the
   user's own BSC address is msg.sender for mint/redeem (Confío only
   sponsors gas), so restricting callers would break the architecture.

7. **GM settlement on BNB** — **MOSTLY RESOLVED.** Contract:
   `GMTokenManager 0x91f8Aff3738825e8eB16FC6f6b1A7A4647bDB299` (BNB).
   Payment: official docs state **"We accept USDC on Ethereum, and USDT on
   BNB Chain"** — our USDT-BSC rail is exactly the right token. Settlement
   runs through **USDon** (`0x1f8955E640Cbd9abc3C3Bb408c9E2E1f5F20DfE6`,
   ~39.7M supply, "permissionless ERC20 stablecoin representing USD held in
   Ondo's brokerage account" — a settlement dollar, NOT yield-bearing);
   non-USDon deposit tokens are swapped to USDon zero-slippage inside the
   call. ABI: `mintWithAttestation(quote, signature, depositToken,
   depositTokenAmount)` / `redeemWithAttestation(quote, signature,
   receiveToken, minimumReceiveAmount)` with EIP-712 quotes signed by
   Ondo's attestation service; the caller must be **whitelisted and its
   stored `userID` must match the quote** (per-user onboarding — the real
   partnership blocker for a non-custodial router); `attestationId` replay
   protection, `minimumDepositUSD`, per-user/per-token rate limits.
   `_gmBuy/_gmSell` need attestation params added. Still open: partner fee
   schedule (embedded in quote spread), which decides `stockFeeBps`, and
   how distribution partners bulk-onboard users. A `GMTokenLimitOrder`
   contract also exists on BNB (future feature). Eligibility: prohibited =
   US/Canada/Cuba + sanctions; Brazil restricted to Qualified Investors —
   matches our existing geofence (US/CA/BR + sanctions) exactly.

## Deployment checklist (when ungated)

- [x] Foundry scaffold + OZ pin; compile, fuzz the invariant
      (`backingRatioBps() ≥ 10000` under arbitrary op sequences) — done
      2026-07-04
- [x] Stateful invariant suite (2026-07-06,
      test/CusdPlusVault.invariant.t.sol): multi-actor handler with
      `fail_on_revert` — proves LIVENESS (entitled redemptions can never
      revert), pPlus monotonicity, and full-exit solvency via
      afterInvariant(); 48 runs × 96 depth, 0 reverts
- [x] Differential mirror (2026-07-06, test/mirror/mirror_accrual.py +
      CusdPlusVault.differential.t.sol): independent Python port of the
      accrual/share math; 418 mixed ops across 3 frozen sequences
      (incl. oracle-guard trips + resets) replayed on-contract with EXACT
      state equality after every step — the rounding-direction net
- [x] Adversarial suite (2026-07-06,
      test/CusdPlusVault.adversarial.t.sol): ERC4626-style first-depositor
      inflation shown structurally dead (pPlus is oracle-driven, never
      balance-derived — donations land in surplus, not the share price);
      donation-exactness; redeem floor bounded to 1 USDY-wei; 60-round
      marathon with full exit stays solvent
- [x] Fill IM interface from official ABI (2026-07-07: BNB IM
      `0x9bA36008...`, oracle `0x8aaa843b...`, selectors verified,
      mocks updated, 33/33 green)
- [ ] BSC MAINNET-FORK integration test against the real IM + oracle +
      USDY (contracts are live — fork test replaces the testnet plan;
      mint/redeem paths need a whitelisted caller, so full E2E lands
      after PP approval, but wiring/oracle/view paths fork-test today)
- [ ] External review of `accrue()` math (WAD/BPS rounding)
- [ ] Deploy implementation + ERC1967 proxy; `initialize(treasury multisig)`;
      `CONFIO_YIELD_SHARE_BPS = 1500`; storage-layout checks in CI for every
      subsequent upgrade
- [ ] Timelock on the owner before scale; `lockUpgrades()` at the proven-
      stable milestone (public announcement)
- [ ] Daily keeper cron calling `accrue()` (guard hygiene + fresh display
      data; not required for correctness)
- [ ] Whitelist vault in OndoIDRegistry (Ondo onboarding)
- [ ] Wire addresses into `cusd_plus/schema.py` resolvers + statsSummary
      `usdy_reserve`; flip ProtectedSavings BscScan links live
