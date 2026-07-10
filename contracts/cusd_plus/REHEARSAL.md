# Rehearsal record — vault + router on a live EVM network

## Run 1: anvil fork, chainId 97 — 2026-07-04 — **PASS**

Full lifecycle driven by the APP'S OWN SIGNER (`evmWallet.signLegacyTransaction`,
legacy type-0 + EIP-155) with the user wallet derived via the **V2
master-secret path** (`deriveEvmKeyFromMasterSecret`) — exercising the gap
fix live. ethers used only to ABI-encode calldata. Script:
`apps/scripts/rehearsal-e2e.mts`; deploy: `script/DeployRehearsal.s.sol`.

| Step | Result | Check |
| --- | --- | --- |
| 1 Gas dust (sponsor → user, 0.03 BNB) | OK | sponsorship pattern |
| 2 Mint + approve test USDT | OK | |
| 3 `subscribeAndMint` $500 | 500.000000 cUSD+ | 1:1 at $1.00 |
| 4 Oracle +1% → `accrue()` | pPlus = **1.0085** exactly | 85/15 split on-network |
| 5 `buyWithSavings` $100 of TSLA | 0.335158 shares; fee **0.302549 USDT** to treasury | explicit fee = 0.30% of 100.85 redeemed |
| 6 `sellToSavings` | 499.400899 cUSD+ (shares) | round trip loses fees only |
| 7 `redeemToUsdt` 50 shares | +50.425 USDT | 50 × pPlus |
| Invariant | `backingRatioBps = 10016` | ≥ 10000; the +16bps IS Confío's surplus from the accrued yield |

## Run 2: real BSC testnet — SUPERSEDED (2026-07-10)

**Do not fund or chase `0x4eb41b82064c4dcf23822A5a40c1878eEb60F9e6`.** Its
private key lived only in a session scratchpad that macOS tmp-cleaning
wiped; the key was never logged anywhere (all session transcripts and
local snapshots searched). The 0.002 mainnet BNB + 0.3 tBNB on it are
permanently stranded. Rule going forward: key material derives from code
or lives in Secrets Manager — never in tmp.

Replacement deployer (deterministic, unloseable):
`deriveEvmKeyFromMasterSecret(fill(43), personal/0)` →
`0xAE3f12A895FBD0D86f5db657B92CfdD2c411B750`.

**Preferred path now: BSC MAINNET-FORK rehearsal.** The real Instant
Manager (`0x9bA36008...`), oracle and USDY are live on mainnet, so an
`anvil --fork-url` run exercises the REAL contracts (whitelist pranked) —
something testnet mocks never could. Public-testnet realism (gas market,
receipt latency) stays optional afterwards via the deterministic
deployer: fund 0.002 BNB as a LOAN, claim the faucet, then sweep the
0.002 back to the sponsor — net cost ≈ gas. Sponsor outflows only with
Julian's explicit go.
