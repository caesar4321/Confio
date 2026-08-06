# cUSD+ cross-chain contract specification

This document freezes the economic behavior shared by the Solana program and
the Solidity vault. It intentionally does not pretend that Jupiter and Ondo's
EVM InstantManager have the same execution model.

| Invariant / operation | Solana | Solidity (BSC) |
|---|---|---|
| Upgrade mechanism | Solana loader upgrade authority | UUPS `_authorizeUpgrade`, owner gated |
| Initialization authority | current loader ProgramData upgrade authority must sign | proxy construction atomically calls `initialize` |
| Backing asset | native Solana USDY mint via legacy SPL Token (Token-2022 extensions rejected in v1) | BSC USDY ERC-20 |
| Current acquisition | Jupiter instructions composed before vault deposit | Ondo InstantManager `subscribe` inside vault call |
| Future acquisition | InstantManager CPI can be added by program upgrade; reserved program address is already in state | Current InstantManager implementation; immutable wiring changes with a UUPS implementation upgrade |
| Atomic backing proof | vault transfers exact USDY into reserve before mint in same Solana transaction | vault measures/receives USDY from IM before mint in same EVM transaction |
| Share price | `p_plus_wad`, starts at 1e18 | `pPlus`, starts at 1e18 |
| Holder yield | 85% of positive USDY reference appreciation by default | 85% of positive USDY oracle appreciation |
| Confío yield share | reserve surplus only; no unbacked fee mint | reserve surplus only; no unbacked fee mint |
| Mint rounding | floor | floor |
| Redeem rounding | floor | floor |
| Obligation rounding | ceiling | ceiling |
| Primary issuance | sponsor PDA must co-sign; shares always go to depositor | registered sponsor must originate; recipient is caller or registered relay |
| Exit sponsorship | none | none |
| Oracle guard | pushed-price freshness + decrease/jump guard | synchronous Ondo oracle decrease/jump guard |
| Guard resolution | evidence hash + verified range | evidence hash + verified range |
| Pause | blocks mint and redeem | blocks mint and public USDT redeem |
| Fee collection | authority, surplus only, fixed treasury USDY account | owner, surplus only, fixed owner recipient |
| Backing sweep | no instruction exists | `sweep` rejects USDY |
| Authority rotation | two-step config authority; loader authority separately governed | OZ two-step ownership |

## Method mapping

- Solana `deposit_and_mint` corresponds to Solidity's collateral-receive plus
  `_mintAgainstUsdy`. Jupiter is outside the program; InstantManager is inside
  the Solidity transaction.
- Solana `redeem_to_usdy` corresponds to Solidity's share-to-USDY accounting.
  On BSC raw USDY delivery remains treasury-only due to that deployment's Ondo
  purchaser representations; public users call `redeemToUsdt` instead.
- Solana `update_price` corresponds to Solidity `accrue`. The different input
  is unavoidable until a first-party readable Solana oracle exists.
- Solana `accept_verified_growth` and `rebaseline_verified_fault` correspond
  to `acceptVerifiedOracleGrowth` and
  `rebaselineAfterVerifiedOracleFault`.
- Both `collect_fees` / `collectFees` can move only proven surplus.

## What “mirror” does not mean

The bytecode and settlement plumbing should not be identical across VMs. A
Solana vault CPI-hardcoded to Jupiter would be more brittle than the Solidity
contract and would make every Jupiter account-layout change an upgrade event.
The mirror is the accounting, authorization, guard and backing invariant.

The BSC contract additionally enforces address-wide freeze in its ERC-20
transfer hook. The Solana v1 program does not yet claim that property; it
requires a Token-2022 transfer hook fixed at mint creation and a separate
audit. This gap must remain visible in product/compliance claims.
