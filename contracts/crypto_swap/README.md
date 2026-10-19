# Crypto & metals router (BSC, PancakeSwap)

`ConfioSwapRouter` lets a Confío user buy and sell catalog tokens (BTCB, ETH,
WBNB shown as BNB, XAUt…) with either Confío dollar, inside a sponsored
EIP-7702 batch.

- **Buy:** cUSD+ shares → `redeemToUsdt`, or cUSD → `redeemWithFee` (cUSD's
  0.9% exit fee) → PancakeSwap SmartRouter. All of the net USDT is swapped,
  and the token goes straight to the user.
- **Sell:** token → PancakeSwap → USDT → `subscribeAndMint` (cUSD+), or
  `mintWithFee` (cUSD) (0.9% entry fee). The result is minted straight to the
  user.
- **No fee of its own** and nothing held at rest: every leg is measured by
  balance delta, with exact-consumption allowance checks.
- The only external target is the immutable SmartRouter. The router builds the
  call itself: the recipient is fixed, and only the route endpoints are checked
  (USDT ↔ token).
- Every trade must be originated by Confío's relay (`tx.origin` is a cUSD+
  sponsor). The relay sponsors only catalog tokens, catalog routes and floors
  within `CRYPTO_MAX_SLIPPAGE_BPS` of a live requote
  (`cusd_plus/crypto_policy.py`).

The catalog lives in `cusd_plus/crypto_tokens.json`.

## Test

```sh
forge test --match-contract ConfioSwapRouterTest
forge test --match-path test/ConfioSwapRouter.fork.t.sol \
  --fork-url https://bsc-dataseed.bnbchain.org -vv
```

The package reuses `../ondo_stocks/node_modules` and `../ondo_stocks/lib`.
Run `npm install` and `npm run setup:forge-std` there first.

Fork results (2026-10-19) for a $10 round trip, two 0.9% fees included:
BTCB 1.81%, XAUt 1.95%.

## Deploy

1. On the production host, after the code is deployed there:
   `myvenv/bin/python manage.py deploy_swap_router` (dry run), then
   `--broadcast --yes-mainnet`. The command takes the shared sponsor nonce lock
   and refuses unless it sees the relay's Redis heartbeat. **Never broadcast
   from a laptop**: a laptop running its own Celery beat against a local Redis
   can fake that heartbeat, and its nonce lock is not the relay's.
2. Safe multisend (printed by the command): `cUSD+.setSponsor(router, true)`
   and `cUSD.setSponsor(router, true)`.
3. Verify the source on BscScan.
4. Set `CRYPTO_SWAP_ROUTER_ADDRESS`, `CRYPTO_ENABLED` and
   `CRYPTO_BUY_ALLOWED_USER_IDS` (canary), then `CRYPTO_TRADING_ENABLED` last.
