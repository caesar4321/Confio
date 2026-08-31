# cUSD conversion fee system

Status: approved engineering design

Date: 2026-08-29

## Outcome

Confío charges one symmetric 0.9% conversion fee whenever value crosses between external BSC-USDT and the Confío dollar system. The origin and destination rail do not affect pricing.

```text
External perimeter

USDT -- 0.9% --> cUSD -- 0% --> cUSD+
USDT <-- 0.9% -- cUSD <-- 0% -- cUSD+

Inside Confío

cUSD send                         0%
cUSD+ send                        0%
cUSD <-> cUSD+                    0% (sponsor required)
Confío Pay                        0.9% (existing payment fee)
```

Koywe, Infinia, Binance, MetaMask, an exchange withdrawal, and any other USDT source use the same contract path and fee. Provenance is metadata only. It never changes pricing.

The Ondo Stock Router is a deliberately separate product rail. Confío app and
server stock trades always use sponsored cUSD+ settlement and pay only the
router's fixed 0.3% trading fee; the vault grants that one configured router
fee-free cUSD+ settlement. The router also exposes a permissionless
stock-to-raw-USDT redemption with the same 0.3% fee for an advanced
crypto-native caller using their own contract tooling. Confío never prepares,
sponsors, submits, or exposes that raw-USDT selector in its client or server.

## Old application behavior

Old builds remain fully operational during the store-review and adoption window. They pay the same 0.9% conversion fee as new builds; there is no temporary fee waiver and no minimum-build block on Top Up, Sell, automatic conversion, or normal withdrawal.

The current Top Up and Sell screens hardcode `Comisión de Confío — Gratis`. During this short compatibility window they therefore show a stale fee label even though the contract deducts 0.9%. Top Up still displays and credits the contract-produced net amount. For Sell/Withdraw, the server treats the old client's entered amount as the gross Confío-dollar debit, computes the authoritative fee and net with the contract preview, creates the provider order for that net amount, and prepares one atomic redemption-and-funding operation for exactly the provider order amount. This prevents the old exact-funding flow from underfunding or reverting.

The stale `Gratis` label and any gross-based fiat estimate are an explicitly accepted, temporary disclosure defect while Apple review is pending. Monitoring segments these executions by app build. Once the fee-capable build is available, the server may request or require the update according to product policy, but store approval is not a prerequisite for activating the contract fee.

Old Emergency Exit remains permissionless and pays the contract fee. The destination receives the net USDT amount. The old Emergency Exit does not show the new fee row, preserving server-independent access at the same conversion economics.

An old build does not know the new cUSD proxy address. The server therefore records the latest fee-capable build observed for each account/device. Sends to a recipient that has not registered a fee-capable build settle in the existing cUSD+ token, regardless of the recipient's current product eligibility. This is permitted by the selected open-secondary-transfer policy and preserves the old app's display, send, and Emergency Exit paths. After an ineligible recipient updates, a sponsor unwraps that cUSD+ to cUSD for free.

React Native sends `X-Confio-Platform` and `X-Confio-Build` on every API request. Django uses these headers for compatibility response shaping, amount semantics, disclosure monitoring, and eventual update policy—not to waive the fee or reject legacy conversion requests. Missing headers are treated as an old build.

## Contract topology

```text
                           +------------------------+
                           | Confio cUSD+ proxy     |
                           | existing address       |
                           | existing shares/USDY   |
                           +-----------+------------+
                                       |
                                       | calls only; cUSD never calls cUSD+
                                       v
USDT <-------------------->+------------------------+
                           | Confio cUSD proxy      |
                           | new UUPS proxy         |
                           | USDT reserve + fees    |
                           +------------------------+
```

Both contracts are UUPS-upgradeable and owned by the Safe. cUSD+ is upgraded in place. Its proxy address, balances, share supply, `pPlus`, oracle state, and USDY backing stay unchanged. cUSD is deployed as a new proxy.

The dependency direction is cUSD+ to cUSD only. cUSD stores the registered savings-vault address/role but does not import or call a cUSD+ interface.

## Authorization matrix

| Operation | Fee | Required authority |
|---|---:|---|
| USDT to cUSD | 0.9% | authorized sponsor |
| USDT to cUSD+ | 0.9% | authorized sponsor plus registered cUSD+ path |
| cUSD to cUSD+ | 0% | authorized sponsor plus registered cUSD+ path |
| cUSD+ to cUSD | 0% | authorized sponsor plus registered cUSD+ path |
| cUSD to USDT | 0.9% | permissionless holder exit |
| cUSD+ to USDT | 0.9% | permissionless holder exit through cUSD fee accounting |
| cUSD/cUSD+ transfer | 0% | token holder; normal app execution remains sponsored |

There is no permissionless fee-free conversion. Sponsor failure cannot prevent a fee-bearing USDT exit, but the selected global contract pause can.

The Stock Router exception does not make a general cUSD/cUSD+ conversion
fee-free. Its vault adapters require the caller to be both the single configured
`stockRouter` and an authorized sponsor. App stock buys and sells are themselves
sponsor-origin-gated. Only the router's stock-to-raw-USDT selector is
permissionless, and it charges the router's fixed 30 bps fee.

## cUSD proxy

### State

- immutable implementation wiring: BSC-USDT;
- `feeBps`, initialized to 90;
- `MAX_FEE_BPS = 90`;
- `accruedEntryFees` and `accruedExitFees` in USDT wei;
- authorized sponsor set;
- registered cUSD+ savings role/address;
- global pause;
- UUPS owner/Safe state.

The Safe may lower `feeBps` to any value from 0 through 90. Raising it above 90 requires a reviewed implementation upgrade. V1 has no per-user, per-provider, volume, or attestation exemption.

### Fee math

```text
fee = ceil(gross * feeBps / 10_000)
net = gross - fee
```

The contract exposes:

- `feeFor(gross)`;
- `previewMint(gross) -> (fee, netCusd)`;
- `previewRedeem(gross) -> (fee, netUsdt)`.

These views are authoritative for binding quotes. Python and TypeScript do not independently decide monetary results.

### Reserve accounting

Entry pulls gross USDT and mints net cUSD. Exit burns gross cUSD and transfers net USDT. The retained difference increments the appropriate accrued-fee counter.

After every monetary state change:

```text
USDT.balanceOf(cUSD) - accruedEntryFees - accruedExitFees >= cUSD.totalSupply()
```

The Safe may collect no more than the explicit accrued-fee sum. Donations and operational deposits are not fee revenue and cannot be inferred as such.

### Public and privileged methods

The exact Solidity names may follow repository conventions, but the surfaces are distinct:

- sponsor-only fee-bearing USDT mint;
- permissionless fee-bearing USDT redemption;
- sponsor-and-savings-only fee-free mint/redeem used by cUSD+ wrapping;
- sponsor-and-savings-only fee-bearing direct-entry settlement used by legacy/direct USDT to cUSD+ without temporary cUSD supply;
- savings-only fee-bearing direct-exit settlement used by permissionless cUSD+ redemption;
- fee collection, sponsor rotation, savings-vault rotation, fee lowering, pause/unpause, and UUPS authorization.

The optimized savings settlement methods preserve the same fee and reserve invariant while avoiding a temporary cUSD mint followed immediately by a burn.

The approved pause is global: mint, redeem, transfer, fee-free internal conversion, and savings settlement all stop. Product/legal text must therefore describe Emergency Exit as server-independent, not governance-independent.

## cUSD+ in-place upgrade

The upgrade retains the current storage layout and existing compatibility reads. It adds cUSD wiring and the following canonical behavior:

- `wrapCusd`: sponsor-authorized, fee-free cUSD to cUSD+;
- `unwrapToCusd`: sponsor-authorized, fee-free cUSD+ to cUSD;
- legacy `subscribeAndMint`: retained, sponsor-authorized, and routed through cUSD's 0.9% entry accounting;
- legacy `redeemToUsdt`: retained and permissionless, routed through cUSD's 0.9% exit accounting;
- existing `balanceOf`, `pPlus`, `lastOraclePrice`, accrual, surplus, freeze, pause, and upgrade surfaces remain compatible.

Primary wrapping/minting uses the existing Confío eligibility decision. Secondary ERC-20 transfers remain open. The app routes cross-jurisdiction friend sends through cUSD, but the token does not add a recipient allowlist.

No USDY or share migration is required. Existing cUSD+ continues to hold the existing USDY backing.

## Ondo Stock Router settlement

- `buyWithSavings`: sponsored Confío execution, fee-free cUSD+ redemption at
  the vault boundary, then a fixed 30 bps Stock Router fee;
- `sellToSavings`: sponsored Confío execution, fixed 30 bps Stock Router fee,
  then fee-free cUSD+ minting at the vault boundary;
- `sellToUsdt`: permissionless contract-only stock redemption to raw USDT with
  the same fixed 30 bps fee. This is for an advanced crypto-native caller and is
  absent from the Confío app, GraphQL API, and sponsor selector allowlist.

The first two functions are the only stock paths used by the Confío platform.
The third does not depend on the Confío sponsor, although the caller must still
supply inputs accepted by the external GM settlement contracts. Global owner
pause remains applicable to all three paths.

## User flows

### External or ramp entry

```text
USDT arrives at user's BSC address
  -> chain scanner records receipt
  -> app foreground requests binding preparation
  -> server applies legacy/new response shaping and checks eligibility
  -> contract preview returns gross / 0.9% / net
  -> user locally signs exact sponsored intent
  -> eligible: direct fee-bearing savings entry -> USDY -> cUSD+
  -> ineligible: fee-bearing cUSD mint
  -> receipt/event reconciliation closes Conversion row
```

Ramp and direct on-chain entry are identical after USDT arrival. `source` remains useful for analytics and support but never enters fee logic.

### Exit to an external wallet or ramp

```text
User chooses gross Confío dollars to convert
  -> server reads previewRedeem(gross)
  -> UI shows gross, 0.9% fee, and net USDT
  -> ramp provider order is created for NET USDT
  -> cUSD: burn gross and pay net to destination
  -> cUSD+: redeem USDY, apply cUSD exit accounting, pay net
  -> contract event and provider order reconcile against the same net
```

This removes the current pattern where the client creates and transfers the same gross amount. The provider must expect the contract-previewed net settlement amount.

### Friend sends

```text
eligible -> eligible       cUSD+ transfer                        0%
ineligible -> ineligible   cUSD transfer                         0%
eligible -> ineligible     cUSD+ unwrap -> cUSD transfer         0%
ineligible -> eligible     cUSD transfer; recipient auto-wraps   0%
any -> outdated recipient  cUSD+ compatibility delivery         0%
```

Fee-free wrapping/unwrapping remains sponsor-authorized. The receiver's automatic wrap can occur on the next foreground. The home balance sums cUSD and cUSD+ so the user does not manage two balances. An outdated-recipient compatibility delivery is normalized on that recipient's first fee-capable foreground: eligible users keep cUSD+; ineligible users unwrap to cUSD.

### Dust and automatic conversion

Raw USDT is a transient settlement asset, not a selectable balance. The UI includes pending raw USDT in the single dollar total.

Automatic conversion waits until sweepable USDT reaches $1, then converts the aggregate once. This prevents sponsor-gas griefing and respects the Ondo minimum. Every foreground retries. Emergency Exit can transfer still-pending USDT directly.

## Binding quote and sponsored execution

Fee-bearing and fee-free conversion actions use domain-specific prepare/submit APIs.

Prepare:

1. authenticate the active account from JWT;
2. detect platform/build for backward-compatible amount and disclosure shaping without blocking legacy builds;
3. read the appropriate on-chain preview;
4. evaluate eligibility and choose cUSD or cUSD+ destination;
5. reserve sweepable funds/idempotency scope;
6. persist gross, fee, net, assets, calls, intent ID, and expiry;
7. return the exact calls and disclosure fields.

Submit:

1. recover the local signer and bind it to the active account address;
2. require a byte-for-byte match with the prepared calls;
3. re-read mutable safety state where required;
4. atomically claim the durable sponsored-batch idempotency record;
5. broadcast through the KMS sponsor;
6. classify executed/reverted/noop/unknown without double submission;
7. reconcile contract events into the Conversion ledger.

The generic sponsored validator does not gain unrestricted new cUSD selectors. New fee operations must belong to a stored domain intent.

## Ledger and asset identity

Internal assets use chain-qualified identifiers:

- `CUSD_ALGO`;
- `USDC_ALGO`;
- `USDT_BSC`;
- `CUSD_BSC`;
- `CUSD_PLUS_BSC`.

Presentation labels remain localized and simple.

`Conversion` is the canonical perimeter ledger. It records exact 18-decimal gross, fee, and net amounts; fee bps; source/destination assets; entry/exit direction; source metadata; prepared intent; execution hash; and observed contract event. Ramp transactions link to the conversion. Direct on-chain conversions create the same record.

Existing six-decimal fields remain compatibility projections until all readers move to the exact fields.

## Single coordinated rollout

1. Land contract, server, client, Emergency Exit, ledger migration, documentation, and monitoring code behind disabled server configuration.
2. Submit the fee-capable mobile builds for store review; approval is not a dependency for the backend/contract activation because legacy amount semantics are supported server-side.
3. Deploy the cUSD implementation and proxy globally paused with fee set to 90 bps.
4. Deploy the storage-compatible cUSD+ implementation and the updated Stock
   Router implementation for its existing proxy.
5. Execute one reviewed Safe rollout window:
   - pause the existing cUSD+ proxy;
   - upgrade cUSD+ with its cUSD wiring initializer;
   - upgrade the existing Stock Router proxy without replacing its address or
     state;
   - register sponsors and cUSD's cUSD+ savings role/address;
   - register the existing Stock Router proxy as both cUSD+ sponsor and the
     single configured stock router;
   - update backend contract addresses and selector policy;
   - enable build-aware legacy/new conversion preparation without blocking legacy builds;
   - run on-chain post-upgrade assertions and canaries;
   - unpause cUSD and cUSD+;
   - enable automatic conversion and ramp entry/exit.
6. Monitor reverts, quote-versus-event differences, accrued-fee invariants, legacy stale-disclosure volume, sponsor gas, and provider underfunds. After store approval and adequate propagation, end the temporary disclosure window through the chosen update policy.

If any canary fails before unpause, leave both dollar contracts paused and restore the prior cUSD+ implementation/configuration through the reviewed Safe rollback transaction.

## Failure modes

| Failure | Handling | User result | Required test |
|---|---|---|---|
| Old build starts normal conversion | server applies legacy gross-input semantics and contract preview; fee remains 90 bps | conversion completes; stale `Gratis` disclosure is temporarily accepted | Django + Jest + ramp integration |
| New sender targets an outdated recipient | server routes the friend transfer as cUSD+ | old app can display/send/emergency-exit; later app normalizes | Django + Jest + E2E |
| Contract/server fee mismatch | binding preview and exact stored intent | preparation fails closed | vector + integration |
| Fee changes after quote | submit expiry/state recheck; re-prepare | refreshed quote required | contract/server integration |
| Ramp provider expects gross instead of net | order creation uses previewed net | no order until amounts agree | Koywe/Infinia integration |
| Sponsor times out after broadcast | durable batch plus outcome-unknown classification | user told to wait; no duplicate | Django + Jest |
| App closes after USDT arrival | chain receipt and foreground resume | conversion resumes once | Django + Jest |
| Dust spam | aggregate below $1 without sponsorship | pending amount remains in total | task + client test |
| cUSD global pause | every cUSD movement/conversion reverts | clear paused state; Emergency Exit can only fall back to raw-token transfer | Foundry + Jest |
| Ondo/IM failure during cUSD+ exit | transaction reverts atomically; Emergency Exit raw-share fallback | funds remain cUSD+ or move as raw shares | fork + Jest |
| Storage layout mismatch | upgrade rehearsal fails before production | deployment blocked | Foundry storage + fork |
| Fee withdrawal exceeds accrual | contract reverts | backing unaffected | invariant/fuzz |
| cUSD+ privileged method called without sponsor | contract reverts | no fee-free bypass | Foundry fuzz |

## Test plan

### Foundry

- Unit-test every public and privileged cUSD branch, pause branch, authorization branch, zero/boundary input, min-output failure, fee-rate update, fee collection, and event.
- Fuzz gross amounts across the full uint range accepted by the contract and assert ceil rounding and reserve invariants.
- Stateful invariant: reserve excluding accrued fees always covers supply.
- Prove every fee-free method requires both the cUSD+ role/address and an authorized sponsor.
- Prove permissionless cUSD and cUSD+ USDT exits always charge 90 bps.
- Prove app-facing Stock Router buy/sell paths require sponsored origin and
  charge exactly 30 bps without an additional 90 bps cUSD+ conversion fee.
- Prove `sellToUsdt` is sponsor-independent, pays raw USDT directly to its
  contract caller, charges exactly 30 bps, and is absent from application
  selector allowlists.
- Pin storage layouts for both proxies.
- Mainnet-fork upgrade the live cUSD+ proxy and assert balances, total supply, `pPlus`, oracle state, USDY backing, legacy selectors, and Emergency Exit redemption.
- Mainnet-fork upgrade the live Stock Router proxy and assert owner, accrued
  fees, pause state, immutable wiring, 30 bps pricing, sponsored app-path
  enforcement, and permissionless reachability of `sellToUsdt`.

### Django

- Test build parsing and legacy/new response shaping for Android, iOS, missing, malformed, boundary, and newer builds; none of these cases waives the fee.
- Test recipient capability lookup, cUSD+ compatibility delivery, and later ineligible normalization to cUSD.
- Test binding preview persistence and exact gross/fee/net reconciliation.
- Test ramp and external-deposit sources produce identical fee results.
- Test ramp provider orders use net USDT while user history records gross spend and fee.
- Test prepare/submit byte matching, expiry, fee-rate race, signer/account binding, idempotency, noop, revert, and outcome unknown.
- Test the application quote API rejects both stock buy and stock sell when the
  sponsored app rail is unavailable; it must not expose a raw-USDT alternative.
- Test chain-qualified asset migration and every ledger/history projection.
- Test below-$1 aggregation and a later deposit crossing the threshold.

### React Native

- Test fee disclosure for entry, exit, ramp, and direct on-chain conversion.
- Preserve fixtures proving old request payloads remain executable with server-side gross/net translation.
- Test combined cUSD/cUSD+ balance and pending raw-USDT projection.
- Test all four friend-send routes.
- Test the fifth compatibility route to an outdated recipient without revealing private version details to the sender.
- Test app close/resume, rapid retry, stale quote, no network, sponsor busy, and receipt unknown.
- Test Emergency Exit with cUSD, cUSD+, pending USDT, global pause, IM failure, and raw-token fallbacks.
- Keep contract-derived quote vectors shared with Python and TypeScript tests.

### End-to-end rehearsals

- New external USDT deposit to eligible and ineligible accounts.
- Koywe/Infinia on-ramp and off-ramp using net provider settlement.
- Direct external wallet exit.
- Eligible/ineligible cross-send in both directions.
- Existing-holder live-proxy upgrade and rollback.
- Installed old build after activation: normal operations remain executable and pay 0.9%; stale `Gratis` disclosure is accepted only for the short store-review window; Emergency Exit remains executable.
- New-build sender to old-build recipient: cUSD+ delivery, old Emergency Exit, then post-update normalization.
- Sponsored app stock buy and sell through cUSD+, plus an independent direct
  contract call to the advanced raw-USDT stock redemption selector.

## What already exists

- Existing cUSD+ UUPS proxy and storage-pinned Foundry upgrade rehearsals: reused.
- Sponsor-gated cUSD+ mint and permissionless redemption: preserved and extended.
- EIP-7702 locally signed exact batches, KMS sponsorship, durable batch records, and outcome classification: reused.
- Ramp quote/order, Koywe exact-amount funding, deposit scanner, foreground savings resume, and conversion saga: adapted rather than replaced.
- Exact cUSD+ redeem math and whole-position calculation: extended with the cUSD fee preview.
- Emergency Exit public-RPC transport, checkpoints, USDT log proof, and raw-share fallback: extended for cUSD.
- Unified conversion/history ledger: migrated instead of creating a parallel fee ledger.

## NOT in scope

- Provenance-based ramp pricing or fee waivers: pricing is universal.
- General raw-USDT holding mode: USDT remains transient.
- Volume tiers, fee caps, negotiated institutional rates, or whale exemptions: data-triggered follow-up.
- Recipient eligibility allowlist on secondary cUSD+ transfers: existing open-transfer interpretation retained.
- New cUSD+ proxy or USDY/share migration: existing proxy/backing remain.
- Separate fee router fleet: the cUSD perimeter is the fee authority.
- Different entry and exit rates: one symmetric value is used.
- App/server access to the Stock Router's raw-USDT redemption: the selector is
  contract-only for advanced callers.

## Parallel implementation lanes

| Lane | Modules | Depends on |
|---|---|---|
| A: contracts | `contracts/cusd_plus/` | approved ABI and storage plan |
| B: ledger and quote API | `conversion/`, new cUSD server module, `ramps/` | contract preview ABI |
| C: mobile and Emergency Exit | `apps/src/` | GraphQL schema and contract ABI |
| D: deployment/operations | deployment scripts, settings, monitoring, docs | A, B, and C |

Start A and the model-only portion of B in parallel. Once the ABI is frozen, finish B and C in parallel. Run the cross-language vectors and fork rehearsal after A-C merge. D performs the coordinated deployment only after the full suite passes.

## Implementation Tasks

- [ ] **T1 (P1)** — Contracts — Implement and fuzz the new UUPS cUSD reserve/fee vault.
- [ ] **T2 (P1)** — Contracts — Upgrade cUSD+ in place with cUSD wrap/unwrap and legacy compatibility paths.
- [ ] **T3 (P1)** — Contracts — Add storage-layout pins, invariants, and live-proxy upgrade/rollback rehearsals.
- [ ] **T4 (P1)** — API — Add centralized platform/build headers and legacy/new compatibility shaping without blocking or waiving legacy conversions.
- [ ] **T5 (P1)** — API — Build domain-specific conversion prepare/submit with on-chain previews and durable idempotency.
- [ ] **T6 (P1)** — Ledger — Add exact fee fields and chain-qualified asset IDs; migrate all readers/writers.
- [ ] **T7 (P1)** — Ramps — Create provider orders for net USDT and reconcile them to gross/fee/net conversion rows.
- [ ] **T8 (P1)** — Mobile — Display the 0.9% fee and exact final amount in every normal conversion context.
- [ ] **T9 (P1)** — Mobile/server — Replace raw-USDT/cUSD+ spending logic with combined cUSD/cUSD+ routing, outdated-recipient cUSD+ compatibility, and $1 aggregation.
- [ ] **T10 (P1)** — Emergency Exit — Add cUSD redemption and paused/failed raw-token fallback while preserving the existing cUSD+ selector.
- [ ] **T11 (P2)** — Operations — Add accrued-fee, backing, quote-drift, old-build, sponsor-cost, and provider-underfund monitoring.
- [ ] **T12 (P1)** — Release — Execute the coordinated Safe upgrade, canaries, activation, and rollback rehearsal.
- [ ] **T13 (P1)** — Stocks — Upgrade the existing Stock Router proxy, register
  its dual cUSD+ role, preserve sponsored app settlement at 30 bps, and retain
  the contract-only permissionless raw-USDT redemption at 30 bps.

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|---|---|---|---:|---|---|
| CEO Review | `/plan-ceo-review` | Scope and strategy | 0 | not run | Product model supplied by user |
| Codex Review | `/codex review` | Independent second opinion | 0 | not run | Claude discussion supplied and reviewed issue-by-issue |
| Eng Review | `/plan-eng-review` | Architecture and tests | 1 | clear | 17 decisions, 0 unresolved, full test matrix |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | not run | Fee disclosure UI remains implementation scope |
| DX Review | `/plan-devex-review` | Developer experience | 0 | not run | Not required |

**CROSS-MODEL:** The supplied Claude discussion and this review agree on cUSD as the universal base, cUSD+ as its savings wrapper, one fee perimeter, and no provenance pricing. The finalized design keeps old builds operational (with temporarily stale disclosure), adds exact provider-net settlement, preserves the in-place proxy, and requires explicit fee-ledger invariants.

**VERDICT:** ENG CLEARED. The system is ready for implementation with a coordinated activation.

NO UNRESOLVED DECISIONS
