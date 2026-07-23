# $CONFIO Tokenomics

**Fixed supply. Verifiable allocations. Utility earned through real participation.**

**Global reference · Version 2.0 · July 2026**
Julian Moon · Founder & CEO
[confio.lat](https://confio.lat) · [GitHub](https://github.com/caesar4321/Confio)

**Authoritative original:** This English document is the sole authoritative version of the $CONFIO tokenomics. [Español](README.es.md) and [한국어](README.ko.md) are translations provided for convenience. If a translation differs from the English text, the English text controls.

## How to read this document

This document describes the fixed supply, planned allocation, sale schedule, reward pools, vesting, chain policy, and material risks of $CONFIO. It supersedes the 2025 English Edition.

$CONFIO is separate from Confío’s financial products:

- **cUSD** is the Algorand payment asset.
- **cUSD+** is the BNB Smart Chain savings product backed by Ondo USDY.
- **$CONFIO** is the community, rewards, and future ecosystem-utility token. It does not back cUSD or cUSD+.

Nothing in this document promises a market price, exchange listing, yield, revenue share, company ownership, or right to Confío’s profits.

<details>
<summary><strong>Contents</strong></summary>

1. [Principles](#1-principles)
2. [On-chain identity and fixed supply](#2-on-chain-identity-and-fixed-supply)
3. [Allocation](#3-allocation)
4. [Public presale](#4-public-presale)
5. [Referral and usage rewards](#5-referral-and-usage-rewards)
6. [Cultural Invitation Fund](#6-cultural-invitation-fund)
7. [Creative Co-Builder allocation](#7-creative-co-builder-allocation)
8. [Founder allocation](#8-founder-allocation)
9. [Unlocks and circulating supply](#9-unlocks-and-circulating-supply)
10. [Multi-chain policy and supply integrity](#10-multi-chain-policy-and-supply-integrity)
11. [Utility and value-accrual boundary](#11-utility-and-value-accrual-boundary)
12. [Disclosure before a DEX listing](#12-disclosure-before-a-dex-listing)
13. [Material risks](#13-material-risks)
14. [Legal disclaimer](#14-legal-disclaimer)
15. [Sources and verification](#15-sources-and-verification)

</details>

---

## 1. Principles

$CONFIO is designed around five principles:

1. **Fixed supply:** no additional $CONFIO can be minted.
2. **Public identity:** the official Algorand Asset ID is the primary defense against imitation assets.
3. **Real participation:** rewards are tied to verified product use or documented early community contribution, not indiscriminate airdrops.
4. **Visible concentration:** large founder and contributor allocations are disclosed and time-locked rather than obscured.
5. **Supply integrity across chains:** no future chain representation or migration may duplicate the economic supply.

Tokenomics cannot replace product adoption. The long-term relevance of $CONFIO depends on Confío serving real users and establishing useful, legally sustainable token functions.

## 2. On-chain identity and fixed supply

| Parameter | Current state |
| --- | --- |
| Network | Algorand Mainnet |
| Token standard | Algorand Standard Asset (ASA) |
| Name | Confío |
| Unit | CONFIO |
| Asset ID | **3351104258** |
| Decimals | 6 |
| Fixed supply | **1,000,000,000 CONFIO** |
| Manager authority | None |
| Freeze authority | None |
| Clawback authority | None |

[Verify $CONFIO on Pera Explorer](https://explorer.perawallet.app/asset/3351104258/).

The absence of manager authority means the asset parameters and total supply cannot be changed. The absence of freeze and clawback authorities means Confío cannot freeze or forcibly retrieve $CONFIO held in a user’s Algorand account. Algorand’s reserve metadata field does not create minting power and does not change the fixed supply.

Users should verify the Asset ID rather than relying only on the name or ticker.

## 3. Allocation

| Allocation | Tokens | Share | Release policy |
| --- | ---: | ---: | --- |
| Public presale | 74,000,000 | 7.40% | Locked until completion of Phase 3 and the official DEX launch/unlock event |
| Referral and usage rewards | 7,400,000 | 0.74% | Earned and claimed under the active reward rules |
| Cultural Invitation Fund | 15,000,000 | 1.50% | Planned 90-day linear vesting after the presale/DEX trigger |
| Creative Co-Builder | 10,000,000 | 1.00% | Locked until the trigger, then linear vesting over 24 months |
| Founder — Julian Moon | 893,600,000 | 89.36% | Locked until the trigger, then linear vesting over 36 months |
| **Total** | **1,000,000,000** | **100.00%** | Fixed |

The 10,000,000-token Creative Co-Builder allocation was carved out of Julian Moon’s original 903,600,000-token founder allocation. It did not increase total supply. After that reallocation, Julian’s founder allocation is 893,600,000 tokens.

The Cultural Invitation Fund is fixed at 15,000,000 tokens in this version. Any future increase would require a clearly disclosed reallocation from an existing category; the total supply cannot be increased.

## 4. Public presale

The public presale has five price windows. Phase 1 contains three operational sub-rounds; Phases 2 and 3 are standalone rounds.

| Price window | Reference sale price | Fundraising target/cap | Tokens at the stated target |
| --- | ---: | ---: | ---: |
| Phase 1-1 | US$0.20 | US$250,000 | 1,250,000 |
| Phase 1-2 | US$0.25 | US$350,000 | 1,400,000 |
| Phase 1-3 | US$0.30 | US$400,000 | approximately 1,333,333.33 |
| Phase 2 | US$0.50 | US$10,000,000 | 20,000,000 |
| Phase 3 | US$1.00 | US$50,000,000 | 50,000,000 |
| **Total** | — | **Up to US$61,000,000** | **up to 74,000,000 allocated** |

The target-price arithmetic above uses approximately 73,983,333.33 tokens. The remaining approximately 16,666.67 tokens stay inside the fixed 74,000,000-token presale allocation for rounding and final reconciliation; they do not increase the presale allocation.

The targets are maximum program amounts, not fundraising forecasts or commitments. Unsold tokens remain part of the presale allocation until Confío publishes a subsequent disposition policy.

### 4.1 Operational sub-round transitions

The application backend currently represents Phase 1 as one aggregate phase. Phase 1-1, 1-2, and 1-3 are implemented as manually controlled price windows:

- at each scheduled transition, an authorized operator updates the backend price, cap, and displayed sub-round state;
- the presale contract’s active round or price is updated through an on-chain administrator transaction;
- the rewards application’s manually configured presale-price and round snapshot must be updated to keep referral conversions aligned with the same window;
- the transition is not performed automatically merely because a date or fundraising threshold has passed.

The price and round recorded on-chain at the time of a transaction control its token calculation. Operational procedures must reconcile the backend, presale contract, and rewards contract after every transition. Authorized controls can change an active round prospectively, but they cannot increase the fixed one-billion-token supply or the 74,000,000-token presale allocation.

### 4.2 Price interpretation

Presale prices are offering prices for the applicable phase. They are not independently determined valuations, guaranteed market prices, or promises that a DEX will open or remain at the same price.

For arithmetic context only:

| Sale price | Fully diluted value reference |
| ---: | ---: |
| US$0.20 | US$200,000,000 |
| US$0.25 | US$250,000,000 |
| US$0.30 | US$300,000,000 |
| US$0.50 | US$500,000,000 |
| US$1.00 | US$1,000,000,000 |

These figures multiply the phase price by the fixed one-billion-token supply. They do not represent a company valuation, an appraisal, or an expected market capitalization.

### 4.3 Lock and claim policy

Presale purchases create locked token entitlements. The current policy is:

- no presale allocation becomes claimable before Phase 3 is completed and the official DEX launch/unlock event occurs;
- the on-chain unlock is intended to be permanent once executed;
- a purchaser must satisfy the live claim, account, and jurisdictional requirements;
- the definitive presale terms and in-product records control individual purchases.

The presale allocation is therefore not the same as circulating supply before the unlock.

### 4.4 Eligibility

Participation is subject to applicable law, identity and sanctions controls, product terms, and geographic restrictions. Confío’s current implementation excludes U.S. residents and South Korean citizens or residents from the presale. Restrictions may be expanded or changed when required, and technical access does not establish legal eligibility.

Presale proceeds do not back cUSD or cUSD+. User-asset backing must be assessed separately through the relevant stablecoin, reserve, vault, contract, and redemption arrangements.

## 5. Referral and usage rewards

The 7,400,000-token reward pool is intended to reward verified adoption rather than passive wallet creation.

Under the current referral flow:

1. a referred user completes a qualifying top-up of at least US$19 equivalent;
2. the referred user completes a qualifying USDC-to-cUSD conversion of at least US$19 equivalent;
3. the referred user and referrer each become eligible for **US$5 equivalent in $CONFIO**, converted at the active presale reference price;
4. claims and withdrawals are subject to personal identity verification and duplicate-person controls.

Examples:

| Active reference price | Each eligible person | Total per valid pair |
| ---: | ---: | ---: |
| US$0.25 | 20 CONFIO | 40 CONFIO |
| US$0.50 | 10 CONFIO | 20 CONFIO |
| US$1.00 | 5 CONFIO | 10 CONFIO |

The current anti-abuse model uses personal identity evidence rather than phone or device checks alone. A person completes identity verification using a government-issued document and live-selfie liveness and face-matching checks. Duplicate-person detection uses the normalized document identity together with the issuing country. Only the earliest valid referral linked to the same verified identity retains the reward; later duplicate referrals fail.

Reward parameters and qualifying events may change prospectively as the product evolves. The rules displayed in the live application and recorded for a specific reward event control that event. Earned rewards cannot exceed the funded reward pool.

## 6. Cultural Invitation Fund

The Cultural Invitation Fund reserves 15,000,000 $CONFIO for people whose documented hospitality, meals, transport, professional assistance, donations, memberships, creator gifts, or other direct support helped Confío take shape before conventional institutional validation.

This allocation is:

- not a public airdrop;
- not a sale;
- not compensation for employment;
- a limited recognition program for documented early contribution.

Current distribution safeguards are:

- fixed pool: **15,000,000 CONFIO**;
- planned maximum per recipient: **150,000 CONFIO**;
- planned minimum for an included recipient: **1,000 CONFIO**;
- a public review and correction period before the final allocation is committed;
- linear vesting over approximately 90 days after the presale/DEX trigger.

The final scoring methodology, eligible-participant ledger, appeal process, and aggregate reconciliation must be published before distribution. Earlier illustrative scoring tables are not incorporated into this version because they contained overlapping loyalty multipliers and did not constitute a final, internally consistent allocation rule.

The Cultural Invitation Fund is distinct from the product referral program: one recognizes documented pre-product human contribution; the other rewards verified product adoption.

## 7. Creative Co-Builder allocation

**10,000,000 CONFIO (1.00%)** is allocated to Susy Ramirez for long-term creative and community-building contributions.

The allocation is held in a dedicated Algorand vesting application:

- total locked: 10,000,000 CONFIO;
- vesting duration after activation: approximately 24 months;
- vesting start had not been activated as of 23 July 2026;
- claimed amount was zero as of that date.

[Verify the co-builder vesting application, App ID 3359297921, on Pera Explorer](https://explorer.perawallet.app/application/3359297921/).

The vesting contract controls release timing; it does not imply that vested tokens will be sold.

## 8. Founder allocation

**893,600,000 CONFIO (89.36%) belongs to founder Julian Moon.** It is a founder-owned allocation—not a community-governed ecosystem reserve, protocol treasury, or unassigned team pool.

Confío deliberately uses a traditional-startup analogy: the founder began with ownership of the fixed token supply and makes defined portions available through the presale and disclosed community and contributor allocations. Presale participants are purchasing part of that fixed token supply from the founder-led project. This analogy explains the ownership and financing model; **$CONFIO is not company equity**, and purchasing it does not make a holder a shareholder of Confío or an affiliated legal entity.

After vesting, Julian may retain, transfer, or sell his tokens, or use them to fund hiring, development, operations, partnerships, and expansion. Those possible uses do not convert the founder-owned allocation into a separate “ecosystem reserve.”

The allocation is held in a dedicated Algorand vesting application:

- total locked: 893,600,000 CONFIO;
- vesting duration after activation: approximately 36 months;
- vesting start had not been activated as of 23 July 2026;
- claimed amount was zero as of that date.

[Verify Julian Moon’s founder vesting application, App ID 3359301443, on Pera Explorer](https://explorer.perawallet.app/application/3359301443/).

For scale, straight-line vesting over 36 months is economically equivalent to approximately 24.82 million tokens becoming vested per month on average. Vesting is continuous over time, not a scheduled monthly sale, and vested does not mean sold.

The high concentration makes public wallet mapping, vesting-state disclosure, transfer transparency, and disciplined treasury reporting more important than the choice of blockchain.

## 9. Unlocks and circulating supply

Allocation is not circulation.

The previous 2025 edition described approximately 96.4 million tokens, or 9.64%, as “initial circulating supply.” That figure combined the full presale, reward, and Cultural Invitation allocations even though they do not all become liquid at the same time. It is therefore replaced by the following definition:

> **Circulating supply at DEX launch equals the tokens actually unlocked, claimed, vested, and transferable at that time—not the maximum size of every potentially distributable category.**

The actual launch figure will depend on:

- presale entitlements that are unlocked and claimed;
- referral and usage rewards that have been validly earned and claimed;
- the portion, if any, of the Cultural Invitation Fund vested by the measurement timestamp;
- any founder or co-builder amount vested after activation;
- any liquidity or market-making allocation disclosed for the launch.

Before an official DEX launch, Confío should publish a dated supply snapshot that reconciles:

1. total fixed supply;
2. balances held in vesting and reward applications;
3. locked presale entitlements;
4. earned but unclaimed rewards;
5. unlocked and transferable supply;
6. liquidity and market-making balances;
7. any excluded, lost, or otherwise non-circulating balances.

## 10. Multi-chain policy and supply integrity

$CONFIO is currently an Algorand ASA. cUSD remains on Algorand for payments, while cUSD+ uses BNB Smart Chain because its underlying savings integration is built around Ondo USDY, USDT, and EVM contracts.

This document does not announce a $CONFIO migration or a BNB Smart Chain version. The canonical chain should be reconsidered only when token utility, DEX readiness, liquidity design, exchange requirements, and actual use across Confío’s products provide enough evidence.

If $CONFIO later gains a representation on another chain:

- already distributed Algorand tokens must not be duplicated through an unconditional airdrop;
- a lock-and-mint, burn-and-claim, or equivalent supply-preserving mechanism must connect old and new circulation;
- each claim must be protected against replay and double issuance;
- undistributed allocations may be first distributed on the selected chain without creating a second circulating copy;
- aggregate supply and circulation across all chains must remain publicly reconcilable.

The fixed one-billion-token economic limit applies across any future representations, not separately to each chain.

## 11. Utility and value-accrual boundary

$CONFIO’s current and intended role includes community recognition, product rewards, and future ecosystem participation or governance. Exact utility may develop with the product and must be implemented and disclosed before users rely on it.

$CONFIO does **not** currently provide:

- ownership of Confío or any affiliated legal entity;
- a claim on company assets, revenue, yield, or profits;
- a claim on cUSD or cUSD+ reserves;
- a right to Ondo USDY or Ondo Stocks;
- guaranteed voting power over regulated providers or issuer obligations;
- guaranteed buybacks, burns, staking returns, dividends, or fee sharing;
- a guaranteed DEX or centralized-exchange listing;
- a guaranteed price or liquidity floor.

Confío’s operating revenue—including merchant or payroll fees, its share of cUSD+ reference-price appreciation, fiat-provider economics, and any fee from Ondo Stocks transactions—does not automatically accrue to $CONFIO holders. Any future buyback, burn, fee-linked utility, or revenue-linked mechanism would require a separate public policy and appropriate legal review.

## 12. Disclosure before a DEX listing

Before an official DEX listing or presale unlock, the definitive listing disclosure should publish:

- the launch date, network, official contract or Asset ID, and trading venue;
- the exact unlocked and circulating supply at a stated timestamp;
- wallet and application mapping for every material allocation;
- vesting start transactions and current vesting state;
- presale claims and unclaimed entitlements;
- reward and Cultural Invitation distributions;
- liquidity-provider and market-making allocations and their restrictions;
- treasury custody and governance arrangements;
- any change to token utility, chain policy, or legal eligibility;
- material conflicts, related-party arrangements, and market-support agreements.

No promotional price should substitute for this supply disclosure.

## 13. Material risks

| Risk | Why it matters |
| --- | --- |
| Founder concentration | Julian Moon owns an 89.36% founder allocation. Vesting reduces immediate liquidity but does not remove control, perception, or future selling risk. |
| Presale valuation | Phase prices imply large fully diluted value references before an external market establishes price. |
| Unlock pressure | Presale claims and later vesting can increase transferable supply substantially. |
| Utility uncertainty | Product success does not automatically create demand for $CONFIO unless useful token functions are implemented. |
| Liquidity | A DEX pool may be shallow, volatile, or unavailable; quoted price can diverge from executable price. |
| Regulatory classification | Authorities may classify a token, presale, reward, or utility differently across jurisdictions or over time. |
| Operational and contract risk | Presale, reward, vesting, claim, bridge, or migration software can contain defects or be operated incorrectly. |
| Chain and provider risk | Algorand, a future representation chain, wallets, indexers, exchanges, and infrastructure providers can fail or restrict access. |
| Migration risk | A poorly designed migration can duplicate supply, strand holders, or create competing “official” assets. |
| Fraud and impersonation | Tokens with similar names or tickers can mislead users; the Asset ID is the authoritative identifier. |
| No automatic value capture | Confío may grow without $CONFIO receiving company revenue or product yield. |

This table is not exhaustive.

## 14. Legal disclaimer

This document is provided for informational and technical-reference purposes only. It is not investment, legal, tax, accounting, or financial advice and is not a prospectus, offer, solicitation, recommendation, or promise of returns.

$CONFIO is not a bank deposit, is not insured, and may lose some or all of its market value. It does not represent equity, debt, a deposit claim, or a guaranteed right to revenue, profit, yield, liquidity, redemption, or listing. Availability, sale, rewards, claims, transfers, and utility may be restricted by law, jurisdiction, identity, sanctions, provider policy, or definitive product terms.

Presale participation is governed by separate definitive terms. If this document conflicts with applicable law, an executed agreement, the on-chain asset parameters, or the definitive terms of a specific transaction, the applicable law and transaction-specific terms control to the extent required.

Forward-looking statements—including product plans, exchange plans, utilities, fundraising targets, and ecosystem uses—are uncertain and may change.

## 15. Sources and verification

1. Pera Explorer, $CONFIO Asset ID 3351104258: fixed supply and current asset parameters.
   https://explorer.perawallet.app/asset/3351104258/

2. Confío public repository, token specification and deployment tooling.
   https://github.com/caesar4321/Confio/blob/main/contracts/confio/CONFIO_TOKEN_SPEC.md

3. Confío public repository, aggregate backend phases and the manually operated on-chain round and price controls used for presale sub-rounds.
   https://github.com/caesar4321/Confio/blob/main/presale/management/commands/setup_presale.py
   https://github.com/caesar4321/Confio/blob/main/contracts/presale/admin_presale.py
   https://github.com/caesar4321/Confio/blob/main/contracts/rewards/confio_rewards.py

4. Confío public repository, presale contract and irreversible unlock design.
   https://github.com/caesar4321/Confio/blob/main/contracts/presale/README.md

5. Confío public repository, current referral reward configuration and identity policy.
   https://github.com/caesar4321/Confio/blob/main/achievements/services/referral_rewards.py
   https://github.com/caesar4321/Confio/blob/main/docs/security/REFERRAL_REWARD_IDENTITY_POLICY.md

6. Pera Explorer, Creative Co-Builder vesting App ID 3359297921.
   https://explorer.perawallet.app/application/3359297921/

7. Pera Explorer, Julian Moon founder vesting App ID 3359301443.
   https://explorer.perawallet.app/application/3359301443/

8. Confío public repository, current presale geographic restrictions.
   https://github.com/caesar4321/Confio/blob/main/docs/legal/GEO_BLOCKING.md

9. Confío global whitepaper, product architecture and chain policy.
    https://github.com/caesar4321/Confio/blob/main/docs/whitepaper/README.md

### Document provenance

Prepared from the 2025 English tokenomics, the current public repository, Algorand Mainnet state, the current Confío whitepaper, and the product and strategy decisions reflected in the repository as of 23 July 2026.
