# Confío: The AI Assistant That Pays in Latin America

**Tell Confío what you need. It pays, buys, and invests with your dollars — and you stay in control.**

Confío is an AI-first, fully open-source, non-custodial financial assistant built for Latin America’s dollar reality. A person asks Confío IA in plain words to pay a person or a store, buy something online, top up, or invest; Confío prepares it on the local rail of that country, shows the exact terms, and acts only on the person’s confirmation or within limits the person signed. Underneath sits verifiable dollar infrastructure on BNB Smart Chain that Confío cannot withdraw from.

**Global reference · Version 4.5 · November 2026**<br>
Julian Moon · Founder & CEO<br>
[confio.lat](https://confio.lat) · [GitHub](https://github.com/caesar4321/Confio)

*Lo tuyo, tuyo. · Pídelo en palabras; Confío lo hace.*

**Authoritative original:** This English document is the sole authoritative version of the Confío whitepaper. A Spanish translation is provided for convenience and may lag behind this original. If the translation differs from the English text, the English text controls.

This paper is the current global reference for Confío’s product architecture, strategy, operating model, and material risks. Detailed $CONFIO allocation and vesting terms remain in the separate tokenomics document.

<details>
<summary><strong>Contents</strong></summary>

1. [Executive summary](#1-executive-summary)
2. [The market thesis](#2-the-market-thesis)
3. [Confío IA: the assistant that pays](#3-confío-ia-the-assistant-that-pays)
4. [Cuenta inteligente: an account the assistant can operate](#4-cuenta-inteligente-an-account-the-assistant-can-operate)
5. [Why an AI can be trusted to pay: the BNB Smart Chain foundation](#5-why-an-ai-can-be-trusted-to-pay-the-bnb-smart-chain-foundation)
6. [cUSD and cUSD+: money and savings](#6-cusd-and-cusd-money-and-savings)
7. [Payments, payroll, investing, and Comprar](#7-payments-payroll-investing-and-comprar)
8. [$CONFIO on BNB Smart Chain](#8-confio-on-bnb-smart-chain)
9. [Wallet, security, and open-source architecture](#9-wallet-security-and-open-source-architecture)
10. [Users, distribution, and go-to-market](#10-users-distribution-and-go-to-market)
11. [Business model](#11-business-model)
12. [Compliance and operating model](#12-compliance-and-operating-model)
13. [Risks and mitigations](#13-risks-and-mitigations)
14. [Roadmap and current status](#14-roadmap-and-current-status)
15. [Legal disclaimer](#15-legal-disclaimer)
16. [Endnotes](#endnotes)

</details>

---

## 1. Executive summary

Confío is an AI-first financial assistant for Latin America. The conversation with **Confío IA** is the product surface: on current app builds, the home screen is the chat, the first conversation is the onboarding, and every job in the app can be reached from it. A person writes what they need in their own words — pay this QR, send dollars to my sister, buy this at that store and pay it, top up, buy some gold — and Confío does it with the person’s own dollars, on that country’s local rail, after an exact confirmation. <sup>[3, 26]</sup>

> **Product thesis**
>
> In Latin America the hard part of paying is not choosing a product; it is crossing fragmented local rails, informal payment habits, and a deficit of trust. The winning consumer platform will not ask people to learn crypto or install ten apps. It will let them ask in words, and it will prove — in code anyone can read and on-chain limits anyone can check — that the assistant can only do what the person approved. Confío combines that assistant with non-custodial dollars, local payment rails, and a founder-led Spanish-language channel of approximately 480,000 people, with effectively zero paid-media spend to date.

What Confío IA can do today, each step confirmed by the person or bounded by limits they signed:

| Job | How it works |
| --- | --- |
| Pay people and QR codes | The assistant prepares a send or a local-rail payment as a card in the chat; code, not the model, asks for the amount and checks the payee; the person confirms and signs on their own phone. |
| Buy at online stores | A shopping agent searches one or several stores in a cloud browser, builds the cart, shows the real total with shipping, and pays the store with the local rail of its country: SPEI in Mexico, Pix in Brazil, Pago Móvil in Venezuela (limited to stores that ask only for the payment reference); in Bolivia the order is placed and the person pays the store’s QR. |
| Top up and withdraw | The chat leaves the top-up or withdrawal form with the country’s live provider limits. |
| Invest | Ondo Stocks, gold, and bitcoin trades are proposed as priced cards. For Cuenta inteligente subscribers, chat trades can execute within an owner-signed weekly cap. |
| Automate | Cuenta inteligente runs scheduled sends, bank payouts (CLABE, Pix, Pago Móvil), and automatic investing, and can pass to one named beneficiary. |

The foundation is what makes it safe to give an assistant access to money. The user’s wallet key is generated on the user’s device and is not held by Confío; balances are cUSD or cUSD+ on BNB Smart Chain; network fees are sponsored; and hands-off actions run through a per-user smart-contract account whose limits are enforced on-chain. Confío’s relayer key alone cannot withdraw a user’s funds.

| Component | Primary job | Design |
| --- | --- | --- |
| Confío IA | The assistant and the product surface. | Models read and propose; code checks facts, asks for amounts, and enforces confirmations, caps, and country switches. |
| Cuenta inteligente | An account the assistant can operate within limits. | One immutable smart-contract account per user, owned by the user’s wallet; US$149.99 per year (default) or US$14.99 per month. |
| cUSD | Universal payment dollar. | Upgradeable, 1:1 USDT-backed BSC token; the sole external 0.9% conversion-fee perimeter. |
| cUSD+ | Eligible dollar savings wrapper. | Upgradeable USDY-backed accumulating shares for Ondo-eligible users; internal cUSD↔cUSD+ conversion is fee-free. |
| Ondo Stocks, gold, bitcoin, Futuros | Investing. | Source-verified routers settle trades directly to the user; Oro y Bitcoin and Futuros are not offered in the iOS build. |
| $CONFIO | Community and ecosystem token. | Fixed-supply BEP-20 with a cUSD-funded on-chain presale. It does not back user dollar balances. |

As of 25 November 2026, Confío records 10,233 users who completed phone verification and 3,407 push-reachable devices, 3,402 of them used within the last 30 days. As of 23 July 2026 (the latest snapshot available under the same definition), 177 users had completed Didit identity verification by submitting a government-issued identity document and capturing a live selfie, with a 61.5% completion rate among users who began it. These are internal operating metrics rather than independently audited figures and should not be read as funded-user or monthly-active-user counts. <sup>[14]</sup>

The cUSD and cUSD+ vaults, the Ondo Stocks and swap routers, the sponsored-transaction delegate, the Cuenta inteligente factory and account implementations, the purchase spender, the Comprar escrow, the $CONFIO token and its presale, reward, and vesting vaults, the merchant-payment contract, and the payroll vault are deployed and source-verified on BNB Smart Chain. <sup>[8, 9, 17, 27]</sup>

## 2. The market thesis

### 2.1 A dollar-access problem, not a crypto-awareness problem

Latin America is not one homogeneous monetary crisis. Some users need protection from local-currency volatility; others need affordable cross-border settlement, a safe place for dollar savings, or a practical way to pay and be paid. What connects these markets is demand for a reliable dollar unit and dissatisfaction with the friction surrounding it. Stablecoin adoption across the region shows that this behavior is already on-chain rather than merely theoretical. <sup>[2]</sup>

| Market | Observed dollar need | Product implication |
| --- | --- | --- |
| Argentina | Repeated inflation and capital controls, together with the institutional memory of the 2001 *corralito* and forced conversion of dollar deposits, taught households to value access and control as much as nominal yield. Most recent exchange restrictions have eased, but the historical trust deficit remains relevant. <sup>[19]</sup> | A dollar product must make custody boundaries, withdrawal rights, pricing, and rule changes unusually clear. |
| Venezuela | Extreme inflation pushed the U.S. dollar into both store-of-value and everyday payment functions, creating a highly dollarized but operationally fragmented economy. <sup>[20]</sup> | Dollar access and Pago Móvil utility are immediate needs, while sanctions, provider availability, and compliance require tighter controls. |
| Bolivia | The IMF’s 2025 assessment described usable foreign-exchange reserves as close to zero, a widening parallel-rate gap, and severe limits on private-sector access to official-rate dollars. <sup>[21]</sup> | Reliable access, transparent local pricing, and interoperable QR rails can solve a daily liquidity problem rather than a speculative use case. |
| Peru | Households already hold tens of billions of dollars in foreign-currency deposits, while Yape, PLIN, and interoperable QR systems have normalized mobile payments. <sup>[22]</sup> | The opportunity is not to teach users to want dollars, but to provide portable dollar savings and payments with familiar local entry points. |
| Mexico | Foreign-currency bank deposits and approximately US$62.5 billion in annual remittances demonstrate both dollar savings and cross-border demand. <sup>[23]</sup> | SPEI access, dollar balances, yield, and family transfers can live in one consumer product. |
| Colombia | The United States supplies more than half of remittance inflows, while Colombia hosts approximately 2.8 million Venezuelans. <sup>[24, 25]</sup> | Local bank access can connect international remittances with the Colombia–Venezuela family-transfer corridor. |
| United States and Spain | These are two of the most important origin markets for Latin American remittances. The United States accounts for 35.7% of South American inflows; Europe accounts for 36.2%, including 19.7 percentage points from Spain. <sup>[24]</sup> | Diaspora earnings should reach recipients’ dollar balances without forcing both sides into a trading product. |

The result is a regional **dollar reflex**: people seek USD exposure even when access is expensive, informal, or operationally fragile.

### 2.2 Remittances are a balance-sheet opportunity

Latin America and the Caribbean received an estimated US$173.7 billion in remittances in 2025. <sup>[1]</sup> Most products treat a remittance as a one-time transfer. Confío treats it as the start of a financial relationship: the recipient can retain dollars, earn variable yield through cUSD+, send to contacts, pay a merchant or an online store, or withdraw through a local rail — by asking.

### 2.3 Why AI-first matters in Latin America

Each country runs its own payment system. Brazil pays with Pix, the central bank’s instant payment system; Mexico with SPEI transfers to an 18-digit CLABE; Colombia is moving to Bre-B keys and QR; Peru with Yape, PLIN, and interoperable QR; Venezuela with Pago Móvil; Bolivia with bank QR codes. <sup>[22, 28, 29]</sup> A checkout in one country rarely accepts the rail of another, and many everyday payments — a seller on WhatsApp, a worker paid by QR, an online store that shows bank details instead of a card form — happen outside card networks.

For the person this means learning a different app, form, and set of identifiers for each job. For an assistant it is the opposite opportunity: the rail can be picked by code from the country of the payee, while the person only says what they want. Card-based agent payments, common in markets where everyone holds a card, do not reach these rails. An assistant that holds a self-custody dollar balance and has payout access to the national rails can pay where a card-based assistant cannot follow.

Confío’s own assistant logs point in the same direction: people already ask it, in their own words, to send money abroad and to pay by QR. Confío reports this qualitatively; it does not publish chat content.

### 2.4 The deeper problem: *falta de confianza*

Latin American users have experienced bank freezes, currency controls, failed fintechs, informal brokers, hidden spreads, and crypto platforms designed around speculation. Giving money to an AI raises the same question more sharply: what stops it from doing the wrong thing?

Confío’s answer has three layers:

1. **Verifiable control:** the user’s wallet key is generated on the user’s device and is not held by Confío.
2. **Bounded agency:** the assistant cannot invent amounts or payees; every payment is an exact confirmation or falls inside a limit the person signed on-chain.
3. **Human trust:** Spanish-first education, clear pricing, local payment methods, visible leadership, and an assistant that says plainly what it cannot do.

*Lo tuyo, tuyo* is therefore both a brand promise and an architectural constraint.

## 3. Confío IA: the assistant that pays

### 3.1 The chat is the product

On current builds, Inicio is the conversation with Confío IA. A new user meets their assistant and is asked, in words, what they want Confío for; the answer shapes the next steps. Every screen the menu offers — top-up, withdrawal, Cobrar, invitations, history, investments, Comprar, Cuenta inteligente, business and payroll tools — has a door from the chat, so a person who never opens a menu can still do everything. The assistant answers questions, reads the person’s own movements and monthly summary, accepts photos and voice notes, and can search the web for general questions. <sup>[3, 26]</sup>

Confío IA answers and advises for everyone. It explains instruments, risks, and the person’s own numbers, but it does not tell a person to buy, sell, or hold a named ticker, and it does not predict prices.

### 3.2 How a request becomes a payment

| Step | Who does it | What is checked |
| --- | --- | --- |
| 1. Understand | The model reads the request and decides which job it is. | Tool output and third-party text are treated as data, never as instructions; after a web search the turn loses its money tools. |
| 2. Ask the amount | Code, not the model, writes the question (“¿Cuántos dólares? Escribe solo el número”). | No amount is ever read out of a sentence; the number typed alone as the next message is both the amount and the yes. A “no” withdraws pending cards. |
| 3. Resolve the payee | Code parses and validates the destination: Pix keys and QR codes with their checksum, CLABE check digits, Pago Móvil data, Confío contacts. | The card shows only what code resolved and the rail validated; a name nobody verified is never marked as verified. |
| 4. Quote | Code prices the payment: local amount, dollar total, exchange rate, Confío fee, expiry. | A charge with a fixed local amount is paid exactly; the person sees the total before confirming. |
| 5. Confirm | The person reviews the card and signs on their own device (or, for a subscriber’s hands-off action, the account checks its signed cap on-chain). | The model cannot draw the confirmation sheet and cannot sign. |
| 6. Settle and report | The payout runs on the local rail; the card follows the provider’s status. | A card never says “paid” before the rail reports completion. |

Which rails are offered is decided by live switches per country and per provider, not by the model. When a corridor is paused, the assistant says so rather than improvising a route.

### 3.3 The shopping agent

Confío IA can buy at online stores. The person names a product (and optionally a store); when no store is named, one search across several stores returns a short list of offers. A shopping agent then works in a cloud browser that the person can watch live: it opens the store, adds the chosen items, reaches the checkout, and reads the real total with shipping. <sup>[3]</sup>

- **Choice is consent.** Each offered product shows a top total (“hasta $X con envío”). Choosing it approves that item, quantity, and top total. A higher real total, an unreadable price, or a different payer brings back an ordinary order card with the real breakdown.
- **Models decide, code checks facts.** One model drives the browser and a separate judge — from a different model family — reviews each press; a final review reads the last page before ordering. Code checks only facts: one approval places one order; both models must read the same total, and that total must appear on the page; a payment identifier must be a valid one shown beside the approved amount on a page that appeared after the order, never one taken from an item title or seen before the order.
- **Ceilings in code.** Each task has step, time, and model-cost limits enforced by the server, never by the model.
- **Local rails by store country.** The rail follows the store’s country: SPEI bank details read from the store’s own checkout in Mexico (paid out for the exact peso amount; any conversion surplus stays in the person’s local account), Pix QR in Brazil, and Pago Móvil in Venezuela, where the payment is made before the order and the reference is entered into the store’s form. In Bolivia, while QR payments by Confío are switched off, the agent places the order and the person pays the store’s QR from their bank. Other countries are refused rather than paid by an approximate transfer.
- **Who pays.** Search, cart, and the priced review are free for everyone. Buying and paying the store is a Cuenta inteligente benefit: the account pays through a “Compras con Confío IA” rule signed once with Confío Face (default US$200 per 28-day period, editable). A purchase is never paid directly from the personal wallet.

The shopping agent is early. Store pages change, some checkouts do not offer a payable local rail to ordinary accounts, and Confío has not yet demonstrated reliable completion across many stores. Confío presents it as a working capability with honest limits, not as a solved problem.

### 3.4 Hands-off execution within signed limits

For Cuenta inteligente subscribers, live since 25 November 2026, chat trades in Ondo Stocks, gold, and bitcoin, Comprar purchases, and store purchases can be executed by the person’s account without a signature per action, within limits the owner signed:

- **Trade cap.** Chosen at the first hands-off trade and signed once with Face (for example US$250, 1,000, or 2,500 per week, or another amount). Buys and sells both count. The cap is a leaky bucket: at most one cap at any instant and one cap per week on average (just under two caps within any single week).
- **Funds stay in the account.** What the chat buys is held in the account. The relayer can trigger only rule-shaped actions: swaps must stay within 1.5% of a Chainlink price feed, the stock fee is bounded at 90 basis points, and sells must return their value to the account within that band.
- **Notification and kill switch.** Every hands-off trade notifies the owner; one without a chat proposal behind it raises a security alert. The Safe can stop every hands-off path at once (`tradePaused`).
- **Self-directed screens stay free.** The Acciones, Oro y Bitcoin, and Comprar screens remain available from the personal wallet, signed by the person.

### 3.5 What Confío IA will not do

- Read an amount out of a sentence, or move money on a “yes” to a question it wrote itself without code-checked terms.
- Pay a payee whose details code could not validate, or present an unverified name as verified.
- Pay above a total the person approved, or above a cap the person signed.
- Pay a store in a country without a rail that pays the store’s exact local amount.
- Recommend a named ticker or predict prices.
- Offer Oro y Bitcoin or Futuros to iOS users, or any product where the person’s country or eligibility excludes it.
- Hand the conversation off silently: when it cannot do something, it says so and, where possible, opens the screen where the person can do it themselves.

### 3.6 Current limits by country

Capabilities follow live provider switches and change; this is the state as of 25 November 2026. <sup>[13]</sup>

| Country | Live today | Not available or paused |
| --- | --- | --- |
| Mexico | Top-up and withdrawal; own CLABE to receive pesos; SPEI payouts to any CLABE; Cuenta inteligente scheduled CLABE payouts; shopping-agent SPEI payments. | — |
| Brazil | Pix payments by key, QR, or code; receiving by Pix QR; Cuenta inteligente scheduled Pix payouts; shopping-agent Pix payments. | — |
| Venezuela | Pago Móvil top-up and Pago Móvil sends; Cuenta inteligente Pago Móvil payouts; shopping agent for stores that ask only the payment reference. | Stores that require other payment data. |
| Bolivia | Top-up and bank withdrawal; Comprar marketplace; shopping agent with the person paying the store’s QR. | Paying and receiving bank QR codes through Confío (switched off). |
| Argentina, Chile, Peru | Local top-up rails; withdrawals where the provider offers them. | Argentine CVU and QR payouts from a Confío local account (pending provider readiness). |
| Colombia | Withdrawals through the existing ramp. | Top-up and Bre-B conversion and payouts (paused). |

## 4. Cuenta inteligente: an account the assistant can operate

### 4.1 What it is

Cuenta inteligente is a paid account inside Confío. Technically it is a separate smart contract, one per user, owned by the user’s personal wallet. The user moves assets into it; assets inside it can be moved by rules the user sets and can pass to one named beneficiary. Assets in the personal wallet are not affected. <sup>[27]</sup>

| Included | What the user gets |
| --- | --- |
| Automatic payments and transfers | Daily, weekly, biweekly, or monthly sends to Confío users and payouts to a saved bank destination (CLABE, Pix, Pago Móvil; Colombian Bre-B payouts are paused). |
| Automatic investing | Periodic buys of stocks, bitcoin, and gold. |
| Confío IA+ | The assistant executes on the owner’s account: it proposes rule changes the owner asks for, keeps a target split with new buys, sets alerts, writes a monthly review, makes hands-off trades within the weekly cap, and buys at stores within the purchase cap. |
| Beneficiary (*Herencia Digital*) | One Didit-verified beneficiary can take ownership after a challenge window (default 180 days, selectable from 90 to 1,825) during which any owner-signed action cancels the claim. |

**Price:** US$149.99 per year (preselected) or US$14.99 per month, one tier, no refunds. The fee is taken from inside the account: dollars first, then, after notices, a forced sale of one period’s fee from other assets. The 0.9% conversion fee is unchanged and not waived for subscribers. <sup>[27]</sup>

### 4.2 Contract design

- **Accounts are immutable.** Each account is an EIP-1167 clone with no upgrade function, no `DELEGATECALL`, and no `SELFDESTRUCT`. Every limit the account depends on (maximum fee, notice floors, challenge-window bounds) is a constant of the account, and values read from the factory are clamped, so a factory upgrade cannot widen them. `withdraw`, `withdrawAll`, `cancelClaim`, and the claim functions work even if every factory call fails.
- **Factory per generation.** The UUPS factory, owned by the 3-of-5 Safe, holds global settings and creates one current account per owner. Since 25 November 2026 it records one implementation per generation: existing v1 accounts keep their bytecode, new accounts use `ConfioSmartAccountV2`, and moving to v2 is an opt-in `migrate()` that the owner signs in one batch.
- **v2 additions.** Trade and Purchase rule kinds, relayer-only `relayTrade` and `relayPurchase`, a per-rule leaky bucket, a minimum gap between relayed trades, price-feed bands, and the fee bound described in section 3.4.
- **Purchases.** A store purchase is pulled by `ConfioPurchaseSpender`: the account’s own rule check sends exactly the approved USDT through the normal 0.9% exit, and the same transaction forwards all of it to that payment’s bridge deposit; nothing stays in the spender. Comprar purchases from the chat go into the Comprar escrow through `depositFrom`, which records the owner as buyer and refunds to the paying account.

### 4.3 Trust assumption, stated plainly

Hands-off trades and purchases trust `ConfioStockRouter`, `ConfioSwapRouter`, and `ConfioMarketEscrow`, which the Safe can upgrade — as v1 buy rules already trust the routers. A compromised relayer key alone cannot move value out of an account. A compromised relayer key together with a malicious Safe upgrade of the stock router could still sell stock at a forged price, because the account cannot verify Ondo’s quote signature itself. A compromised purchase-operator key is bounded by each owner’s signed purchase cap (at worst about twice the cap around a period boundary), the Safe’s spender allowlist, and its card pause. The Comprar escrow’s order signer has its own key, separate from the arbiter and relayer.

The v2 changes received an internal independent review on 25 November 2026 before go-live. Its findings were fixed and each proof of concept is kept as a Foundry regression test asserting that the attack now fails — among them, sells now count in the cap at feed value, and dollars received from a stock sale are held to the quote value even if the router were replaced. This was not an external audit by a security firm. <sup>[27]</sup>

## 5. Why an AI can be trusted to pay: the BNB Smart Chain foundation

An assistant is only as trustworthy as the money system beneath it. Confío’s foundation was built so that the assistant never needs custody: the user’s key stays on the user’s device, assets live in contracts with public rules, and the server can only prepare calls that the user — or the user’s own account, within signed limits — executes.

| User action | Asset or contract | What happens on-chain |
| --- | --- | --- |
| Add dollars | cUSD or cUSD+ | A fiat provider or external wallet delivers BSC-USDT. The app automatically converts it into cUSD for an Ondo-ineligible user or cUSD+ for an eligible user, charging the 0.9% Confío conversion fee. |
| Save | cUSD↔cUSD+ wrapper boundary | Eligible users can move cUSD into USDY-backed cUSD+ without a conversion fee; the reverse internal conversion is also free. Both paths require a Confío-sponsored transaction. |
| Send | cUSD or cUSD+ | Like-for-like transfers stay in the sender’s asset; cross-eligibility friend transfers convert internally without a fee. |
| Pay a local rail | cUSD or cUSD+ → USDT → local currency | The dollar leaves through cUSD’s 0.9% exit and a provider pays the exact local amount. |
| Pay a merchant | cUSD+, cUSD, or $CONFIO | The payment contract pays the merchant, enforces the separate 0.9% Pay fee, and records fee accrual on-chain. |
| Run payroll | cUSD+ or cUSD | Businesses fund asset-separated escrow; authorized delegates sign payouts. |
| Trade stocks, gold, or bitcoin | Stock router or swap router | A sponsored transaction settles and delivers the asset directly to the user’s wallet or Cuenta inteligente; sales return to the user’s dollar. |
| Buy in Comprar | Comprar escrow | The buyer’s dollars are held per order until delivery is confirmed or a dispute is resolved. |
| Automate or delegate | Cuenta inteligente | Rules and caps the owner signed are enforced by the account contract. |

### 5.1 Public BNB Smart Chain deployments

All contracts listed below are live on BNB Smart Chain mainnet and source-verified on BscScan (proxies linked to their verified implementations). Upgradeable contracts are owned by the 3-of-5 Safe `0xF29A418744E793973BF4eEc676F8a30B2793b623`.

| Contract | Address |
| --- | --- |
| cUSD vault proxy | [`0x6101cC370635cF2c7f2725EaB010aC407A8d543F`](https://bscscan.com/address/0x6101cC370635cF2c7f2725EaB010aC407A8d543F#code) |
| cUSD+ vault proxy | [`0x3C29417eb4314155e63d4C7D4507852b87763Ed1`](https://bscscan.com/address/0x3C29417eb4314155e63d4C7D4507852b87763Ed1#code) |
| Ondo Stocks router (UUPS proxy) | [`0x40c8e134BCAf44EEf9e7D184846F36c9862329c3`](https://bscscan.com/address/0x40c8e134BCAf44EEf9e7D184846F36c9862329c3#code) |
| Gold and bitcoin swap router, `ConfioSwapRouter` (proxy) | [`0xA7C27684aB38eC369cB1F4474f279ea503dbF712`](https://bscscan.com/address/0xA7C27684aB38eC369cB1F4474f279ea503dbF712#code) |
| Sponsored-batch delegate | [`0xC06BD197b34a587026615C6AEd21301F5E99bc00`](https://bscscan.com/address/0xC06BD197b34a587026615C6AEd21301F5E99bc00#code) |
| Cuenta inteligente factory (UUPS proxy) | [`0x339094A17605B842e0b2fc01441204E67020f953`](https://bscscan.com/address/0x339094A17605B842e0b2fc01441204E67020f953#code) |
| Cuenta inteligente account implementation v2, `ConfioSmartAccountV2` | [`0x0b3DAf407AF2cF5bC7a1475bF44bD3952533cdF7`](https://bscscan.com/address/0x0b3DAf407AF2cF5bC7a1475bF44bD3952533cdF7#code) |
| Cuenta inteligente account implementation v1 | [`0x8a20a0B3d2C0c6BED8BeB00bB6Bc7AE3c7ace44A`](https://bscscan.com/address/0x8a20a0B3d2C0c6BED8BeB00bB6Bc7AE3c7ace44A#code) |
| Cuenta inteligente fee collector | [`0x1AE0ACB82bAb9F506188c49305953CB655A539CD`](https://bscscan.com/address/0x1AE0ACB82bAb9F506188c49305953CB655A539CD#code) |
| Purchase spender, `ConfioPurchaseSpender` | [`0xD0ea8Ec3a6F3AD49f13a18Ce801C9594311A32Ca`](https://bscscan.com/address/0xD0ea8Ec3a6F3AD49f13a18Ce801C9594311A32Ca#code) |
| Comprar escrow, `ConfioMarketEscrow` (UUPS proxy) | [`0x2DFDC1fB809322c12f54beFE8CC98E0d103a99Fd`](https://bscscan.com/address/0x2DFDC1fB809322c12f54beFE8CC98E0d103a99Fd#code) |
| Emergency-exit heartbeat, `ConfioHeartbeat` (proxy) | [`0xAE49E3AD57531974CD2AEc2633b03770fF4a20FF`](https://bscscan.com/address/0xAE49E3AD57531974CD2AEc2633b03770fF4a20FF#code) |
| $CONFIO token | [`0xF5765933764562A51e179F6AF2b19b7a3d506101`](https://bscscan.com/token/0xF5765933764562A51e179F6AF2b19b7a3d506101) |
| $CONFIO presale vault | [`0xB13Cda84348609c534aD1eFA9D4D39a62b2F18b4`](https://bscscan.com/address/0xB13Cda84348609c534aD1eFA9D4D39a62b2F18b4#code) |
| $CONFIO reward vault | [`0x3E022ADD4b3ae8618e431D83004e2aeb5F76AA49`](https://bscscan.com/address/0x3E022ADD4b3ae8618e431D83004e2aeb5F76AA49#code) |
| $CONFIO vesting vault | [`0x873A68182A384DD84385C7B610Df5D2A3746D75a`](https://bscscan.com/address/0x873A68182A384DD84385C7B610Df5D2A3746D75a#code) |
| Invitation escrow | [`0xe6c49CcEb57b86dfE2F597053f8f475F18AcDb59`](https://bscscan.com/address/0xe6c49CcEb57b86dfE2F597053f8f475F18AcDb59#code) |
| Merchant-payment contract | [`0x942BF5F3C9079Ab29492324B9F1E501Db5B830bA`](https://bscscan.com/address/0x942BF5F3C9079Ab29492324B9F1E501Db5B830bA#code) |
| Payroll vault | [`0x851e1a56De5c0ADBB75e904B2E7325e132692027`](https://bscscan.com/address/0x851e1a56De5c0ADBB75e904B2E7325e132692027#code) |

**Changes since version 4.4.** All through the Safe and recorded in the public deployment records: <sup>[8, 27]</sup>

- 9 November 2026: Ondo Stocks router v3 deleted the transitional 0.30% fee path (section 7.4).
- 21–22 November 2026: Cuenta inteligente factory, v1 account implementation, and fee collector deployed; cUSD upgraded so factory accounts can arm the fee referral; inheritance enabled (one-way).
- 25 November 2026: `ConfioSmartAccountV2` deployed; the factory proxy upgraded (implementation per generation, `migrate()`, `tradePaused`); the Comprar escrow proxy upgraded (`depositFrom` with a payer-bound signature, refunds to the paying account; the order signer moved to its own key while the arbiter remains the sponsor); `ConfioPurchaseSpender` deployed and allowlisted; hands-off trading unpaused after a canary migration of a founder account.

### 5.2 Why one network matters

- no bridge is required between the primary dollar balance, savings, payments, payroll, Cuenta inteligente, investing, and $CONFIO;
- one EVM address can receive the user’s funding, product balances, and ecosystem token; and
- one sponsored-transaction system can pay network fees across the product, so the assistant never has to ask a person to buy gas.

Users still face product-specific eligibility and provider rules. A unified chain does not make all assets economically or legally identical.

### 5.3 Why BNB Smart Chain

**The product followed Ondo’s infrastructure.** cUSD+ was designed around USDY, and Ondo deployed the production USDY token, InstantManager, price oracle, USDT subscription/redemption route, and Global Markets settlement infrastructure on BNB Smart Chain. Keeping the Confío product system beside that infrastructure provides direct routes into USDY-backed savings and eligible Ondo Stocks access. <sup>[7, 8, 10, 18]</sup>

**Consumer-scale economics and liquidity.** BNB Smart Chain adds broad USDT liquidity, low transaction costs suitable for sponsored consumer activity, mature wallets, RPC providers, explorers, and developer tooling, and one environment for every Confío contract. <sup>[5, 6, 12]</sup> Chain ecosystem size does not create product demand by itself.

**Trade-offs.** BNB Smart Chain has different decentralization and operational characteristics from other networks. Network interruption, validator coordination, congestion, gas-price changes, RPC failures, or ecosystem-level policy changes remain possible. Confío mitigates these risks with sponsored transactions, multiple RPC paths, explicit emergency exits, non-custodial ownership, and public contract state, but it cannot eliminate base-network risk.

## 6. cUSD and cUSD+: money and savings

cUSD is the universal payment dollar, backed 1:1 by USDT in its deployed UUPS vault. cUSD+ is an accumulating dollar-denominated savings share backed by USDY in the existing upgraded cUSD+ proxy. The app selects cUSD for users who are not eligible for USDY exposure and cUSD+ for eligible users, and a user holds one or the other, never both, presented as one dollar balance.

### 6.1 Deposit and redemption flow

| Entry | Exit |
| --- | --- |
| 1. USDT reaches the user’s BSC address from a ramp or an external wallet. | 1. The user requests local-currency withdrawal, a local-rail payment, or an external USDT send. |
| 2. A user-authorized sponsored batch calls the appropriate fee-bearing mint path. | 2. cUSD burns directly, or cUSD+ burns and redeems USDY through InstantManager. |
| 3. The cUSD fee perimeter retains 0.9% and mints cUSD, or returns net USDT to cUSD+ for USDY subscription. | 3. The cUSD fee perimeter retains 0.9% of the gross exit value. |
| 4. The user receives cUSD if Ondo-ineligible or cUSD+ if eligible. | 4. Net USDT goes to the designated external wallet or ramp address. |

The cUSD vault is the only external conversion-fee perimeter. Its fee is capped in code at 90 basis points. Minting always requires an authorized sponsor; fee-free redemption is restricted to the cUSD+ savings boundary; ordinary fee-bearing redemption remains permissionless so a holder can exit without Confío’s sponsor. cUSD+ follows the same exit principle.

The cUSD+ vault, not the end user, is the permissioned USDY purchaser. Users hold cUSD+, not raw USDY. Internal cUSD↔cUSD+ conversion is fee-free only because value stays inside the Confío dollar system; it does not create a free external USDT path.

### 6.2 Accumulating value and yield share

USDY’s reference price is designed to appreciate as underlying yield accrues. On each relevant interaction, the vault updates the cUSD+ reference value: 85% of positive USDY reference-price appreciation increases the cUSD+ holder reference value, and 15% becomes vault surplus available to Confío. The share count does not increase; the dollar reference value per share rises. Yield is variable, may change, and is not guaranteed. <sup>[7, 11]</sup>

### 6.3 Backing and oracle controls

The vault exposes public views for total obligations, backing ratio, and surplus. Its accounting rounds in favor of backing and restricts fee collection to provable surplus. USDY backing cannot be swept by the owner. If the USDY oracle falls or moves beyond a configured guard threshold, value-moving paths halt, and multi-party governance must record an evidence-linked decision before they resume. This reduces automated mispricing risk but cannot remove oracle, issuer, or governance risk.

## 7. Payments, payroll, investing, and Comprar

### 7.1 Person-to-person transfers

The server prepares the exact calls, the user signs them, and Confío sponsors network gas. cUSD+ transfers directly to an eligible recipient, cUSD to a recipient who should hold cUSD, and a sponsor-authorized, fee-free conversion bridges the eligibility boundary. Confío takes no platform fee on person-to-person transfers; the 0.9% conversion fee applies only when value enters from or leaves to USDT.

### 7.2 Merchant payments

A merchant charges in **Confío dollars** or **$CONFIO**. The payment contract calculates the 0.9% merchant fee, pays the merchant net amount directly, and accrues only earned fees. Confío’s backend signs a short-lived authorization over the exact payment terms; exactly one payment can settle an invoice, and each invoice records the single network permitted to settle it. Raw USDT remains a legacy allowlisted token that the production backend does not authorize, so Pay cannot become a route around the conversion fee.

### 7.3 Payroll and mass payouts

Businesses can hold working capital as cUSD+ or cUSD in asset-separated escrow and authorize delegates to sign specific payouts. Eligible recipients can receive cUSD+; ineligible recipients receive cUSD through the fee-free internal conversion boundary. Payroll fee accounting stays separate from business principal.

### 7.4 Ondo Stocks

Confío integrates eligible access to Ondo Stocks through Ondo Global Markets on BNB Smart Chain via the UUPS `ConfioStockRouter` proxy, whose upgrade authority is held by the 3-of-5 Safe that owns it. A purchase redeems the authorized cUSD+ into USDT through cUSD+’s ordinary exit (where cUSD charges the 0.9% fee), settles the attested purchase, and delivers the stock token directly to the user’s wallet or Cuenta inteligente; a sale returns the actual USDT proceeds to the user’s dollar through its ordinary entry. The router charges no fee of its own. Since router v3 (9 November 2026) it has no other fee path, an intent signed for a lower fee than cUSD’s live fee reverts, and any excess USDT from settlement is returned rather than retained. Access remains subject to Ondo eligibility, jurisdiction, market availability, and provider terms. <sup>[17, 18]</sup>

### 7.5 Oro y Bitcoin

`ConfioSwapRouter` lets a user buy and sell catalog tokens — including bitcoin (BTCB) and gold (XAUt) — with either Confío dollar inside a sponsored batch. Buys leave through cUSD’s 0.9% exit and swap all net USDT on PancakeSwap; sells swap back to USDT and re-enter through the 0.9% entry, with the result minted straight to the user. The router has no fee of its own, holds nothing at rest, builds the swap call itself with a fixed recipient, and accepts only trades originated by Confío’s relay within a maximum slippage of a live requote. Oro y Bitcoin is not offered in the iOS build and is blocked in certain countries. <sup>[30]</sup>

### 7.6 Futuros

Futuros gives eligible Android users access to perpetual futures on Hyperliquid. Money moves between the user’s dollar and Hyperliquid through Relay bridging; the 0.9% perimeter fee applies on each open, close, or margin addition, and Confío charges no separate builder fee. The app verifies each bridge order and every signature it is asked to make rather than trusting the server. Futuros is not offered in the iOS build, is blocked in the United States, Canada, the United Kingdom, and Belgium, and carries the high risks of leveraged trading, including rapid total loss of margin. <sup>[3]</sup>

### 7.7 Comprar marketplace

Comprar is an in-app marketplace for physical goods, starting with Bolivia, in which both buyers and sellers pass Didit identity verification. Purchases settle through the shared `ConfioMarketEscrow`: the buyer’s dollars are held per order; the seller has a shipping window; the buyer can confirm delivery, open a dispute, or reclaim the funds when a deadline passes; disputes are resolved by an arbiter. Sellers pay an 8% marketplace fee. Comprar is in an early pilot with very few stores and orders. <sup>[3]</sup>

## 8. $CONFIO on BNB Smart Chain

$CONFIO is the community and ecosystem token of Confío. It is not a stablecoin, does not represent a bank deposit, and does not back USDT, cUSD+, or USDY.

### 8.1 Fixed-supply token

The current BNB Smart Chain token contract has a fixed initial supply of 1,000,000,000 CONFIO. The contract has no post-deployment mint function, no global pause, and no upgrade path; the complete initial supply was created once at deployment to the multi-party treasury. Total supply can decrease through voluntary burn but cannot increase. The multi-party treasury can freeze an address during a serious security incident and, after a public 7-day wait, return a frozen balance to the party it was stolen from; this creates no tokens. <sup>[17]</sup>

**Canonical BSC contract:** [`0xF5765933764562A51e179F6AF2b19b7a3d506101`](https://bscscan.com/token/0xF5765933764562A51e179F6AF2b19b7a3d506101)

The on-chain token name is deliberately the ASCII **“Confio”**, while the accented **“Confío”** remains the product and brand name. Readers should use only the canonical address above. Allocation, founder ownership, vesting, presale rights, and concentration risks are disclosed in the separate authoritative English tokenomics.

### 8.2 On-chain presale

The replacement BSC presale vault accepts cUSD and prices purchases on an immutable piecewise-linear curve tied to cumulative tokens sold:

| Cumulative presale allocation | Curve price |
| --- | --- |
| 0–4 million CONFIO | US$0.20 → US$0.30 |
| 4–24 million CONFIO | US$0.30 → US$0.70 |
| 24–74 million CONFIO | US$0.70 → US$1.30 |

The curve segments have no administrative repricing function. The contract charges the integral under the curve, records the allocation, prevents split-purchase discounts through its pricing math, and opens claims only after sufficient CONFIO funding. It was initialized with the exact pre-deployment purchase history and is funded for the migrated claim obligation; the superseded vault is paused. Participation remains subject to eligibility, geographic controls, and the presale terms. Presale CONFIO cannot be held in a Cuenta inteligente. <sup>[17]</sup>

### 8.3 Rewards and DEX-locked claims

Reward accrual is recorded in Confío’s database and converted into CONFIO at the live presale-curve price. At claim time, the backend signer issues a short-lived EIP-712 authorization for the user’s cumulative earned amount; the RewardVault pays only the difference from what was already claimed. Claims are locked until governance calls the one-way `unlockClaims()` at the DEX launch.

> **Treasury-controlled reward pool**
>
> The RewardVault is not a trustless escrow. Its governance owner can rotate the signer, pause claims, and withdraw funds, including after the DEX unlock. Users rely on the treasury to reconcile database obligations, fund the pool, and keep valid claims available. Short signature deadlines and a daily claim cap limit signer exposure but do not remove treasury trust.

## 9. Wallet, security, and open-source architecture

### 9.1 Non-custodial wallet model

Confío generates the user’s EVM key on the user’s device. Confío’s server does not hold that private key. Encrypted recovery material is designed for the user’s personal cloud account, so recovery does not require Confío to maintain a central vault of user keys. <sup>[3, 4]</sup>

> **Ni siquiera nosotros**
>
> Confío never holds the user’s wallet key, so neither Confío nor its assistant can sign an ordinary wallet transaction as that user. What the assistant can do without a per-action signature is limited to a Cuenta inteligente the user funded, under rules and caps the user signed. Product contracts and issued assets still have their own disclosed eligibility, pause, freeze, upgrade, or governance controls. Non-custodial keys do not mean control-free financial products.

### 9.2 Sponsored transactions

Users do not need to acquire BNB. Confío uses EIP-7702 user authorizations and a deployed, ownerless batch delegate so that the user signs the intended calls while Confío’s sponsor pays gas. Approvals and actions execute atomically, reducing standing allowance risk. Server policy restricts destinations, selectors, amounts, recipients, deadlines, and daily limits before broadcast. Emergency fallback paths and direct exits remain important because sponsorship is an application service, not a blockchain guarantee. <sup>[8, 17]</sup>

### 9.3 Assistant safeguards in code

The assistant’s safety does not rest on a prompt. Money tools are scoped by the authenticated session, never by an account identifier the model supplies; business employees get no money tools; amounts come only from a code-written question; payees are validated by rail-specific parsers; confirmations are drawn by the app, not the model; tool output and page content are treated as data; the shopping agent’s spending, steps, and model cost are capped by the server; and per-country rails are turned on or off by switches that the model cannot change. Changes to the assistant and the shopping agent are tested against recorded multi-turn conversations and recorded real store pages.

### 9.4 Open source and public verifiability

The mobile application, backend, assistant, shopping agent, smart contracts, deployment records, and tests are publicly available. Deployed contracts are source-verified, allowing reviewers to compare public source and live bytecode. Security is pursued through unit, fork, invariant/fuzz, adversarial, and upgrade-rehearsal tests; public deployment records; multi-party governance; bounded fee collection and non-sweepable backing; oracle guards, pauses, replay protection, and slippage limits; and feature flags for production rollout. No review method eliminates smart-contract or operational risk. <sup>[3, 8, 9, 17, 27]</sup>

### 9.5 Upgradeability and governance

| Component | Upgradeable? | By whom |
| --- | --- | --- |
| cUSD and cUSD+ vaults | Yes (UUPS) | 3-of-5 Safe, with public implementations and storage-layout checks |
| Stock router, swap router | Yes (proxies) | 3-of-5 Safe |
| Cuenta inteligente factory | Yes (UUPS) | 3-of-5 Safe; it can add a new account implementation for new or migrating accounts and pause hands-off or card paths, but cannot change an existing account |
| Cuenta inteligente accounts | No (immutable clones) | Moving to a new version is an owner-signed `migrate()` |
| Comprar escrow, heartbeat | Yes (UUPS / proxy) | 3-of-5 Safe |
| Purchase spender, fee collector, batch delegate | No | A new operator means a new deployment allowlisted by the Safe |
| $CONFIO token, presale price curve | No | — |

The vaults remain upgradeable because cUSD+ permanently depends on external Ondo contracts that may migrate or change, and cUSD is the shared fee perimeter across product contracts. The accepted consequence is the trust assumption in section 4.3: hands-off actions trust the Safe not to install a malicious router or escrow.

## 10. Users, distribution, and go-to-market

### 10.1 Current operating metrics

| Metric | Snapshot | Date | Definition |
| --- | ---: | --- | --- |
| Phone-complete users | 10,233 | 25 Nov 2026 | Users who completed phone verification. |
| Push-reachable devices | 3,407 | 25 Nov 2026 | Devices currently addressable through push notifications. |
| Used in the last 30 days | 3,402 | 25 Nov 2026 | Push-reachable devices recorded as used within the preceding 30 days; not presented as a standardized MAU figure. |
| Didit-verified users | 177 | 23 Jul 2026 | Users who submitted a government-issued identity document and completed live-selfie liveness and face matching. |
| Identity-verification completion | 61.5% | 23 Jul 2026 | Share of users who completed the Didit flow among those who started it. |

These internal metrics are unaudited. Since late October 2026, signup no longer requires a phone number, so the phone-complete count does not include every user who finished signup. The metrics do not imply that every user is funded, active, eligible for every product, or unique across all device measures. <sup>[14]</sup>

### 10.2 Trust is the distribution channel

Confío’s founder-led Spanish-language audience is approximately 480,000 across social platforms. The strategic advantage is not the follower count alone; it is the ability to explain financial products — and now an assistant that pays — repeatedly, publicly, and in the cultural language of the target user. <sup>[15]</sup>

> **Distribution + trust + local fit**
>
> Confío does not plan to win by permanently outbidding competitors on cashback. It aims to convert a trusted audience into people who let the assistant pay for them once, and then again. The agreed success measure for the assistant is the share of people who let it pay once and let it pay again within 30 days.

### 10.3 Country-by-country rollout

Confío does not expose every feature in every country. Fiat methods, identity requirements, USDY eligibility, sanctions controls, withdrawal options, shopping-agent rails, and support procedures vary by market, and corridors are paused when a provider or fraud signal requires it. Rollout follows verified provider capabilities and legal/operational readiness rather than a country flag in a marketing page.

## 11. Business model

Confío aligns revenue with useful financial activity rather than speculative trading. The assistant that acts for a person is paid for by Cuenta inteligente; moving money in and out of the dollar system is paid for by the 0.9% perimeter fee.

| Revenue line | Current policy |
| --- | --- |
| Cuenta inteligente | US$149.99 per year (default) or US$14.99 per month, taken from inside the account; no refunds. Includes automation, the beneficiary, and Confío IA+ (the assistant executing on the account, hands-off trades within the weekly cap, and store purchases within the purchase cap). |
| Enter the Confío dollar system | 0.9% when USDT becomes cUSD or cUSD+, from a fiat ramp or an on-chain transfer. |
| Leave the Confío dollar system | 0.9% when cUSD or cUSD+ becomes external USDT, including local-rail payments and assistant purchases paid from a Cuenta inteligente. |
| Transfers and internal savings conversion | 0% Confío fee; network fees are sponsored. |
| Merchant payments and payroll | 0.9% flat Confío platform fee, enforced on-chain. |
| Comprar | 8% marketplace fee paid by the seller. |
| cUSD+ yield share | 15% of positive USDY reference-price appreciation to Confío, 85% to holders. Variable and not guaranteed. |
| Ondo Stocks, Oro y Bitcoin, Futuros | The uniform 0.9% perimeter fee when value leaves or re-enters the dollar; no separate trading or builder fee. Third-party spreads, bridge, venue, and network costs may apply separately. |
| Fiat-rail economics | Provider pricing and any local-account fees are shown in the live quote. |

The pricing rule is the same one shown on the public website: **0.9% to enter, 0% to move inside, and 0.9% to leave**. Confío Pay is a separate 0.9% service fee. Cuenta inteligente does not waive or discount the 0.9% fee. Search, carts, and priced reviews by the shopping agent, and Confío IA’s answers, are free. Network sponsorship and model usage are product costs, not proof that every action is economically free.

## 12. Compliance and operating model

Confío’s architecture separates wallet-key custody from product and provider obligations. A non-custodial wallet can still integrate permissioned assets, identity verification, sanctions screening, fiat providers, and contract controls.

**Know Your Customer (KYC)** means the checks used to establish who a user is and, where required, where the user resides. **Anti-Money Laundering (AML)** means provider and transaction controls intended to detect or prevent sanctions violations, fraud, money laundering, terrorist financing, and other prohibited activity.

> **Provider-integrated architecture**
>
> Fiat custody, currency conversion, identity verification, and permissioned-asset access are performed by the relevant providers rather than by Confío’s wallet software. This describes the operating design; it is not a claim that Confío has no legal or compliance obligations.

- Didit supports the identity-verification flow: a government-issued document and a live selfie, with document, liveness, and face-matching checks. Users under 18 are declined.
- Fiat providers apply their own identity, address, eligibility, sanctions, and transaction controls; completing Didit verification alone does not guarantee approval by a provider.
- USDY minting and Ondo Stocks access are limited by Ondo eligibility, geographic, and compliance requirements. <sup>[7, 10, 18]</sup>
- A Cuenta inteligente beneficiary must be a Didit-verified Confío user, designated only through Confío’s sponsor gate, and must accept; U.S.-resident beneficiaries are blocked.
- Comprar requires Didit verification for both buyers and sellers.
- The shopping agent never works around a site’s block and refuses countries without a rail that pays the exact order amount.
- Additional countries and rails launch only after the corresponding legal, operational, and provider checks.

## 13. Risks and mitigations

No blockchain financial product, and no AI agent, is risk-free. This table is not exhaustive.

| Risk | Current mitigation | Residual exposure |
| --- | --- | --- |
| **AI misunderstanding or model error** | Models propose; code asks for amounts, validates payees, prices, and draws the confirmation; tool and page text are data, not instructions; behavior is tested against recorded conversations. | A model can still misread a request, pick the wrong product, or give a wrong answer; a person can confirm a card without reading it. |
| **Wrong or failed store purchase** | Choice approves a top total; a higher real total brings back the order card; two models must read the same total, which must appear on the page; one approval places one order; server caps on steps, time, and cost; purchases paid from a capped account rule. | Stores change pages, cancel orders, mis-ship, or delay refunds; a store-side failure may require the person to deal with the store. The agent is early and not yet proven across many stores. |
| **Local-rail payment errors** | Checksum-validated identifiers, exact-amount quotes, provider status tracking, no “paid” before the rail confirms. | Providers can fail, delay, reverse, or pause; an unverified store payee read from a checkout can still be wrong. |
| **Hands-off and smart-account trust** | Immutable accounts; owner-signed caps enforced on-chain; buys and sells counted; price-feed bands; fee bound; notifications and alerts; Safe kill switches; separate key for the escrow order signer; internal independent review with regression tests. | Hands-off actions trust Safe-upgradeable routers and escrow; relayer compromise plus a malicious Safe upgrade could sell stock at a forged price; a purchase-operator compromise is bounded by each owner’s cap. Rules execute as signed, even if the owner later regrets them. |
| **Underlying assets and issuers** | cUSD is backed by USDT; cUSD+ holds USDY; disclosures of structure, accounting, and eligibility. | Depeg, issuer, custody, legal, reserve, and redemption risks remain for USDY and USDT. |
| **Smart contracts** | Open source, verified deployments, layered tests, bounded controls, and public state. | Bugs, integration failures, and upgrade errors remain possible. |
| **Oracle** | Threshold guard halts value paths pending an evidence-linked governance response. | Incorrect or unavailable data can delay deposits and redemptions. |
| **Liquidity and redemption** | Permissionless fee-bearing USDT redemption; Emergency Exit can broadcast directly through public BSC nodes. | InstantManager liquidity, provider availability, network conditions, or compliance actions may delay exits. |
| **Investing and leverage** | Source-verified routers, direct delivery to the user, fee bounds, slippage limits, eligibility and country gates; Futuros not offered on iOS and blocked in several countries. | Market, slippage, issuer, venue, bridge, liquidation, and total-loss risks remain, especially for leveraged Futuros. |
| **Key recovery** | Device-generated keys and personal-cloud recovery avoid a central key vault. | Loss of device/cloud access, platform changes, or recovery defects can affect access. |
| **Upgrade governance** | Multi-party Safe control, public upgrade records, source verification, storage-layout checks. | Authorized signers could make a harmful change or fail to respond during an incident. |
| **BNB Smart Chain dependency** | Single-network architecture removes bridge risk inside the core product; multiple RPC and emergency-exit paths. | Network interruption, congestion, RPC failure, gas changes, or ecosystem policy changes can affect the whole product. |
| **Fiat rails and paused corridors** | Live switches per country and provider; corridors paused on provider incidents or fraud signals (Colombia top-up and Bre-B are paused as of this version). | Coverage, payment methods, banking dependencies, pricing, and provider availability can change without notice. |
| **Regulatory and financial crime** | Government-document/live-selfie checks, provider screening, product geofencing, legal review, and bans of abusive accounts. | Providers or authorities may reject, delay, report, or restrict activity; rules for AI agents acting on payments are still developing. |
| **Token concentration and rewards** | Fixed supply, public contracts, immutable presale curve, separate tokenomics; cumulative EIP-712 reward claims with a DEX lock. | Founder concentration, vesting, liquidity, and token-price volatility; rewards depend on treasury funding. |
| **Metrics and concentration** | Definitions, snapshot dates, and unaudited status are disclosed. | Early usage and revenue may be concentrated and may not predict broad adoption. |

## 14. Roadmap and current status

| Workstream | Completed / current | Next verifiable gate |
| --- | --- | --- |
| Confío IA | Chat-first home and onboarding; payment, trade, and top-up cards in the chat with code-asked amounts; doors to every app job; memory and conversation compaction. | Measure repeat assistant payers; complete the pending independent review of chat payments. |
| Shopping agent | Cloud-browser purchases with model judges and code-checked facts; multi-store search; SPEI, Pix, and Pago Móvil payment; Bolivia with the person paying the store’s QR. | Reliable completed purchases across more stores; exact-amount payouts for Argentina’s fixed QR. |
| Cuenta inteligente | Factory, v1 and v2 accounts, fee collector, purchase spender deployed and verified; inheritance enabled; hands-off trades, Comprar, and store purchases live since 25 November 2026. | Carry send, payout, and card rules through migration; grow paying subscribers. |
| cUSD/cUSD+ fee system | 90-bps external perimeter and fee-free internal boundary live. | Monitor fee reconciliation, backing, eligibility routing, and permissionless exits. |
| Sponsored transactions | Ownerless EIP-7702 batch delegate, server policy, and ledgers live. | Monitor reliability, sponsor cost, and emergency fallbacks. |
| Payments and payroll | Transfers, merchant payments, invitation escrow, and payroll vault live. | Measure merchant and payroll repeat usage. |
| Investing | Ondo Stocks router v3, swap router for gold and bitcoin, Futuros on Android. | Legal review needed to offer Oro y Bitcoin and Futuros in an iOS build. |
| Comprar | Escrow upgraded for account purchases; pilot open. | Sellers and repeat buyers in the pilot cities. |
| Fiat access | Local rails live in Mexico, Brazil, Venezuela, Bolivia, Argentina, Chile, and Peru as described in section 3.6; Colombia paused. | Re-open Colombia when providers allow; QR Bolivia payments; additional verified providers. |
| $CONFIO | Fixed-supply token, replacement presale, reward and vesting vaults live. | Keep tokenomics synchronized with on-chain state; open claims only under the disclosed controls. |
| Distribution | 10,233 phone-complete users; approximately 480,000 founder audience; effectively zero paid-media spend to date. | Convert distribution into funded users, repeat assistant payments, and country-level cohorts. |

### 14.1 Measurement principles

Confío distinguishes signups, onboarded users, verified users, funded users, reachable devices, active users, and retained balances. Core operating measures include funded users, repeat assistant payers, completed and failed agent purchases, Cuenta inteligente subscribers, cUSD and cUSD+ obligations, backing, conversion fees, net inflow, balance retention, merchant and payroll volume, and country cohorts. Organic acquisition is separated from paid campaigns, and revenue is reported excluding banned and founder accounts.

### 14.2 The next proof point

> **From an assistant that can pay to one people trust to pay again**
>
> The next proof point is repeat use: people who let Confío IA pay a person, a QR, or a store once and do it again within 30 days, with funded balances and paying Cuenta inteligente subscribers across several Latin American markets.

## 15. Legal disclaimer

This document is provided for informational and technical-reference purposes only. It is not investment, legal, tax, accounting, or financial advice; it is not a prospectus, offer, solicitation, recommendation, or promise of returns. Product descriptions reflect the current design and status as of 25 November 2026 and may change.

Confío IA is an automated assistant. Its answers may be incomplete or wrong and are not personalized financial advice. Purchases made by the shopping agent are contracts between the person and the store; Confío does not guarantee a store’s products, delivery, returns, or refunds. Actions executed by a Cuenta inteligente follow the rules and caps its owner signed.

USDT, cUSD, and cUSD+ are not bank deposits and are not insured by a deposit-insurance scheme. Stablecoins, tokenized notes, smart contracts, blockchains, oracles, fiat providers, market makers, custodians, and other infrastructure can fail, be suspended, lose value, or become subject to new rules.

Any cUSD+ yield is variable, depends on USDY and the vault, and is not guaranteed. USDY access and cUSD+ minting are subject to Ondo eligibility, compliance conditions, provider availability, and applicable law.

Ondo Stocks are tokenized financial instruments and are not bank deposits or insured savings products. Gold and bitcoin tokens and leveraged perpetual futures can lose value rapidly, and Futuros can lose the entire margin. Access and trading depend on eligibility, jurisdiction, market availability, third-party venues, and applicable terms and law.

$CONFIO is separate from USDT, cUSD, cUSD+, and USDY. It does not provide a claim on the backing, revenue, equity, assets, or profits of Confío unless definitive terms expressly state otherwise.

Readers should review definitive product terms, risk disclosures, smart contracts, provider terms, and local law before using any service.

## Endnotes

1. Inter-American Development Bank, “Remittances to Latin America and the Caribbean Ease After 2025 Surge,” 16 June 2026: estimated regional remittances of US$173.7 billion in 2025, up 7.3% from 2024. https://www.iadb.org/en/blog/migration/remittances-latin-america-and-caribbean-ease-after-2025-surge

2. Chainalysis, “Latin America Emerges as Crypto Powerhouse Amid Volatile Growth,” 2 October 2025. https://www.chainalysis.com/blog/latin-america-crypto-adoption-2025/

3. Confío public GitHub repository: mobile application, backend, assistant (`assistant/`), shopping agent (`agent_tasks/`), marketplace, BSC contracts, wallet model, payments, payroll, token, and presale. https://github.com/caesar4321/Confio

4. Confío, “Por qué Confío no guarda tu dinero - y por qué eso importa,” project source, accessed July 2026.

5. BNB Chain developer documentation, BNB Smart Chain introduction and finality. https://docs.bnbchain.org/bnb-smart-chain/introduction/

6. BNB Chain developer documentation, transaction fees and network concepts. https://docs.bnbchain.org/bnb-smart-chain/

7. Ondo Finance documentation, “USDY Basics,” accessed July 2026. https://docs.ondo.finance/general-access-products/usdy/basics

8. Confío, “cUSD+ deployment record - BSC mainnet,” updated November 2026: cUSD, cUSD+, stock router, Cuenta inteligente, heartbeat, and Comprar escrow deployments. https://github.com/caesar4321/Confio/blob/main/contracts/cusd_plus/DEPLOYMENT.md

9. BscScan, Confío Dollar+ ERC1967 proxy, address `0x3C29417eb4314155e63d4C7D4507852b87763Ed1`. https://bscscan.com/address/0x3C29417eb4314155e63d4C7D4507852b87763Ed1#code

10. Ondo Finance developer documentation, “Integrating with the USDY InstantManager contract.” https://docs.ondo.finance/developer-guides/usdy-instant-manager-integration

11. Confío, `CusdPlusVault.sol`: deployed accounting, redemption, oracle guard, and 15% Confío yield-share logic. https://github.com/caesar4321/Confio/blob/main/contracts/cusd_plus/CusdPlusVault.sol

12. BNB Chain ecosystem and developer documentation, accessed July 2026. https://www.bnbchain.org/en/developers

13. Confío partner records and production configuration, 25 November 2026: local top-up, withdrawal, and payout rails through Koywe, Infinia, Pago ASAP, and VEXPay, with per-country switches and pauses. Commercial terms remain governed by the respective agreements.

14. Confío internal product analytics snapshots: 25 November 2026 for phone-complete users and FCM push-reachable devices (active device tokens; used within 30 days by last recorded use); 23 July 2026 for Didit government-document and live-selfie identity verification and its completion rate. Unaudited.

15. Confío internal founder-channel analytics snapshot, 23 July 2026. Audience figure is approximate and changes over time.

16. Benedetto Biondi, “The New Face Of Global Payments: Onchain Consumer Finance Apps,” *Forbes Technology Council*, 6 July 2026. https://www.forbes.com/councils/forbestechcouncil/2026/07/06/the-new-face-of-global-payments-onchain-consumer-finance-apps/

17. Confío BSC contracts and deployment records: `ConfioToken.sol`, `ConfioPresaleVault.sol`, `ConfioRewardVault.sol`, `ConfioVestingVault.sol`, `ConfioInviteEscrow.sol`, `ConfioBatchDelegate.sol`, `ConfioStockRouter.sol`, and verified deployment addresses. https://github.com/caesar4321/Confio/tree/main/contracts/cusd_plus and https://github.com/caesar4321/Confio/tree/main/contracts/ondo_stocks

18. Ondo Finance, “Ondo Stocks” and Global Markets API documentation, accessed July 2026. https://ondo.finance/ondo-stocks and https://docs.ondo.finance/api-reference/quickstart

19. International Monetary Fund Independent Evaluation Office, historical documentation of Argentina’s 2001 partial deposit freeze, capital controls, and forced conversion; and IMF review of the relaxation of most exchange restrictions under the 2025 stabilization program. https://www.imf.org/External/NP/ieo/2003/arg/ and https://www.imf.org/es/news/articles/2025/07/31/pr25272-argentina-imf-completes-first-review-of-the-extended-arrangement-under-the-eff

20. International Monetary Fund, “Digital Money and Central Banks Balance Sheet,” Working Paper No. 2022/206: Venezuela as a case of real dollarization. https://www.elibrary.imf.org/view/journals/001/2022/206/article-A001-en.xml

21. International Monetary Fund, “Bolivia: 2025 Article IV Consultation,” Country Report No. 2025/116. https://www.imf.org/en/publications/cr/issues/2025/06/02/bolivia-2025-article-iv-consultation-press-release-staff-report-and-statement-by-the-567384

22. Superintendencia de Banca, Seguros y AFP del Perú, *Carpeta de Información del Sistema Financiero*, February 2026, deposits by currency. https://intranet2.sbs.gob.pe/estadistica/financiera/2026/Febrero/SF-2102-fe2026.PDF

23. Banco de México, 2024 monetary aggregates; and Inter-American Development Bank, 2025 remittance estimate for Mexico. https://www.banxico.org.mx/TablasWeb/informe-anual/compilacion-2024/7EF1402E-1443-4070-9C0A-6B352272C3B9.html and https://publications.iadb.org/publications/english/document/Remittances-to-Latin-America-and-the-Caribbean-in-2025-Adaptations-in-a-Context-of-Uncertainty.pdf

24. Inter-American Development Bank, *Remittances to Latin America and the Caribbean in 2025: Adaptations in a Context of Uncertainty*. https://publications.iadb.org/publications/english/document/Remittances-to-Latin-America-and-the-Caribbean-in-2025-Adaptations-in-a-Context-of-Uncertainty.pdf

25. UNHCR, *Global Report 2025 — Situation Overview: Colombia*: Colombia hosted approximately 2.8 million Venezuelans in 2025. https://www.unhcr.org/sites/default/files/2026-06/global-report-2025-situation-overview-colombia.pdf

26. Confío, assistant design records: `docs/designs/ai-assistant-first-redesign.md`, `docs/designs/confio-assistant.md`, and `docs/designs/confio-assistant-three-jobs.md`. https://github.com/caesar4321/Confio/tree/main/docs/designs

27. Confío, Cuenta inteligente specification, hands-off account design, and hands-off v2 deployment record (contract addresses, Safe batches, transaction hashes, and the v2 review’s regression tests): `docs/designs/cuenta-inteligente-spec.md`, `docs/designs/hands-off-account.md`, `docs/deploy/hands-off-v2-deploy.md`, and `contracts/smart_account/`. https://github.com/caesar4321/Confio/tree/main/contracts/smart_account

28. Banco Central do Brasil, “Pix.” https://www.bcb.gov.br/en/financialstability/pix_en

29. Banco de la República (Colombia), “Bre-B.” https://www.banrep.gov.co/es/bre-b

30. Confío, `ConfioSwapRouter` source and notes. https://github.com/caesar4321/Confio/tree/main/contracts/crypto_swap

### Document provenance

Version 4.5 (25 November 2026) restructures the paper around Confío IA as an AI-first assistant that pays, adds Cuenta inteligente, the shopping agent, Oro y Bitcoin, Futuros, and Comprar, refreshes the contract table against BscScan source verification and on-chain state, and refreshes operating metrics from read-only production queries using the definitions of version 4.4. It was prepared from the prior English whitepaper, Confío’s design and deployment records in the public repository, production configuration, partner records, official BNB Chain, Ondo, and central-bank documentation, and cited market literature.
