# Confío: Latin America’s Trusted Digital Dollar Platform

**Dollar finance built for Latin America — user-controlled money, distributed through trust.**

Confío is a fully open-source, non-custodial financial application built for Latin America’s dollar reality. It combines local fiat access, yield-bearing dollars, transfers, payments, payroll, and eligible access to Ondo Stocks in a familiar mobile experience without requiring users to understand crypto.

**Global reference · Version 4.3 · August 2026**<br>
Julian Moon · Founder & CEO<br>
[confio.lat](https://confio.lat) · [GitHub](https://github.com/caesar4321/Confio)

*Lo tuyo, tuyo. · Blockchain inside. Simple as PayPal.*

**Authoritative original:** This English document is the sole authoritative version of the Confío whitepaper. Translations are provided for convenience and may lag behind this original. If a translation differs from the English text, the English text controls.

This paper is the current global reference for Confío’s product architecture, strategy, operating model, and material risks. Detailed $CONFIO allocation and vesting terms remain in the separate tokenomics document.

<details>
<summary><strong>Contents</strong></summary>

1. [Executive summary](#1-executive-summary)
2. [The market thesis](#2-the-market-thesis)
3. [The BNB Smart Chain product system](#3-the-bnb-smart-chain-product-system)
4. [Why BNB Smart Chain](#4-why-bnb-smart-chain)
5. [cUSD and cUSD+: money and savings](#5-cusd-and-cusd-money-and-savings)
6. [Payments, payroll, and Ondo Stocks](#6-payments-payroll-and-ondo-stocks)
7. [$CONFIO on BNB Smart Chain](#7-confio-on-bnb-smart-chain)
8. [Wallet, security, and open-source architecture](#8-wallet-security-and-open-source-architecture)
9. [Users, distribution, and go-to-market](#9-users-distribution-and-go-to-market)
10. [Business model](#10-business-model)
11. [Compliance and operating model](#11-compliance-and-operating-model)
12. [Risks and mitigations](#12-risks-and-mitigations)
13. [Roadmap and current status](#13-roadmap-and-current-status)
14. [Legal disclaimer](#14-legal-disclaimer)
15. [Endnotes](#endnotes)

</details>

---

## 1. Executive summary

Confío is a fully open-source, non-custodial digital-dollar application for Latin America. It gives users a familiar mobile interface to hold, save, send, and spend without requiring them to manage gas tokens, memorize blockchain addresses, or navigate exchange screens. <sup>[3]</sup>

> **Product thesis**
>
> The winning consumer dollar platform in Latin America will not ask users to become crypto experts. It will combine verifiable on-chain ownership with the clarity, recovery flows, local payment methods, and human support expected from a modern fintech. The contest will be decided not by feature parity but by distribution, trust, and local fit. Confío enters with a founder-led Spanish-language channel of approximately 480,000 people, a years-long public relationship with the region it serves, and effectively zero paid-media spend to date.

Confío’s product system now settles entirely on BNB Smart Chain:

| Component | Primary job | Design |
| --- | --- | --- |
| USDT | External funding, liquidity, and exit asset. | Incoming BSC-USDT is automatically converted while the app is active. Users do not manage a normal raw-USDT balance in the consumer interface. |
| cUSD | Universal payment dollar. | Upgradeable, 1:1 USDT-backed BSC token for payments and for users who are not eligible for USDY exposure. It is the sole external 0.9% conversion-fee perimeter. |
| cUSD+ | Eligible dollar savings wrapper. | Upgradeable USDY-backed accumulating shares for Ondo-eligible users. Internal cUSD↔cUSD+ conversion is fee-free and sponsor-gated. |
| Ondo Stocks | Eligible tokenized-market access. | Users buy from cUSD+ and sell proceeds back into cUSD+ through a dedicated, source-verified router. Every completed purchase and sale carries an explicit 0.30% Confío fee. |
| $CONFIO | Community and ecosystem token. | Fixed-supply BEP-20 on BNB Smart Chain with a cUSD-funded on-chain presale. It does not back user dollar balances. |

The single-network design is not a generic chain bet. It follows the product’s economic center of gravity: Ondo Finance made its USDY, InstantManager, price oracle, and USDT subscription/redemption path available on BNB Smart Chain. Confío then consolidated payments, payroll, transfers, and $CONFIO onto the same network to eliminate chain switching and fragmented liquidity. <sup>[7, 8, 10]</sup>

As of 23 July 2026, Confío records 8,004 users who completed phone verification and 177 users who completed Didit identity verification by submitting a government-issued identity document and capturing a live selfie for liveness and face-matching checks. The Didit flow has a 61.5% completion rate among users who began it. Confío also records 2,094 push-reachable devices, with 2,092 of those devices used within the last 30 days. These are internal operating metrics rather than independently audited figures and should not be read as funded-user or monthly-active-user counts. <sup>[14]</sup>

The cUSD and cUSD+ vaults, Ondo Stocks router, sponsored-transaction delegate, $CONFIO token, replacement $CONFIO presale vault, $CONFIO reward vault, merchant-payment contract, and payroll vault are deployed and source-verified on BNB Smart Chain. The contracts are wired into the production application, with runtime controls governing staged user exposure. The cUSD+ vault is registered for Ondo’s permissioned infrastructure and integrates production USDY, USDT, InstantManager, and oracle contracts. <sup>[8, 9, 17, 18]</sup>

## 2. The market thesis

### 2.1 A dollar-access problem, not a crypto-awareness problem

Latin America is not one homogeneous monetary crisis. Some users need protection from local-currency volatility; others need affordable cross-border settlement, a safe place for dollar savings, or a practical way to pay and be paid. What connects these markets is demand for a reliable dollar unit and dissatisfaction with the friction surrounding it. Stablecoin adoption across the region shows that this behavior is already on-chain rather than merely theoretical. <sup>[2]</sup>

| Market | Observed dollar need | Product implication |
| --- | --- | --- |
| Argentina | Repeated inflation and capital controls, together with the institutional memory of the 2001 *corralito* and forced conversion of dollar deposits, taught households to value access and control as much as nominal yield. Most recent exchange restrictions have eased, but the historical trust deficit remains relevant. <sup>[19]</sup> | A dollar product must make custody boundaries, withdrawal rights, pricing, and rule changes unusually clear. |
| Venezuela | Extreme inflation pushed the U.S. dollar into both store-of-value and everyday payment functions, creating a highly dollarized but operationally fragmented economy. <sup>[20]</sup> | Dollar access and payment utility are immediate needs, while sanctions, provider availability, and compliance require tighter controls. |
| Bolivia | The IMF’s 2025 assessment described usable foreign-exchange reserves as close to zero, a widening parallel-rate gap, and severe limits on private-sector access to official-rate dollars. <sup>[21]</sup> | Reliable access, transparent local pricing, and interoperable QR rails can solve a daily liquidity problem rather than a speculative use case. |
| Peru | Households already hold tens of billions of dollars in foreign-currency deposits, while Yape, PLIN, and interoperable QR systems have normalized mobile payments. <sup>[22]</sup> | The opportunity is not to teach users to want dollars, but to provide portable dollar savings and payments with familiar local entry points. |
| Mexico | Foreign-currency bank deposits and approximately US$62.5 billion in annual remittances demonstrate both dollar savings and cross-border demand. <sup>[23]</sup> | SPEI access, dollar balances, yield, and family transfers can live in one consumer product. |
| Colombia | The United States supplies more than half of remittance inflows, while Colombia hosts approximately 2.8 million Venezuelans. <sup>[24, 25]</sup> | PSE, Nequi, and local bank access can connect international remittances with the Colombia–Venezuela family-transfer corridor. |
| United States and Spain | These are two of the most important origin markets for Latin American remittances. The United States accounts for 35.7% of South American inflows; Europe accounts for 36.2%, including 19.7 percentage points from Spain. <sup>[24]</sup> | Card and SEPA access should connect diaspora earnings to recipients’ dollar balances without forcing both sides into a trading product. |

The result is a regional **dollar reflex**: people seek USD exposure even when access is expensive, informal, or operationally fragile.

### 2.2 Remittances are a balance-sheet opportunity

Latin America and the Caribbean received an estimated US$173.7 billion in remittances in 2025. <sup>[1]</sup> Most products treat a remittance as a one-time transfer. Confío treats it as the start of a financial relationship: the recipient can retain dollars, earn variable yield through cUSD+, send to contacts, pay a merchant, or withdraw through a local rail.

This changes the objective from moving money once to retaining trusted balances over time.

### 2.3 The consumer-finance convergence

Exchanges, fintechs, wallets, and stablecoin companies are converging on similar consumer products: dollar balances, yield, cards, transfers, and tokenized assets. As product menus converge, many competitors rely on cashback or acquisition subsidies to win the same crypto-aware users. Confío competes through a distribution channel and local trust relationship that are difficult to replicate, paired with country-specific rails rather than a generic global interface. <sup>[15, 16]</sup>

### 2.4 The deeper problem: *falta de confianza*

Latin American users have experienced bank freezes, currency controls, failed fintechs, informal brokers, hidden spreads, and crypto platforms designed around speculation. The resulting problem is not only financial access; it is lack of trust.

Confío’s answer has two layers:

1. **Verifiable control:** the user’s wallet key is generated on the user’s device and is not held by Confío.
2. **Human trust:** Spanish-first education, clear pricing, local payment methods, visible leadership, and support that understands the user’s context.

*Lo tuyo, tuyo* is therefore both a brand promise and an architectural constraint.

## 3. The BNB Smart Chain product system

Confío presents one dollar experience while using different assets for different jobs on the same network.

| User action | Asset or contract | What happens on-chain |
| --- | --- | --- |
| Add dollars | cUSD or cUSD+ | A fiat provider or external wallet delivers BSC-USDT. The app automatically converts it into cUSD for an Ondo-ineligible user or cUSD+ for an eligible user, charging the same 0.9% Confío conversion fee. |
| Save | cUSD↔cUSD+ wrapper boundary | Eligible users can move cUSD into USDY-backed cUSD+ without a conversion fee; the reverse internal conversion is also free. Both paths require a Confío-sponsored transaction. |
| Send | cUSD or cUSD+ | Like-for-like transfers stay in the sender’s asset. Cross-eligibility friend transfers convert cUSD and cUSD+ internally without a fee so the recipient receives the asset appropriate for their jurisdiction. |
| Pay a merchant | cUSD+, cUSD, or $CONFIO | The payment contract pays the merchant, enforces the separate 0.9% Pay fee, and records fee accrual on-chain. Raw USDT remains a legacy allowlisted token but is not authorized by the production backend. |
| Run payroll | cUSD+ or cUSD | Businesses fund asset-separated escrow; authorized delegates sign payouts, and recipients receive cUSD+ or cUSD according to eligibility. |
| Buy or sell an Ondo Stock | cUSD+, Ondo Stock token, and stock router | A sponsored transaction settles through Ondo Global Markets. Purchases redeem the required cUSD+ into USDT and deliver the stock token to the user; sales return net proceeds to cUSD+. |
| Participate in $CONFIO presale | cUSD | A sponsored transaction purchases an allocation against an immutable on-chain price curve without forcing the user through an extra cUSD/cUSD+→USDT redemption. |
| Earn and claim rewards | $CONFIO RewardVault | Eligible rewards are recorded cumulatively off-chain and become claimable through signed on-chain claims after the DEX unlock. |

### 3.1 Public BNB Smart Chain deployments

All contracts listed below are live on BNB Smart Chain mainnet and source-verified. The replacement presale, reward, merchant-payment, and payroll addresses are configured in the production application.

| Contract | Address |
| --- | --- |
| cUSD vault proxy | [`0x6101cC370635cF2c7f2725EaB010aC407A8d543F`](https://bscscan.com/address/0x6101cC370635cF2c7f2725EaB010aC407A8d543F#code) |
| cUSD+ vault proxy | [`0x3C29417eb4314155e63d4C7D4507852b87763Ed1`](https://bscscan.com/address/0x3C29417eb4314155e63d4C7D4507852b87763Ed1#code) |
| Ondo Stocks router (UUPS proxy) | [`0x40c8e134BCAf44EEf9e7D184846F36c9862329c3`](https://bscscan.com/address/0x40c8e134BCAf44EEf9e7D184846F36c9862329c3#code) |
| Sponsored-batch delegate | [`0xC06BD197b34a587026615C6AEd21301F5E99bc00`](https://bscscan.com/address/0xC06BD197b34a587026615C6AEd21301F5E99bc00#code) |
| $CONFIO token | [`0xCcEb3F6127FA9160a26A1B85857Ca4C9D56B3fa8`](https://bscscan.com/token/0xCcEb3F6127FA9160a26A1B85857Ca4C9D56B3fa8) |
| $CONFIO presale vault | [`0x8c3A1fffcFfE1B07108486Be85C0dC42B4aC0358`](https://bscscan.com/address/0x8c3A1fffcFfE1B07108486Be85C0dC42B4aC0358#code) |
| $CONFIO reward vault | [`0x812b8d86952123bED0a33E92a76211cbbACDe730`](https://bscscan.com/address/0x812b8d86952123bED0a33E92a76211cbbACDe730#code) |
| $CONFIO vesting vault | [`0xb873e4dbFdf25EcB0F663CA9154F7384d780bE7A`](https://bscscan.com/address/0xb873e4dbFdf25EcB0F663CA9154F7384d780bE7A#code) |
| Invitation escrow | [`0xe6c49CcEb57b86dfE2F597053f8f475F18AcDb59`](https://bscscan.com/address/0xe6c49CcEb57b86dfE2F597053f8f475F18AcDb59#code) |
| Merchant-payment contract | [`0x942BF5F3C9079Ab29492324B9F1E501Db5B830bA`](https://bscscan.com/address/0x942BF5F3C9079Ab29492324B9F1E501Db5B830bA#code) |
| Payroll vault | [`0x851e1a56De5c0ADBB75e904B2E7325e132692027`](https://bscscan.com/address/0x851e1a56De5c0ADBB75e904B2E7325e132692027#code) |

### 3.2 Why one network matters

The consolidation removes three recurring sources of consumer friction:

- no bridge is required between the primary dollar balance, savings, payments, payroll, and $CONFIO;
- one EVM address can receive the user’s funding, product balances, and ecosystem token; and
- one sponsored-transaction system can pay network fees across the product.

Users still face product-specific eligibility and provider rules. A unified chain does not make all assets economically or legally identical.

### 3.3 Local and international access

Koywe provides live local rails across seven Latin American markets, including combinations of bank transfers, Alias/CVU, SPEI, interoperable QR, PSE/Nequi, and PIX according to the country and payment method. Guardarian provides SEPA access in the eurozone and USD purchases through Visa, Mastercard, Apple Pay, and Google Pay. Additional providers are integrated only after commercial and production capabilities are confirmed. <sup>[13]</sup>

## 4. Why BNB Smart Chain

### 4.1 The product followed Ondo’s infrastructure

The primary reason is Ondo Finance. Confío did not choose a network and then search for financial products. cUSD+ was designed around USDY, and Ondo deployed the production USDY token, InstantManager, price oracle, USDT subscription/redemption route, and Global Markets settlement infrastructure on BNB Smart Chain. Keeping the Confío product system beside that infrastructure provides direct routes into USDY-backed savings and eligible Ondo Stocks access. <sup>[7, 8, 10, 18]</sup>

### 4.2 Consumer-scale economics and liquidity

BNB Smart Chain adds:

- broad USDT liquidity and familiar EVM infrastructure;
- low transaction costs suitable for sponsored consumer activity;
- mature wallets, RPC providers, explorers, exchanges, and developer tooling;
- access to BNB Chain’s payments, wallet, DeFi, and RWA ecosystem; and
- one environment for cUSD, cUSD+, USDT, $CONFIO, merchant payments, and payroll. <sup>[5, 6, 12]</sup>

Chain ecosystem size does not create product demand by itself. Confío’s value still depends on users, retained balances, reliable exits, distribution, security, and transparent economics.

### 4.3 Network and governance trade-offs

BNB Smart Chain has different decentralization and operational characteristics from other networks. Network interruption, validator coordination, congestion, gas-price changes, RPC failures, or ecosystem-level policy changes remain possible. Confío mitigates these risks with sponsored transactions, multiple RPC paths, explicit emergency exits, non-custodial ownership, and public contract state, but it cannot eliminate base-network risk.

## 5. cUSD and cUSD+: money and savings

cUSD is the universal payment dollar, backed 1:1 by USDT in its deployed UUPS vault. cUSD+ is an accumulating dollar-denominated savings share backed by USDY in the existing upgraded cUSD+ proxy. The app selects cUSD for users who are not eligible for USDY exposure and cUSD+ for eligible users, while presenting one dollar experience rather than vault shares, gas, approvals, or oracle calculations.

### 5.1 Deposit and redemption flow

| Entry | Exit |
| --- | --- |
| 1. USDT reaches the user’s BSC address from a ramp or an external wallet. | 1. The user requests local-currency withdrawal or an external USDT send. |
| 2. A user-authorized sponsored batch calls the appropriate fee-bearing mint path. | 2. cUSD burns directly, or cUSD+ burns and redeems USDY through InstantManager. |
| 3. The cUSD fee perimeter retains 0.9% and mints cUSD, or returns net USDT to cUSD+ for USDY subscription. | 3. The cUSD fee perimeter retains 0.9% of the gross exit value. |
| 4. The user receives cUSD if Ondo-ineligible or cUSD+ if eligible. | 4. Net USDT goes to the designated external wallet or ramp address. |

The cUSD vault is the only external conversion-fee perimeter. Its fee is capped in code at 90 basis points. Minting always requires an authorized sponsor; fee-free redemption is restricted to the cUSD+ savings boundary; ordinary fee-bearing redemption remains permissionless so a holder can exit without Confío’s sponsor. cUSD+ follows the same exit principle: normal app minting and fee-free internal conversion require a sponsor, while fee-bearing redemption to USDT is permissionless.

The cUSD+ vault, not the end user, is the permissioned USDY purchaser. Users hold cUSD+, not raw USDY. Minting is subject to product eligibility. Internal cUSD↔cUSD+ conversion is fee-free only because value stays inside the Confío dollar system; it does not create a free external USDT path.

### 5.2 Accumulating value and yield share

USDY’s reference price is designed to appreciate as underlying yield accrues. On each relevant interaction, the vault updates the cUSD+ reference value:

- 85% of positive USDY reference-price appreciation increases the cUSD+ holder reference value; and
- 15% becomes vault surplus available to Confío.

The share count does not increase. The dollar reference value per cUSD+ share rises. Yield is variable, may change, and is not guaranteed. <sup>[7, 11]</sup>

### 5.3 Backing and oracle controls

The vault exposes public views for total obligations, backing ratio, and surplus. Its accounting rounds in favor of backing and restricts fee collection to provable surplus. USDY backing cannot be swept by the owner.

If the USDY oracle falls or moves beyond a configured guard threshold, value-moving paths halt. Multi-party governance must then record an evidence-linked decision to accept verified appreciation or rebaseline after a verified oracle fault. This reduces automated mispricing risk but cannot remove oracle, issuer, or governance risk.

### 5.4 One balance experience across eligibility

cUSD+ is the preferred representation for eligible users because value can continue accumulating until it is spent. cUSD is the universal payment representation for users who cannot receive USDY exposure. Like-for-like friend transfers remain direct; when sender and recipient eligibility differs, the sponsored flow converts cUSD and cUSD+ internally without charging the 0.9% external conversion fee. Raw USDT is an entry/exit intermediate and emergency asset, not a normal selectable consumer balance.

## 6. Payments, payroll, and Ondo Stocks

### 6.1 Person-to-person transfers

The server prepares the exact calls, the user signs them, and Confío sponsors network gas. Depending on the sender’s balance and the recipient’s eligibility:

- cUSD+ transfers directly to an eligible Confío recipient;
- cUSD transfers directly to a recipient who should hold cUSD; or
- a sponsor-authorized, fee-free cUSD↔cUSD+ conversion delivers the appropriate representation across the eligibility boundary.

Confío does not take a platform fee on person-to-person transfers. The 0.9% conversion fee applies only when value enters from USDT or leaves to USDT, regardless of whether that USDT came from or goes to a fiat ramp or an on-chain wallet.

### 6.2 Merchant payments

A merchant charges in **Confío dollars** or **$CONFIO**, quoted as a token count rather than a dollar amount. Dollar settlement uses cUSD+ or cUSD according to the payer and merchant route.

The payment contract retains raw USDT only as a legacy compatibility token. Once the conversion perimeter is enabled, Confío’s backend does not authorize raw-USDT Pay calls, preventing Pay from becoming a route around the mandatory USDT↔cUSD conversion fee.

The payment contract calculates the 0.9% merchant fee, pays the merchant net amount directly, and accrues only earned fees in the contract for transparent collection. Confío’s backend signs a short-lived authorization over the exact payment terms, and the contract records settlement against the invoice identifier itself. Exactly one payment can settle an invoice, and an identifier cannot be consumed by anyone the backend has not authorized. Each invoice also records the single network permitted to settle it, so one charge cannot be paid twice across networks. The payer’s approval and payment execute atomically in a sponsored batch.

### 6.3 Payroll and mass payouts

Businesses can hold working capital as cUSD+ or cUSD in asset-separated escrow. The business authorizes delegates to sign specific payouts. Eligible recipients can receive cUSD+; ineligible recipients receive cUSD through the fee-free internal conversion boundary. A legacy raw-USDT pool remains only for draining or migrating old escrow, while payroll fee accounting stays separate from business principal.

### 6.4 Ondo Stocks

Confío integrates eligible access to Ondo Stocks through Ondo Global Markets on BNB Smart Chain. The dedicated UUPS `ConfioStockRouter` proxy is deployed and source-verified at [`0x40c8e134BCAf44EEf9e7D184846F36c9862329c3`](https://bscscan.com/address/0x40c8e134BCAf44EEf9e7D184846F36c9862329c3#code). Its upgrade authority is held by the same 3-of-5 Safe that owns the router, allowing Ondo settlement migrations without changing the whitelisted purchaser address. Product access remains subject to Ondo eligibility, jurisdiction, market availability, provider terms, and Confío’s staged activation controls. <sup>[17, 18]</sup>

The router connects stock trading directly to the user’s cUSD+ balance:

- **Purchase:** the router redeems the authorized amount of cUSD+ into USDT, retains the explicit Confío fee, settles the attested purchase through Ondo Global Markets, and delivers the resulting stock token directly to the user’s wallet.
- **Sale:** the router sells the user-authorized stock token through Ondo Global Markets, deducts the explicit Confío fee from actual USDT proceeds, and subscribes the net amount back into cUSD+ for the user.

Every completed purchase and sale charges a fixed **30 basis points (0.30%)** Confío fee in USDT. The rate is fixed in the current implementation, while any implementation upgrade requires the owner Safe. The user-authorized transaction also carries a maximum-fee bound, and any excess USDT created by cUSD+ price movement or settlement conversion is returned rather than retained as a second hidden fee. The router separately accounts for earned fees and does not retain trade principal or stock tokens after successful settlement.

## 7. $CONFIO on BNB Smart Chain

$CONFIO is the community and ecosystem token of Confío. It is not a stablecoin, does not represent a bank deposit, and does not back USDT, cUSD+, or USDY.

### 7.1 Fixed-supply token

The current BNB Smart Chain token contract has a fixed initial supply of 1,000,000,000 CONFIO. The contract has no owner, no post-deployment mint function, and no pause function; the complete initial supply was created once at deployment to the multi-party treasury. ERC-20 permit and voluntary burn are the only extensions, so total supply can decrease but cannot increase. <sup>[17]</sup>

**Canonical BSC contract:** [`0xCcEb3F6127FA9160a26A1B85857Ca4C9D56B3fa8`](https://bscscan.com/token/0xCcEb3F6127FA9160a26A1B85857Ca4C9D56B3fa8)

The on-chain token name is deliberately the ASCII **“Confio”**, while the accented **“Confío”** remains the product and brand name. This avoids inconsistent HTML escaping and rendering of non-ASCII metadata across explorers, wallets, and decentralized exchanges. Readers should use only the canonical address above. <sup>[17]</sup>

Allocation, founder ownership, vesting, presale rights, and concentration risks are disclosed in the separate authoritative English tokenomics. The founder allocation is a founder allocation; custody in a distribution treasury does not reclassify it as an undefined ecosystem reserve.

### 7.2 On-chain presale

The replacement BSC presale vault accepts cUSD and prices purchases on an immutable piecewise-linear curve tied to cumulative tokens sold:

| Cumulative presale allocation | Curve price |
| --- | --- |
| 0–4 million CONFIO | US$0.20 → US$0.30 |
| 4–24 million CONFIO | US$0.30 → US$0.70 |
| 24–74 million CONFIO | US$0.70 → US$1.30 |

The curve segments have no administrative repricing function. The contract charges the integral under the curve, records the allocation, prevents split-purchase discounts through its pricing math, and opens claims only after sufficient CONFIO funding. Participation remains subject to eligibility, geographic controls, and the presale terms. <sup>[17]</sup>

The replacement contract was initialized with the exact pre-deployment purchase history, so migrated purchases continue to push the same cumulative curve rather than resetting the price. It is funded for the migrated claim obligation; the superseded vault is paused.

**Presale contract:** [`0x8c3A1fffcFfE1B07108486Be85C0dC42B4aC0358`](https://bscscan.com/address/0x8c3A1fffcFfE1B07108486Be85C0dC42B4aC0358#code)

### 7.3 Rewards and DEX-locked claims

Confío’s reward system separates accrual from distribution. When reward accrual is enabled, qualifying activity is recorded in Confío’s database and dollar-denominated rewards are converted into CONFIO at the live on-chain presale-curve price. This avoids maintaining a manual token price and does not move tokens on-chain before the DEX launch.

At claim time, the backend signer issues a short-lived EIP-712 authorization for the user’s cumulative earned amount. The RewardVault subtracts the amount already claimed and pays only the difference, making the cumulative total the replay guard. Short deadlines limit the life of a signature if an entitlement must be corrected downward.

Claims are locked until the DEX launch. Before claims open, the multi-party treasury must fund a CONFIO tranche, the claim-signer and client claim flow must be active, and governance must call the one-way `unlockClaims()` function. User claims can then be submitted through Confío’s sponsored-transaction flow.

> **Treasury-controlled reward pool**
>
> The RewardVault is not a trustless escrow. Reward entitlements remain discretionary treasury obligations: its governance owner can rotate the signer, pause claims, and withdraw funds, including after the one-way DEX unlock. Users therefore rely on the treasury to reconcile database obligations, fund the pool, and keep valid claims available. The signer’s exposure is limited operationally by short signature deadlines and by funding the vault in working tranches, but these controls do not remove treasury trust.

**Canonical RewardVault:** [`0x812b8d86952123bED0a33E92a76211cbbACDe730`](https://bscscan.com/address/0x812b8d86952123bED0a33E92a76211cbbACDe730#code)

## 8. Wallet, security, and open-source architecture

### 8.1 Non-custodial wallet model

Confío generates the user’s EVM key on the user’s device. Confío’s server does not hold that private key. Encrypted recovery material is designed for the user’s personal cloud account, so recovery does not require Confío to maintain a central vault of user keys. <sup>[3, 4]</sup>

> **Ni siquiera nosotros**
>
> Confío never holds the user’s wallet key, so Confío cannot sign an ordinary wallet transaction as that user. Product contracts and issued assets still have their own disclosed eligibility, pause, freeze, upgrade, or governance controls. Non-custodial keys do not mean control-free financial products.

### 8.2 Sponsored transactions

Users do not need to acquire BNB to use the normal product flows. Confío uses EIP-7702 user authorizations and a deployed, ownerless batch delegate so that the user signs the intended calls while Confío’s sponsor pays gas. Approvals and actions can be executed atomically, reducing standing allowance risk. <sup>[8, 17]</sup>

The sponsor cannot choose arbitrary calls. Server policy restricts destinations, selectors, amounts, recipients, deadlines, and daily limits before broadcast. Emergency fallback paths and direct exits remain important because sponsorship is an application service, not a blockchain guarantee.

### 8.3 Open source and public verifiability

The mobile application, backend, smart contracts, deployment records, and tests are publicly available. Deployed contracts are source-verified where supported, allowing reviewers to compare public source and live bytecode. <sup>[3, 8, 9, 17]</sup>

Security is pursued through open verifiability and conservative controls rather than obscurity:

- unit, fork, invariant/fuzz, adversarial, differential, and upgrade-rehearsal tests;
- public source and deployment records;
- multi-party governance for privileged operations;
- bounded fee collection and non-sweepable backing;
- oracle guards, pauses, replay protection, slippage limits, and explicit emergency paths; and
- feature flags and canary limits for production rollout.

No review method eliminates smart-contract or operational risk.

### 8.4 Upgradeability and governance

The cUSD and cUSD+ vaults remain upgradeable. cUSD+ permanently depends on external Ondo contracts that may migrate or change, while cUSD is the shared payment and fee perimeter used across product contracts. Irreversible immutability could strand users or freeze an ecosystem-wide integration fault. Upgrades are therefore controlled through multi-party governance, public implementations, storage-layout checks, and verifiable transaction history.

Other components use narrower designs where appropriate. The $CONFIO token and presale price curve are non-upgradeable; the replacement payment, payroll, invite, and presale contracts restrict administrative power to defined operations such as pausing new activity, rotating sponsors, or collecting provably accrued fees.

## 9. Users, distribution, and go-to-market

### 9.1 Current operating metrics

| Metric | Snapshot | Definition |
| --- | ---: | --- |
| Phone-complete users | 8,004 | Users who completed phone verification. |
| Didit-verified users | 177 | Users who submitted a government-issued identity document and completed live-selfie liveness and face matching. |
| Identity-verification completion | 61.5% | Share of users who completed the Didit flow among those who started it. |
| Push-reachable devices | 2,094 | Devices currently addressable through push notifications. |
| Used in the last 30 days | 2,092 | Push-reachable devices recorded as used within the preceding 30 days; not presented as a standardized MAU figure. |

These internal metrics are unaudited and dated 23 July 2026. They do not imply that every user is funded, active, eligible for every product, or unique across all device measures. <sup>[14]</sup>

### 9.2 Trust is the distribution channel

Confío’s founder-led Spanish-language audience is approximately 480,000 across social platforms. The strategic advantage is not the follower count alone; it is the ability to explain financial products repeatedly, publicly, and in the cultural language of the target user. <sup>[15]</sup>

> **Distribution + trust + local fit**
>
> Confío does not plan to win by permanently outbidding competitors on cashback. It aims to convert a trusted audience into verified users, funded balances, retained savings, repeat payments, and referrals with effectively zero paid-media spend to date.

The funnel is measured from content reach through installation, phone completion, identity verification, first funding, retained balance, repeat deposit or transaction, and referral. Country-level cohorts matter more than a single global signup count.

### 9.3 Country-by-country rollout

Confío does not expose every feature in every country. Fiat methods, identity requirements, USDY eligibility, sanctions controls, withdrawal options, and support procedures vary by market. Rollout follows verified provider capabilities and legal/operational readiness rather than a country flag in a marketing page.

## 10. Business model

Confío aligns revenue with useful financial activity rather than speculative trading.

| Revenue line | Current policy |
| --- | --- |
| Enter the Confío dollar system | 0.9% Confío conversion fee when USDT becomes cUSD or cUSD+, whether the USDT arrives through a fiat ramp or an on-chain transfer. People and businesses pay the same rate. |
| Leave the Confío dollar system | 0.9% Confío conversion fee when cUSD or cUSD+ becomes external USDT, whether the destination is a fiat ramp or an on-chain wallet. People and businesses pay the same rate. |
| Person-to-person transfers and internal savings conversion | 0% Confío platform fee for internal sends and sponsor-authorized cUSD↔cUSD+ conversion. Network fees are sponsored. |
| Merchant payments | 0.9% flat Confío platform fee, enforced by the payment contract. |
| Payroll and mass payouts | 0.9% flat Confío platform fee, with fee shares accrued separately from business escrow. |
| cUSD+ yield share | 15% of positive USDY reference-price appreciation to Confío and 85% to the cUSD+ holder reference value. Yield is variable and not guaranteed. |
| Ondo Stocks | Fixed 0.30% explicit Confío fee on every completed purchase and sale, charged in USDT by the deployed stock router. Provider pricing, spreads, taxes, or other third-party costs may apply separately where disclosed. |
| Fiat-rail economics | Koywe provider pricing and Guardarian revenue-sharing may apply according to the live quote and relevant partner agreement. |
| Other financial products | Potential fees or revenue share from other eligible RWA, brokerage, card, or business-service partners, subject to separate terms and approvals. |

The pricing rule is the same one shown on the public website: **0.9% to enter, 0% to move inside, and 0.9% to leave**. Confío Pay is a separate 0.9% service fee. Exchange rates and any third-party provider charges are disclosed separately where applicable. Network sponsorship is a product cost, not proof that every product action is economically free.

Current fee-capable clients show the Confío fee and final amount before confirmation. During the app-store transition, an already-installed legacy build may still render its old “Comisión de Confío — Gratis” label even though the server and contracts apply the 0.9% fee and return the correct post-fee final amount. Legacy builds remain operable during this short compatibility window rather than blocking access while a store review is pending.

## 11. Compliance and operating model

Confío’s architecture separates wallet-key custody from product and provider obligations. A non-custodial wallet can still integrate permissioned assets, identity verification, sanctions screening, fiat providers, and contract controls.

**Know Your Customer (KYC)** means the checks used to establish who a user is and, where required, where the user resides. **Anti-Money Laundering (AML)** means provider and transaction controls intended to detect or prevent sanctions violations, fraud, money laundering, terrorist financing, and other prohibited activity. The applicable checks depend on the product, legal entity, user location, transaction, and partner.

> **Provider-integrated architecture**
>
> Confío is architected so that fiat custody, currency conversion, identity verification, and permissioned-asset access are performed by the relevant providers rather than by Confío’s wallet software. This describes the operating design; it is not a claim that Confío has no legal or compliance obligations.

- Didit supports the current identity-verification flow. A user submits a government-issued identity document and captures a live selfie; Didit performs document, liveness, and face-matching checks.
- Residential-address information is a separate provider requirement. For Koywe transactions, Confío asks the user to enter the address and, with the user’s consent, submits it to Koywe for provider-side verification. <sup>[13]</sup>
- Koywe applies its own identity, address, eligibility, sanctions, and transaction controls across its supported local rails. <sup>[13]</sup>
- Guardarian’s onboarding for SEPA and card access also includes residential-address information and remains subject to its identity, eligibility, payment-method, sanctions, and transaction controls. <sup>[13]</sup>
- Phone completion or Didit verification alone does not guarantee that Koywe, Guardarian, Ondo, or another provider will approve a user or transaction.
- USDY minting is limited by Ondo eligibility, geographic, address, and compliance requirements. <sup>[7, 10]</sup>
- Ondo Stocks access is separately subject to Ondo Global Markets eligibility, asset and market availability, jurisdictional restrictions, signed trade attestations, and applicable provider terms. <sup>[18]</sup>
- Additional countries and rails launch only after the corresponding legal, operational, and provider checks.

## 12. Risks and mitigations

No blockchain financial product is risk-free. This table is not exhaustive.

| Risk | Current mitigation | Residual exposure |
| --- | --- | --- |
| Underlying assets and issuers | cUSD is backed by USDT; cUSD+ holds USDY and discloses its structure, accounting, and eligibility; USDT is the external entry/exit asset. | Depeg, issuer, custody, legal, reserve, and redemption risks remain for USDY and USDT. |
| Smart contracts | Open source, verified deployments, layered tests, continuous adversarial review, bounded controls, and public state. | Bugs, integration failures, and upgrade errors remain possible. |
| Oracle | Threshold guard halts value paths and requires an evidence-linked governance response. | Incorrect or unavailable data can delay deposits and redemptions. |
| Liquidity and redemption | cUSD and cUSD+ have defined, permissionless fee-bearing USDT redemption paths; Emergency Exit can broadcast directly through multiple public BSC nodes and can fall back to sending cUSD/cUSD+ itself. | InstantManager liquidity, provider availability, network conditions, or compliance actions may delay exits. |
| Permissioning | Minting and provider access follow applicable eligibility rules; users hold cUSD+ rather than raw USDY. | Ondo or another provider may change eligibility or restrict an address or transaction. |
| Ondo Stocks and market trading | The stock router is source-verified, UUPS-upgradeable only by the 3-of-5 owner Safe, fee-bounded, user-authorized, and designed to return principal, stock tokens, and settlement excess directly to the user. | Market closure, price movement, slippage, issuer, token, broker, custodian, liquidity, attestation, settlement, eligibility, regulatory, tax, provider, and contract-upgrade risks remain. Trading can be delayed, rejected, restricted, or unavailable. |
| Key recovery | Device-generated keys and personal-cloud recovery avoid a central key vault. | Loss of device/cloud access, platform changes, or recovery defects can affect access. |
| Upgrade governance | Multi-party control, public upgrade records, source verification, and storage-layout checks. | Authorized signers could make a harmful change or fail to respond during an incident. |
| BNB Smart Chain dependency | Single-network architecture removes bridge risk and the app uses multiple RPC and emergency-exit paths. | Network interruption, congestion, validator coordination, RPC failure, gas changes, or ecosystem policy changes can affect the whole product. |
| Fiat rails | Koywe and Guardarian are live; additional providers are named only after capabilities are verified. | Coverage, payment methods, banking dependencies, pricing, and provider availability can change. |
| Regulatory and financial crime | Government-document/live-selfie checks, residential-address verification where required, provider screening, product geofencing, and legal review. | Verification does not eliminate fraud or illicit-finance risk; providers or authorities may reject, delay, report, or restrict activity. |
| Token concentration and presale | Fixed supply, public contracts, immutable presale curve, separate tokenomics, and on-chain treasury visibility. | Concentrated founder ownership, vesting, treasury transfers, market liquidity, and token-price volatility remain material risks. |
| Reward claims | Cumulative EIP-712 claims, replay accounting, short signature deadlines, DEX lock, public contract, and working-tranche funding model. | The treasury can rotate the signer, pause claims, withdraw the pool, or decline to fund database obligations; rewards are not trustless claims on an immutable reserve. |
| Metrics and concentration | Definitions, snapshot dates, and unaudited status are disclosed. | Early usage or balances may be concentrated and may not predict broad adoption. |

## 13. Roadmap and current status

| Workstream | Completed / current | Next verifiable gate |
| --- | --- | --- |
| cUSD/cUSD+ fee system | New cUSD UUPS proxy deployed and source-verified; existing cUSD+ proxy upgraded in place; 90-bps external USDT perimeter and fee-free sponsor-only internal wrapper boundary installed. | Monitor fee-event reconciliation, backing, eligibility routing, legacy-client disclosure, and permissionless exits during rollout. |
| Sponsored transactions | Ownerless EIP-7702 batch delegate deployed and verified; server policy, ledgers, and canary controls implemented. | Expand canary volume and monitor reliability, sponsor cost, and emergency fallbacks. |
| Transfers | BSC cUSD/cUSD+ friend flows, cross-eligibility fee-free conversion, and invitation escrow implemented across contracts, backend, and mobile client. | Controlled production rollout and retained-use measurement. |
| Merchant payments | Replacement cUSD+/cUSD payment contract with the separate 0.9% Pay fee deployed, source-verified, and wired into production. | Expand staged user exposure and measure merchant settlement, repeat usage, and fee accrual. |
| Payroll | Replacement asset-separated cUSD+/cUSD escrow, delegate-signed payouts, backend/client flows, and payroll vault deployed and source-verified. | Pilot with businesses, expand staged user exposure, and verify escrow and payout reliability at meaningful volume. |
| $CONFIO | Fixed-supply token and cUSD-funded replacement continuous-curve presale vault deployed, source-verified, historical purchases imported, claim obligation funded, and wired into production on BSC. | Keep tokenomics disclosures synchronized with on-chain state and open claims only under the disclosed controls. |
| $CONFIO rewards | Canonical RewardVault deployed, source-verified, wired to the canonical token, and locked until DEX launch; database-only accrual uses the live presale-curve price when enabled. | Enable database-only accrual when operationally ready; at DEX time, fund a working tranche, activate the short-deadline EIP-712 signer and sponsored client claim flow, and unlock claims. |
| Ondo Stocks | Dedicated UUPS router proxy deployed and source-verified at `0x40c8e134BCAf44EEf9e7D184846F36c9862329c3`; app, backend, attestation, sponsored execution, direct-to-user delivery, sell-to-savings flow, and fixed 0.30% fee are implemented. | Complete and maintain the provider, sponsor, rehearsal, canary, eligibility, and runtime activation gates before expanding live trading. |
| Fiat access | Koywe live across seven LATAM markets; Guardarian live for SEPA and card-based access. | Add verified providers and fallback routes without creating hidden dependencies. |
| Distribution | 8,004 phone-complete users; 177 Didit-verified users; approximately 480,000 founder audience; effectively zero paid-media spend to date. | Convert distribution into funded users, retained balances, repeat transactions, referrals, and country-level cohorts. |

### 13.1 Measurement principles

Confío distinguishes signups, phone-complete users, verified users, funded users, reachable devices, active users, and retained balances. Core operating measures include funded users, cUSD and cUSD+ obligations, backing, conversion fees, gross deposits, redemptions, net inflow, average and median balance, balance retention, fiat-originated inflow, concentration, merchant volume, payroll volume, and country cohorts.

Distribution is measured as a funnel: content reach, store visit, installation, phone completion, identity verification, first funding, retained balance, repeat deposit or transaction, and referral. Organic acquisition is separated from paid campaigns.

### 13.2 The next proof point

> **From deployed infrastructure to retained use**
>
> The next proof point is sustained consumer adoption on BNB Smart Chain: funded users, repeat deposits, reliable redemptions, retained cUSD/cUSD+ balances, USDT liquidity, merchant and payroll activity, and measurable fiat-originated inflow across multiple Latin American markets.

## 14. Legal disclaimer

This document is provided for informational and technical-reference purposes only. It is not investment, legal, tax, accounting, or financial advice; it is not a prospectus, offer, solicitation, recommendation, or promise of returns. Product descriptions reflect the current design and status as of 31 August 2026 and may change.

USDT, cUSD, and cUSD+ are not bank deposits and are not insured by a deposit-insurance scheme. Stablecoins, tokenized notes, smart contracts, blockchains, oracles, fiat providers, market makers, custodians, and other infrastructure can fail, be suspended, lose value, or become subject to new rules.

Any cUSD+ yield is variable, depends on USDY and the vault, and is not guaranteed. USDY access and cUSD+ minting are subject to Ondo eligibility, compliance conditions, provider availability, and applicable law.

Ondo Stocks are tokenized financial instruments and are not bank deposits or insured savings products. Access and trading depend on eligibility, jurisdiction, market hours and availability, Ondo Global Markets attestations and settlement, blockchain operation, and applicable provider terms and law. The displayed market value and eventual execution price may differ, and a user may be unable to purchase, sell, transfer, or redeem an instrument when desired.

$CONFIO is separate from USDT, cUSD, cUSD+, and USDY. It does not provide a claim on the backing, revenue, equity, assets, or profits of Confío unless definitive terms expressly state otherwise. Token purchasers should review the separate tokenomics, presale terms, smart contracts, vesting state, treasury concentration, and applicable law.

Readers should review definitive product terms, risk disclosures, smart contracts, provider terms, and local law before using any service.

## Endnotes

1. Inter-American Development Bank, “Remittances to Latin America and the Caribbean Ease After 2025 Surge,” 16 June 2026: estimated regional remittances of US$173.7 billion in 2025, up 7.3% from 2024. https://www.iadb.org/en/blog/migration/remittances-latin-america-and-caribbean-ease-after-2025-surge

2. Chainalysis, “Latin America Emerges as Crypto Powerhouse Amid Volatile Growth,” 2 October 2025. https://www.chainalysis.com/blog/latin-america-crypto-adoption-2025/

3. Confío public GitHub repository and README: open-source mobile application, backend, BSC contracts, wallet model, payments, payroll, token, and presale. https://github.com/caesar4321/Confio

4. Confío, “Por qué Confío no guarda tu dinero - y por qué eso importa,” project source, accessed July 2026.

5. BNB Chain developer documentation, BNB Smart Chain introduction and finality. https://docs.bnbchain.org/bnb-smart-chain/introduction/

6. BNB Chain developer documentation, transaction fees and network concepts. https://docs.bnbchain.org/bnb-smart-chain/

7. Ondo Finance documentation, “USDY Basics,” accessed July 2026. https://docs.ondo.finance/general-access-products/usdy/basics

8. Confío, “cUSD+ deployment record - BSC mainnet,” updated 31 August 2026. https://github.com/caesar4321/Confio/blob/main/contracts/cusd_plus/DEPLOYMENT.md

9. BscScan, Confío Dollar+ ERC1967 proxy, address `0x3C29417eb4314155e63d4C7D4507852b87763Ed1`. https://bscscan.com/address/0x3C29417eb4314155e63d4C7D4507852b87763Ed1#code

10. Ondo Finance developer documentation, “Integrating with the USDY InstantManager contract.” https://docs.ondo.finance/developer-guides/usdy-instant-manager-integration

11. Confío, `CusdPlusVault.sol`: deployed accounting, redemption, oracle guard, and 15% Confío yield-share logic. https://github.com/caesar4321/Confio/blob/main/contracts/cusd_plus/CusdPlusVault.sol

12. BNB Chain ecosystem and developer documentation, accessed July 2026. https://www.bnbchain.org/en/developers

13. Confío partner records, July 2026: Koywe and Guardarian commercial agreements and production integrations across supported markets and payment methods. Commercial terms remain governed by the respective agreements.

14. Confío internal product analytics snapshot, 23 July 2026: phone-complete, Didit government-document and live-selfie identity-verification completion, and FCM device metrics. Unaudited.

15. Confío internal founder-channel analytics snapshot, 23 July 2026. Audience figure is approximate and changes over time.

16. Benedetto Biondi, “The New Face Of Global Payments: Onchain Consumer Finance Apps,” *Forbes Technology Council*, 6 July 2026. https://www.forbes.com/councils/forbestechcouncil/2026/07/06/the-new-face-of-global-payments-onchain-consumer-finance-apps/

17. Confío BSC contracts and deployment records: `ConfioToken.sol`, `ConfioPresaleVault.sol`, `ConfioRewardVault.sol`, `ConfioVestingVault.sol`, `ConfioInviteEscrow.sol`, `ConfioBatchDelegate.sol`, `ConfioStockRouter.sol`, and verified deployment addresses. https://github.com/caesar4321/Confio/tree/main/contracts/cusd_plus, https://github.com/caesar4321/Confio/tree/main/contracts/ondo_stocks, and https://github.com/caesar4321/Confio/blob/main/contracts/cusd_plus/DEPLOYMENT.md

18. Ondo Finance, “Ondo Stocks” and Global Markets API documentation, accessed July 2026. https://ondo.finance/ondo-stocks and https://docs.ondo.finance/api-reference/quickstart

19. International Monetary Fund Independent Evaluation Office, historical documentation of Argentina’s 2001 partial deposit freeze, capital controls, and forced conversion; and IMF review of the relaxation of most exchange restrictions under the 2025 stabilization program. https://www.imf.org/External/NP/ieo/2003/arg/ and https://www.imf.org/es/news/articles/2025/07/31/pr25272-argentina-imf-completes-first-review-of-the-extended-arrangement-under-the-eff

20. International Monetary Fund, “Digital Money and Central Banks Balance Sheet,” Working Paper No. 2022/206: Venezuela as a case of real dollarization. https://www.elibrary.imf.org/view/journals/001/2022/206/article-A001-en.xml

21. International Monetary Fund, “Bolivia: 2025 Article IV Consultation,” Country Report No. 2025/116. https://www.imf.org/en/publications/cr/issues/2025/06/02/bolivia-2025-article-iv-consultation-press-release-staff-report-and-statement-by-the-567384

22. Superintendencia de Banca, Seguros y AFP del Perú, *Carpeta de Información del Sistema Financiero*, February 2026, deposits by currency. https://intranet2.sbs.gob.pe/estadistica/financiera/2026/Febrero/SF-2102-fe2026.PDF

23. Banco de México, 2024 monetary aggregates; and Inter-American Development Bank, 2025 remittance estimate for Mexico. https://www.banxico.org.mx/TablasWeb/informe-anual/compilacion-2024/7EF1402E-1443-4070-9C0A-6B352272C3B9.html and https://publications.iadb.org/publications/english/document/Remittances-to-Latin-America-and-the-Caribbean-in-2025-Adaptations-in-a-Context-of-Uncertainty.pdf

24. Inter-American Development Bank, *Remittances to Latin America and the Caribbean in 2025: Adaptations in a Context of Uncertainty*. https://publications.iadb.org/publications/english/document/Remittances-to-Latin-America-and-the-Caribbean-in-2025-Adaptations-in-a-Context-of-Uncertainty.pdf

25. UNHCR, *Global Report 2025 — Situation Overview: Colombia*: Colombia hosted approximately 2.8 million Venezuelans in 2025. https://www.unhcr.org/sites/default/files/2026-06/global-report-2025-situation-overview-colombia.pdf

### Document provenance

Prepared from the prior English whitepaper, Confío’s product and tokenomics materials, Koywe and Guardarian partner records, the public repository and BSC deployment records, official BNB Chain and Ondo documentation, cited market literature, and the internal operating metrics explicitly provided for this update.
