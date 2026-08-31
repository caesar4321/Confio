# cUSD+ deployment record — BSC mainnet

## Coordinated cUSD fee-perimeter release (90 bps) — deployed 2026-08-31

This release keeps the existing cUSD+ proxy and introduces a new UUPS cUSD
proxy. The contract rollout and post-deploy reads succeeded. Server config now
contains the new addresses and ships with `CUSD_CONVERSION_FEE_ENABLED=True`;
the EC2 cutover, migrations, service restart, and live canaries complete the
activation.

| Contract | Address | Deployment / upgrade transaction |
| --- | --- | --- |
| cUSD implementation | `0xf7F2062b4249aD91f061c29Ed059A3073213a93C` | `0x82f28fbd6fed1d353ecd7d49efacaffd61df5495f2cc14eea635148e8eefcfa3` |
| **cUSD ERC1967 proxy** | **`0x6101cC370635cF2c7f2725EaB010aC407A8d543F`** | `0x052947b6cd8bf6e6c19dd7e3e422d8aa17d91e9f72d6dfb0a1301ec8beb4b3e4` |
| cUSD+ implementation | `0x1E5D09badBaE8f7b1b81C30B612ef452e7F7eC44` | `0x223cb081c9a984bff1fd92a9a616877f3f69d0c9827984172c29e77c56eb5ba9` |
| Stock Router implementation | `0xF933976473Ba2291d5BA5934BA8915A058A3C83a` | `0x87b7aae34cac09529697c7cb26ca7bf97e5fa7e0f574aa4a23b0b4d538fb45ba` |
| cUSD+/Stock coordinated Safe multisend | existing proxies retained | `0x4120a2c2be2151d264e208b0155578b586c6c58a3fbefe0ee5fa7b1db51c57aa` |
| ConfioPayContract | `0x942BF5F3C9079Ab29492324B9F1E501Db5B830bA` | `0x960d3d4070f7dbc857545027beadbea4fd97877580f215b7cfd909eb1a04137b` |
| ConfioPayrollVault | `0x851e1a56De5c0ADBB75e904B2E7325e132692027` | `0x34a17c3656add5b7276b7a6f398c31fe5ba3d4da677384ca851f2160542f6aba` |
| ConfioInviteEscrow | `0xe6c49CcEb57b86dfE2F597053f8f475F18AcDb59` | `0xe3ec4ecb06d0f871e4a3eb280e5f65ea2d1f13f4a5639fdb1e19085d4143f2a3` |
| ConfioPresaleVault | `0x8c3A1fffcFfE1B07108486Be85C0dC42B4aC0358` | `0x9954eaedadb9c551bab96cffbdc544c454208fecd19a74e1a14d6f33225806e7` |

Safe nonce 14 installed the cUSD/cUSD+/Stock topology atomically. Safe nonce
15 paused new purchases on the predecessor Presale
(`0xf668f9c3f141df415266affe3bb42d5b50d86510fd68ccd9efbcdf567a7d8bf4`).
The frozen snapshot proved three outstanding buyer allocations totaling
323.97608200352 CONFIO. Safe nonce 16 imported those allocations, funded the
replacement with exactly 18,037.82608200352 CONFIO (including the unassigned
17,713.85 migration pool), and wired the CONFIO token
(`0xe48de62ee2e758e9270c8bc8bb2ec5aa3ed2ad1d48210047005d51e12aeef65f`).
`legacyPool == 0`; claims remain deliberately locked.

Post-deploy: cUSD fee = 90 bps, sponsor and savings wiring correct, cUSD fully
backed at zero supply; cUSD+ owner/supply/pPlus/oracle/backing all survived and
its USDY yield surplus remained untouched; Stock Router retained owner/state,
uses the new implementation, and reports 30 bps. Fee event scan starts at
BSC block `119102396`.

BscScan source verification passed for the cUSD implementation and proxy,
cUSD+ implementation, Stock Router implementation, Pay, Payroll, Invite, and
Presale deployments. Existing cUSD+ and Stock proxy addresses remain linked by
their ERC-1967 implementation slots.

Production configuration is part of the coordinated cutover:

- Set `CUSD_VAULT_ADDRESS` to the deployed cUSD proxy.
- Set `CUSD_VAULT_FEE_EVENTS_START_BLOCK` to the exact earliest block of
  the cUSD proxy deployment or cUSD+ upgrade. First-boot fee reconciliation
  deliberately fails closed when this is zero.
- Set `KOYWE_BSC_SETTLEMENT_ADDRESSES` and
  `GUARDARIAN_BSC_SETTLEMENT_ADDRESSES` to verified provider settlement
  senders when a provider API does not supply its BSC transaction hash.
  Attribution otherwise fails closed; amount/time alone is never accepted
  as ramp-origin proof.

Record the final values and deployment transaction hashes here before
enabling client conversion flows. The fee watcher must first reconcile from
the configured start block.

### Pre-cutover USDT treasury drain — 2026-08-31

At BSC block ~119,099,137, every current and superseded Confío BSC contract
was inventoried for USDT before the cUSD fee-perimeter deployment. Four live
contracts held USDT. The 3-of-5 Safe withdrew only provably treasury-owned
proceeds/fees to the KMS sponsor; Payroll's business escrow was excluded by
the contract's accounting guard.

| Source | Treasury USDT withdrawn | Transaction |
| --- | ---: | --- |
| Stock Router accrued fees | 2.847502847193699995 | `0x53e38846ea34522544641a5f47ed15da2521d973382198301fbbbbf97fb6c2c6` |
| Pay accrued fees | 0.01017 | `0xc806c46060cd2a8760e5f5b5be6ffd5dc372a44d7bdf81c07c42673633d36c87` |
| Presale proceeds | 44.939999999983471928 | `0x263816d12606f643c5709465a83987164fd157b12325cf14a4a2b4f34ab0c32d` |
| Payroll accrued fees | 0.0099 | `0x882001251543df4f8bc7ef77fbfb8bc451fd7fec608438e5625391f9793ab7c9` |
| **Total** | **47.807572847177171923** | Safe nonces 10–13 |

The sponsor approved exactly that amount to PancakeSwap V2
(`0x1a7653d11cf399fa1a1c9029cef88960ad0b425f171e75d822de88288176c777`)
and swapped it through USDT→WBNB to native BNB with a 50 bps slippage cap
(`0x8a27f0e0e192f3b7c0b30481ece4c2f70d78428e754dcd49e093ac0f05336aae`).
Net sponsor BNB increased by 0.069463485346723784 after swap gas. The
sponsor's pre-existing 0.508264376741423219 USDT was deliberately left
untouched; Pancake allowance returned to zero.

Post-operation reconciliation at Safe nonce 14:

- Stock Router USDT / `accruedUsdtFees`: 0 / 0
- Pay USDT / accrued USDT fees: 0 / 0
- Presale USDT: 0
- Payroll USDT / `totalEscrowUsdt` / accrued fees / surplus:
  0.0191 / 0.0191 / 0 / 0 — exact protected business escrow
- cUSD+ vault, Invite, Reward, Vesting, Batch Delegate, and every recorded
  superseded Pay/Payroll/Presale/Stock deployment: 0 USDT
- sponsor: 0.508264376741423219 USDT and 0.089988206527913925 BNB

Deployment order:

1. Run `manage.py deploy_cusd_fee_system` as a dry run, review its predicted
   addresses and Safe calldata, then repeat with `--broadcast --yes-mainnet`.
   It deploys `CusdVault` implementation + ERC1967 proxy initialized with the
   3-of-5 Safe and `feeBps = 90`, the new `CusdPlusVault` implementation, and
   the new `ConfioStockRouter` implementation for the existing router proxy.
2. Rehearse the live cUSD+ proxy upgrade with
   `UpgradeRehearsalV5.fork.t.sol`, and compare storage layout before signing.
3. Execute one Safe multisend in the printed order: register the KMS sponsor
   on cUSD, set the existing cUSD+ proxy as cUSD's savings vault, upgrade and
   initialize cUSD+, upgrade the existing Stock Router proxy, then register
   that proxy through both cUSD+ `setSponsor(router, true)` and
   `setStockRouter(router)`.
4. Read back cUSD `owner`, `feeBps`, `savingsVault`, sponsor status and full
   backing; read back cUSD+ `CUSD`, `stockRouter`, router sponsor status,
   owner, supply, pPlus, oracle baseline and backing; read back the Stock
   Router implementation slot, owner, immutable wiring, `stockFeeBps == 30`,
   and permissionless `sellToUsdt` selector. Any mismatch aborts activation.
5. Redeploy `ConfioPayContract` with both cUSD+ and cUSD immutables. Verify all
   six constructor values using `manage.py deploy_pay_contract` before setting
   `BSC_PAY_CONTRACT_ADDRESS`/the matching ABI flag.
6. Redeploy the non-upgradeable `ConfioPayrollVault` with cUSD+ and cUSD. Its
   appended asset 2 is the active non-yield cUSD pool; asset 1 remains a
   legacy USDT pool only so old escrow can be drained/migrated. Verify
   `CUSD_PLUS()`, `CUSD()` and `owner()` before switching
   `BSC_PAYROLL_VAULT_ADDRESS`.
7. Redeploy `ConfioInviteEscrow` with cUSD+, cUSD, CONFIO, sponsor and Safe.
   Stop creating invitations in the predecessor first. Existing invitations
   remain claimable/reclaimable there until drained; new invitations use the
   replacement. Verify all five immutable/role reads before switching
   `BSC_INVITE_ESCROW_ADDRESS`.
8. Pause the predecessor `ConfioPresaleVault`, then snapshot `totalSold`,
   `totalClaimed`, the unassigned Algorand migration pool, and every BSC
   buyer's outstanding `purchased - claimed` allocation. Deploy the replacement
   with cUSD as `PAYMENT_TOKEN` and the exact four aggregate constructor values.
   Before switching `BSC_PRESALE_VAULT_ADDRESS`, execute `creditLegacy()` for
   every outstanding BSC buyer and prove that `legacyPool() == 0` and each
   imported `purchased(address)` equals the snapshot. Never infer these values
   from aggregate totals alone. Fund the replacement's outstanding CONFIO
   liability before claims are unlocked; keep the predecessor paused but
   claim-capable until its final reconciliation is recorded.
9. Configure server `CUSD_VAULT_ADDRESS`; compile the same proxy into the app
   as `BSC_CUSD_VAULT_ADDRESS`. Enable the fee feature flag for the coordinated
   production release, then run a $1
   entry, Guardarian checkout disclosure, internal cUSD↔cUSD+ round trip,
   fee-bearing exit, Pay, friend-send, Invite, Payroll, Presale, off-ramp and
   Emergency Exit canary all pass.
10. Enable the server/contract path first. Legacy builds remain operational and
   pay the 0.9% contract fee; for roughly the review window they can still
   display stale `Comisión de Confío — Gratis`. New builds disclose the exact
   contract preview and debit gross/send net on exits.

`StockRouter` remains the Ondo-eligible cUSD+/USDT trading path and must not
accept cUSD, but its existing proxy is part of this coordinated cutover. The
new implementation uses the vault's dedicated fee-free stock settlement so
app trades pay only 30 bps; its contract-only `sellToUsdt` exit is
permissionless and is never called by Confío's client or server.

Rollback before any new cUSD supply exists: disable the feature flag and Safe
upgrade cUSD+ back to the recorded implementation. After cUSD supply exists,
never detach the perimeter blindly. A global pause intentionally blocks both
conversion and raw-token transfers, including Emergency Exit fallbacks; Safe
must unpause or deploy a reviewed forward upgrade before holders can exit.
Diagnose first, then restore an audited exit path through governance.

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

### Status: WHITELISTED (2026-07-30) — ready for the $1 live E2E

Duende Limited fully approved for Ondo Global Markets 2026-07-30;
Subscription Form executed via Dropbox Sign; vault proxy registered via
app.ondo.finance/account/wallets and whitelisted within minutes.
On-chain proof: `IM.subscribe` eth_call as the vault no longer reverts
`UserNotRegistered()` — it proceeds to the USDT balance pull ("BEP20:
transfer amount exceeds balance" in simulation). Ondo GM write API key
stored at Secrets Manager `prod/ondo-gm-api-key` (eu-central-2) —
readable by the EC2 role (prod/* wildcard added 2026-07-31; the old
per-ARN enumeration is gone). Unwired in code until GM trading lands.

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
- [x] Send vault proxy address to Ondo — DONE; account approved and
      address whitelisted in the OndoIDRegistry 2026-07-30 (self-serve
      via the Ondo dashboard, confirmed on-chain by the IM probe).
- [ ] $1 live E2E (subscribeAndMint -> redeemToUsdt round trip) — vault
      needs ~1 USDT on BSC to run it
- [x] Router deploy (separate) once GM attestation ABI is wired — UUPS proxy
      deployed 2026-08-10 at `0x40c8e134BCAf44EEf9e7D184846F36c9862329c3`,
      proxy tx `0x6809c34e2483fa311ea60f0af183dc330a934dac0cfe1f531268f06706e9df8c`;
      implementation `0xb502b25eF3Bb431e869374a4e0df30daF8EC44B3`, tx
      `0x2f908d02b7cfed2d7891ce32751dd07a49c435982ff7bb11bf7c0bcb0c426046`.
      Both contracts passed BscScan/Etherscan verification 2026-08-10. The
      earlier non-upgradeable deployment at `0x57895513ad375B247d702D86DC545E8f880Cc8F6`
      was never activated and is superseded. Trading remains
      disabled pending Ondo address whitelisting, Safe sponsor registration,
      fork rehearsal, and a minimum-size canary.
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
| **ConfioBatchDelegate** (v2, intent-bound) | `0xC06BD197b34a587026615C6AEd21301F5E99bc00` |
| ~~ConfioBatchDelegate v1~~ (no intentId, abandoned) | ~~`0xE9d9Ae4d97aE8128DF4501152540d7aA091b435C`~~ |
| Deployer | `0xf9f93Ba8ebf50515Ed2729Eb07657c8298cdfc9D` (KMS sponsor) |

**REDEPLOYED 2026-07-31 (migration audit P2 — intent binding):** the
`Execute` struct now carries a `bytes32 intentId` = keccak(kind:sourceId),
so the user's signature binds the flow purpose + the exact domain row (new
EXECUTE_TYPEHASH, three-way parity vector `0xf955b917…`). v2 at
`0xC06BD197b34a587026615C6AEd21301F5E99bc00`, creation tx
`0xc810100af1e6b2ef732a20748657018cbd1592a0b70d7a201accb39f773793c8`
(nonce 36), BscScan verified. **v1 signs the old struct and is abandoned;
already-shipped clients target v1, so `CUSD_PLUS_7702_ENABLED` is dark until
the intent-binding client ships.**

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

## ConfioPresaleVault — REDEPLOYED 2026-07-31 (audit)

> The 2026-07-30 deployment at `0x77e74deEed3A0f0e338EBd0A457dE3b3C0E95583`
> is **ABANDONED**. A Codex 5.6-Sol audit found three P1s in it: `claim()`
> left `migratedCredited` standing so `uncreditMigrated` could revoke
> tokens a buyer had PAID for; claims could become undercollateralized
> (unlock didn't prove backing, and post-unlock buys borrowed earlier
> buyers' collateral, so claim ORDER decided who got stranded); and
> `setClaimsUnlocked(bool)` let the Safe RE-LOCK claims — a freeze power
> `pause()` was deliberately denied. It was replaced while it still held
> **no funds, no assigned credits, and locked claims**, so nothing had to
> be migrated. Fixes in commit `9f9cdbf2`.

## ConfioPresaleVault — deployed 2026-07-31

$CONFIO presale on curve "A" (0–4M @ $0.20→0.30, 4–24M @ $0.30→0.70,
24–74M @ $0.70→1.30; full sale $61M), USDT-denominated, sponsor-gated
buys, migratedPool credits for Algorand purchasers. Non-upgradeable —
the segment table has no setter.

| Role | Address |
| --- | --- |
| **ConfioPresaleVault** | `0x1a2dD9b49987DE86dC96fC86c715b62aaDFf095c` |
| Owner | `0xF29A418744E793973BF4eEc676F8a30B2793b623` (3-of-5 Safe) |
| Sponsor (gate) | `0xf9f93Ba8ebf50515Ed2729Eb07657c8298cdfc9D` (KMS) |
| Payment token | `0x55d398326f99059fF775485246999027B3197955` (USDT 18dp) |

- Creation tx: `0x5f30dea02a021cc4f3f72725badf19de606ab95c77fd50bf1429dcf3c1b43a3e`
  (KMS sponsor, nonce 23, ~2.31M gas ≈ 0.0023 BNB), deployed via
  `manage.py deploy_presale_vault --broadcast --yes-mainnet`. BscScan
  verified. Post-deploy reads: currentPrice 0.200443, totalSold =
  migratedPool = 17,713.85 CONFIO (re-seeded live from Algorand app
  3353218127), claimsUnlocked false.
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
  `unlockClaims()` (one-way, and refuses unless every outstanding
  allocation is already funded), both Safe-only.

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
  3. `ConfioPresaleVault.unlockClaims()` when claims open — ONE-WAY, and
     it reverts unless the vault already holds `totalSold - totalClaimed`

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

## Phase 2 — ConfioPayContract + ConfioPayrollVault, deployed 2026-07-31

The cUSD phase-out's money-movement contracts. Both Safe-owned,
non-upgradeable, and both hold fee revenue IN the contract (Julian's
accounting rule, 07-31): balances read straight off-chain, no treasury
EOA exists to reconcile.

| Contract | Address |
| --- | --- |
| **ConfioPayContract** (v3, CONFIO in the allowlist) | `0x039Ebe91283c686F23F4C751600a39567967736D` |
| ~~ConfioPayContract v2~~ (superseded, 2-token allowlist) | ~~`0x71256d060Ba718ff758647Ab4CB91A113a09E93d`~~ |
| ~~ConfioPayContract v1~~ (STALE, permissionless) | ~~`0x1FAEFF796cd1a737FB8E1A660E84b80fd1702FCD`~~ |
| **ConfioPayrollVault** (v2, two-asset escrow) | `0x851cA801c3028D4C0e651d29803f8e35D86d7299` |
| ~~ConfioPayrollVault v1~~ (ABANDONED 2026-08-02, cUSD+ only) | ~~`0x664378b2668f320ce3573D0eD6DD154b8C8B3835`~~ |
| Owner (both) | `0xF29A418744E793973BF4eEc676F8a30B2793b623` (3-of-5 Safe) |
| cUSD+ vault | `0x3C29417eb4314155e63d4C7D4507852b87763Ed1` |

- **ConfioPayContract** — invoice payments. Payer's 7702 batch is
  `[token.approve(this, gross), pay(invoiceId, token, gross, merchant,
  deadline, authSig)]`; the CONTRACT computes the 0.9% ceiling fee
  (`feeFor`, wei-parity with the Algorand builder), pays the merchant net,
  and accrues fees per token.
  **REDEPLOYED 2026-07-31 (migration audit P1):** v1's replay guard traded
  griefing for an honest double-charge (two payers of one invoice both
  settled on distinct keys). v2 is SERVER-AUTHORIZED — the backend (the
  sponsor KMS key = `paymentSigner`) signs an EIP-712
  `Pay(invoiceId,payer,token,gross,merchant,deadline)`, and the guard is
  GLOBAL `invoiceDone[invoiceId]`: un-grief-able (no forge-able signature)
  AND exactly one settlement per invoice. Owner can rotate the signer
  (`setPaymentSigner`). Creation tx
  `0xc910369cea3736b6e5bac2bf644ee798277be928c42934db7d2e2feb812f51bc`
  (nonce 34, ~0.0014 BNB). BscScan verified ("Pass - Verified"). Post-deploy
  reads: `paymentSigner` = sponsor `0xf9f9…fc9D`, `owner` = Safe.
  **v1 `0x1FAEFF…` is abandoned — do not use.**
  **REDEPLOYED AGAIN 2026-08-01 → v3 `0x039Ebe91…736D` (ChargeScreen BSC
  migration):** the merchant charge menu became cUSD+ **and CONFIO**, and
  v2's allowlist was the immutable pair `{CUSD_PLUS, USDT}` — a CONFIO
  invoice reverted "token not allowed". v3 adds a third immutable `CONFIO`
  (`0xCcEb3F61…B3fa8`); USDT stays, since it is the PAYER's funding fallback
  (a raw-USDT holder, including anyone geo-ineligible to mint cUSD+, must
  still be able to pay), not a charge option. Nothing else changed; 22/22
  forge tests pass. Creation tx
  `0x3d8753c3f9fc5b56547872655875ee21814b7fb5e36109e7f89f0e0d0547f289`
  (nonce 46, ~0.0014 BNB). BscScan verified ("Pass - Verified").
  Post-deploy reads (now FATAL on mismatch, not merely printed): CUSD_PLUS,
  USDT, CONFIO, paymentSigner = sponsor `0xf9f9…fc9D`, owner = Safe — all
  OK. `BSC_PAY_CONTRACT_ADDRESS` updated in `.env.mainnet`.
  **v1 `0x1FAEFF…` and v2 `0x71256d06…` are abandoned — do not use.**

  **Before `BSC_PAY_ENABLED=True`** (Codex audit 2026-08-01, rounds 1-5 —
  all P1s closed, two P2s open): land a DB check constraint + outlier
  cleanup for the 24h invoice-lifetime ceiling (`Invoice.save()` bounds ORM
  writes, but `queryset.update()` / raw SQL / fixtures bypass it), and
  remove-or-track the non-invoice payment mode of
  `SubmitSponsoredPaymentMutation` (now requires `internal_id`, which no
  in-repo caller omits).
- **ConfioPayrollVault** — per-business cUSD+ share escrow with an
  on-chain delegate allowlist and EIP-712 delegate-signed payouts. The
  token's per-address freeze is honored through the escrow (audit P2:
  shares sit under THIS contract, so cUSD+ saw an unfrozen sender);
  `totalEscrowShares` makes the invariant `balance == Σescrow + fees`
  checkable, and `rescueSurplus` is bounded by it. `withdraw` is never
  pausable. Creation tx
  `0xe258a3eb257a54fbe1a043f1b31fb427646ccde03792aef8603378967dae2c1b`
  (nonce 25, ~0.0016 BNB). Verified.
- Config: `BSC_PAY_CONTRACT_ADDRESS`, `BSC_PAYROLL_VAULT_ADDRESS` in
  `.env.mainnet`. Flags `BSC_SEND_ENABLED` / `BSC_PAY_ENABLED` /
  `BSC_PAYROLL_ENABLED` all ship **False** — enable when bsc_address
  coverage is meaningful. Payroll `withdraw` ignores its flag by design.

### ConfioToken RE-ISSUE 2026-07-31 — ASCII name "Confio"

BscScan HTML-escapes non-ASCII token names; rather than live with
"Conf&#237;o" on every explorer surface, the token was re-issued with the
plain-ASCII on-chain name **"Confio"** (symbol CONFIO unchanged; the
accented "Confío" stays in UI/branding). Timing: zero holders beyond the
Safe, nothing wired (`setConfioToken` never executed) — the one cheap
moment for a metadata fix.

| Role | Address |
| --- | --- |
| **ConfioToken (CONFIO), CURRENT** | `0xCcEb3F6127FA9160a26A1B85857Ca4C9D56B3fa8` |
| Old token (SUPERSEDED, delisted + burned) | `0xd57BEc35857839DC33F6FaBE7356C6a19a8d72c1` |

- New creation tx: `0xac4a6e2b5cf40ed772b85dd74f83267066fbcc78b7db7ef9c990aa2413382abb`
  (KMS sponsor, ~1.03M gas). Post-deploy reads: name() = "Confio",
  totalSupply = balanceOf(Safe) = 1B. BscScan source verified 2026-07-31.
- Old token wind-down: BscScan ownership verification RELEASED (signed
  message 2026-07-31 via bsc_sign_message); Safe burns its full 1B —
  Safe tx to `0xd57BEc35857839DC33F6FaBE7356C6a19a8d72c1`, calldata
  `0x42966c680000000000000000000000000000000000000000033b2e3c9fd0803ce8000000`
  (`burn(1_000_000_000e18)` — drops totalSupply to 0, the clearest
  "dead token" signal an explorer can show).
- The pending claim-wiring Safe steps now use the NEW address:
  `presaleVault.setConfioToken(0xCcEb…3fa8)` — calldata
  `0x76eba8ba000000000000000000000000cceb3f6127fa9160a26a1b85857ca4c9d56b3fa8`.

## CusdPlusVault v5 — mint gate (LIVE 2026-07-31, Safe nonce 4)

Closes the open-mint gap: `subscribeAndMint` was permissionless on-chain,
so Ondo eligibility (§21(b)(F) continuing US-person representation) could
be bypassed by calling the vault directly, around Confío's phone + IP
checks. v5 requires `isSponsor[msg.sender] || isSponsor[tx.origin]` AND
`recipient == msg.sender || isSponsor[msg.sender]` (the second condition
came out of the Codex audit: `tx.origin` alone proves only that a sponsor
was somewhere above the call, not that it approved the recipient).

| Item | Value |
| --- | --- |
| **v5 implementation** | `0xAa9AFf7CD9B995DF7d54B1e646e2746a90DbF5a9` |
| Proxy (unchanged) | `0x3C29417eb4314155e63d4C7D4507852b87763Ed1` |
| Creation tx | `0xfc01a0fc914ae4c755e67f99924e0eec7a54e8ba1567acf8c55f46638469cbda` |

- Impl deployed via `manage.py deploy_cusd_plus_vault --impl-only
  --broadcast --yes-mainnet` (KMS nonce 27, ~0.0033 BNB). BscScan verified.
- **Proxy RE-LINKED on BscScan to v5** (`verifyproxycontract` +
  `checkproxyverification`, confirmed reading back
  `Implementation = 0xaa9aff7c…f5a9`). This is a SEPARATE step from
  verifying the implementation source: until it is done the explorer still
  resolves the proxy to the previous implementation, so "Read/Write as
  Proxy" shows the OLD ABI (no `isSponsor` / `setSponsor`). Do this after
  every UUPS upgrade.
- **The Safe transaction — ONE atomic tx:**
  - `to`: `0x3C29417eb4314155e63d4C7D4507852b87763Ed1`
  - `value`: `0`
  - `operation`: **CALL** (never DELEGATECALL)
  - `data`: `0x4f1ef286` … = `upgradeToAndCall(0xAa9AFf7C…F5a9,
    setSponsor(0xf9f93Ba8…fc9D, true))` — full bytes pinned in
    `test/SafeTxV5.fork.t.sol`, which REPLAYS those literal bytes against
    live state as the Safe and asserts the outcome.
- **Never use plain `upgradeTo`.** Without a sponsor seeded in the same
  transaction, minting is bricked until the Safe fixes it (exits are
  unaffected either way).
- Storage: `isSponsor` APPENDED at slot 5; slots 0–4 unchanged and pinned
  by `test_storageLayout_pinnedToLiveProxy`.
- **Future requirement:** when the standalone `contracts/ondo_stocks`
  `ConfioStockRouter` is deployed it MUST get
  both `setSponsor(router, true)` and `setStockRouter(router)`. Stock
  settlement then uses the dedicated fee-free cUSD+↔USDT surfaces, so the
  user pays exactly the router's fixed 30 bps instead of an additional
  90 bps conversion fee.
- **EXECUTED at Safe nonce 4** (signers 1/3/5 via
  `.kms-local/kms_evm_multisig/sign_safe_transaction.py --execute`; the
  script prompts `Type 'execute bsc' to submit:` — that exact phrase, or it
  signs and cancels without broadcasting).
- Post-execution VERIFIED live: impl slot = `0xaa9aff7c…f5a9`; Safe nonce 5;
  `isSponsor(KMS)` true / anyone else false; pPlus 1.001707…, lastOraclePrice
  1.141248…, supply 2.9849…, owner = Safe, unpaused, backing 10000 bps, guard
  untripped; a direct mint reverts `not sponsored`; `redeemToUsdt` reverts
  only on ERC20InsufficientBalance (i.e. the exit is NOT gated).
  `test/PostUpgradeV5.fork.t.sol` (5/5) exercises the DEPLOYED implementation
  against live state: production relayed mint works, unsponsored mint
  rejected, third-party recipient rejected, exit works with no sponsor.
- Trust model, stated honestly: this guarantees SPONSOR ROTATION CANNOT
  AFFECT EXITS. The owner Safe still can — `redeemToUsdt` is
  `whenNotPaused`, a frozen holder cannot burn, and UUPS could replace the
  logic. Those powers are deliberate (oracle/IM emergencies, Ondo
  dependency migration) and predate this gate.
- Old-token burn EXECUTED 2026-07-31: Safe nonce 3 (KMS owners 1/3/5,
  sponsor-submitted) — tx
  `0xa321f178f2c91d5807f5c56d0c12166f6b1ea8644430a5799660f2aca7fb6930`,
  block 113200348. Verified on-chain: OLD totalSupply = 0,
  OLD balanceOf(Safe) = 0; NEW balanceOf(Safe) = 1,000,000,000.
  (Etherscan.io "release verification" form for the old record rejects
  deployer signatures their own verify tool accepts — appears to compare
  against the token address itself; abandoned as cosmetic, support-ticket
  evidence pack = any signed release message + verifiedSignatures pass.)

## ConfioRewardVault — REDEPLOYED 2026-07-31 (DEX-locked signature-claim)

Rewards accrue OFF-CHAIN in the DB; nothing on-chain until a user claims,
and claims are LOCKED until the Safe opens them at DEX launch. Claim
authorization is a backend EIP-712 signature over the user's cumulative
earned CONFIO. **Supersedes the abandoned attestation-model vault
`0x1766A2Ac798dA2247E5Da6E410453D526FD2f6ab`** (empty, never funded — the
redesign scrapped on-chain per-reward attestation because CONFIO has no
liquidity before DEX; Julian 07-31).

| Item | Value |
| --- | --- |
| **ConfioRewardVault** | `0x812b8d86952123bED0a33E92a76211cbbACDe730` |
| CONFIO | `0xCcEb3F6127FA9160a26A1B85857Ca4C9D56B3fa8` |
| signer (backend hot key) | `0xf9f93Ba8ebf50515Ed2729Eb07657c8298cdfc9D` (KMS sponsor) |
| owner | `0xF29A418744E793973BF4eEc676F8a30B2793b623` (3-of-5 Safe) |

- Deployed via `manage.py deploy_reward_vault` (KMS nonce 31). BscScan
  verified. Live reads: claimsUnlocked false, signer/owner/CONFIO wired.
- Codex 5.6-Sol audit: no P1/P2; cumulative-claim double-spend argument
  verified. Trust model is explicit — a treasury-controlled pool, NOT
  trustless: the Safe can pause()+withdraw() and defund claims even after
  unlock; rewards are discretionary Safe obligations.
- **Before operational (in order):** (1) Safe funds a CONFIO tranche;
  (2) at DEX, Safe calls `unlockClaims()` (one-way); (3) build the KMS
  EIP-712 claim-SIGNER service (sign with SHORT deadlines — a corrected-down
  entitlement can't revoke an already-issued higher signature before its
  deadline) + the client `claim()` flow. Rewards accrue in the DB now
  (behind BSC_REWARD_ENABLED) regardless.
- Config: `BSC_REWARD_VAULT_ADDRESS`, `BSC_REWARD_ENABLED` (dark).

## ConfioVestingVault + ConfioInviteEscrow — deployed 2026-07-31

BSC mirrors of the Algorand vesting pool and invite_send (P2P deprecated,
not mirrored). Both Safe-owned, non-upgradeable, Codex-audited (vesting
clean at all severities; invite escrow had one P3 — invite-id squatting —
fixed by namespacing storage keccak256(inviter, inviteId)).

| Contract | Address |
| --- | --- |
| **ConfioVestingVault** | `0xb873e4dbFdf25EcB0F663CA9154F7384d780bE7A` |
| **ConfioInviteEscrow** | `0xeFF0Af29FcB8f010f3B1e58bd5bbA36AEad4D0d6` |
| CONFIO | `0xCcEb3F6127FA9160a26A1B85857Ca4C9D56B3fa8` |
| cUSD+ (escrow only) | `0x3C29417eb4314155e63d4C7D4507852b87763Ed1` |
| sponsor (escrow claims) | `0xf9f93Ba8ebf50515Ed2729Eb07657c8298cdfc9D` (KMS) |
| owner (both) | `0xF29A418744E793973BF4eEc676F8a30B2793b623` (3-of-5 Safe) |

- Vesting: linear per-grant (own start+duration → founder 36mo /
  co-builder 24mo / cultural 90d in one vault). Creation tx
  `0x1d1d295d…9252` (nonce 32). BscScan verified. Pending: fund CONFIO +
  `addGrant`/`startGrant` per beneficiary. **Migration note:** the
  founder/co-builder allocations are still vesting on ALGORAND (apps
  3359301443 / 3359297921) holding Algorand CONFIO; moving them to BSC is a
  token-migration decision (tokenomics §10 no-duplication).
- Invite escrow: cUSD+/CONFIO escrow for a not-yet-user; sponsor claims to
  the verified joining user, inviter reclaims after 7 days (never
  pausable). Creation tx `0x1b97c3e9…675d` (nonce 33). BscScan verified.
  Config `BSC_INVITE_ESCROW_ADDRESS` + `BSC_INVITE_ENABLED` (dark). Backend
  create/claim/reclaim flow + client are the next piece.

### ConfioPayrollVault v2 — two-asset escrow, deployed 2026-08-02

v1 escrowed cUSD+ SHARES only, which quietly made Nómina an
eligible-employers-only product. An Ondo-geo-blocked employer holds its
dollars as raw USDT and can never mint shares — the mint gate refuses it —
so `fundableBalance` read $0.00 and funding failed `insufficient_balance` on
money the business plainly owned. v1 already paid INELIGIBLE employees
(atomic `redeemToUsdt` inside `payout`); nothing handled an ineligible
EMPLOYER.

v2 escrows cUSD+ shares OR raw USDT, per business, never fungible between
them. `Payout` gained `asset` and renamed `netShares`/`feeShares` →
`netAmount`/`feeAmount`; the EIP-712 domain version moved `"1"` → `"2"`.

| Role | Address |
| --- | --- |
| **ConfioPayrollVault v2** | `0x851cA801c3028D4C0e651d29803f8e35D86d7299` |
| cUSD+ vault (constructor arg) | `0x3C29417eb4314155e63d4C7D4507852b87763Ed1` |
| USDT (read FROM the vault at construction, never passed in) | `0x55d398326f99059fF775485246999027B3197955` |
| Owner (3-of-5 Safe) | `0xF29A418744E793973BF4eEc676F8a30B2793b623` |
| Deployer | `0xf9f93Ba8ebf50515Ed2729Eb07657c8298cdfc9D` (KMS sponsor) |

- deploy tx: `0x81dbc3dc3ff31ad4f9b8f34a0e2a563ab325c200cb993a96b2ba0814769afe3a`
  (`manage.py deploy_payroll_vault --broadcast --yes-mainnet`, nonce 75,
  1,899,477 gas ≈ 0.0019 BNB)
- post-deploy verified live: CUSD_PLUS / USDT / owner wired as above,
  `paused = false`, all four counters (`totalEscrowShares`,
  `totalEscrowUsdt`, `accruedFeeShares`, `accruedFeeUsdt`) at zero, and
  `PAYOUT_TYPEHASH` equal to the v2 type string the server signs against.

Codex audit 2026-08-02 (2 P1 + 2 P2, all fixed before deploy):
- [P1] one server-side pool selector could not express "both pools hold
  money" — the caller now names the pool explicitly; `funding_token()`
  demoted to a default and to pinning a run at creation.
- [P1] the top-up screen validated withdrawals against the SUM of both
  pools and treated `insufficient_escrow` as licence to drain the Algorand
  vault instead. Per-pool validation; that fall-through is gone.
- [P2] `_decode_settled_amount` decoded the v1 `PaidOut` layout. Fixing it
  surfaced an older bug: `signer` was never indexed, so v1's decoder was
  off by one for its whole life and recorded the nominal wage instead of
  actual `usdtOut` for every redeemed payout.
- [P2] a frozen business could still `deposit()` into escrow it could not
  exit. Deposits are now freeze-gated like withdraw and payout.

**v1 is ABANDONED, not migrated** (Julian, 08-02). It held 0.000381 cUSD+ of
business escrow and 0.019581 of accrued fees — roughly two cents, not worth
a dual-vault code path. Note this is a *cutover*, not an upgrade: v2 starts
with EMPTY `isDelegate` mappings, so **every business must re-activate
payroll before it can pay anyone**. Items left `PREPARED` across the cutover
answer `payout_not_prepared`; the client re-prepares them.
