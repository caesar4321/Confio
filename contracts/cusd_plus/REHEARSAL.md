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

## Run 2: real BSC testnet — PENDING faucet

Deployer `0x4eb41b82064c4dcf23822A5a40c1878eEb60F9e6` awaits tBNB (official
faucet requires ≥0.002 mainnet BNB on the receiving address; programmatic
faucets are captcha-gated). Once funded, the same deploy + script re-run
verbatim against `https://data-seed-prebsc-1-s1.bnbchain.org:8545` — run 1
already validates every code path; run 2 adds public-network realism
(gas market, receipt latency, RPC quirks).
