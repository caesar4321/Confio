# cUSD+ on Solana

Upgradeable Anchor program for an accumulating cUSD+ share backed by native
Solana USDY. The production USDY mint must be supplied at initialization; as
of 2026-08-06 Ondo lists it as
`A1KLoBrKBde8Ty9qtNQUtq3C2ortoC3u7twggz7sEto6`.

## Settlement boundary

The program does **not** CPI into Jupiter. Jupiter routes have dynamic account
graphs and should not become part of the vault's permanent security boundary.
Instead, the client composes one atomic Solana transaction:

Deposit:

1. Jupiter swaps the user's stablecoin into the user's USDY token account.
2. `deposit_and_mint` transfers the exact `usdy_in` into the vault reserve.
3. The vault mints floor(`usdy_in × USDY price / pPlus`) cUSD+ shares.

Redeem:

1. `redeem_to_usdy` burns cUSD+ and transfers the exact USDY output to the
   holder's USDY token account.
2. Jupiter swaps that USDY to the requested stablecoin.

If any instruction fails, the whole transaction rolls back. A caller-supplied
minimum protects each vault leg; the Jupiter instruction carries its own
slippage threshold.

This is intentionally adapter-neutral. `future_settlement_program` reserves
state for a future Ondo InstantManager program. When such a Solana program and
ABI exist, an upgrade can add `subscribe_and_mint` / `redeem_to_stable` CPI
instructions while leaving the mint, reserve, share accounting and direct
USDY fallback unchanged.

Version 1 deliberately accepts only the legacy SPL Token program for both
USDY and cUSD+. Token-2022 transfer-fee, transfer-hook, permanent-delegate and
similar extensions are rejected at the account boundary because they can make
the nominal transfer amount differ from the backing actually received. The
cUSD+ mint must be new, zero-supply, distinct from USDY, controlled by the
vault PDA, and have no freeze authority. Initialization also validates the
fixed treasury as a USDY token account owned by the config authority. An
authority handoff must provide a replacement USDY treasury owned by the new
authority, and rotates both governance and fee destination atomically.

## Economic mirror

The accounting matches `contracts/cusd_plus/CusdPlusVault.sol`:

- cUSD+ is an accumulating share; `pPlus` begins at $1.
- holders receive 85% of positive USDY reference-price appreciation by
  default; the remaining 15% becomes reserve surplus.
- mint and redeem round down; total obligations round up.
- fees can only be collected from reserve USDY above ceiling-rounded holder
  obligations.
- decreasing or over-threshold price updates trip a persistent guard.
- guard resolutions require a nonzero evidence hash and a pinned price range.
- initialization requires the initial price's observation timestamp and
  rejects stale or excessively future-dated observations.
- `pPlus` is capped at `u64::MAX`, matching the width assumed by all token
  amount multiplication paths.
- primary issuance requires a registered sponsor; redemption does not.
- authority transfer is two-step.

Unlike BSC, Ondo does not currently document a synchronous USDY price oracle
program on Solana. A dedicated price authority therefore pushes Ondo's
published reference price. Every value path rejects stale data. This is an
explicit trust assumption and should be replaced with a first-party oracle CPI
if Ondo publishes one.

## Upgrade authority

Solana program upgradeability is controlled by the loader, independently of
the config authority. The one-time `initialize` instruction verifies the
executable program's ProgramData account and requires its current loader
upgrade authority to sign. Callers must pass both the cUSD+ program account and
its loader-derived ProgramData account. This prevents an unrelated signer from
seizing the global config PDA after deployment; an already immutable program
cannot be initialized.

Deploy with an upgrade authority, initialize from that authority, and then
move the loader authority to the governance multisig. Do not finalize the
program: future InstantManager/oracle integration is a stated requirement.
Keep the loader upgrade authority and the config authority under the same
documented timelock/multisig policy.

## Build and test

The workspace pins Anchor 1.1.2. With Rust, Solana CLI and AVM installed:

```sh
avm use 1.1.2
anchor build
npm test
```

The checked-in program id is a development id. Generate and commit the real
deployment keypair/program id before any public deployment.

## Deliberate v1 boundary

The economic and issuance controls are implemented. Address-level freeze on
all secondary token transfers is **not** claimed in v1: enforcing an
address-wide rule across arbitrary Solana token accounts requires a Token-2022
transfer hook designed into the mint before creation. Add and audit that hook
before using the BSC contract's “frozen address cannot send or receive” claim
on Solana.
