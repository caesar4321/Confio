# CONFIO allocation contracts — audit and fix loop

Date: 28 September 2026. **Source review and scoped local validation complete. One supported operational defect fixed in source; no further actionable findings identified in the final scoped pass. Existing deployments were not changed.** This is not a claim that the contracts are vulnerability-free.

## Scope and requirements

Reviewed ConfioToken, ConfioVestingVault, ConfioPresaleVault and ConfioRewardVault; their ownership, token transfer and signature-library dependencies; allocation integration; and the existing vesting deployment command as context. The user explicitly authorized conventional source review and local Foundry after the optional CSO helper failed. No CSO helper verification labels are claimed.

Preserved requirements:

- Three separate vesting instances: founder 893.6M, creative co-builder 10M, cultural 15M.
- Existing presale allocation 74M and reward allocation 7.4M; exact aggregate 1B.
- Same treasury Safe may be temporary beneficiary in each separate vesting instance.
- No clock starts on funding, grant creation, beneficiary change or passage of time.
- Safe may change beneficiaries; pre-start revocation remains permitted.
- Activation is a separate future action. DEX time is not guessed or encoded now.

## Finding CONFIO-ALLOC-01 — ownership renunciation can strand presale claims

**Severity: medium operational/availability. Confidence: high. Prerequisite: the owner Safe authorizes renounceOwnership; not an unauthenticated attacker exploit.**

ConfioPresaleVault inherited renounceOwnership from Ownable without disabling it. If the Safe renounces before claims are unlocked, ownership becomes the zero address permanently. No account can then call the owner-only unlockClaims. Buyers' recorded and funded allocations remain unclaimable. Post-unlock renunciation can also strand unassigned migration credits and leave paused purchases permanently disabled. Vesting and reward vaults already prohibit renunciation.

Reproduction: a legitimate sponsored purchase records 100 CONFIO; the vault is funded and wired. The regression expects renunciation to be rejected, but the original source emits OwnershipTransferred to zero and succeeds. The exact regression then passes after the fix and confirms the owner can still unlock and the buyer can claim the full 100 CONFIO.

Repair: override renounceOwnership with the same owner-only reverting implementation already used in the other two vaults. Two-step ownership transfer remains available. No price, migration, beneficiary, funding, claim or pause policy changed.

Evidence: renounce-before.log and renounce-after.log; test_owner_cannot_renounce_and_strand_locked_allocations in ConfioPresaleVault.t.sol.

**Deployment status:** fixed locally only. The deployed presale is non-upgradeable. Do not submit renounceOwnership to the current presale Safe. Applying the code change on-chain would require a separately reviewed replacement/migration; that is not authorized or performed in this audit. This residual deployment difference does not require changing the unchanged vesting bytecode for the planned new category instances.

## Loop and validation

1. Baseline: all 60 existing tests belonging to the four scoped contracts passed.
2. Challenge: inspected access control, arbitrary/duplicate recipients, unstarted and active grant transitions, beneficiary migration after claims, rounding/overflow, reserves and withdrawal paths, presale migration pools and purchase accounting, cumulative reward claims, EIP-712 domain binding, replay, pause and ownership transitions.
3. Reproduced the renunciation failure; added regression; repaired its source.
4. Added exact five-allocation integration tests, cultural pre-start split, temporary beneficiary replacement, long-unstarted clocks, ownership acceptance, negative authority tests, reward cross-vault/cross-chain replay and rollback/retry tests, permit replay, and vesting/presale stateful invariants.
5. Re-read changed source and performed a separate skeptical sequential pass. No independent agent review was performed.
6. Final scoped run: **76 passed, 0 failed, 0 skipped**. Fuzz tests use **4,096 cases each**, seed **0x20260928**. Each of two invariant suites ran **128 sequences at depth 128**, totaling **32,768 handler calls**, zero unexpected reverts. Handler functions guard inapplicable actions, so call counts are not counts of unique successful state changes. The presale handler maintains the planned funded operating mode; existing unit tests separately cover permitted pre-unlock underfunding and mandatory backing at/after unlock.

Foundry 1.7.1; solc 0.8.26; optimizer 200; Cancun EVM; installed OpenZeppelin 5.6.1. Tests ran in an isolated local copy of scoped sources and tests, with local dependency directories shared read-only by convention. No host application/backend or KMS signer was executed.

Initial unrestricted test discovery also collected forge-std's own tests due to the repository's src='.' layout. Twelve library-fixture/RPC tests failed independently of the four contract suites. The scope was corrected with explicit test/Confio*.t.sol selection; no target failures were excluded. This is a scoped contract suite, not a claim that every unrelated repository test passes.

Reproduce from contracts/cusd_plus (explicit names exclude unrelated Confio payment/payroll/delegate suites):

```sh
FOUNDRY_INVARIANT_RUNS=128 FOUNDRY_INVARIANT_DEPTH=128 forge test --offline --match-contract '^(ConfioTokenTest|ConfioVestingVaultTest|ConfioPresaleVaultTest|ConfioRewardVaultTest|ConfioAllocationAuditTest|ConfioVestingInvariantTest|ConfioPresaleInvariantTest)$' --fuzz-runs 4096 --fuzz-seed 0x20260928
```

## Deployed-code comparison

Public read-only BSC check at block **124596218**: ConfioToken, ConfioVestingVault and ConfioRewardVault executable runtime bytes match the local build after removing Solidity metadata and masking compiler-listed immutable slots. Actual immutable words are recorded separately in deployed-bytecode-check.json. This is not a blanket verification of every constructor value, Safe module, signer, proxy, external asset or deployment setting. The prior allocation audit checked the vault token and owner wiring. The presale source is intentionally changed by this audit and is not claimed to match its existing deployment.

## Intended controls, not defects to remove

- Beneficiary changes and pre-start revocation are retained. A funded registered grant is protected from surplus withdrawal but can be revoked by the Safe before activation. It is not an irrevocable pre-DEX lock.
- Token transfers into a vesting vault alone are surplus; reserve them with addGrant. A combined Safe funding+grant batch avoids an intermediate unassigned state.
- Founder 36-month and co-builder 24-month durations use the existing legacy convention of 1,095 and 730 days respectively; culture uses 90 days. Confirm this convention in the final allocation disclosure.
- Cultural awards can be split before start by revoking the pool grant and creating fully funded participant grants atomically. changeBeneficiary alone moves an entire grant.
- Reward signer and treasury control are explicit trust assumptions. After unlock a compromised signer can drain the funded reward balance; depositing the whole 7.4M raises that exposure from a working tranche to the full pool. No undisclosed change to reward policy was introduced.
- Presale inventory above outstanding obligations remains owner-withdrawable; an allocation cap is not an irrevocable lock of unsold tokens.

## Boundaries before execution

No deployment, Safe proposal, signature, activation, claim unlock or transfer occurred. The earlier combined 918.6M funding draft is superseded for the separate-vault design and must not be used. Actual new addresses, immutable wiring, Safe batch contents, gas, source verification, legacy Algorand reconciliation and the decision for the live presale renunciation surface still require the deployment/funding preflight. This audit does not certify backend reward liabilities, third-party cUSD implementation, all sponsor infrastructure, Safe owners/modules or general repository security.
