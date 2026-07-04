# cUSD+ Vault (BSC) — design draft

Solidity port of the trust architecture proven in [`contracts/cusd/cusd.py`](../cusd/cusd.py)
(Algorand), for Confío Dollar+ (cUSD+): the USDY-backed savings token.

**Status: DRAFT, uncompiled.** The build behind it stays gated on the whale
deposit-intent signal (decision 68e9cd45). No foundry/hardhat scaffold yet.

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

## Open questions (blockers before implementation)

1. **Instant Manager ABI on BNB** — `IOndoInstantManager` here is
   provisional. Confirm exact `subscribe`/`redeem` signatures, USDT deposit
   support, and the IM contract address (asked in the pending Michael email).
   Only `_imSubscribe`/`_imRedeem` bodies should need changes.
2. **USDY flavor on BSC** — assumed accumulating (Ethereum-style USDY, not
   rebasing rUSDY) and 18 decimals. Verify.
3. **RWADynamicOracle deployment on BSC** — address + confirm `getPrice()`
   1e18 semantics match the Ethereum deployment (`0xA0219AA5...`).
4. **USDT-BSC decimals** — 18 on BSC (unlike Ethereum's 6); constants assume
   1e18 everywhere. Verify against the canonical BSC-USD contract.
5. **OndoIDRegistry whitelisting** — the vault address must be whitelisted as
   a Primary Purchaser contract (Option 1 KYB, in progress). Redeeming to
   arbitrary `to` addresses may also require registry checks — confirm
   whether USDY transfers out of the vault to non-whitelisted addresses are
   allowed, or whether `redeem`'s raw-USDY path must be treasury-only.
6. **Relayer authz** — mint/redeem are currently permissionless (anyone
   bringing collateral can mint; any holder can redeem). Decide whether v1
   restricts callers to the Confío relayer set while the Algorand↔BSC
   conversion orchestration matures, or ships open.

## Deployment checklist (when ungated)

- [ ] Foundry scaffold + OZ pin; compile, fuzz the invariant
      (`backingRatioBps() ≥ 10000` under arbitrary op sequences)
- [ ] Fill IM interface from official ABI; integration test on BSC testnet
      against real IM + oracle
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
