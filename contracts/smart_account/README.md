# Cuenta inteligente (BSC)

The contracts behind "Cuenta inteligente": one smart-contract account per
user, owned by the user's personal wallet, with a subscription fee taken from
inside it, rules the owner stores on-chain (automation) and one beneficiary
who can take ownership after a long challenge window (inheritance).

Specification: [`docs/designs/cuenta-inteligente-spec.md`](../../docs/designs/cuenta-inteligente-spec.md),
sections 4 to 6. The ABI the backend and the app build against is frozen in
[`interfaces/`](interfaces/).

| Contract | What it is |
|---|---|
| `ConfioSmartAccount` | The per-user account. Deployed as an EIP-1167 clone. Immutable: no upgrade function, no `DELEGATECALL`, `CALLCODE` or `SELFDESTRUCT` in the implementation |
| `ConfioSmartAccountFactory` | Clones one account per owner at a CREATE2 address and holds the global settings. UUPS, `Ownable2Step`, owned by the Confío Safe, renounce disabled |
| `ConfioSmartAccountFeeCollector` | Receives the fee (cUSD, and cUSD+ shares in kind). No owner, no upgrade; anyone sweeps, only the immutable treasury receives |

One existing contract changes: `../cusd_plus/CusdVault.sol` gains an appended
`isSmartAccountFactory` mapping so that an account created by a recognised
factory can arm the fee referral (spec decision 32).

## How it holds together

- **Roles are decided by `msg.sender` only.** Owner and beneficiary are
  wallets. The relayer is a cUSD+ sponsor that is also `tx.origin`; a sponsor
  that is a contract (the routers are) can never act as relayer.
- **Every owner function cancels a pending claim**, with a cooldown. No
  relayer or permissionless function changes claim state.
- **The account does not trust the factory.** The factory is upgradeable and
  an account is not, so each limit is a constant of the account (maximum fee
  US$29.99 / US$299.99, notice floor 3 days, cooldown 1 to 90 days, challenge
  window 90 to 1,825 days) and what the factory returns is clamped. Factory
  reads are gas-capped static calls whose failure is a value, never a revert,
  so `withdraw`, `withdrawAll`, `returnAsset`, `cancelClaim` and the claim
  functions work even if every factory call fails. The inherited-withdraw
  destination "the new owner's own account" is computed by the account from
  the factory address, its own implementation address and the owner (the
  CREATE2 clone address), not read from the factory.
- **Designation and acceptance need a relayer approval** (decision 26,
  invariant 18). `setBeneficiary(addr, window)` requires a live
  `factory.designationApprovedUntil(account, keccak256(abi.encode(addr, window)))`
  and `acceptBeneficiary()` a live
  `factory.acceptanceApprovedUntil(account, beneficiary)`. Only the relayer
  (a cUSD+ sponsor that is also `tx.origin`) can record them, with
  `factory.approveDesignation(account, beneficiary, window)` and
  `factory.approveAcceptance(account, beneficiary)`, for an account of that
  factory, while the relayer is not paused; each lasts one hour
  (`APPROVAL_TTL`). An unreadable factory refuses both steps. The origin of
  the owner's or beneficiary's call no longer matters: a self-sent or
  forwarded call without an approval fails.
- **Fixed targets, measured deltas, no allowance left.** The account calls
  only the two vaults, the two routers and (for CONFIO, once the Safe has set
  it and the account has latched it) one sale venue. The traded pair is read
  from the router calldata, not taken from the caller's arguments.
- **A forced sale is one atomic operation** that sells and collects the fee.
  Bitcoin and gold are checked against Chainlink feeds fixed in the
  implementation; a stock's price is the Ondo-signed quote the stock router
  settles at.

The eleven addresses of the implementation other than `FACTORY` are private
immutables: public getters for them would push the implementation over the
24 KB code limit. They are the constructor arguments of the verified
implementation.

## Test

```sh
forge build --sizes
forge test
forge test --match-path "test/*.fork.t.sol" \
  --fork-url https://bsc-dataseed.bnbchain.org -vv
```

The package reuses `../ondo_stocks/node_modules` and `../ondo_stocks/lib`.
Run `npm install` and `npm run setup:forge-std` there first.

The unit tests run against the real `CusdVault`, `CusdPlusVault`,
`ConfioStockRouter` and `ConfioSwapRouter` sources; only what is outside
Confío is mocked (Ondo's oracle, Instant Manager and GM, PancakeSwap,
Chainlink). The test files follow the spec's test list (section 10.2):
`Billing`, `Assets`, `Rules`, `Inheritance`, `Property` (invariants 1, 2, 3,
8, 9 and 14 after every call of fuzzed sequences) and `Factory`. The
`Inheritance` tests also drive the real `../cusd_plus/ConfioBatchDelegate.sol`
(etched at the owner's address, as a 7702 delegation) so `msg.sender` is the
owner's EOA.

The fork suite runs against the live vaults, routers, PancakeSwap pools and
feeds. It skips (passes as a no-op) without `--fork-url`. On the fork it:

- upgrades the live cUSD proxy to the candidate `CusdVault` as the Safe and
  checks that its state is unchanged;
- replaces Ondo's GM token manager with a stand-in for the stock tests,
  because an Ondo-signed quote cannot be produced in a test (the stock router
  and the vaults in those tests are the live ones);
- re-stamps feed rounds after a time warp (a forced sale needs 37 days to
  pass, and both the Chainlink feeds and the USDT feed Ondo reads are then
  stale by construction). The answers are the live ones.

The `CusdVault` change has its own tests in
`../cusd_plus/test/CusdVaultSmartAccountReferral.t.sol`; run the whole
`../cusd_plus` suite after touching it.

## Deploy

Order matters: the account's `FACTORY` is an immutable, so the implementation
is deployed against the factory proxy's predicted address, and the factory's
`initialize` refuses an implementation that names another factory. The
factory logic takes the cUSD+ vault and the stock router as constructor
immutables (the relayer check and the CONFIO venue check); a factory upgrade
must pass the same two addresses.

**Accounts are immutable.** Every address the implementation is built with,
the CONFIO token included, is fixed for every account it ever clones. Deploy
only after the CONFIO token is final (it was re-issued once, v2). The script
refuses to run unless `EXPECTED_CONFIO_TOKEN` (required, no default) equals
the token it is about to use (`CONFIO_TOKEN_ADDRESS`, or the constant in the
script).

1. **Before anything.** Match the two feed addresses in
   `script/DeploySmartAccount.s.sol` against Chainlink's published BSC list
   (spec 9.2, C2). They become constants of every account. Confirm the swap
   router's deployed bytecode against the source (spec X1) and that CONFIO,
   BTCB and XAUt move to and from a contract without a tax (X2, X3).
2. **cUSD upgrade (Safe), its own audit pass first.** Deploy the new
   `CusdVault` implementation and have the Safe call
   `cUSD.upgradeToAndCall(newImplementation, "")`. Storage is append-only:
   `isSmartAccountFactory` takes slot 8, after `batchDelegate` (slot 7).
   Diff `forge inspect CusdVault storage-layout` against the live
   implementation before signing.
3. **Deploy the package** on the production host, by the documented deploy
   path, never from a laptop (the same rule as `../crypto_swap/README.md`:
   the deploy takes the relay's shared sponsor nonce lock, which a laptop
   does not hold).
   `script/DeploySmartAccount.s.sol` deploys the collector, the
   implementation, the factory logic and the factory proxy, with ownership
   to the Safe, prices US$14.99 / US$149.99, windows 90 / 180 / 365 days,
   cooldown 30 days, notice 7 days and `inheritanceEnabled = false`. It
   needs `CRYPTO_SWAP_ROUTER_ADDRESS` and `EXPECTED_CONFIO_TOKEN` in the
   environment. A management
   command that wraps it with the sponsor nonce lock, like
   `deploy_swap_router`, is still to be written.
4. **Safe:** `cUSD.setSmartAccountFactory(factory, true)`.
5. **Verify** the collector, the implementation, the factory logic and the
   proxy on BscScan, and match the deployed bytecode against this source.
6. **Settings:** the factory address, then `SMART_ACCOUNT_ENABLED` for the
   canary list (spec 10.1, step 1).
7. **Later, Safe, one-way:** `factory.enableInheritance()` (rollout step 2),
   and `factory.setConfioSale(venue, priceRef)` once CONFIO has a market
   (spec 5.5; it can be set once and never changed). It refuses the stock
   router or zero as venue, and a price reference that does not answer
   `decimals()` and `latestRoundData()` with a positive price updated within
   26 hours.

Sponsor requirements:

- **None for the factory, the account or the collector.** No
  `setSponsor(account, ...)` is needed, now or per user. An account mints
  only to itself (`recipient == msg.sender`), and its wrap, unwrap, router
  and referral calls pass on the relayer being `tx.origin`.
- **The relayer key must be a sponsor in both cUSD+ and cUSD** (it is, as the
  KMS sponsor). The account recognises the relayer through cUSD+'s set;
  `mintWithFee` and `armReferral` check cUSD's own.
- **Both routers must stay sponsors of cUSD+, and the swap router of cUSD**,
  as they are today.
- **Owner and beneficiary calls** reach the account through a sponsored 7702
  batch. `initiateClaim`, `executeClaim`, `withdraw` and `cancelClaim` need
  nothing more.
- **The backend relayer calls the factory's approval functions.** Right after
  the server's designation checks (spec 6.1) and before relaying the owner's
  `setBeneficiary(addr, window)`, the relayer key sends
  `factory.approveDesignation(account, addr, window)`; after the acceptance
  checks and before relaying `acceptBeneficiary()`, it sends
  `factory.approveAcceptance(account, beneficiary)`. Each is its own
  transaction from the relayer key (it must be `tx.origin`), valid for one
  hour, and refused while `relayerPaused` is set.

## Things the contract cannot fix

- Ondo's Instant Manager refuses a subscription or redemption under US$1.
  USDT dust below that cannot be converted into cUSD+ by `convertUsdt`
  (cUSD has no minimum), and a cUSD+ payout or converted send under US$1
  reverts.
- A payment rule's USDT goes to the address the relayer names for that run
  (spec C7). It is the one exit whose destination the contract does not bind.
- The Safe can upgrade or pause the vaults and routers the account calls.
  The limits above bound the relayer key, not the Safe.
