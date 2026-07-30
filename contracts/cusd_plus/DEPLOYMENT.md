# cUSD+ deployment record — BSC mainnet

## CusdPlusVault — deployed 2026-07-10, upgraded 2026-07-13 (v2) and 2026-07-20 (v4)

| Role | Address |
| --- | --- |
| **Vault (ERC1967 proxy)** | `0x3C29417eb4314155e63d4C7D4507852b87763Ed1` |
| Implementation (current, v4 — review-cycle hardened) | `0x1c12685ca9ceb8785171b3834BacDd5C881a4F5A` |
| Implementation (v3, ORPHAN — deployed, never attached) | `0x563B6FB5418101057809B457587e28A7aF8171E2` |
| Implementation (v2, superseded 07-20) | `0x578fd4d235acF608979b63BBB28bD2292E7e201e` |
| Implementation (v1, superseded 07-13) | `0xB0C2122047a69C8Ee336ce75fd61050a06630823` |
| Owner + treasury | `0xF29A418744E793973BF4eEc676F8a30B2793b623` (3-of-5 Safe) |
| Deployer | `0xf9f93Ba8ebf50515Ed2729Eb07657c8298cdfc9D` (KMS sponsor) |

Deploy txns (BscScan):
- impl v1: `0x44be3e14bd3d6886a929dff6664fa2901c300e817741c6930deaa9519f970a27`
- proxy:   `0x79326b3b7f124abe97b6d83cc7d5666dd1cce0c8f10a66a178726c74b7e1c58a`

Deployed via `manage.py deploy_cusd_plus_vault --broadcast --yes-mainnet`
(KMS-signed creation txns — no extractable deployer key). Cost ≈ 0.0032 BNB.

### UUPS upgrade 2026-07-13 — guard-gated resetOracleBaseline (commit `0a049edf`)

Closes the HIGH finding from the 2026-07-13 review: v1 let the owner call
`resetOracleBaseline()` on a healthy oracle, skipping holders' 85% of
pending sub-2% growth into collectable surplus. Executed at zero supply.

- impl v2 deploy: `0xdf8da12c04fb1f407db0856cc5564a21f5fc75621e36efc124569a06cd6bd3ec`
  (`manage.py deploy_cusd_plus_vault --impl-only --broadcast --yes-mainnet`)
- Safe `upgradeToAndCall(0x578f…201e, "")`, nonce 1, signers 1/3/5:
  `0xe9eeaf6f6b84f78e8d06fa0c8f1fdd2de2a5772e396394149579761cb05e5ff5`
- Post-upgrade verified live: impl slot = v2; owner/pPlus/supply/backing
  unchanged; `resetOracleBaseline()` from the Safe reverts
  `guard not tripped` (eth_call); non-owner still rejected.
- impl v2 source: Sourcify exact_match (creation + runtime) + BscScan
  verified, proxy re-linked to impl v2, 2026-07-13.

### UUPS upgrade 2026-07-20 — v4, the 8-round review-cycle build (commit `fbd3085f`)

Everything from the July external review cycle (ChatGPT + Claude + Codex),
executed at zero supply:
- raw-USDY paths owner-only, recipients hardcoded to the Safe (PP reps
  are a code invariant); holder exit = redeemToUsdt only
- tripped guard halts ALL value paths; evidence-tagged verdict pair
  (accept = 85/15 preserved / rebaseline = fault) with [min,max] TOCTOU
  pins + guardedOraclePrice forensics (slot 4)
- lockUpgrades REMOVED (Ondo-dependency foot-gun); deprecated
  upgradesLocked byte reserved at slot 2.1; layout pinned in CI
- zero/huge oracle-read defenses (Math.mulDiv guard math); value paths
  price at the guard-validated snapshot, never a re-read
- zero-address freeze blocked; zero-recipient redeemToUsdt blocked

Execution:
- fork rehearsal vs LIVE proxy state PASSED first
  (test/UpgradeRehearsal.fork.t.sol — state survival, removed surface,
  verdict gating, live-oracle accrual, PP gate)
- impl v4 deploy: `0x098d3756a335da23b091b12a3f8ab20142f199912ef782e5ad2fef1aa91f951e`
- Safe `upgradeToAndCall(0x1c12…4F5A, "")`, nonce 2, signers 1/3/5:
  `0x458f796bba1dc6f80feaab8f4ad949b9c61c863cc4f7b8645e82be72564183f7`
- post-upgrade verified live: impl slot = v4; owner/pPlus/baseline/
  supply/backing intact; guardedOraclePrice = 0; resetOracleBaseline /
  lockUpgrades / upgradesLocked selectors gone; verdicts revert
  "guard not tripped"; redeem onlyOwner; collectFees(0) rejected;
  accrue() simulates clean against the live oracle
- source: Sourcify exact_match (creation + runtime) + BscScan verified,
  proxy re-linked to v4, 2026-07-20

### On-chain wiring (immutables, verified live 2026-07-07 + fork rehearsal)

| Immutable | Address |
| --- | --- |
| USDY | `0x608593d17A2decBbc4399e4185bE4922F97eD32E` |
| USDT (BSC-USD, 18dp) | `0x55d398326f99059fF775485246999027B3197955` |
| Instant Manager | `0x9bA360087075A4Cef548eeD71Eed197bf4cFA4E2` |
| RWA price oracle | `0x8aaa843b848c2E3c83956Bc09aFBE4D9Dcf297b7` |
| CONFIO_YIELD_SHARE_BPS | 1500 (15%) |

Post-deploy reads: `name()` = "Confio Dollar+", `symbol()` = "cUSD+",
`owner()` = Safe, `pPlus()` = 1e18 (genesis $1.00),
`backingRatioBps()` = 10000 (empty vault, fully backed).

### Status: LIVE but DORMANT until PP whitelisting

`subscribeAndMint` reverts `UserNotRegistered` at the IM until the vault
proxy address is whitelisted in the OndoIDRegistry
(`0x898128F9f22c0192da0c5acD394D9eeAc461D911`) via Primary Purchaser
onboarding. No funds, no risk, until then.

### Remaining checklist

- [x] **Verified on BscScan + Sourcify** (exact_match, both impl + proxy)
      2026-07-10. Source is public and bytecode-matched on both explorers.
      Constructor args below (for reference / re-verification).
- [x] **UUPS upgrade to the guard-gated impl** (commit `0a049edf`) — DONE
      2026-07-13, impl v2 `0x578f…201e` (see upgrade record above).
- [x] BscScan verify impl v2 — DONE 2026-07-13 (Sourcify exact_match +
      BscScan source verified; proxy re-linked to impl v2 via
      verifyproxycontract). Etherscan v2 key lives in git-crypted `.env`
      as `ETHERSCAN_API_KEY`.
- [ ] **Storage-layout diff before EVERY upgrade**: `forge inspect
      CusdPlusVault storageLayout` vs the table below. Pinned in CI by
      `test_storageLayout_pinnedToLiveProxy` (raw vm.load asserts).

      Canonical layout (compiler-verified; contract-own vars start at
      slot 0 — OZ v5 parents are ERC-7201 namespaced):

      | Slot.Off | v2 (live 0xB0C2→0x578f lineage) | v4 candidate |
      | --- | --- | --- |
      | 0.0 | pPlus | pPlus |
      | 1.0 | lastOraclePrice | lastOraclePrice |
      | 2.0 | oracleGuardTripped | oracleGuardTripped |
      | 2.1 | upgradesLocked (false on-chain) | __deprecatedUpgradesLocked (reserved, never reuse) |
      | 3.0 | frozen (mapping base) | frozen (mapping base) |
      | 4.0 | — | guardedOraclePrice (appended) |

      New variables append at slot 5+, never between existing ones.
- [ ] Send vault proxy address to Ondo (Daniel) for PP whitelisting
- [ ] $1 live E2E once whitelisted
- [ ] Router deploy (separate) once GM attestation ABI is wired — deploy
      only from `d78315a8`+ (pre-fix `sellToSavings` forwarded the shares
      floor as the IM's `minUsdyOut`, bricking every sell with honest
      slippage params)
- [x] ~~`lockUpgrades()` at the proven-stable milestone~~ — REMOVED from
      the contract 2026-07-20 (foot-gun: permanent Ondo oracle/IM
      dependency means a locked vault + Ondo migration = stranded funds;
      trust control is the timelocked Safe owner, not immutability)

### Verification constructor args (ABI-encoded, no 0x)

Impl `CusdPlusVault(address,address,address,address,uint256)`:
```
000000000000000000000000608593d17a2decbbc4399e4185be4922f97ed32e
00000000000000000000000055d398326f99059ff775485246999027b3197955
0000000000000000000000009ba360087075a4cef548eed71eed197bf4cfa4e2
0000000000000000000000008aaa843b848c2e3c83956bc09afbe4d9dcf297b7
00000000000000000000000000000000000000000000000000000000000005dc
```
Proxy `ERC1967Proxy(address,bytes)`: impl address +
`initialize(0xF29A…b623)` calldata — regenerate with
`scripts/print_verify_args.py` if needed.

## ConfioBatchDelegate — deployed 2026-07-30

The EIP-7702 sponsored-batch delegate (successor to gas dusting): every
user EOA designates this one shared contract via a 7702 authorization;
the KMS sponsor then executes user-signed batches (approve+subscribeAndMint,
redeemToUsdt) as type-4/type-2 transactions, paying all gas. Immutable,
ownerless, no constructor args — replace-by-redeploy like the router.

| Role | Address |
| --- | --- |
| **ConfioBatchDelegate** | `0xE9d9Ae4d97aE8128DF4501152540d7aA091b435C` |
| Deployer | `0xf9f93Ba8ebf50515Ed2729Eb07657c8298cdfc9D` (KMS sponsor, nonce 16) |

- Deployed via `manage.py deploy_batch_delegate --broadcast --yes-mainnet`
  (~719k gas ≈ 0.0007 BNB). Creation tx: (in deployer terminal output —
  fill in from BscScan contract page).
- On-chain runtime bytecode verified byte-equal to the forge artifact
  (solc 0.8.26, optimizer 200, cancun) post-deploy, 2026-07-30.
- BscScan source verified 2026-07-30 (`forge verify-contract`, "Pass -
  Verified"); Sourcify submitted same day.
- Server config: `CUSD_PLUS_BATCH_DELEGATE_ADDRESS` (this address),
  rollout gate `CUSD_PLUS_7702_ENABLED` (canary with
  `CUSD_PLUS_7702_MAX_PER_DAY=3`; `CUSD_PLUS_GAS_DUST_ENABLED` stays
  armed as the break-glass fallback). Policy/broadcast code:
  `cusd_plus/sponsor_7702.py`; audit ledger: SponsoredBatch (admin).

## ConfioPresaleVault — deployed 2026-07-30

$CONFIO presale on curve "A" (0–4M @ $0.20→0.30, 4–24M @ $0.30→0.70,
24–74M @ $0.70→1.30; full sale $61M), USDT-denominated, sponsor-gated
buys, migratedPool credits for Algorand purchasers. Non-upgradeable —
the segment table has no setter.

| Role | Address |
| --- | --- |
| **ConfioPresaleVault** | `0x77e74deEed3A0f0e338EBd0A457dE3b3C0E95583` |
| Owner | `0xF29A418744E793973BF4eEc676F8a30B2793b623` (3-of-5 Safe) |
| Sponsor (gate) | `0xf9f93Ba8ebf50515Ed2729Eb07657c8298cdfc9D` (KMS) |
| Payment token | `0x55d398326f99059fF775485246999027B3197955` (USDT 18dp) |

- Creation tx: `0x3f3ce2a9e9298f6f60e490fffd4dfd4a6e0d61d0b5347f2d7fabe8061bfd5f18`
  (KMS sponsor, nonce 19, ~2.23M gas ≈ 0.0022 BNB), deployed via
  `manage.py deploy_presale_vault --broadcast --yes-mainnet`.
- `initialSold` seeded LIVE from Algorand app 3353218127 `confio_sold`
  at broadcast: 17,713.85 CONFIO (17713850000 ×1e12). Post-deploy reads
  confirmed: currentPrice 0.200443 USDT, totalSold = migratedPool =
  17,713.85. Algorand sales after this moment are added via
  `expandMigratedPool()` at cutover.
- BscScan source verified 2026-07-30 (`forge verify-contract`, "Pass -
  Verified").
- Server config: `BSC_PRESALE_VAULT_ADDRESS` (.env.mainnet). Migration
  credits: `manage.py presale_migration_credits sync|batch|verify|status`
  (Safe executes the printed creditMigrated calldata). Claims stay closed
  until the CONFIO BEP-20 exists: `setConfioToken()` (one-shot) then
  `setClaimsUnlocked(true)`, both Safe-only.

## ConfioToken ($CONFIO BEP-20) — deployed 2026-07-30

Fixed-supply BEP-20 home of $CONFIO after the Algorand→BSC migration.
Mirrors ASA 3351104258 (name "Confío", unit CONFIO, 1B total) at 18dp.
NO owner, NO minter, NO pause — the entire 1,000,000,000 CONFIO was
minted in the constructor to the Safe treasury; ERC20Permit + Burnable
are the only extensions.

| Role | Address |
| --- | --- |
| **ConfioToken (CONFIO)** | `0xd57BEc35857839DC33F6FaBE7356C6a19a8d72c1` |
| Treasury (full supply) | `0xF29A418744E793973BF4eEc676F8a30B2793b623` (3-of-5 Safe) |

- Creation tx: `0x178930be1412d14dcc721096765a744f50fef05ed02fe7a2f77e85509d5d2c95`
  (KMS sponsor, nonce 20, ~1.03M gas ≈ 0.001 BNB), deployed via
  `manage.py deploy_confio_token --broadcast --yes-mainnet`.
- Post-deploy reads: totalSupply = balanceOf(Safe) = 1,000,000,000 CONFIO.
- BscScan source verified 2026-07-30 (`forge verify-contract`, "Pass -
  Verified").
- Server config: `BSC_CONFIO_TOKEN_ADDRESS` (.env.mainnet).
- Pending Safe transactions to open presale claims:
  1. `ConfioPresaleVault.setConfioToken(0xd57BEc35857839DC33F6FaBE7356C6a19a8d72c1)`
     — calldata `0x76eba8ba000000000000000000000000d57bec35857839dc33f6fabe7356c6a19a8d72c1`
     to `0x77e74deEed3A0f0e338EBd0A457dE3b3C0E95583` (one-shot, verify first)
  2. `ConfioToken.transfer(0x77e74deEed3A0f0e338EBd0A457dE3b3C0E95583, amount ≥ totalSold)`
  3. `ConfioPresaleVault.setClaimsUnlocked(true)` when claims open

### Token name display on BscScan (decision 2026-07-30)

BscScan HTML-escapes the accented on-chain name ("Conf&#237;o") as
anti-spoofing. DECIDED: keep `name() = "Confío"` on-chain (no redeploy);
fix presentation via the BscScan **token info update** instead. Process:
1. Log in at bscscan.com (account required) → token page → "Update Token
   Info" → ownership verification for
   `0xd57BEc35857839DC33F6FaBE7356C6a19a8d72c1`.
2. Ownership is proven by signing their nonce message with the DEPLOYER
   (KMS sponsor `0xf9f9…fc9D` — no wallet has this key):
   `manage.py bsc_sign_message "<exact message from the form>"`
   prints the EIP-191 signature to paste back (verified recovering
   correctly 2026-07-30).
3. Submit form: name "Confío", symbol CONFIO, logo (256px PNG from
   apps/src/assets/png/CONFIO.png), site https://confio.lat, socials.
