# Hands-off Cuenta inteligente (account v2): BSC mainnet deployment plan

Prepared 2026-11-25. Nothing in this document has been broadcast, signed or paid for. Everything was
rehearsed on a local anvil fork of BSC mainnet (forks taken at blocks 135653043 and 135653305).
Design: `docs/designs/hands-off-account.md` ("Deploy (Safe)").

## Status

| | |
| --- | --- |
| Contracts | `ConfioSmartAccountV2`, `ConfioSmartAccountFactory` (v2 logic) and `ConfioMarketEscrow` (depositFrom). The working tree files are byte-identical to commit `a6d8d6dc4`. **Note:** `a6d8d6dc4` is not an ancestor of `main` (HEAD `6d998fe8a`), and in the checkout these files are untracked or modified. Land the commit on `main` before building the artifacts for the real run. |
| Dry runs (mainnet RPC, no broadcast) | Both scripts pass: EIP-170 ok, the factory is owned by the Safe, the v1 implementation equals `factory.implementation()`, and the immutables match the v1 record. |
| Fork rehearsal | **PASS**, both variants (Trade rule in cUSD, and Trade rule in cUSD+): deploy, Safe batch, storage diff, post-checks, a v1 account still works, a new account is v2, unpause, migration batch, relay buy/sell (BTCB) and buy (XAUT), relayPurchase → `depositFrom`, buyer reclaim → refund to the account. |
| **Blocker 1** | No KMS deploy tool exists for these three implementations. Every past implementation was deployed by the KMS sponsor through a `manage.py deploy_*` command on prod, under the shared sponsor nonce lock. There is no `deploy_*` twin for `DeploySmartAccountV2` or `UpgradeConfioMarketEscrowDepositFrom`, and the forge scripts say "NEVER broadcast from a laptop". See "Step 1". |
| **Blocker 2** | `config/settings.py` never defines `SMART_ACCOUNT_V2_IMPLEMENTATION_ADDRESS`. `smart_account/hands_off.py` reads it with `getattr(settings, …, '')`, so setting it in `.env.mainnet` does nothing until settings has `SMART_ACCOUNT_V2_IMPLEMENTATION_ADDRESS = config('SMART_ACCOUNT_V2_IMPLEMENTATION_ADDRESS', default='')`. |
| Not rehearsed | (a) A real GM stock relay trade: it needs a fresh signed Ondo attestation, which cannot be produced on a fork (as in `ondo_stocks/test/UpgradeRehearsal.fork.t.sol`). The real ConfioSwapRouter carried the relay trades instead (BTCB and XAUT). (b) A pre-existing production v1 account: public RPCs prune `eth_getLogs` (publicnode returned nothing for the factory's `AccountCreated` range, and the dataseeds refuse), so accounts could not be listed. v1 accounts were opened on the fork from the **real** factory and v1 implementation before the upgrade. `HandsOffV2ForkRehearsal.s.sol` takes any owner if a real account address is supplied. |

## Addresses (BSC mainnet, chain 56)

| Role | Address | Source |
| --- | --- | --- |
| Safe (3-of-5 KMS, v1.4.1, nonce 32 at preparation) | `0xF29A418744E793973BF4eEc676F8a30B2793b623` | DEPLOYMENT.md, on-chain `getThreshold()=3` |
| Safe owners (KMS signers 1–5) | `0x3E5b538A721b25C974dAD8735B3679Fe69a2dA22`, `0x2E40667D1930580f346723beD24985A94a8fcBdf`, `0x311153Bc7CD82D3D0c31A0d332DBFb3FF2bbf5f9`, `0xf2cf8e1a7908DAB536DC9DBcba0A4aaB9fb6f32a`, `0x13D29DeD5A7172244db2F35A61E7d785DAF2738c` | on-chain `getOwners()` |
| MultiSendCallOnly (v1.4.1) | `0x40A2aCCbd92BCA938b02010E17A5b8929b49130D` | `.kms-local/kms_evm_multisig/build_routers_multisend.py`, Safe nonces 22/27 |
| Smart account factory **proxy** | `0x339094A17605B842e0b2fc01441204E67020f953` | DEPLOYMENT.md, `SMART_ACCOUNT_FACTORY_ADDRESS` |
| Factory logic (live, v1) | `0x1FE1701915F6A85B218f5B7521A01fd3642f6C50` | ERC-1967 slot |
| Account implementation v1 | `0x8a20a0B3d2C0c6BED8BeB00bB6Bc7AE3c7ace44A` | `factory.implementation()` |
| Fee collector | `0x1AE0ACB82bAb9F506188c49305953CB655A539CD` | `SMART_ACCOUNT_FEE_COLLECTOR_ADDRESS` |
| ConfioMarketEscrow **proxy** | `0x2DFDC1fB809322c12f54beFE8CC98E0d103a99Fd` | DEPLOYMENT.md, `CONFIO_MARKET_ESCROW_ADDRESS` |
| Escrow implementation (live) | `0x0b618364936FA39aB325255e732831006895D4Fc` | ERC-1967 slot |
| Escrow orderSigner / arbiter | `0xf9f93Ba8ebf50515Ed2729Eb07657c8298cdfc9D` (KMS sponsor) | on-chain |
| KMS sponsor = deployer = relayer | `0xf9f93Ba8ebf50515Ed2729Eb07657c8298cdfc9D` | `BSC_SPONSOR_ADDRESS`. `isSponsor` is true on both cUSD+ and cUSD |
| cUSD | `0x6101cC370635cF2c7f2725EaB010aC407A8d543F` | |
| cUSD+ vault | `0x3C29417eb4314155e63d4C7D4507852b87763Ed1` | |
| USDT | `0x55d398326f99059fF775485246999027B3197955` | |
| CONFIO (v2) | `0xF5765933764562A51e179F6AF2b19b7a3d506101` | `BSC_CONFIO_TOKEN_ADDRESS` |
| ConfioStockRouter (proxy) | `0x40c8e134BCAf44EEf9e7D184846F36c9862329c3` | `CUSD_PLUS_STOCK_ROUTER_ADDRESS` |
| ConfioSwapRouter | `0xA7C27684aB38eC369cB1F4474f279ea503dbF712` | `CRYPTO_SWAP_ROUTER_ADDRESS` |
| BTCB / XAUT | `0x7130d2A12B9BCbFAe4f2634d864A1Ee1Ce3Ead9c` / `0x21cAef8A43163Eea865baeE23b9C2E327696A3bf` | |
| Chainlink BTC/USD, XAU/USD | `0x264990fbd0A4796A3E3d8E37C4d5F87a3aCa5Ebf` ("BTC / USD"), `0x86896fEB19D8A607c3b11f2aF50A0f239Bd71CD0` ("XAU / USD") | |
| 7702 batch delegate | `0xC06BD197b34a587026615C6AEd21301F5E99bc00` | `CUSD_PLUS_BATCH_DELEGATE_ADDRESS` |

The v2 constructor arguments other than the escrow equal the v1 implementation's (decoded from the
`verify_args` of the v1 record): factory, cUSD, cUSD+, USDT, CONFIO, stock router, swap router, collector,
BTCB, BTC/USD, XAUT, XAU/USD. The 13th argument is the escrow proxy.

## Step 1: deploy the three implementations (KMS sponsor)

There is nothing to initialize: the factory logic and the escrow implementation call `_disableInitializers`,
and v2 has only immutables. Order does not matter, since v2 needs only the escrow **proxy** address. At
0.05 gwei, the three creations cost 11.79M gas, about 0.0006 BNB (measured on the fork):

| Creation | Gas |
| --- | --- |
| ConfioMarketEscrow implementation | 3,552,368 |
| ConfioSmartAccountV2 implementation | 5,344,438 |
| ConfioSmartAccountFactory logic | 2,891,580 |

**Dry runs** (done 2026-11-25, no broadcast; each simulates from the sponsor's current nonce, 1567, so both
print the same predicted address `0x6195a6c4…2344`):

```sh
cd contracts/cusd_plus && forge build && forge script script/UpgradeConfioMarketEscrowDepositFrom.s.sol \
  --rpc-url https://bsc-dataseed.bnbchain.org --sender 0xf9f93Ba8ebf50515Ed2729Eb07657c8298cdfc9D

cd contracts/smart_account && forge build && \
SMART_ACCOUNT_FACTORY_ADDRESS=0x339094A17605B842e0b2fc01441204E67020f953 \
CONFIO_MARKET_ESCROW_ADDRESS=0x2DFDC1fB809322c12f54beFE8CC98E0d103a99Fd \
CRYPTO_SWAP_ROUTER_ADDRESS=0xA7C27684aB38eC369cB1F4474f279ea503dbF712 \
CONFIO_TOKEN_ADDRESS=0xF5765933764562A51e179F6AF2b19b7a3d506101 \
SMART_ACCOUNT_FEE_COLLECTOR_ADDRESS=0x1AE0ACB82bAb9F506188c49305953CB655A539CD \
V1_IMPLEMENTATION=0x8a20a0B3d2C0c6BED8BeB00bB6Bc7AE3c7ace44A \
forge script script/DeploySmartAccountV2.s.sol \
  --rpc-url https://bsc-dataseed.bnbchain.org --sender 0xf9f93Ba8ebf50515Ed2729Eb07657c8298cdfc9D
```

Both printed "Script ran successfully". The V2 script estimated 10.7M gas for its two creations and printed
the factory Safe call `0x4f1ef286…29b6eca9…` and `setTradePaused(true)` = `0x4158bb94…01`.

**Real run: choose one (Blocker 1).**

- **(Recommended) a KMS twin**, like `deploy_cusd_impl`: `manage.py deploy_hands_off_impls [--broadcast
  --yes-mainnet]` on prod. It would deploy the three artifacts at consecutive sponsor nonces, under the shared
  `bsc_sponsor_nonce_lock`, and record them in `.kms-local/kms_evm_multisig/hands_off_v2_deploy_bsc.json`.
  It would refuse artifacts whose source hashes differ from the checkout, and it would post-check the immutables
  and runtime bytecode against `out/`. This tool does not exist yet. Build it on a laptop first: `forge build` in
  `contracts/smart_account` and `contracts/cusd_plus`, then copy `out/ConfioSmartAccountV2.sol/`,
  `out/ConfioSmartAccountFactory.sol/` and `cusd_plus/out/ConfioMarketEscrow.sol/` to prod.
- **(Exception) forge with the KMS signer.** Only if the founder accepts a laptop broadcast with the relay
  paused (holding the nonce lock): add `--broadcast --aws` to the two commands above, with `AWS_KMS_KEY_ID` set
  to the sponsor key and `--sender 0xf9f9…dfc9D`. The scripts' own header forbids this.

After the deploy, verify on BscScan (`ETHERSCAN_API_KEY` from the git-crypted `.env`):

```sh
cd contracts/smart_account
forge verify-contract <V2_IMPL> ConfioSmartAccountV2 --chain 56 --compiler-version v0.8.26+commit.8a97fa7a \
  --num-of-optimizations 100 --via-ir --constructor-args $(cast abi-encode \
  "c(address,address,address,address,address,address,address,address,address,address,address,address,address)" \
  0x339094A17605B842e0b2fc01441204E67020f953 0x6101cC370635cF2c7f2725EaB010aC407A8d543F \
  0x3C29417eb4314155e63d4C7D4507852b87763Ed1 0x55d398326f99059fF775485246999027B3197955 \
  0xF5765933764562A51e179F6AF2b19b7a3d506101 0x40c8e134BCAf44EEf9e7D184846F36c9862329c3 \
  0xA7C27684aB38eC369cB1F4474f279ea503dbF712 0x1AE0ACB82bAb9F506188c49305953CB655A539CD \
  0x7130d2A12B9BCbFAe4f2634d864A1Ee1Ce3Ead9c 0x264990fbd0A4796A3E3d8E37C4d5F87a3aCa5Ebf \
  0x21cAef8A43163Eea865baeE23b9C2E327696A3bf 0x86896fEB19D8A607c3b11f2aF50A0f239Bd71CD0 \
  0x2DFDC1fB809322c12f54beFE8CC98E0d103a99Fd)
forge verify-contract <NEW_FACTORY_LOGIC> ConfioSmartAccountFactory --chain 56 \
  --compiler-version v0.8.26+commit.8a97fa7a --num-of-optimizations 100 --via-ir \
  --constructor-args $(cast abi-encode "c(address,address)" 0x3C29417eb4314155e63d4C7D4507852b87763Ed1 0x40c8e134BCAf44EEf9e7D184846F36c9862329c3)
cd ../cusd_plus
forge verify-contract <NEW_ESCROW_IMPL> ConfioMarketEscrow --chain 56 --compiler-version v0.8.26+commit.8a97fa7a --num-of-optimizations 200
```

After the Safe batch, re-link both proxies on BscScan (`verifyproxycontract`, as in DEPLOYMENT.md step 10).

## Step 2: the one Safe transaction (nonce 32)

One `execTransaction` to MultiSendCallOnly, **operation 1 (DELEGATECALL)**, value 0. It contains three inner
CALLs, each with msg.sender = Safe:

1. factory proxy `0x3390…f953`: `upgradeToAndCall(NEW_FACTORY_LOGIC, initializeV2(V2_IMPL))`.
   `initializeV2` is `reinitializer(2) onlyOwner`. It lists v1 as `implementationAt(0)` and makes v2 current.
2. factory proxy: `setTradePaused(true)` = `0x4158bb940000000000000000000000000000000000000000000000000000000000000001`.
3. escrow proxy `0x2DFD…99Fd`: `upgradeToAndCall(NEW_ESCROW_IMPL, setAccountFactory(0x3390…f953))`.
   `depositFrom` is never live with a zero factory.

Encode it with the real addresses. The function is pure, so no RPC is needed:

```sh
cd contracts/smart_account
forge script script/HandsOffV2ForkRehearsal.s.sol:HandsOffV2ForkRehearsal \
  --sig "batchCalldata(address,address,address)" <NEW_FACTORY_LOGIC> <V2_IMPL> <NEW_ESCROW_IMPL>
# returns c1, c2, c3 and multiSend (the Safe tx data)
```

The layout is `multiSend(bytes)` (`0x8d80ff0a`) over three packed `uint8 0 | address | uint256 0 | uint256 len | data`.
The fork run produced this (addresses are the **fork's**, shown only as the exact shape: 0x26b = 619 bytes of payload):

```
inner 1  0x4f1ef286 <logic 0x1c1793f4…c539> 0x40 0x24 29b6eca9 <v2 0xe7c7cf40…3ce7>
inner 2  0x4158bb94 …01
inner 3  0x4f1ef286 <escrow impl 0x9839eb00…ac47> 0x40 0x24 addc1a76 <factory 0x339094a1…f953>
data     0x8d80ff0a…0000026b 00 339094a1…f953 0…0 0…a4 4f1ef286… 00 339094a1…f953 0…0 0…24 4158bb94…01
         00 2dfdc1fb…99fd 0…0 0…a4 4f1ef286…
fork SafeTxHash (nonce 32, fork addresses) 0x5f4f3f86c437fa1acfb119e3bc2b0fccd704d7e2bb4b65cfee25d48c0aea9e92
```

**Proposal in the repo's Safe tool format** (`.kms-local/kms_evm_multisig/sign_safe_transaction.py`, the same
shape as `safe_tx_bsc_nonce27_fee_referral.json`). Write it once the real addresses exist:

```json
{"network": "bsc", "chain_id": 56, "safe": "0xF29A418744E793973BF4eEc676F8a30B2793b623",
 "to": "0x40A2aCCbd92BCA938b02010E17A5b8929b49130D", "value": 0, "operation": 1, "nonce": 32,
 "data": "<multiSend from batchCalldata(...)>", "description": "hands-off v2: factory v2 logic + initializeV2, tradePaused, escrow depositFrom + setAccountFactory"}
```

Sign and execute. The tool checks the local SafeTxHash against `Safe.getTransactionHash` on-chain and asks
`Type 'execute bsc' to submit:`. **Do not run it until the fork replay below passes with the real addresses.**

```sh
cd .kms-local/kms_evm_multisig
venv/bin/python sign_safe_transaction.py --network bsc --to 0x40A2aCCbd92BCA938b02010E17A5b8929b49130D \
  --data <multiSend> --operation 1 --nonce 32 --kms-signers 1 3 5 \
  --output safe_tx_bsc_nonce32_hands_off_v2_signed.json --execute
```

**Fork replay with the real addresses, before signing:** run the rehearsal (below), skipping step 2 of the
wrapper and exporting the real `NEW_FACTORY_LOGIC`, `V2_IMPL` and `NEW_ESCROW_IMPL` (they already exist on the
fork once deployed). Fork execution of the batch: 255,669 gas with pre-approved hashes. Three ECDSA signatures
add about 10k.

**Post-checks on mainnet** (`--sig "postChecks()"` against the public RPC is read-only and checks exactly these;
it needs `bob()` replaced by a real v1 owner for the last line):
- factory ERC-1967 slot = NEW_FACTORY_LOGIC, and `implementation()` = V2_IMPL;
- `implementationCount()` = 2, `implementationAt(0)` = `0x8a20…e44A`, `implementationAt(1)` = V2_IMPL;
- `tradePaused()` true;
- escrow ERC-1967 slot = NEW_ESCROW_IMPL, and `accountFactory()` = `0x3390…f953`;
- owners are still the Safe, and Safe nonce is 33.

## Step 3: server, canary, unpause

1. Add `SMART_ACCOUNT_V2_IMPLEMENTATION_ADDRESS` to `config/settings.py` (Blocker 2). Set it to V2_IMPL in
   `.env.mainnet`. Hands-off stays stopped on chain while `tradePaused` is true.
2. Canary on a founder account: migrate it (one Face), then set the cap.
3. Safe nonce 33: `factory.setTradePaused(false)`, operation 0, to `0x339094A17605B842e0b2fc01441204E67020f953`,
   data `0x4158bb940000000000000000000000000000000000000000000000000000000000000000`. Fork: 85,789 gas.
4. Record addresses, txs and blocks in `contracts/cusd_plus/DEPLOYMENT.md`.

## Fork rehearsal

Tools (new, fork-only, refuse any non-local RPC):
`contracts/smart_account/script/HandsOffV2ForkRehearsal.s.sol`,
`contracts/smart_account/script/run_handsoff_fork_rehearsal.sh` and
`contracts/smart_account/script/fork_rpc_proxy.py`. publicnode answers unknown tx-hash lookups with an
"archive" 403, which breaks anvil's receipt fallback. The proxy answers those lookups with null.

```sh
python3 -I contracts/smart_account/script/fork_rpc_proxy.py https://bsc-rpc.publicnode.com 8598 &
anvil --fork-url http://127.0.0.1:8598 --port 8547 --auto-impersonate --chain-id 56 --retries 10 &
OUT=/tmp/handsoff contracts/smart_account/script/run_handsoff_fork_rehearsal.sh        # Trade rule in cUSD
USE_PLUS=1 OUT=/tmp/handsoff-plus contracts/smart_account/script/run_handsoff_fork_rehearsal.sh  # cUSD+ (fresh anvil)
```

Public nodes keep roughly 15 minutes of state, so the whole run (about 3 minutes) must start right after anvil.

What it does and what passed (both variants):

1. **Before the upgrade:** two test owners open v1 accounts on the real factory (v1 clones). The sponsor mints
   cUSD into them. BTCB and, with `USE_PLUS`, cUSD+ come from a Binance wallet on the fork only. Both subscribe
   monthly.
2. **Deploy as the impersonated sponsor**, with the real scripts unmodified: `UpgradeConfioMarketEscrowDepositFrom`
   and `DeploySmartAccountV2`. All script checks pass.
3. **Safe batch** via the real Safe: owners 1, 3 and 5 `approveHash`, the sponsor submits `execTransaction`
   (MultiSendCallOnly, DELEGATECALL).
4. **Storage diff** of 64 values before and after. Getters cover factory owner, flags, fees, windows, accountOf,
   isAccount and generationOf; escrow owner, signer, arbiter, windows, token limits, open principal, fees and balance.
   Raw slots cover factory 0–13 and escrow 0–8, plus the ERC-1967, Ownable, Ownable2Step, Pausable and
   Initializable slots. **Only the expected values changed:**
   - factory slot 0 (`implementation`): v1 → v2;
   - factory slot 12: `0x…0100` (`tradePaused` packed after `cardPaused`);
   - factory slot 13: `2` (`_implementations` length);
   - factory ERC-1967 slot: new logic;
   - factory Initializable: 1 → 2;
   - escrow slot 7 (`accountFactory`): the factory;
   - escrow ERC-1967 slot: new implementation;
   - Safe nonce: 32 → 33.

   Everything else is identical, including the v1 accounts' `accountOf` and `isAccount`, open principal and token limits.
5. **postChecks:** OK.
6. **v1 still works:** owner reads, then `withdraw(cUSD, 1)` from the v1 account (76,983 gas).
   **A new account is v2:** `createAccount` → `implementationOf` = v2, `VERSION()` = 2 (169,818 gas).
7. **Unpause** (Safe nonce 33). Then, **fork only**, the Safe rotates the escrow `orderSigner` to a throwaway key
   (Safe nonce 34), so that a `depositFrom` authorization can be signed. On mainnet the KMS order signer does this.
8. **Migration batch:** the owner's EOA is set to the real ConfioBatchDelegate's 7702 designator, signed once
   with the owner's key, and the sponsor submits `execute`. The batch is cancelSubscription → `factory.migrate()`
   → withdrawAll(6 tokens) → transfer each non-zero token to the new account → createRule(Trade, cap
   US$1,000/week) → createRule(Purchase, cUSD, escrow, US$200). Result: the new account is at the predicted
   address and runs v2. The old account stays `isAccount` and is empty. The new account holds every amount.
   The subscription is carried (same `paidUntil`, status Active).
9. **relayTrade (sponsor):** buy BTCB for US$20 through ConfioSwapRouter. After the 60 s gap, sell all BTCB
   back to dollars. After another gap, buy XAUT for US$10.
10. **relayPurchase:** US$25 cUSD → `escrow.depositFrom`. The owner is the buyer, `refundToOf` is the account,
    and exactly US$25 left the account. After shipBy (+4 days) the owner calls `reclaim` and the US$25 return to
    the account (69,211 gas).

### Gas (receipts, anvil fork)

| Transaction | Trade rule in cUSD | Trade rule in cUSD+ |
| --- | --- | --- |
| relayTrade, BTCB buy (swap) | 410,598 | 747,973 |
| relayTrade, BTCB sell (swap) | 409,619 | 792,601 |
| relayTrade, XAUT buy (swap) | 394,487 | 735,121 |
| relayTrade, GM stock buy/sell | not measurable on a fork (Ondo attestation) | — |
| relayPurchase (→ depositFrom) | 337,943 | 337,967 |
| `factory.migrate()` (inner call, from trace) | 190,412 | — |
| Migration batch (7 calls, 2 tokens moved / 8 calls, 3 tokens) | 646,041 | 676,623 |
| createAccount (v2) | 169,818 | |
| Safe batch execTransaction | 255,669 | |
| Safe setTradePaused(false) | 85,789 | |

Each extra token moved in a migration costs about 25–30k. The cUSD+ legs cost more because they redeem
cUSD+ to USDT through the vault (USDY) before swapping. Server gas limits for `relayTrade` must allow about
800k on the cUSD+ path. `CUSD_PLUS_7702_GAS_LIMIT` (2.5M) covers a migration batch with all six tokens and the
rules.

## Deployed on BSC mainnet (2026-11-25)

| What | Address / tx |
|---|---|
| ConfioSmartAccountV2 (implementation) | `0x0b3DAf407AF2cF5bC7a1475bF44bD3952533cdF7` (24,236 bytes; `VERSION()` 2) |
| ConfioSmartAccountFactory (new logic) | `0xD3F24fd9822B42a691379Fe47886b9Fb971cFea1` |
| ConfioMarketEscrow (new logic) | `0xf729d76Dd16EaBCCA2461390D15768ae627D493A` |
| Deployer | KMS sponsor `0xf9f93Ba8ebf50515Ed2729Eb07657c8298cdfc9D` (`manage.py deploy_hands_off_impls --broadcast --yes-mainnet`, ≈ 0.0007 BNB) |
| Safe batch (nonce 32) | tx `0x8195a04b564bae92b9886c906db806139d740c0bfa2cc3bb2ab0e64ae1bf1e01`, block 135679815, 260,248 gas; SafeTxHash `0x3e64091ff96ffe0790ce6f18669cf3fd5d2a091c5a7fe9d8133e674b8b726ebc` |

Fork replay with these exact addresses passed before signing. Mainnet post-checks after the batch: factory ERC-1967
slot = new logic; `implementation()` = v2; `implementationAt(0)` = v1 `0x8a20…e44A`, `implementationAt(1)` = v2;
`tradePaused()` true; owners still the Safe; escrow slot = new logic, `accountFactory()` = the factory; Safe nonce 33.

Server: `SMART_ACCOUNT_V2_IMPLEMENTATION_ADDRESS` set in `.env.mainnet` (hands-off routing on; while `tradePaused`
a v2 account falls back to the signed card, v1 subscribers get the migration offer). Still to do: BscScan
verification and proxy re-link; a separate KMS key for the escrow's order signer (audit M2) before hands-off
Comprar; canary migration of a founder account; then Safe nonce 33 `setTradePaused(false)`.

## Live (2026-11-25)

- Canary: the founder's account migrated v1 `0x3df1…e7d8` → v2 `0x59bDD1dC51DCb229fCc96fe1950DB8C8Bfc63e9c`
  (tx `0x8c14e7c1c58ae7204ce8d1dbe8731fd89bb75fdc7ffc62ccb497bce1c4a285fb`, block 135687314, 588,332 gas): every
  token moved, paidUntil carried, buy rule re-created, Trade rule US$250/week. It exposed two server bugs, fixed
  before go-live: the sponsor's second (policy) 4-call cap (a3b0c9bb7) and a reconcile ordering deadlock — the new
  account's Subscribed is logged before AccountCreated (a72052016).
- ConfioPurchaseSpender `0xD0ea8Ec3a6F3AD49f13a18Ce801C9594311A32Ca` (operator = KMS sponsor, EOA, sponsor on both
  vaults; tx `0x35d51c06887514d357127ea2fd6bc252019520317411c3d06e0a596ab68729a0`, block 135691060,
  `manage.py deploy_purchase_spender`).
- Safe nonce 33 (founder's decision: unpause and go live with everything): one MultiSend with
  `setTradePaused(false)` + `setCardSpender(0xD0ea…32Ca, true)`, SafeTxHash
  `0xc9405595b6c9221bc4fa0fbe51ed78780da06e6b722992e8df9c55db498b54f3`. After: `tradePaused` false,
  `isCardSpender(spender)` true, `cardPaused` false, Safe nonce 34.
- Server: `SMART_ACCOUNT_PURCHASE_SPENDER_ADDRESS` and `SMART_ACCOUNT_CARD_RULES_ENABLED=True` set; hands-off trades,
  hands-off Comprar and account-paid store purchases are live; the offer shows the hands-off wording.
- Escrow orderSigner moved to its own KMS key (audit M2): `alias/confio-mainnet-escrow-order-signer-evm-secp256k1`
  (eu-central-2; only the prod role ConfioS3PresignRole may sign; Julian's user may not sign, delete or disable),
  address `0x6D611FDD68290f68F7e7089F5c68f607304E9F3C`. Safe nonce 34 `escrow.setOrderSigner` (SafeTxHash
  `0xcd79b864b3566133365148edc948f6c2c6e1227ba48271e0b683e86c9d3cc9ea`); server `MARKETPLACE_ORDER_SIGNER_*` set
  (748a06c71). The arbiter and Pay invoices stay on the sponsor. Safe nonce now 35.
- BscScan: ConfioSmartAccountV2, the factory logic, the escrow logic and ConfioPurchaseSpender verified (forge
  verify-contract, Pass - Verified); the factory and escrow proxies re-linked to their new implementations
  (verifyproxycontract). Nothing open.
