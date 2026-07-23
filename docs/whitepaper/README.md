# Confío: Latin America’s Trusted Digital Dollar Platform

**Payments on Algorand. Savings on BNB Smart Chain.**

Confío is a fully open-source, non-custodial financial application that turns stablecoin and tokenized-asset rails into a familiar mobile experience for Latin American users.

**Global reference · Version 3.1 · July 2026**<br>
Julian Moon · Founder & CEO<br>
[confio.lat](https://confio.lat) · [GitHub](https://github.com/caesar4321/Confio)

*Lo tuyo, tuyo. · Blockchain inside. Simple as PayPal.*

## How to read this paper

> **One Product, Purpose-Built Rails**
>
> Confío uses Algorand for cUSD payments and BNB Smart Chain for cUSD+ savings. The chains serve different product roles while the application presents one coherent, non-custodial financial experience.

This paper is the current global reference for Confío’s product architecture, strategy, operating model, and material risks. It replaces the previous Argentina/Venezuela-heavy framing with a region-wide thesis centered on simple dollar payments, accessible dollar savings, non-custodial control, and country-by-country fiat connectivity.

<details>
<summary><strong>Contents</strong></summary>

1. [Executive summary](#1-executive-summary)
2. [The market thesis](#2-the-market-thesis)
3. [The product system](#3-the-product-system)
4. [cUSD: the Algorand payment rail](#4-cusd-the-algorand-payment-rail)
5. [cUSD+: the BNB Smart Chain savings rail](#5-cusd-the-bnb-smart-chain-savings-rail)
6. [Wallet, security, and open-source architecture](#6-wallet-security-and-open-source-architecture)
7. [Users, distribution, and go-to-market](#7-users-distribution-and-go-to-market)
8. [Business model](#8-business-model)
9. [Multi-chain and token strategy](#9-multi-chain-and-token-strategy)
10. [Compliance and operating model](#10-compliance-and-operating-model)
11. [Risks and mitigations](#11-risks-and-mitigations)
12. [Roadmap and current status](#12-roadmap-and-current-status)
13. [Legal disclaimer](#13-legal-disclaimer)
14. [Endnotes](#endnotes)

</details>

---

## 1. Executive summary

Confío is a fully open-source, non-custodial digital-dollar application for Latin America. It gives users a familiar mobile interface to hold, send, spend, and grow dollar-denominated assets without requiring them to manage gas tokens, memorize blockchain addresses, or navigate exchange screens. <sup>[3]</sup>

> **Product Thesis**
>
> The winning consumer dollar platform in Latin America will not ask users to become crypto experts. It will combine verifiable on-chain ownership with the clarity, recovery flows, local payment methods, and human support expected from a modern fintech. The contest will be decided not by feature parity but by distribution, trust, and local fit. Confío enters with a founder-led Spanish-language channel of approximately 480,000 people, a years-long public relationship with the region it serves, and effectively zero paid-media spend to date.

As on-chain consumer applications converge around similar combinations of saving, sending, and spending, product availability alone becomes less differentiating. Distribution, trust, and local relevance become the scarce advantages. Confío brings these together through a founder-led Spanish-language audience, an existing verified-user base, country-specific payment rails, and a product designed around the financial behavior of Latin American users rather than a generic global crypto interface. <sup>[15, 16]</sup>

Confío uses a deliberate role-based multi-chain architecture. cUSD remains on Algorand as the payment and transfer rail. cUSD+ operates on BNB Smart Chain as the savings rail, backed by Ondo USDY. The app is responsible for making these different settlement systems feel like one coherent product.

| Product | Primary job | Settlement design |
| --- | --- | --- |
| cUSD | Everyday digital dollars for transfers, contacts, payments, and business flows. | Algorand; designed as a 1:1 USDC-backed unit for fast, low-cost settlement. |
| cUSD+ | Dollar savings with variable yield exposure, presented as an accumulating balance. | BNB Smart Chain; vault-backed by Ondo USDY and entered/exited through USDT. |
| $CONFIO | Community, rewards, and future ecosystem utility; separate from backing assets. | Currently Algorand. No BNB migration is assumed by this whitepaper. |

As of 23 July 2026, Confío records 8,004 users who completed phone verification, 177 users verified through Didit, a 61.5% completion rate among users who began the Didit flow, 2,094 push-reachable devices, and 2,092 of those devices used within the last 30 days. These are internal operating metrics rather than independently audited figures and should not be read as funded-user or monthly-active-user counts. <sup>[14]</sup>

The BNB Smart Chain vault is deployed and verified, is controlled through multi-party Safe governance, and integrates production USDY, USDT, the Ondo InstantManager, and the USDY price oracle. Confío works with Ondo Finance within its eligibility and compliance framework to provide the cUSD+ savings experience. <sup>[8, 9]</sup>

## 2. The market thesis

### 2.1 A dollar-access problem, not a crypto-awareness problem

Latin America is not one homogeneous monetary crisis. Some users need protection from local-currency volatility; others need affordable cross-border settlement, a safe place for dollar savings, or a practical way to pay and be paid. What connects these markets is demand for a reliable dollar unit and dissatisfaction with the friction surrounding it.

Stablecoins have moved beyond a niche trading instrument. Chainalysis reports that stablecoins represented more than half of exchange purchases in selected major Latin American fiat markets during the year ending June 2025, while regional crypto adoption grew strongly across retail and institutional segments. <sup>[2]</sup>

Remittances remain economically significant across the region. The World Bank estimated approximately US$162 billion in remittance flows to Latin America and the Caribbean in 2025. Confío does not assume it will replace the entire remittance stack; it focuses on the wallet and settlement experience that begins after a user wants to move value in dollars. <sup>[1]</sup>

### 2.2 The product gap

Existing options often force a trade-off. Banks and local fintechs can offer strong UX but retain custody and depend on domestic account access. Exchanges offer liquidity but are optimized for traders. Self-custody wallets offer control but expose users to seed phrases, addresses, gas, bridging, and token-selection risk.

- Confío is dollar-first rather than trading-first.
- The wallet is non-custodial at the key layer, while fiat-facing services apply the identity and compliance controls required by their respective providers.
- Blockchain selection follows the job to be done: payment reliability for cUSD and EVM/RWA connectivity for cUSD+.
- Country expansion follows operational readiness and partner coverage, not a single-country ideology.

### 2.3 Competitive landscape

| Category | Typical strength and limitation | Confío’s distinction |
| --- | --- | --- |
| Banks and remittance services | Familiar brands and cash or account reach, but generally custodial and constrained by accounts, corridors, schedules, and intermediaries. | A user-controlled dollar wallet with direct digital settlement and local access rails. |
| Exchanges and P2P markets | Deep liquidity and broad stablecoin access, but trading screens, order books, disputes, and counterparty risk create cognitive load. | A dollar-first experience that hides exchange mechanics and presents clear consumer actions. |
| Custodial dollar apps and neobanks | Strong localized UX, but access can depend on the platform’s custody model and a narrow set of banking or corridor partners. | Local fintech UX combined with user-controlled signing keys and transparently separated provider controls. |
| Self-custody wallets | Open asset control, but seed phrases, gas tokens, hexadecimal addresses, bridging, and token selection remain visible to users. | Personal-cloud recovery, sponsored network fees, contact-based sending, and product-level abstraction of cUSD and cUSD+. |
| On-chain consumer finance apps | Increasingly similar bundles of dollar saving, yield, transfers, and spending; many compete for the same crypto-aware users through rewards and cashback. | Founder-led Spanish distribution, community trust, and country-specific products and rails aimed at bringing new Latin American users on-chain. |

### 2.4 Distribution is the competitive frontier

Stablecoin infrastructure is becoming broadly available, and consumer applications are converging on a familiar bundle: hold dollars, earn variable yield, send across borders, and spend through local methods. As these features become easier to reproduce, the contest shifts from access to infrastructure toward the ability to reach users, earn their trust, and match the product to local demand. Industry analysis increasingly describes this as a distribution competition rather than a purely technical one. <sup>[16]</sup>

Confío’s answer is not to outspend competitors on temporary incentives. It is to compound a founder-led Spanish-language channel into a measurable product loop: education leads to installation, phone and identity verification, funding, retained balances, repeat use, referrals, and eventually greater merchant and payroll utility. Phone contacts, interoperable QR, SPEI, PIX, PSE/Nequi, Alias/CVU, and locally appropriate product surfaces are therefore not after-the-fact localization. They are part of the product and distribution system.

### 2.5 The deeper problem: falta de confianza

Beneath currency volatility sits a deeper structural cost: falta de confianza - the absence of trust. People have learned to distrust institutions that can freeze access, change rules, hide spreads, or fail without warning. Confío does not ask users to replace that experience with blind trust in another company. It combines user-controlled keys, open-source software, transparent asset backing, and clearly separated provider controls so that important claims can be verified rather than merely promised.

> **Lo Tuyo, Tuyo**
>
> Confío’s brand promise is simple: what belongs to the user remains under the user’s control. That promise applies to wallet custody; issuer, asset, compliance, and provider controls remain disclosed rather than hidden.

### 2.6 Who Confío is for

The initial customer is not defined by nationality alone. Confío is designed for ordinary users who think in dollar goals: preserving savings, sending money to family, receiving payment, paying a merchant, or placing a portion of a balance into a transparent dollar savings product. Higher-balance savers are an important early wedge for cUSD+, while the payment product remains designed for broad everyday use.

## 3. The product system

Confío separates the user experience from the settlement rail. A user sees dollar balances and clear actions; the app selects the appropriate chain, prepares the transaction, and abstracts routine network fees. This is not a claim that the chains are identical. Their different properties and risks are disclosed in the product and in this paper.

| Consumer layer | Confío product layer | Settlement and backing layer |
| --- | --- | --- |
| Google/Apple sign-in; phone identity; Spanish-first UX | Wallet creation and recovery; contact-based transfers; balance presentation | Device-generated keys; user-signed blockchain transactions |
| Local and international payment methods | Ramp orchestration; quotes, orders, status, and support | Koywe local rails across seven LATAM markets; Guardarian SEPA and USD card access through Visa, Mastercard, Apple Pay, and Google Pay |
| Pay, send, receive | cUSD | Algorand settlement; USDC-backed issuance design |
| Save and redeem | cUSD+ | BNB Smart Chain vault; USDY backing; USDT entry and exit |

### 3.1 Two chains, two jobs

Payments and savings should not be forced onto the same rail simply for architectural symmetry. Payments favor predictable cost, instant finality, and atomic consumer flows. RWA savings favors EVM compatibility, institutional asset integrations, and access to BNB Chain’s stablecoin and developer ecosystem.

### 3.2 Non-custodial does not mean unregulated

Confío distinguishes three layers: the user’s wallet keys, the issuer or vault contracts, and regulated fiat/RWA providers. Confío does not hold a user’s private key. At the same time, cUSD issuance, cUSD+ eligibility, fiat ramps, and underlying assets can have their own compliance controls. Describing the wallet as non-custodial does not erase those separate controls. <sup>[3, 4]</sup>

## 4. cUSD: the Algorand payment rail

cUSD is Confío’s user-facing digital-dollar unit for everyday transfers and payments. It is designed around a 1:1 USDC-backed model on Algorand. The consumer proposition is simple: a dollar-denominated balance that can be sent to a phone contact or used in a business flow without exposing the user to the underlying asset conversion. <sup>[3]</sup>

### 4.1 Why Algorand remains the home of payments

Reliability comes first for a payment rail. Algorand Mainnet has recorded zero protocol downtime since its launch in June 2019 - more than seven years of uninterrupted network availability as of July 2026. For users who depend on Confío to send money, receive payment, or pay a merchant, continuous availability is a first-order product requirement. <sup>[17]</sup>

Algorand also provides immediate block finality: once a transaction appears in a block it is final, rather than waiting through a reorganization window. Its transaction-fee design uses a low minimum fee and is independent of smart-contract computational complexity. Together, uninterrupted protocol operation, instant finality, and predictable low fees fit retail transfers, QR payments, escrow, and payroll-style atomic flows. <sup>[5, 6]</sup>

- Zero protocol downtime since 2019 provides a demonstrated operational record for an always-on consumer payment rail.
- Contact-based sending and claim flows can be grouped with settlement logic.
- Sponsored fees let the app present a gasless experience without pretending that network fees do not exist.
- Fast finality reduces ambiguity at the point of payment.
- cUSD remains operationally distinct from cUSD+; a savings product on BNB Smart Chain does not require migrating the payment rail.

### 4.2 Backing, controls, and user ownership

The user’s Algorand key is generated on the device and protected through the user’s personal cloud recovery path. Confío does not store the unencrypted private key. cUSD, however, is an issued asset: backing, minting, redemption, and legally required issuer controls are separate from wallet custody. This two-layer model is more accurate than claiming that every part of the product is permissionless. <sup>[3, 4]</sup>

## 5. cUSD+: the BNB Smart Chain savings rail

### 5.1 Product purpose

cUSD+ is an accumulating dollar-savings token designed to give eligible users exposure to the variable yield of Ondo USDY through a familiar Confío balance. USDY is an accumulating tokenized note whose reference price increases as underlying income accrues. Its availability and redemption are subject to Ondo eligibility, compliance, and product terms; cUSD+ does not remove those underlying conditions. <sup>[7]</sup>

> **Production Architecture**
>
> The BSC mainnet vault is deployed, source-verified, and integrated with Ondo’s production USDY, InstantManager, and price-oracle infrastructure. Subscriptions and redemptions operate within Ondo’s permissioned-purchaser and eligibility framework.

### 5.2 Asset flow

| Step | Deposit path | Redemption path |
| --- | --- | --- |
| 1 | User or relayer supplies BSC USDT. | User requests redemption of cUSD+. |
| 2 | Vault calls Ondo InstantManager subscribe. | Vault burns the corresponding cUSD+ amount. |
| 3 | InstantManager delivers USDY to the vault. | Vault sends USDY through InstantManager redeem. |
| 4 | Vault mints cUSD+ to the user at the guarded reference price. | USDT is delivered to the designated user or ramp address. |

Raw USDY is designed to remain within approved infrastructure. Ordinary holders enter and exit through USDT rather than receiving USDY directly. This supports the permissioned nature of the underlying asset while preserving a clear consumer redemption path. Ondo’s integration documentation likewise requires the exact calling address to be registered before InstantManager calls can succeed. <sup>[8, 10]</sup>

### 5.3 Yield sharing and value accrual

The deployed vault encodes a 15% Confío share of positive USDY reference-price appreciation. The remaining 85% is reflected in the cUSD+ holder reference value. This is a share of underlying variable appreciation, not a fixed or guaranteed APY. If USDY yield changes, the gross amount available to both holders and Confío changes. <sup>[8, 11]</sup>

The vault maintains an internal cUSD+ reference value and checks that USDY backing is sufficient for holder obligations. Oracle movements beyond a configured guard threshold trigger a halt of value-moving paths until a governed verdict is recorded. This reduces the risk that an abnormal oracle observation is silently converted into holder dilution or an unsafe redemption. <sup>[8, 11]</sup>

### 5.4 Why BNB Smart Chain

BNB Smart Chain is EVM-compatible and designed for short block times, fast finality, and low transaction fees. For cUSD+, the main advantage is not that chain-wide TVL automatically creates value. It is the practical availability of EVM tooling, USDT liquidity, RWA integrations, wallet infrastructure, and a broader venue for future savings and market integrations. <sup>[12]</sup>

## 6. Wallet, security, and open-source architecture

### 6.1 Open by default

Confío’s mobile application, backend, and smart contracts are published under an MIT license. The repository includes the React Native application, Django/GraphQL services, Algorand contracts, Solidity contracts, ramp integrations, payment and payroll modules, and test infrastructure. This allows users, reviewers, and other builders to inspect, fork, or adapt the full reference implementation rather than trusting a closed client. <sup>[3]</sup>

### 6.2 Key ownership and recovery

Wallet keys are generated on the user’s device and encrypted for recovery through the user’s personal Google or Apple cloud environment. The product deliberately avoids a seed-phrase-first onboarding experience, but the architectural goal remains self-custody: Confío should not possess a server-side master key capable of moving ordinary user funds. <sup>[3, 4]</sup>

> **Ni Siquiera Nosotros**
>
> Confío never holds the user’s signing keys. No Confío operator can sign a wallet transaction on the user’s behalf - not even us. Issued assets such as cUSD and the cUSD+ vault remain subject to their own separately disclosed issuer, asset, compliance, and governance controls.

### 6.3 Contract governance and operational security

The cUSD+ proxy is governed through a multi-party Safe. Upgradeability is retained because the vault depends on external Ondo contracts and oracle infrastructure that may migrate. This creates governance risk, but permanently locking an implementation that depends on changeable external infrastructure could strand funds. The mitigation is transparent governance, multi-party approval, verified source, storage-layout controls, and public upgrade records. <sup>[8, 9]</sup>

Security review is continuous rather than treated as a one-time certification. The codebase undergoes recurring adversarial review using frontier AI coding models alongside unit, mainnet-fork, invariant, fuzz, differential, and upgrade-rehearsal testing. Confío relies on open verifiability, defense in depth, conservative controls, and public upgrade records rather than obscurity. <sup>[8]</sup>

| Control surface | Current design |
| --- | --- |
| User transaction keys | Generated and used on the user device; protected through personal cloud recovery. |
| Routine gas | All user blockchain transactions are sponsored so users do not need to hold ALGO or BNB merely to use the application. |
| cUSD+ treasury and upgrades | Multi-party Safe approval; public implementation and upgrade history. |
| Backing and pricing | USDC backing design for cUSD; USDY vault backing and guarded oracle logic for cUSD+. |
| Source transparency | Mobile, backend, contracts, and deployment documentation are publicly inspectable. |

## 7. Users, distribution, and go-to-market

### 7.1 Current operating metrics

| Metric | Current value | Definition / caution |
| --- | --- | --- |
| Phone-complete users | 8,004 | Users who completed phone verification; not equivalent to funded users. |
| Didit-verified users | 177 | Users who completed the Didit identity-verification flow. |
| KYC completion | 61.5% | Completion among users who started the Didit verification flow. |
| Push-reachable devices | 2,094 | Devices currently reachable through FCM. |
| Used in last 30 days | 2,092 | Reachable devices recorded as used within 30 days; not labeled as audited MAU. |
| Founder audience | ≈480,000 | Approximate Spanish-speaking content audience; platform analytics vary over time. |

Source: Confío internal product and channel analytics, 23 July 2026. Metrics are unaudited. <sup>[14, 15]</sup>

### 7.2 Distribution is a product capability

> **Trust Is The Distribution Channel**
>
> Confío’s founder-led TikTok presence reaches the exact Spanish-speaking audience the product serves, creating an organic acquisition channel with effectively zero paid-media spend.

Financial adoption in Latin America often begins with the credibility of the messenger. Confío’s founder-led Spanish-language distribution is therefore not an ornamental marketing asset; it is a direct acquisition and education channel. The operating test is not follower count by itself, but the measurable conversion from a piece of content to verification, deposit, retained balance, and repeat usage. <sup>[15]</sup>

This changes the economics of growth. Confío can explain a new product, answer objections in the audience’s language, observe conversion, and improve the experience without making subsidy-led acquisition the default. The audience is not treated as a vanity metric or a substitute for product-market fit. It is a repeatable path for testing whether trust and education become funded use.

The intended distribution flywheel is:

1. Founder-led content identifies a concrete financial need and explains the product in plain Spanish.
2. Users enter a familiar mobile onboarding flow and complete phone or identity verification where required.
3. Local and international rails convert intent into funded cUSD or cUSD+ balances.
4. Reliable transfers, redemptions, support, and transparent controls build retained trust.
5. Retained users create referrals, contact-network utility, merchant demand, and evidence for country-by-country expansion.

This is the strategic link between the market thesis and the product: distribution earns the first use, while trustworthy local utility earns retention.

### 7.3 Country expansion

Confío is moving away from a whitepaper centered on Argentina and Venezuela. The product is regional, while access is local. Each country is enabled only when fiat rails, compliance requirements, customer support, pricing, and liquidity are operationally credible.

- Koywe is live across seven LATAM markets: Alias/CVU in Argentina, SPEI in Mexico, interoperable QR in Peru and Bolivia, bank transfer in Chile, PSE/Nequi in Colombia, and PIX in Brazil. <sup>[13]</sup>
- The live interoperable QR rails in Peru and Bolivia position Confío inside an everyday payment behavior often overlooked by card-first on-chain applications; QR is part of the current access layer, not a speculative roadmap item. <sup>[13, 16]</sup>
- Guardarian provides SEPA access in the Eurozone and USD card access through Visa, Mastercard, Apple Pay, and Google Pay. <sup>[13]</sup>
- Additional providers are named only after contracts and production capabilities are confirmed.
- Peru and Mexico are important savings markets; Bolivia and Venezuela exhibit different dollar-access needs; Colombia, Chile, Argentina, and Brazil require their own product and regulatory sequencing.
- The app should expose only the modules that are ready and appropriate in each market.

## 8. Business model

Confío’s business model aligns revenue with useful financial activity rather than speculative trading. Person-to-person transfers remain free at the platform layer, while business payment flows use a simple 0.9% fee and cUSD+ aligns Confío’s revenue with users retaining and growing savings.

| Revenue line | Current policy |
| --- | --- |
| Person-to-person transfers | 0% Confío platform fee. Network fees are sponsored by Confío; fiat or third-party provider charges may still apply where disclosed. |
| Merchant payments | 0.9% flat Confío platform fee. |
| Payroll and mass payouts | 0.9% flat Confío platform fee. |
| cUSD+ yield share | The deployed vault allocates 15% of positive USDY reference-price appreciation to Confío and 85% to the cUSD+ holder reference value. Yield is variable and not guaranteed. |
| Fiat-rail economics | Koywe provider pricing and Guardarian revenue-sharing may apply according to the live quote and the relevant partner agreement. |
| Future financial products | Potential fees or revenue share from eligible RWA, brokerage, or card partners, subject to separate terms and approvals. |

Network sponsorship is a product cost, not proof that transactions are economically free. Confío sponsors user blockchain network fees to preserve a simple experience, while underlying ramp, liquidity, compliance, and support costs remain real.

### 8.1 What does not back the products

$CONFIO does not back cUSD or cUSD+. Product backing must be evaluated through the underlying stablecoin, vault assets, contracts, redemption paths, and applicable legal terms. Presale proceeds, token price, and company equity are separate from user-asset backing.

## 9. Multi-chain and token strategy

### 9.1 Role-based multi-chain design

Confío does not treat chain selection as a loyalty test. cUSD and the payment experience remain on Algorand because that rail is well suited to low-cost, final consumer transactions. cUSD+ uses BNB Smart Chain because its economic activity is tied to USDY, USDT, EVM contracts, and potential RWA ecosystem integrations. The BNB deployment is complementary, not a migration away from Algorand.

### 9.2 $CONFIO

$CONFIO is a separate community and ecosystem token currently issued on Algorand. This whitepaper does not announce a chain migration or a new BNB Smart Chain token. Any future decision would be made when external liquidity design, TGE/DEX readiness, concrete exchange requirements, and token utility can be evaluated with real product data.

If a future representation or migration is pursued, supply integrity is non-negotiable. Already distributed Algorand tokens cannot simply be duplicated by a BSC airdrop; a supply-preserving lock, burn, or claim mechanism would be required. Undistributed allocations can be assigned at first distribution without creating duplicate circulating supply.

> **Current Policy**
>
> Keep cUSD on Algorand, launch cUSD+ on BNB Smart Chain, and defer any $CONFIO chain decision until utility and market-structure evidence justify it.

## 10. Compliance and operating model

Confío’s architecture separates software custody from product and provider obligations. A non-custodial wallet can still integrate permissioned assets, identity verification, sanctions screening, fiat providers, and issuer controls. The relevant obligations depend on the product, legal entity, user location, transaction, and partner.

> **Software-Publisher Architecture**
>
> Confío is architected so regulated activities - fiat custody, currency conversion, identity verification, and permissioned-asset access - are performed by the relevant licensed or regulated providers rather than by Confío’s wallet software. This describes the operating design; it is not a claim that Confío has no legal or compliance obligations.

- Didit supports the current identity-verification flow; completion metrics are reported separately from phone verification.
- Koywe provides live local fiat rails across seven LATAM markets and applies its own service and AML conditions. <sup>[13]</sup>
- Guardarian provides SEPA and card-based dollar access and applies its own service, eligibility, payment-method, and compliance conditions. <sup>[13]</sup>
- USDY access is limited to eligible non-US participants and exact approved addresses under Ondo’s current framework. <sup>[7, 10]</sup>
- cUSD issuer controls and cUSD+ contract controls are distinct from possession of a user’s wallet key.
- Additional countries and rails launch only after the corresponding legal, operational, and provider checks.

## 11. Risks and mitigations

No blockchain financial product is risk-free. The following table summarizes material risks, current controls, and open work. It is not exhaustive.

| Risk | Current mitigation | Residual exposure |
| --- | --- | --- |
| Underlying asset and issuer | cUSD uses a USDC-backed design; cUSD+ holds USDY and discloses its structure and eligibility. | Depeg, issuer, custody, legal, reserve, and redemption risks remain. |
| Smart contracts | Open source, verified deployment, layered testing, continuous adversarial review, multi-party governance, and oracle guards. | Bugs, integration failures, and upgrade errors remain possible despite these controls. |
| Oracle | Threshold guard halts value paths and requires an evidence-tagged governance response. | Incorrect or unavailable oracle data can delay deposits and redemptions. |
| Liquidity and redemption | cUSD+ supports a defined USDT redemption path from day one. | InstantManager liquidity, provider availability, network conditions, or compliance actions may delay exits. |
| Permissioning | USDY access and vault operations follow Ondo’s permissioned-purchaser and eligibility framework. | Ondo may change eligibility or block/deny an address under its rules. |
| Key recovery | Device-generated keys and personal-cloud recovery avoid a central key vault. | Loss of device/cloud access, platform changes, or recovery defects can affect access. |
| Upgrade governance | Multi-party Safe, public upgrade records, source verification, storage-layout checks. | Authorized signers could make a harmful change or fail to respond during an incident. |
| Fiat rails | Koywe and Guardarian are live; additional providers are added only after contracts and production capabilities are verified. | Country coverage, payment methods, bank dependencies, pricing, and provider suspensions can change. |
| Regulatory | Identity checks, provider controls, phased markets, legal review. | Rules differ by jurisdiction and may restrict availability or require product changes. |
| Multi-chain UX | The app abstracts chains and separates product roles. | Bridges, conversions, address recovery, and chain-specific failures add complexity. |
| Metrics and concentration | Definitions and unaudited status are disclosed. | Early usage or TVL may be concentrated and may not predict broad adoption. |

## 12. Roadmap and current status

| Workstream | Completed / current | Next verifiable gate |
| --- | --- | --- |
| cUSD payments | Algorand wallet and cUSD payment stack in production; contact, ramp, payment, and business modules in the open repository. | Deepen funded usage, merchant/payment availability, and country-level reliability. |
| cUSD+ contracts | BSC mainnet proxy deployed, upgraded, verified, and integrated with production USDY/USDT/InstantManager/oracle. | Expand production use while preserving backing, redemption reliability, and transparent governance. |
| cUSD+ operations | Multi-party Safe governance, public deployment record, and sponsored user transactions. | Expand monitoring, reliability automation, and incident runbooks. |
| Security | Layered testing, continuous adversarial review, unit, fork, invariant/fuzz, differential, and upgrade testing; public source. | Continuously expand test coverage, threat models, and public upgrade evidence. |
| Fiat access | Koywe live across seven LATAM markets; Guardarian live for SEPA and card-based access. | Add verified providers and fallback paths as agreements and production capabilities are completed. |
| Distribution | 8,004 phone-complete users; 177 Didit-verified users; ≈480K founder audience and effectively zero paid-media spend to date. | Measure and repeat the content-to-funded-user loop, retained balances, referrals, and country-level cohorts without dependence on subsidy-led acquisition. |

### 12.1 Measurement principles

Confío will distinguish signups, phone-complete users, verified users, funded users, reachable devices, active users, and retained balances. For cUSD+, the primary operating measures will be funded users, TVL, gross deposits, redemptions, net inflow, average and median balance, balance retention, fiat-originated inflow, concentration, and country cohorts.

Distribution will be measured as a funnel rather than a follower count: content reach, profile or store visit, installation, phone completion, identity verification, first funding, retained balance, repeat deposit or transaction, and referral. Confío will also distinguish organic acquisition from paid campaigns and measure performance by content and country so that a large audience is converted into reproducible operating evidence.

### 12.2 The next proof point

> **From Infrastructure To Retained Use**
>
> The next proof point is sustained consumer adoption: funded users, repeat deposits, reliable redemptions, retained balances, and measurable fiat-originated inflow across multiple Latin American markets.

## 13. Legal disclaimer

This document is provided for informational and technical-reference purposes only. It is not investment, legal, tax, accounting, or financial advice; it is not a prospectus, offer, solicitation, recommendation, or promise of returns. Product descriptions reflect the current design and status as of 23 July 2026 and may change.

cUSD and cUSD+ are not bank deposits, are not insured by a deposit-insurance scheme, and may be unavailable in particular jurisdictions or to particular persons. Stablecoins, tokenized notes, smart contracts, blockchains, oracles, bridges, fiat providers, and custodians can fail, be suspended, lose value, or become subject to new rules.

Any cUSD+ yield is variable, depends on the performance and terms of USDY and the vault, and is not guaranteed. USDY access and cUSD+ availability are subject to Ondo eligibility, compliance conditions, provider availability, and applicable law.

$CONFIO is separate from the backing of cUSD and cUSD+. Nothing in this whitepaper changes the terms, allocation, lockups, rights, or disclosures applicable to $CONFIO. Readers should review the definitive product terms, risk disclosures, smart contracts, provider terms, and local law before using any service.

## Endnotes

1. World Bank, Migration and Development Brief: remittance flows to Latin America and the Caribbean, 2025 estimate (US$162B). https://documents1.worldbank.org/curated/en/099714008132436612/pdf/IDU1a9cf73b51fcad1425a1a0dd1cc8f2f3331ce.pdf

2. Chainalysis, “Latin America Emerges as Crypto Powerhouse Amid Volatile Growth,” 2 October 2025. https://www.chainalysis.com/blog/latin-america-crypto-adoption-2025/

3. Confío public GitHub repository and README: open-source application, backend, contracts, cUSD product, wallet model, payments and payroll modules. https://github.com/caesar4321/Confio

4. Confío, “Por qué Confío no guarda tu dinero - y por qué eso importa,” uploaded project source, accessed July 2026.

5. Algorand Foundation Developer Portal, “Instant Finality,” 5 March 2024. https://developer.algorand.org/solutions/avm-evm-instant-finality/

6. Algorand Developer Portal, transaction structure and fee documentation. https://developer.algorand.org/docs/get-details/transactions/

7. Ondo Finance documentation, “USDY Basics,” accessed July 2026. https://docs.ondo.finance/general-access-products/usdy/basics

8. Confío, “cUSD+ deployment record - BSC mainnet,” updated 20 July 2026. https://github.com/caesar4321/Confio/blob/main/contracts/cusd_plus/DEPLOYMENT.md

9. BscScan, Confío Dollar+ ERC1967 proxy, address 0x3C29417eb4314155e63d4C7D4507852b87763Ed1. https://bscscan.com/address/0x3C29417eb4314155e63d4C7D4507852b87763Ed1#code

10. Ondo Finance developer documentation, “Integrating with the USDY_InstantManager contract.” https://docs.ondo.finance/developer-guides/usdy-instant-manager-integration

11. Confío, CusdPlusVault.sol, deployed cUSD+ accounting, redemption, oracle guard, and 15% Confío yield-share logic. https://github.com/caesar4321/Confio/blob/main/contracts/cusd_plus/CusdPlusVault.sol

12. BNB Chain developer documentation, BNB Smart Chain introduction and finality. https://docs.bnbchain.org/bnb-smart-chain/introduction/

13. Confío internal partner records, July 2026: Koywe and Guardarian commercial agreements and production integrations in effect across supported markets and payment methods. Commercial terms remain governed by the respective agreements.

14. Confío internal product analytics snapshot, 23 July 2026: phone-complete, Didit verification, KYC completion, and FCM device metrics. Unaudited.

15. Confío internal founder-channel analytics snapshot, 23 July 2026. Audience figure is approximate and changes over time.

16. Benedetto Biondi, “The New Face Of Global Payments: Onchain Consumer Finance Apps,” *Forbes Technology Council*, 6 July 2026. The article argues that consumer finance products are converging on stablecoin rails and that distribution, trust, and fit with local demand will increasingly determine the winners. https://www.forbes.com/councils/forbestechcouncil/2026/07/06/the-new-face-of-global-payments-onchain-consumer-finance-apps/

17. Algorand, official network overview, accessed 23 July 2026: “0 downtime in 7 years (and counting)” and uninterrupted network availability since launch. https://algorand.co/

### Document provenance

Prepared from the prior English whitepaper, Confío’s uploaded pitch deck and product materials, current Koywe and Guardarian partner records, the public repository and deployment records, official Algorand/BNB Chain/Ondo documentation, cited market literature, and the internal operating metrics explicitly provided for this update.
