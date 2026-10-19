# Ondo Stocks router (BSC)

Standalone Foundry package for Confío's Ondo Global Markets stock router.
It connects the existing cUSD+ vault to Ondo's BSC `GMTokenManager` without
depending on the cUSD+ implementation source.

## Fees (v2, 2026-10)

The router charges **no fee of its own** (`stockFeeBps() == 0`). Stock trades
pay Confío's single 0.9% conversion fee exactly where every other exit from or
entry into Confío Dollar pays it:

- `buyWithSavings` redeems the user's cUSD+ through the vault's public
  `redeemToUsdt`, which routes through cUSD's `settleSavingsExit` (0.9% exit
  fee), then spends the net USDT on the GM mint. Any USDT above the attested
  spend (vault accrual between quote and execution) is returned to the user.
- `sellToSavings` sends GM proceeds through the vault's sponsored
  `subscribeAndMint`, which routes through cUSD's `settleSavingsEntry` (0.9%
  entry fee), minting the net cUSD+ to the user.
- `sellToUsdt` never touches cUSD, so it pays nothing.

Every trade signs `maxFeeBps`, which is checked against cUSD's live `feeBps`
(`conversionFeeBps()`), so a Safe fee change can never apply to an intent
signed at a lower fee.

**Transitional legacy path.** Pre-v2 app builds always sign `maxFeeBps = 30`
and size their redemption and floors for the v1 0.30% router fee. A call
signed at exactly `LEGACY_STOCK_FEE_BPS` (30) settles the v1 way: the
router-only fee-free vault surfaces (`redeemForStock`/`subscribeForStock`)
plus 30 bps accrued in `accruedUsdtFees`. Both entry points are
sponsor-originated, so the relay's `CUSD_PLUS_STOCK_LEGACY_FEE_ENABLED`
decides how long legacy intents are honored. Once the new build is on both
stores: switch that off, force-update, and upgrade to a single-mode router that
deletes this path.

Accrued legacy fees remain withdrawable only through `withdrawFees`; `sweep`
cannot touch them.

## End-to-end wiring

The production flow is deliberately split by custody boundary:

1. Daphne requests a soft quote for preview, then a binding BSC attestation
   from Ondo after confirmation. The write key never leaves the server.
2. The app reads the user's live cUSD+/stock balances and builds an optional
   approval plus the exact router calldata.
3. Daphne validates the quote request, sponsored-rail configuration, issuer
   eligibility, canonical calldata, and the signed fee cap (90 bps v2, or
   30 bps legacy while the transition switch is on).
4. The app signs an EIP-712 intent and the KMS relay broadcasts the sponsored
   EIP-7702 batch.
5. The router settles atomically and Daphne invalidates the vault and GM
   holdings caches.

`sellToUsdt` is deliberately outside this application flow. An advanced user
must obtain a valid Ondo sell attestation, approve the router, and submit the
contract call with their own BNB and tooling.

USDY settlement is separate from GM stock settlement. The cUSD+ vault calls
`USDY_InstantManager.subscribe`/`redeem`; it never calls a USDY
`mintWithAttestation`. Only this stocks router calls GMTokenManager's
`mintWithAttestation` and `redeemWithAttestation`.

## Test

```sh
cd contracts/ondo_stocks
npm install
npm run setup:forge-std
forge test
```

Live immutable wiring and BSC transient-storage support:

```sh
forge test --match-path test/ConfioStockRouter.fork.t.sol \
  --fork-url https://bsc-dataseed.binance.org -vv
```

The tests import the deployed cUSD+ implementation's local test harness from
the sibling package to exercise the real savings integration. Production router
source imports only minimal interfaces declared in `ConfioStockRouter.sol`.

## BSC deployment

### Mainnet deployment — 2026-08-10

| Role | Address |
| --- | --- |
| **ConfioStockRouter (ERC-1967 proxy)** | `0x40c8e134BCAf44EEf9e7D184846F36c9862329c3` |
| Implementation | `0xb502b25eF3Bb431e869374a4e0df30daF8EC44B3` |
| Owner | `0xF29A418744E793973BF4eEc676F8a30B2793b623` (3-of-5 Safe) |
| Deployer | `0xf9f93Ba8ebf50515Ed2729Eb07657c8298cdfc9D` (KMS sponsor) |

Implementation transaction:
`0x2f908d02b7cfed2d7891ce32751dd07a49c435982ff7bb11bf7c0bcb0c426046`.
Proxy transaction:
`0x6809c34e2483fa311ea60f0af183dc330a934dac0cfe1f531268f06706e9df8c`.
The guarded KMS deployment command verified the immutable dependency reads,
Safe ownership, proxy initialization, and fixed 30 bps fee against BSC after
mining. Both contracts are source-verified, and BscScan's Etherscan V2 API
recognizes the ERC-1967 proxy-to-implementation relationship. The previous non-upgradeable router
at `0x57895513ad375B247d702D86DC545E8f880Cc8F6` was never activated and is
superseded.

Trading remains disabled. Pending activation gates:

- [x] Publish and verify the source on BscScan (Solidity 0.8.26,
      optimizer 200, exact constructor arguments) — verified 2026-08-10.
- [ ] Whitelist the router address with Ondo GM. Ondo owns the internal
      purchaser `userId` mapping and returns it in signed attestations; there
      is no separate purchaser-ID value for Confío to configure.
- [ ] Safe calls on the cUSD+ vault:
      `setSponsor(0x40c8e134BCAf44EEf9e7D184846F36c9862329c3, true)` and
      `setStockRouter(0x40c8e134BCAf44EEf9e7D184846F36c9862329c3)`.
- [ ] Production-fork rehearsal against the deployed address.
- [ ] Real minimum-size buy/sell canary.
- [ ] Enable `CUSD_PLUS_STOCK_TRADING_ENABLED` only after every item above.

Deployment used the non-extractable production KMS key:

```sh
python manage.py deploy_stock_router --broadcast --yes-mainnet
```

Dry-run first:

```sh
forge script script/DeployBsc.s.sol --fork-url "$BSC_RPC_URL"
```

Deployment alone does not activate trades. Before enabling the app:

1. Verify the router source on BscScan.
2. Have Ondo whitelist the router address for GM settlement. The attestation
   API supplies the corresponding purchaser `userId`; it is not a separate
   dashboard input.
3. From the Confío Safe, call `CusdPlusVault.setSponsor(router, true)` and
   `CusdPlusVault.setStockRouter(router)`.
4. Confirm the relay origin remains registered as a cUSD+ sponsor.
5. Confirm the production KMS origin is a cUSD+ sponsor and the deployed
   ConfioBatchDelegate is the configured EIP-7702 delegate.
6. Run a production-fork trade rehearsal and a real minimum-size canary.
7. Configure Daphne, in this order:

   ```env
   CUSD_PLUS_STOCK_ROUTER_ADDRESS=0x...
   CUSD_PLUS_GM_TRADE_FEE_BPS=30
   CUSD_PLUS_BATCH_DELEGATE_ADDRESS=0x...
   CUSD_PLUS_7702_ENABLED=True
   CUSD_PLUS_STOCK_TRADING_ENABLED=True
   CUSD_PLUS_STOCKS_ENABLED=True
   ```

   `ONDO_API_KEY` and `ONDO_GM_WRITE_KEY` must already resolve from Secrets
   Manager. The GraphQL execution flag remains false unless every execution
   dependency above is present and the fee mirror is exactly 30.

The mainnet script pins chain ID 56 and the currently deployed cUSD+, USDT,
USDon, GMTokenManager, and Confío Safe addresses.
