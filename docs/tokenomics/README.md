# $CONFIO Tokenomics

**Authoritative English Edition · Version 3.0 · 31 July 2026**

> **Fixed supply. Continuous on-chain presale. Founder ownership disclosed plainly.**

This document describes the canonical $CONFIO token on BNB Smart Chain, its fixed supply and allocation, the continuous presale curve, reward distribution, vesting commitments, governance controls, and material risks.

The English edition is the authoritative source. [Spanish](README.es.md) and [Korean](README.ko.md) editions are convenience translations and may temporarily lag behind this document. If a translation conflicts with the English edition, the English edition controls.

$CONFIO is separate from USDT, cUSD+, USDY, Ondo Stocks, and the operating company. It does not back user dollar balances and does not by itself represent equity, debt, revenue share, or a claim on Confío’s assets or profits.

## Contents

1. [Design principles](#1-design-principles)
2. [Canonical token and supply](#2-canonical-token-and-supply)
3. [Allocation](#3-allocation)
4. [Continuous public presale](#4-continuous-public-presale)
5. [Referral and usage rewards](#5-referral-and-usage-rewards)
6. [Cultural Invitation Fund](#6-cultural-invitation-fund)
7. [Creative co-builder allocation](#7-creative-co-builder-allocation)
8. [Founder allocation](#8-founder-allocation)
9. [Vesting, claims, and circulating supply](#9-vesting-claims-and-circulating-supply)
10. [Utility and value boundaries](#10-utility-and-value-boundaries)
11. [DEX-launch disclosure](#11-dex-launch-disclosure)
12. [Material risks](#12-material-risks)
13. [Legal disclaimer](#13-legal-disclaimer)
14. [Primary sources](#14-primary-sources)

---

## 1. Design principles

1. **One canonical token:** only the disclosed BNB Smart Chain contract is official.
2. **Fixed cap:** 1,000,000,000 CONFIO was minted once. The token has no owner, minter, or pause function. Holders may burn their own tokens, so supply can fall but cannot rise.
3. **Continuous pricing:** the public presale has no phases, rounds, or manually selected price windows. Price follows cumulative tokens sold under an immutable piecewise-linear curve.
4. **Founder ownership stated directly:** 893,600,000 CONFIO is the founder allocation. Treasury custody does not reclassify it as an undefined ecosystem reserve.
5. **Claims are not circulation:** presale allocations and reward entitlements do not circulate until the applicable claim path is opened and tokens are claimed.
6. **On-chain rules where they matter most:** the token cap, presale curve, purchase accounting, and presale backing check are enforced by public contracts.
7. **Explicit trust boundaries:** the reward pool and future vesting operations retain disclosed treasury controls; they are not described as trustless when they are not.
8. **No guaranteed return:** presale prices, token utilities, and future listing plans do not guarantee market value, liquidity, yield, or appreciation.

---

## 2. Canonical token and supply

| Field | Current canonical value |
|---|---|
| Network | BNB Smart Chain |
| Standard | BEP-20 / ERC-20 |
| On-chain name | Confio |
| Brand name | Confío |
| Symbol | CONFIO |
| Decimals | 18 |
| Initial and maximum supply | 1,000,000,000 CONFIO |
| Canonical contract | [`0xCcEb3F6127FA9160a26A1B85857Ca4C9D56B3fa8`](https://bscscan.com/token/0xCcEb3F6127FA9160a26A1B85857Ca4C9D56B3fa8) |
| Privileged token powers | No owner, no minter, no token-level pause |
| Extensions | ERC-2612 Permit and holder-initiated Burnable |

The full one-billion-token supply was minted once to the project’s multi-party treasury at deployment. Distribution from that treasury is governed by the allocations and release conditions in this document; it is not new token issuance.

The on-chain name uses the ASCII spelling **“Confio”** because explorers and wallets render accented token metadata inconsistently. The product and brand remain **“Confío.”**

The canonical contract supersedes the earlier accented-name deployment at `0xd57BEc35857839DC33F6FaBE7356C6a19a8d72c1`. That earlier contract was abandoned before external distribution or presale wiring, and its entire supply was burned. It must not be treated as an official $CONFIO token.

---

## 3. Allocation

| Allocation | CONFIO | Share of initial supply | Release principle |
|---|---:|---:|---|
| Public presale | 74,000,000 | 7.40% | Purchase allocations remain locked until the official DEX launch and one-way presale claim unlock |
| Referral and usage rewards | 7,400,000 | 0.74% | Accrues under active program rules; on-chain claims remain locked until DEX launch |
| Cultural Invitation Fund | 15,000,000 | 1.50% | 90-day linear vesting after its published activation event |
| Creative co-builder allocation | 10,000,000 | 1.00% | 24-month linear vesting after activation |
| Founder allocation — Julian Moon | 893,600,000 | 89.36% | 36-month linear vesting after activation |
| **Total** | **1,000,000,000** | **100.00%** | Fixed initial supply |

The 89.36% founder allocation is intentionally shown as a founder allocation. The presale and disclosed contributor/community allocations are portions of the fixed supply made available by a founder-led startup; they do not turn $CONFIO into company shares.

The 10,000,000-token creative co-builder allocation was carved out of Julian Moon’s original 903,600,000-token founder allocation. It did not increase total supply. The Cultural Invitation Fund remains capped at 15,000,000 tokens unless a future version transparently reallocates tokens from an existing category; the token contract cannot mint additional supply.

---

## 4. Continuous public presale

### 4.1 One curve, no phases

The public presale offers up to 74,000,000 CONFIO through one continuous, USDT-denominated price curve. There are no Phase 1, Phase 2, Phase 3, sub-rounds, scheduled repricings, or manual price transitions.

The contract divides the curve into three mathematical **segments** solely to calculate a continuous price efficiently:

| Cumulative CONFIO sold | Spot-price movement | Tokens in segment | Integrated curve-cost reference |
|---:|---:|---:|---:|
| 0 to 4,000,000 | US$0.20 → US$0.30 | 4,000,000 | US$1,000,000 |
| 4,000,000 to 24,000,000 | US$0.30 → US$0.70 | 20,000,000 | US$10,000,000 |
| 24,000,000 to 74,000,000 | US$0.70 → US$1.30 | 50,000,000 | US$50,000,000 |
| **Full curve** | **US$0.20 → US$1.30** | **74,000,000** | **US$61,000,000** |

Within each segment, the spot price rises linearly with cumulative tokens sold. The endpoints and allocation are constructor-set and the deployed contract has no function that can change them.

The integrated curve-cost figures show the mathematical cost of traversing each complete segment from its first token to its last. Actual BSC-USDT proceeds exclude purchase amounts collected under the earlier presale system and can also be lower if the curve is not fully sold.

The segment boundaries do **not** create sales phases. Purchases can cross a boundary in one transaction, and the contract applies the appropriate portion of the continuous curve on each side.

### 4.2 How a purchase is priced

The presale contract charges the exact mathematical area under the curve for the quantity purchased. In practical terms:

- a buyer pays all intervening prices from the current sold position to the new sold position;
- a larger purchase can span more than one segment;
- splitting one purchase into several purchases creates no systematic price discount;
- rounding is performed conservatively in favor of the vault;
- the application reads the current on-chain price rather than maintaining a manual phase price; and
- the buyer signs a maximum-payment amount, so a concurrent purchase that moves the curve above that cap causes the transaction to revert instead of charging more than authorized.

The contract is the authority for the purchase cost and cumulative amount sold. Backend records support eligibility, limits, user history, and display, but cannot manually select another curve price.

### 4.3 Implied fully diluted value references

| Curve landmark | Arithmetic reference using 1B initial supply |
|---:|---:|
| US$0.20 | US$200,000,000 |
| US$0.30 | US$300,000,000 |
| US$0.70 | US$700,000,000 |
| US$1.30 | US$1,300,000,000 |

These are simple price-times-supply references. They are not company valuations, independent appraisals, forecasts, guaranteed market capitalizations, or promises that a secondary market will trade at a curve price.

### 4.4 Presale contract and controls

**Canonical presale contract:** [`0x1a2dD9b49987DE86dC96fC86c715b62aaDFf095c`](https://bscscan.com/address/0x1a2dD9b49987DE86dC96fC86c715b62aaDFf095c#code)

The contract is non-upgradeable. Its owner cannot rewrite the curve or mint CONFIO. Its limited administrative powers include:

- rotating approved transaction sponsors;
- pausing new purchases;
- assigning or correcting bounded legacy purchase credits;
- wiring the canonical CONFIO token once;
- opening claims once, subject to full backing;
- withdrawing presale proceeds; and
- withdrawing only CONFIO that exceeds outstanding presale obligations.

Purchases use BSC-USDT and sponsored EIP-7702 transaction batches. Confío’s backend applies product terms, geographic eligibility, sanctions controls, purchase limits, and account checks; the contract independently enforces price and allocation accounting.

### 4.5 Claims and backing

Buying during the presale records an allocation; it does not make the tokens transferable immediately.

- Presale claims remain locked until the official DEX launch and unlock event.
- Before the one-way unlock, the vault must hold enough canonical CONFIO to cover every outstanding presale allocation.
- After unlock, the contract refuses any new purchase obligation that is not already backed by tokens held in the vault.
- Each purchaser claims directly to the same BSC address that owns the recorded allocation.
- The owner cannot sweep CONFIO reserved for unclaimed presale obligations.

The presale allocation is therefore not circulating supply merely because it has been sold or credited.

If the presale is closed before all 74,000,000 tokens are sold, the unsold amount remains classified within the presale allocation until a later authoritative tokenomics version discloses a different disposition. It does not silently become additional founder allocation or circulating supply.

### 4.6 Earlier presale purchases

The replacement BSC vault was initialized with **17,713.85 CONFIO** previously sold under the earlier presale system. This amount was included in `totalSold`, establishing the correct starting point on the continuous curve, and in a bounded migration pool.

As users’ current BSC addresses are linked, their exact earlier allocations can be credited from that pool. Credits reduce the remaining pool and cannot create obligations beyond the amount already included in the curve. A mistaken, unclaimed credit can be corrected; a claimed allocation cannot be revoked through the migration-credit mechanism.

### 4.7 Eligibility

Participation is subject to the definitive presale terms, identity and sanctions controls, applicable law, account limits, and geographic restrictions. The current product excludes U.S. residents and South Korean citizens or residents from the presale. Restrictions may be expanded or changed where required, and technical access never establishes legal eligibility.

---

## 5. Referral and usage rewards

The 7,400,000-token pool is intended to recognize verified product adoption and qualifying activity rather than passive wallet creation.

When BSC reward accrual is enabled:

1. a user completes the qualifying actions shown in the live reward terms;
2. Confío applies identity, duplicate-person, account, and anti-abuse checks;
3. the dollar-denominated reward is converted into CONFIO using the live on-chain presale-curve price at the time it is earned;
4. the resulting CONFIO amount is recorded in Confío’s database as part of the user’s cumulative entitlement; and
5. no reward token moves on-chain until reward claims open at the DEX launch.

The conversion formula is:

```text
CONFIO reward = dollar-denominated reward ÷ live on-chain curve price
```

This means the same dollar-denominated reward produces fewer CONFIO as the presale curve advances. It eliminates manual phase-price maintenance but does not guarantee the later market value of the resulting CONFIO.

The current anti-abuse model uses identity evidence rather than phone or device checks alone. Identity verification includes a government-issued document, a live selfie, liveness checks, and face matching. Duplicate-person controls use normalized identity data and issuing country. Only the earliest valid referral associated with the same verified identity may retain the applicable reward.

Exact qualifying events, reward amounts, limits, and program availability may change prospectively. The live terms and the data recorded for a specific event control that event.

### 5.1 RewardVault claim model

**Canonical RewardVault:** [`0x812b8d86952123bED0a33E92a76211cbbACDe730`](https://bscscan.com/address/0x812b8d86952123bED0a33E92a76211cbbACDe730#code)

Reward claims use a short-lived EIP-712 signature over the user’s cumulative earned amount. The contract pays only the difference between that signed cumulative amount and the amount already claimed, preventing replayed claims from paying twice.

This is a **treasury-controlled reward pool**, not a trustless escrow. The multi-party treasury owner can rotate the signer, pause claims, and withdraw vault funds, including after claims have been unlocked. Users therefore rely on Confío’s database records, signing service, funding policy, and treasury to honor valid reward obligations. Short signature deadlines limit the life of stale or mistakenly high authorizations.

The RewardVault is deployed and source-verified, while reward accrual and claims remain subject to operational feature controls. At DEX launch, Confío must fund an appropriate CONFIO tranche, activate the claim-signing and client-claim path, and open claims before users can receive tokens from this vault.

---

## 6. Cultural Invitation Fund

The Cultural Invitation Fund allocates 15,000,000 CONFIO to recognize documented community contribution made before the product had conventional scale.

The intended release structure is:

- aggregate allocation capped at 15,000,000 CONFIO;
- participant-level amounts determined under a published and reconciled ledger;
- 90-day linear vesting after the published activation event; and
- public disclosure of the final methodology, eligible ledger, appeal process, and aggregate reconciliation before distribution.

This fund is separate from referral rewards. Referral rewards recognize qualifying product adoption; the Cultural Invitation Fund recognizes documented early cultural and community contribution.

---

## 7. Creative co-builder allocation

The creative co-builder allocation is 10,000,000 CONFIO, or 1.00% of the initial supply.

Its intended release structure is 24-month linear vesting after activation, with no implication that vesting equals sale. The beneficiary address, funding transaction, vesting contract, activation transaction, and claimed amount must be disclosed when the BSC vesting grant is activated.

---

## 8. Founder allocation

**893,600,000 CONFIO, or 89.36% of the initial supply, is allocated to founder Julian Moon.** This is the largest allocation and creates material concentration, governance, liquidity, and perceived-sale-pressure risks that every purchaser should evaluate directly.

Confío deliberately uses a traditional-startup analogy: the founder begins with ownership of the fixed token supply and sells or allocates defined portions through the presale, community programs, and contributor grants. This describes the project’s ownership and financing logic; **$CONFIO is not company equity**, and buying it does not make a holder a shareholder of Confío or an affiliated legal entity.

The intended founder release structure is approximately 36 months of linear vesting after activation. Straight-line vesting of 893,600,000 CONFIO over 36 months is economically equivalent to approximately **24.82 million CONFIO becoming vested per month on average**. Vesting is continuous, not a scheduled monthly sale, and vested does not mean transferred or sold.

The BSC vesting implementation must be deployed, funded, and publicly activated before its clock begins. Until then, the reserved founder tokens remain under multi-party treasury custody and no claim should be made that the BSC vesting clock is already running. When activated, Confío must publish the vault address, beneficiary, grant amount, start transaction, duration, vested amount, claimed amount, and treasury balances.

The size of this allocation makes public wallet mapping, vesting-state disclosure, transfer transparency, and disciplined founder reporting more important than promotional statements about long-term alignment.

---

## 9. Vesting, claims, and circulating supply

### 9.1 Release triggers

The following concepts must not be treated as interchangeable:

- **allocated:** assigned to a category in this document;
- **sold or earned:** a purchaser or reward participant has a recorded entitlement;
- **vested:** a time-based restriction has elapsed;
- **claimable:** the applicable contract and policy permit withdrawal;
- **claimed:** tokens have moved to the beneficiary’s address; and
- **circulating:** tokens are actually transferable outside a locked vault or restricted claim system.

Presale and reward claims are tied to the official DEX launch, not to completion of a numbered presale phase. Cultural, co-builder, and founder vesting clocks begin only upon their separately disclosed activation transactions.

### 9.2 Circulating-supply definition

For public reporting, circulating supply should include only transferable canonical CONFIO outside locked or reserved distribution contracts. Depending on the date, this can include:

- presale allocations that have been unlocked and claimed;
- reward allocations that have been validly claimed;
- vested cultural, co-builder, or founder tokens that have actually been released; and
- other transfers expressly disclosed by the treasury.

It should exclude:

- unallocated treasury balances;
- unclaimed presale allocations;
- database-recorded but unclaimed rewards;
- unvested grants; and
- tokens held in distribution contracts for future obligations.

The entire 74,000,000-token presale allocation must not be reported as circulating merely because it is offered for sale. Likewise, the full reward or cultural pools must not be reported as circulating before actual claims or releases.

---

## 10. Utility and value boundaries

$CONFIO’s current and intended role includes community recognition, product rewards, participation in the Confío ecosystem, and possible future governance or benefit mechanisms. Any material utility must be implemented and disclosed before users rely on it.

$CONFIO does **not**:

- back USDT, cUSD+, USDY, or Ondo Stocks;
- represent a right to redeem one dollar or any other fixed amount;
- automatically receive Confío’s cUSD+ yield share, merchant fees, payroll fees, Ondo Stocks fees, provider revenue share, or company revenue;
- represent shares in Confío or an affiliated legal entity; or
- guarantee voting power, listing, liquidity, appreciation, yield, dividends, buybacks, or burns.

Confío may later propose staking, governance, fee-linked benefits, buybacks, burns, or other mechanisms. None should be assumed until definitive terms, implementation, legal review, and contract details are published.

---

## 11. DEX-launch disclosure

Before the official DEX launch and token-claim unlock, Confío should publish a dated launch disclosure containing at least:

- the canonical token, presale, reward, and active vesting-contract addresses;
- current total supply and any burns;
- treasury and distribution-vault balances;
- total presale amount sold, total USDT raised, unassigned legacy pool, claims, and unclaimed obligations;
- reward-pool funding, aggregate recorded entitlements, claim rules, and amounts claimed;
- founder, co-builder, and cultural vesting activation status;
- verified circulating supply under the definition in this document;
- the DEX venue, pair, initial liquidity, liquidity ownership or lock terms, and market-making arrangements;
- material treasury transfers and known unlocks; and
- any change to eligibility, utility, fees, or legal terms.

The initial DEX price is a market and liquidity event. It is not guaranteed to equal the current curve price or the final US$1.30 curve endpoint.

---

## 12. Material risks

| Risk | Why it matters |
|---|---|
| Founder concentration | The founder owns 89.36% of the initial supply. Vesting reduces immediate transferability but does not remove long-term concentration or potential sale pressure. |
| Curve-implied valuation | The presale curve reaches price-times-supply references as high as US$1.3B before an external market independently establishes price. |
| Continuous price movement | Every completed purchase can move the curve. Quotes can change before broadcast, and later buyers pay more under the fixed rule. |
| DEX unlock pressure | Presale and reward claims can create meaningful transferable supply at launch. Available liquidity may be much smaller than claimable value. |
| Treasury and reward trust | Reward entitlements live in Confío’s database and depend on a treasury-controlled vault, signer, funding, and operational availability. |
| Vesting implementation | Founder, co-builder, and cultural BSC vesting must be deployed, funded, activated, and reported correctly. Administrative or operational errors can affect release timing. |
| Smart-contract risk | The token, presale, reward, vesting, sponsored-transaction, and related contracts can contain defects despite public code and extensive testing. |
| Network risk | BNB Smart Chain can experience congestion, validator or infrastructure concentration, censorship, reorganization, exploits, fee changes, or interruption. |
| Stablecoin risk | Presale purchases use USDT, which carries issuer, reserve, depeg, freeze, legal, and redemption risks. |
| Regulatory classification | Authorities may classify the token, presale, reward, or future utility differently across jurisdictions or over time. |
| Eligibility and sanctions | A transaction can be technically possible while legally or contractually unavailable. Eligibility rules and provider policies can change. |
| No automatic value capture | Growth in Confío users, cUSD+ balances, payment volume, fees, or company revenue does not automatically create demand or distributions for $CONFIO. |
| Market and liquidity risk | A DEX or centralized exchange listing is not guaranteed. If listed, price can be volatile and liquidity can disappear. |
| Key and treasury risk | Multi-party governance reduces single-key risk but does not eliminate collusion, compromise, signer failure, or mistaken treasury transactions. |
| Impersonation risk | Tokens with the same name or symbol may be created by anyone. Only the canonical address in this document is official. |

---

## 13. Legal disclaimer

This document is informational and may be amended when contracts, products, laws, or definitive terms change. It is not investment, legal, tax, accounting, or financial advice, and it is not a promise of future performance.

$CONFIO is not a bank deposit, is not insured, and may lose some or all of its market value. It does not represent equity, debt, a deposit claim, or a guaranteed right to revenue, profit, yield, liquidity, redemption, governance, buybacks, listing, or appreciation.

Presale access, rewards, claims, transfers, and utility may be limited by identity, jurisdiction, sanctions, applicable law, provider policy, technical controls, or definitive product terms. Purchasers must make their own assessment and obtain professional advice where appropriate.

The deployed smart contracts and definitive transaction records control on-chain behavior. If this document conflicts with a deployed contract regarding an immutable on-chain rule, the contract controls that rule. If marketing copy, a translation, or a social-media statement conflicts with this authoritative English document, this document controls unless superseded by later definitive terms.

---

## 14. Primary sources

1. Canonical ConfioToken on BscScan: 1,000,000,000 initial supply; no token owner, minter, or pause; ERC-2612 Permit and holder burn.
   https://bscscan.com/token/0xCcEb3F6127FA9160a26A1B85857Ca4C9D56B3fa8

2. Canonical ConfioPresaleVault on BscScan: immutable curve, USDT purchases, purchase accounting, backing checks, legacy-credit pool, and claim controls.
   https://bscscan.com/address/0x1a2dD9b49987DE86dC96fC86c715b62aaDFf095c#code

3. Canonical ConfioRewardVault on BscScan: cumulative EIP-712 claims, one-way DEX unlock signal, signer rotation, pause, and treasury withdrawal controls.
   https://bscscan.com/address/0x812b8d86952123bED0a33E92a76211cbbACDe730#code

4. Confío public repository, BSC token, presale and reward contracts, tests, and deployment record.
   https://github.com/caesar4321/Confio/tree/main/contracts/cusd_plus

5. Confío public repository, current on-chain curve-price reader and presale statistics.
   https://github.com/caesar4321/Confio/blob/main/presale/price_utils.py

6. Confío public repository, reward accrual and live-curve conversion logic.
   https://github.com/caesar4321/Confio/blob/main/achievements/services/referral_rewards.py

7. Confío English whitepaper, current BNB Smart Chain product architecture and $CONFIO separation.
   https://github.com/caesar4321/Confio/blob/main/docs/whitepaper/README.md

---

*$CONFIO is separate from Confío’s dollar products. Verify the canonical contract before any transaction.*
