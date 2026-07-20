# cUSD+ deployment record — BSC mainnet

## CusdPlusVault — deployed 2026-07-10, upgraded 2026-07-13

| Role | Address |
| --- | --- |
| **Vault (ERC1967 proxy)** | `0x3C29417eb4314155e63d4C7D4507852b87763Ed1` |
| Implementation (current, guard-gated reset) | `0x578fd4d235acF608979b63BBB28bD2292E7e201e` |
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
      CusdPlusVault storageLayout` vs the live impl's layout. Pinned in CI
      by `test_storageLayout_pinnedToLiveProxy` (raw-slot asserts: 0 pPlus,
      1 lastOraclePrice, 2.0 oracleGuardTripped, 2.1 deprecated
      upgradesLocked byte — reserved, 3 frozen, 4 guardedOraclePrice;
      append at 5+).
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
