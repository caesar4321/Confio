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
| **ConfioPayContract** | `0x1FAEFF796cd1a737FB8E1A660E84b80fd1702FCD` |
| **ConfioPayrollVault** | `0x664378b2668f320ce3573D0eD6DD154b8C8B3835` |
| Owner (both) | `0xF29A418744E793973BF4eEc676F8a30B2793b623` (3-of-5 Safe) |
| cUSD+ vault | `0x3C29417eb4314155e63d4C7D4507852b87763Ed1` |

- **ConfioPayContract** — invoice payments. Payer's 7702 batch is
  `[token.approve(this, gross), pay(invoiceId, token, gross, merchant)]`;
  the CONTRACT computes the 0.9% ceiling fee (`feeFor`, wei-parity with
  the Algorand builder), pays the merchant net, and accrues fees per
  token. Replay key is the full payment terms, not the invoice id alone —
  keying on the id alone let anyone who read the QR brick a payment with
  a 1-wei self-payment (audit P1). Creation tx
  `0xae789ffbdf7cd5b71a04580355d77d375b4303ed59ec10ad3768ee13cfa0b10a`
  (nonce 24, ~0.0009 BNB). Verified. Post-deploy: `feeFor(10e18)` =
  0.09e18, `feeFor(10001)` = 91 (ceiling holds).
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
- **Future requirement:** when `ConfioStockRouter` is deployed it MUST get
  `setSponsor(router, true)` — `sellToSavings` mints to the user while the
  router is `msg.sender`, so without it every sell-into-savings reverts
  `recipient not caller`.
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
