# cUSD+ deployment record — BSC mainnet

## CusdPlusVault — deployed 2026-07-10

| Role | Address |
| --- | --- |
| **Vault (ERC1967 proxy)** | `0x3C29417eb4314155e63d4C7D4507852b87763Ed1` |
| Implementation | `0xB0C2122047a69C8Ee336ce75fd61050a06630823` |
| Owner + treasury | `0xF29A418744E793973BF4eEc676F8a30B2793b623` (3-of-5 Safe) |
| Deployer | `0xf9f93Ba8ebf50515Ed2729Eb07657c8298cdfc9D` (KMS sponsor) |

Deploy txns (BscScan):
- impl:  `0x44be3e14bd3d6886a929dff6664fa2901c300e817741c6930deaa9519f970a27`
- proxy: `0x79326b3b7f124abe97b6d83cc7d5666dd1cce0c8f10a66a178726c74b7e1c58a`

Deployed via `manage.py deploy_cusd_plus_vault --broadcast --yes-mainnet`
(KMS-signed creation txns — no extractable deployer key). Cost ≈ 0.0032 BNB.

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
- [ ] Send vault proxy address to Ondo (Daniel) for PP whitelisting
- [ ] $1 live E2E once whitelisted
- [ ] Router deploy (separate) once GM attestation ABI is wired
- [ ] `lockUpgrades()` at the proven-stable milestone (NOT yet — keep
      UUPS flexibility during IM integration)

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
