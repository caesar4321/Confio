# Confío: The Personal Assistant That Pays in Latin America

**Ask Confío to get it done. It runs the errand and finishes the job by paying, on your country’s own rails, with dollars only you control.**

Confío is a consumer personal assistant for Latin America. Like the personal AI agents now arriving around the world, Confío IA takes everyday errands off a person’s hands: finding and buying things, ordering, keeping track of what is due. Unlike them, it finishes the job by paying. It pays on each country’s local rail (Pix, SPEI, Pago Móvil, bank QR), from the person’s own self-custody dollars, after an exact confirmation or within limits the person signed on-chain. Confío is fully open source and non-custodial.

**Global reference · Version 4.5 · November 2026**<br>
Julian Moon · Founder & CEO<br>
[confio.lat](https://confio.lat) · [GitHub](https://github.com/caesar4321/Confio)

*La confianza ya existe. Falta un sistema que la merezca.* — Trust already exists. What’s missing is a system that deserves it. · *Confío en vos.*

**Authoritative original:** This English document is the sole authoritative version of the Confío whitepaper. [Spanish](README.es.md) and [Korean](README.ko.md) translations are provided for convenience and may lag behind this original. If a translation differs from the English text, the English text controls.

This paper is the current global reference for Confío’s product, strategy, operating model, and material risks. Detailed $CONFIO allocation and vesting terms remain in the separate tokenomics document.

<details>
<summary><strong>Contents</strong></summary>

1. [Executive summary](#1-executive-summary)
2. [The thesis: assistants that cannot pay](#2-the-thesis-assistants-that-cannot-pay)
3. [Competitive landscape](#3-competitive-landscape)
4. [Confío IA: the assistant that runs errands and pays](#4-confío-ia-the-assistant-that-runs-errands-and-pays)
5. [Cuenta inteligente: paid execution within signed limits](#5-cuenta-inteligente-paid-execution-within-signed-limits)
6. [Why an AI can be trusted to pay: the foundation](#6-why-an-ai-can-be-trusted-to-pay-the-foundation)
7. [Wallet, security, and governance](#7-wallet-security-and-governance)
8. [Users and distribution](#8-users-and-distribution)
9. [Business model](#9-business-model)
10. [Compliance and operating model](#10-compliance-and-operating-model)
11. [Risks and mitigations](#11-risks-and-mitigations)
12. [Roadmap and current status](#12-roadmap-and-current-status)
13. [Legal disclaimer](#13-legal-disclaimer)
14. [Endnotes](#endnotes)

</details>

---

## 1. Executive summary

Personal AI assistants that act on a person’s behalf are arriving: Meta’s Muse and OpenAI’s dots in the United States, Pickle in Korea, and, built for Latin America, Zapia. <sup>[1–5]</sup> They converse, search, remind, contact businesses, and build carts. Where they pay at all, they pay with a card. In Latin America that is where the errand stops, because everyday money moves on national rails — Pix in Brazil, SPEI in Mexico, Pago Móvil in Venezuela, bank QR codes in Bolivia, Bre-B in Colombia — that card-based agent payments do not reach. <sup>[7, 8]</sup>

> **Thesis**
>
> Confío is the personal assistant for Latin America that finishes the job by paying. It runs the errand like other assistants, and then it pays the store, the merchant, or the person on that country’s own rail, from a dollar balance the person controls, with an exact confirmation or within an on-chain limit the person signed. The errand is the hook; the rails, the self-custody balance, and the enforced limits are the moat. Confío knows of no other consumer app in the region that offers that combination as one product. In Brazil, people can already ask their own bank’s assistant to send a Pix; Confío’s gap is widest in Spanish-speaking Latin America and across borders.

What Confío IA does today, each payment confirmed by the person or bounded by limits they signed:

| Job | How it works |
| --- | --- |
| Buy at online stores | A shopping agent searches one or several stores in a cloud browser, builds the cart, shows the real total with shipping, and pays the store on its country’s rail: SPEI in Mexico, Pix in Brazil, Pago Móvil in Venezuela (stores that ask only for the payment reference). In Bolivia it places the order and the person pays the store’s QR. |
| Pay people, QR codes, and merchants | The assistant prepares a send or a local-rail payment as a card in the chat; code, not the model, asks the amount and validates the payee; the person confirms and signs on their own phone. |
| Shop locally | Comprar, an in-app marketplace with escrow-held payments and buyer protection, piloting in Bolivia. |
| Keep track of messages and what is due | Linking the person’s own WhatsApp, Gmail, and calendar so the assistant can tell them what needs attention and draft replies is being rolled out with new app builds (section 4.1). |
| Top up and withdraw | The chat opens the top-up or withdrawal form, with the country’s live provider limits. |
| Invest and automate | Stocks, gold, and bitcoin as priced cards; with Cuenta inteligente, scheduled payments and payouts, automatic investing, and hands-off trades within a weekly cap. |

As of 25 November 2026, Confío records 10,886 users who completed sign-up (14,440 registered accounts) and 3,407 push-reachable devices, 3,402 of them used within the last 30 days. As of 23 July 2026 (the latest snapshot available under the same definition), 177 users had completed Didit identity verification with a government-issued document and a live selfie, a 61.5% completion rate among users who began it. These are unaudited internal metrics, not funded-user or monthly-active-user counts. <sup>[31]</sup>

## 2. The thesis: assistants that cannot pay

### 2.1 Personal assistants are arriving

In 2026 the large AI companies moved from chatbots to agents that do errands. Meta launched Muse in the United States in September 2026 as an agent that sends email, books travel, fills out forms, and keeps working after the app is closed; its checkout runs through Stripe’s Link, which issues a one-time card. <sup>[1]</sup> OpenAI launched dots, an always-on assistant that connects to thousands of apps, <sup>[3]</sup> and in November 2026 added ChatGPT Wallet so dots can buy for the user with a tokenized card, built with American Express, Chase, Mastercard, and Visa and initially limited to eligible U.S.-issued cards. <sup>[2]</sup> In Korea, Pickle handles everyday tasks end to end across services such as KakaoTalk and Coupang and has been reported placing phone calls for its users. <sup>[4]</sup>

Latin America has its own. Zapia describes itself as a personal AI agent built for Latin Americans, available on WhatsApp, as an app, and on the web; it searches the web, contacts businesses over WhatsApp, schedules meetings, replies on the user’s behalf, and tracks prices. <sup>[5]</sup> Luzia began as a free assistant inside WhatsApp that answers questions and transcribes voice notes. <sup>[6]</sup> Their public descriptions do not include paying a merchant from a balance on a local rail.

### 2.2 Money in Latin America moves on national rails

Each country runs its own payment system, and the systems do not interoperate:

| Country | How everyday money moves | What an assistant must handle |
| --- | --- | --- |
| Brazil | Pix, the central bank’s instant payment system: keys, QR codes, and copy-paste codes. <sup>[7]</sup> | Parse and validate the Pix code, pay its exact amount. |
| Mexico | SPEI transfers to an 18-digit CLABE; many online stores show bank details and a reference at checkout instead of a card form. | Read the CLABE, amount, and reference from the checkout and pay exactly that. |
| Colombia | Bre-B keys and QR codes, the new interoperable instant system. <sup>[8]</sup> | Resolve the key and pay in pesos. |
| Venezuela | Pago Móvil: phone number, bank, and national ID; the payer then reports the reference to the seller. | Pay first, then hand the reference back to the store. |
| Bolivia | Bank QR codes. | Pay the QR’s amount in bolivianos. |
| Peru | Yape, PLIN, and interoperable QR. <sup>[9]</sup> | — (not yet supported by Confío). |
| Argentina | Alias/CVU transfers and interoperable QR. | — (Confío payouts pending provider readiness). |

A card-based agent cannot complete a checkout that asks for a SPEI transfer, a Pix code, or a Pago Móvil reference, and many everyday payments — a seller on WhatsApp, a worker paid by QR — happen entirely outside card networks. For a person, each rail means another app, form, and identifier. For an assistant, it is an opportunity: code can pick the rail from the payee’s country while the person only says what they want. Because the rail follows the payee rather than the payer’s bank, the same design can, where providers allow it, let a person in one country pay a store or family in another.

### 2.3 Why the balance is in dollars

People across the region hold and receive dollars — through remittances, estimated at US$173.7 billion into Latin America and the Caribbean in 2025, and through stablecoins already in wide use. <sup>[10, 11]</sup> A balance in dollars that can be paid out in pesos, reais, or bolívares lets one assistant pay in any supported country without the person converting first.

### 2.4 Trust decides who people let pay

Giving money to an AI raises the question every Latin American user already asks of a financial app: what stops it from doing the wrong thing? Confío’s answer has three layers: **verifiable control** (the wallet key is generated on the person’s device and is not held by Confío), **bounded agency** (the assistant cannot invent amounts or payees; every payment is an exact confirmation or falls inside a limit signed on-chain), and **human trust** (Spanish-first explanations, clear prices, visible leadership, and an assistant that says plainly what it cannot do). *La confianza ya existe; falta un sistema que la merezca*: people already trust one another with money, and these limits are how Confío earns that trust. The promise is also an architectural constraint.

## 3. Competitive landscape

| Category | Examples (public sources) | What they do | What they lack for this job |
| --- | --- | --- | --- |
| Personal AI assistants | Muse, dots, Pickle, Zapia, Luzia <sup>[1–6]</sup> | Errands, messages, search, scheduling; Muse and dots buy with tokenized cards in the United States. | No payment of merchants from the person’s balance on Pix, SPEI, Pago Móvil, or bank QR. |
| AI inside bank and wallet apps | Nubank’s Pix by voice, text, or image in its app and on WhatsApp (Brazil, since December 2024); Mercado Pago’s Mago, which prepares transfers from a conversation for the person to confirm (Argentina). <sup>[12, 13]</sup> | Execute payments on their own country’s rail for their own customers. | Finance-only and single-country; not personal assistants for errands outside the app. |
| Payment infrastructure for agents | Iniciador’s agentic-payments toolkit lets banks’ and fintechs’ agents propose Pix payments that the user approves with biometrics through Open Finance (Brazil, May 2026). <sup>[14]</sup> | Components for regulated institutions. | Not a consumer product; possible suppliers rather than competitors. |

Confío’s position is the intersection: a consumer assistant for errands, payout and collection access to several countries’ rails, and a self-custody dollar balance with on-chain limits. This is a narrow claim, not “first to combine AI and payments”. In Brazil, a person can already ask their bank’s assistant to send a Pix. The gap is clearest in Spanish-speaking Latin America, where comparable payment-initiation infrastructure for agents is not available to Confío, and for cross-border payments, where no national bank assistant reaches.

## 4. Confío IA: the assistant that runs errands and pays

### 4.1 The chat is the product

On current builds, Inicio is the conversation with Confío IA. A new user meets their assistant and is asked, in words, what they want Confío for; the answer shapes the next steps. Every job the menu offers — top-up, withdrawal, Cobrar, invitations, history, investments, Comprar, Cuenta inteligente, business and payroll tools — has a door from the chat. The assistant reads the person’s own movements and monthly summary, accepts photos and voice notes, and searches the web for general questions. <sup>[15, 16]</sup>

Connections that widen the errands are being rolled out: linking the person’s own WhatsApp as a device so the assistant can tell them what needs attention and help reply; Gmail, open to a limited number of people while Google’s verification is pending; and the phone’s calendar. They are deployed on the server and reach people as new app builds are released. Confío IA explains instruments and risks but does not tell a person to buy, sell, or hold a named ticker, and does not predict prices.

### 4.2 How a request becomes a payment

| Step | Who does it | What is checked |
| --- | --- | --- |
| 1. Understand | The model reads the request, typed or said in a voice note, and decides which job it is. | Tool output and third-party text are data, never instructions; after a web search the turn loses its money tools. A voice note can name what to buy, sell, or pay; it never sets an amount or confirms. |
| 2. Ask the amount | Code, not the model, writes the question (“¿Cuántos dólares? Escribe solo el número”). | No amount is ever read out of a sentence; the number typed alone as the next message is the amount and the yes, and only a typed answer counts. A “no” withdraws pending cards. |
| 3. Resolve the payee | Code parses and validates the destination: Pix keys and codes with their checksum, CLABE check digits, Pago Móvil data, Confío contacts. | The card shows only what code resolved; an unverified name is never marked as verified. |
| 4. Quote | Code prices it: local amount, dollar total, exchange rate, Confío fee, expiry. | A charge with a fixed local amount is paid exactly. |
| 5. Confirm | The person reviews the card and signs on their own device, or, for a subscriber’s hands-off action, the account checks its signed cap on-chain. | The model cannot draw the confirmation sheet and cannot sign. |
| 6. Settle | The payout runs on the local rail; the card follows the provider’s status. | A card never says “paid” before the rail reports completion. |

Which rails are offered is decided by live switches per country and provider, not by the model. When a corridor is paused, the assistant says so rather than improvising a route.

### 4.3 The shopping agent

The person names a product, and optionally a store; when no store is named, one search across several stores returns a short list of offers. The agent then works in a cloud browser the person can watch live: it opens the store, adds the items, reaches the checkout, and reads the real total with shipping. <sup>[15]</sup>

- **Choice is consent.** Each offer shows a top total (“hasta $X con envío”); choosing it approves that item, quantity, and total. A higher real total, an unreadable price, or a different payer brings back an order card with the real breakdown.
- **Models decide, code checks facts.** One model drives; a judge from a different model family reviews each press; a final review reads the last page before ordering. Code checks only facts: one approval places one order; both models must read the same total, which must appear on the page; a payment identifier must be valid, shown beside the approved amount, on a page that appeared after the order.
- **Ceilings in code.** Steps, time, and model cost per task are capped by the server.
- **Rail by store country.** SPEI bank details read from the store’s own checkout in Mexico (paid for the exact peso amount; any conversion surplus stays in the person’s local account), Pix QR in Brazil, and Pago Móvil in Venezuela, paid before the order with the reference entered into the store’s form. In Bolivia, while Confío’s QR payments are off, the agent places the order and the person pays the store’s QR. Other countries are refused rather than paid by an approximate transfer.
- **Who pays.** Search, cart, and the priced review are free. Buying and paying is a Cuenta inteligente benefit: the account pays through a “Compras con Confío IA” rule signed once with Confío Face (default US$200 per 28 days, editable), never directly from the personal wallet.

The shopping agent is early. Store pages change, some checkouts offer no payable local rail to ordinary accounts, and Confío has not yet shown reliable completion across many stores.

### 4.4 What Confío IA will not do

- Read an amount out of a sentence, or pay on a “yes” without code-checked terms.
- Pay a payee whose details code could not validate, or present an unverified name as verified.
- Pay above a total the person approved or a cap the person signed.
- Pay a store in a country without a rail that pays the exact local amount.
- Recommend a named ticker or predict prices.
- Offer Oro y Bitcoin or Futuros to iOS users, or any product the person’s country or eligibility excludes.
- Go silent: when it cannot do something, it says so and, where possible, opens the screen where the person can.

### 4.5 Rails by country

Capabilities follow live provider switches and change; this is the state as of 25 November 2026. <sup>[17]</sup>

| Country | Live today | Not available or paused |
| --- | --- | --- |
| Mexico | Top-up and withdrawal; own CLABE to receive pesos; SPEI payouts to any CLABE; scheduled CLABE payouts; shopping-agent SPEI payments. | — |
| Brazil | Pix payments by key, QR, or code; receiving by Pix QR; scheduled Pix payouts; shopping-agent Pix payments. | — |
| Venezuela | Pago Móvil top-up and sends; scheduled Pago Móvil payouts; shopping agent for stores that ask only the reference. | Stores that require other payment data. |
| Bolivia | Top-up and bank withdrawal; Comprar; shopping agent with the person paying the store’s QR. | Paying and receiving bank QR through Confío (switched off). |
| Argentina, Chile, Peru | Local top-up rails; withdrawals where the provider offers them. | Argentine CVU and QR payouts (pending provider readiness). |
| Colombia | Withdrawals through the existing ramp. | Top-up and Bre-B conversion and payouts (paused). |

## 5. Cuenta inteligente: paid execution within signed limits

### 5.1 What it is

Cuenta inteligente is how the assistant’s paid execution works. It is a separate smart contract, one per user, owned by the user’s personal wallet. The user moves money into it; inside it, the assistant can act under rules and caps the owner signed, and the account can pass to one named beneficiary. The personal wallet is not affected. <sup>[18]</sup>

| Included | What the user gets |
| --- | --- |
| Confío IA+ | The assistant executes on the account: store purchases within the purchase cap, hands-off trades within the weekly cap, rule changes the owner asks for, a target investment split kept with new buys, alerts, and a monthly review. |
| Automatic payments | Daily, weekly, biweekly, or monthly sends to Confío users and payouts to a saved CLABE, Pix, or Pago Móvil destination. |
| Automatic investing | Periodic buys of stocks, bitcoin, and gold. |
| Beneficiary (*Herencia Digital*) | One Didit-verified beneficiary can take ownership after a challenge window (default 180 days, 90 to 1,825) during which any owner-signed action cancels the claim. |

**Price:** US$149.99 per year (preselected) or US$14.99 per month, one tier, no refunds, taken from inside the account (dollars first, then, after notices, a forced sale of one period’s fee). The 0.9% conversion fee is not waived. <sup>[18]</sup>

### 5.2 Hands-off execution (live since 25 November 2026)

Chat trades in stocks, gold, and bitcoin, Comprar purchases, and store purchases can execute from the account without a signature per action:

- **Caps signed once with Face.** A weekly trade cap (for example US$250, 1,000, or 2,500) where buys and sells both count, as a leaky bucket: at most one cap at any instant and one per week on average (just under two within any single week). Store purchases have their own cap.
- **Funds stay in the account.** Swaps must stay within 1.5% of a Chainlink price feed, the stock fee is bounded at 90 basis points, and sells must return their value to the account within that band.
- **Alerts and kill switch.** Every hands-off trade notifies the owner; one without a chat proposal behind it raises a security alert. The Safe can stop every hands-off path at once (`tradePaused`).
- **Results in the chat.** The result (what was bought or sold, and for how much) is posted in the conversation in the person’s language and shown on the trade’s card. The trade counts in the person’s portfolio together with the personal wallet’s holdings, and can be shared to Comunidad like any signed trade, with its result against the account’s own cost.

### 5.3 Contract design and trust assumption

- **Immutable accounts.** Each account is an EIP-1167 clone with no upgrade function, no `DELEGATECALL`, and no `SELFDESTRUCT`. Its limits are constants; values read from the factory are clamped; `withdraw`, `withdrawAll`, `cancelClaim`, and the claim functions work even if every factory call fails.
- **Factory per generation.** The UUPS factory, owned by the 3-of-5 Safe, creates one current account per owner. Since 25 November 2026 it records one implementation per generation: v1 accounts keep their bytecode, new accounts use `ConfioSmartAccountV2` (Trade and Purchase rules, relayer-only `relayTrade` and `relayPurchase`, per-rule buckets, price bands), and moving to v2 is an opt-in, owner-signed `migrate()`.
- **Purchases.** `ConfioPurchaseSpender` pulls exactly the approved USDT through the normal 0.9% exit and, in the same transaction, forwards all of it to that payment’s bridge deposit; nothing stays in it. Comprar purchases go into the escrow through `depositFrom`, which records the owner as buyer and refunds to the paying account.

Hands-off actions trust `ConfioStockRouter`, `ConfioSwapRouter`, and `ConfioMarketEscrow`, which the Safe can upgrade. A compromised relayer key alone cannot move value out of an account. A relayer compromise together with a malicious Safe upgrade of the stock router could still sell stock at a forged price, because the account cannot verify Ondo’s quote signature itself. A compromised purchase-operator key is bounded by each owner’s purchase cap (at worst about twice the cap around a period boundary), the Safe’s spender allowlist, and its card pause. The escrow’s order signer has its own key, separate from the arbiter and relayer.

The v2 changes received an internal independent review on 25 November 2026 before go-live; its findings were fixed and each proof of concept is kept as a Foundry regression test asserting that the attack now fails — for example, sells now count in the cap at feed value, and stock-sale proceeds are held to the quote value even if the router were replaced. This was not an external audit by a security firm. <sup>[18]</sup>

## 6. Why an AI can be trusted to pay: the foundation

An assistant is only as trustworthy as the money system under it. Confío’s was built so that the assistant never needs custody: the key stays on the person’s device, balances live in contracts with public rules on BNB Smart Chain, network fees are sponsored, and the server can only prepare calls that the person — or the person’s own account, within signed limits — executes.

### 6.1 Public BNB Smart Chain deployments

All contracts below are live on BNB Smart Chain mainnet and source-verified on BscScan (proxies linked to their verified implementations). Upgradeable contracts are owned by the 3-of-5 Safe `0xF29A418744E793973BF4eEc676F8a30B2793b623`. <sup>[19, 20]</sup>

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

**Changes since version 4.4**, all through the Safe and recorded in the public deployment records: <sup>[18, 19]</sup>

- 9 November 2026: Ondo Stocks router v3 deleted the transitional 0.30% fee path.
- 21–22 November 2026: Cuenta inteligente factory, v1 account implementation, and fee collector deployed; cUSD upgraded so factory accounts can arm the fee referral; inheritance enabled (one-way).
- 25 November 2026: `ConfioSmartAccountV2` deployed; factory proxy upgraded (implementation per generation, `migrate()`, `tradePaused`); Comprar escrow proxy upgraded (`depositFrom` with a payer-bound signature, refunds to the paying account; order signer moved to its own key, arbiter remains the sponsor); `ConfioPurchaseSpender` deployed and allowlisted; hands-off trading unpaused after a canary migration of a founder account.

### 6.2 The dollar balance: cUSD and cUSD+

A person holds one Confío dollar, shown as one balance. **cUSD** is the universal payment dollar, backed 1:1 by USDT in an upgradeable vault and the sole external conversion-fee perimeter. **cUSD+** is an accumulating dollar share backed by USDY, for Ondo-eligible users. <sup>[22, 24]</sup>

- **Entry and exit.** USDT from a ramp or external wallet is converted into cUSD or cUSD+ with a 0.9% fee; leaving to USDT — including every local-rail payment — pays 0.9%. The fee is capped in code at 90 basis points. Minting requires an authorized sponsor; fee-bearing redemption is permissionless, so a holder can exit without Confío’s sponsor. Internal cUSD↔cUSD+ conversion is fee-free because value stays inside the system.
- **Yield share.** 85% of positive USDY reference-price appreciation accrues to cUSD+ holders and 15% to Confío as vault surplus. Yield is variable and not guaranteed.
- **Backing and oracle.** Public views expose obligations, backing ratio, and surplus; accounting rounds in favor of backing; USDY backing cannot be swept. If the USDY oracle moves beyond a guard threshold, value-moving paths halt until multi-party governance records an evidence-linked decision.
- **Permissioning.** The cUSD+ vault, not the user, is the permissioned USDY purchaser; minting is subject to Ondo eligibility. <sup>[21, 23]</sup>

### 6.3 Payments, payroll, and Comprar

- **Transfers.** The server prepares exact calls, the user signs, Confío sponsors gas; no platform fee, and a fee-free internal conversion bridges cUSD and cUSD+ recipients.
- **Merchant payments.** The payment contract pays the merchant net of the 0.9% Pay fee; a short-lived backend authorization binds the exact terms; exactly one payment can settle an invoice, on one network. Raw USDT is not authorized, so Pay cannot bypass the conversion fee.
- **Payroll.** Businesses fund asset-separated escrow and authorize delegates to sign payouts; fee accounting stays separate from principal.
- **Comprar.** An in-app marketplace for physical goods, piloting in Bolivia, where buyers and sellers pass Didit verification. The shared `ConfioMarketEscrow` holds the buyer’s dollars per order; the buyer can confirm delivery, dispute, or reclaim after a deadline; an arbiter resolves disputes; sellers pay an 8% fee. The pilot has very few stores and orders.

### 6.4 Investing

- **Ondo Stocks.** Through Ondo Global Markets via the UUPS `ConfioStockRouter` (Safe-owned). A purchase leaves cUSD+ through the ordinary 0.9% exit and delivers the stock token to the wallet or Cuenta inteligente; a sale returns proceeds through the 0.9% entry. The router charges no fee of its own; since v3 it has no other fee path and returns settlement excess. Subject to Ondo eligibility and market availability. <sup>[20, 25]</sup>
- **Oro y Bitcoin.** `ConfioSwapRouter` buys and sells catalog tokens such as BTCB and XAUt on PancakeSwap with the same 0.9% exit and entry, no fee of its own, nothing held at rest, a fixed recipient, and relay-only trades within a slippage limit. Not offered on iOS; blocked in some countries. <sup>[26]</sup>
- **Futuros.** Perpetual futures on Hyperliquid for eligible Android users, bridged through Relay with the 0.9% fee on each open, close, or margin addition and no builder fee; the app verifies every bridge order and signature. Not offered on iOS; blocked in the United States, Canada, the United Kingdom, and Belgium. Leverage can lose the entire margin. <sup>[15]</sup>

### 6.5 $CONFIO

$CONFIO is the community token. It is not a stablecoin and does not back any dollar balance. The BEP-20 contract has a fixed supply of 1,000,000,000 CONFIO, no post-deployment mint, no global pause, and no upgrade path; supply can only fall through voluntary burns. The multi-party treasury can freeze an address during a serious security incident and, after a public 7-day wait, return a frozen balance to the party it was stolen from. The on-chain name is the ASCII “Confio”; use only the canonical address above. <sup>[20]</sup>

The replacement presale vault accepts cUSD on an immutable piecewise-linear curve: US$0.20→0.30 for the first 4 million CONFIO, US$0.30→0.70 to 24 million, and US$0.70→1.30 to 74 million. It charges the integral under the curve, was initialized with the prior purchase history, is funded for the migrated claims, and has no repricing function. Rewards accrue in Confío’s database at the live curve price and become claimable through cumulative EIP-712 signatures after the one-way `unlockClaims()` at DEX launch. The RewardVault is treasury-controlled: its owner can rotate the signer, pause claims, and withdraw funds. Allocation, vesting, and concentration are disclosed in the separate tokenomics.

### 6.6 Why BNB Smart Chain

The product followed Ondo: USDY, InstantManager, the price oracle, and Global Markets settlement are deployed on BNB Smart Chain, and keeping every Confío contract beside them means no bridge between the balance, payments, Cuenta inteligente, investing, and $CONFIO, one address for everything, and one sponsored-transaction system so the assistant never has to ask anyone to buy gas. BNB Smart Chain also offers broad USDT liquidity and low fees for sponsored consumer activity. <sup>[21, 25, 27–29]</sup> It carries its own decentralization trade-offs: network interruption, congestion, RPC failures, or ecosystem policy changes could affect the whole product, mitigated but not eliminated by multiple RPC paths and an emergency exit.

## 7. Wallet, security, and governance

### 7.1 Non-custodial wallet

Confío generates the user’s EVM key on the user’s device; the server never holds it. Encrypted recovery material is designed for the user’s personal cloud account, so there is no central vault of user keys. <sup>[15, 30]</sup>

> **Ni siquiera nosotros**
>
> Confío never holds the user’s wallet key, so neither Confío nor its assistant can sign an ordinary wallet transaction as that user. What the assistant can do without a per-action signature is limited to a Cuenta inteligente the user funded, under rules and caps the user signed. Product contracts still have their own disclosed eligibility, pause, freeze, upgrade, or governance controls.

### 7.2 Sponsored transactions

Users never need BNB. EIP-7702 authorizations and an ownerless batch delegate let the user sign the intended calls while Confío’s sponsor pays gas; approvals and actions execute atomically. Server policy restricts destinations, selectors, amounts, recipients, deadlines, and daily limits. Emergency fallbacks and direct exits remain because sponsorship is a service, not a blockchain guarantee.

### 7.3 Assistant safeguards in code

The assistant’s safety does not rest on a prompt. Money tools are scoped by the authenticated session, never by an identifier the model supplies; business employees get no money tools; amounts come only from a code-written question; payees are validated by rail-specific parsers; confirmations are drawn by the app; tool output and page content are data; the shopping agent’s spending, steps, and model cost are capped by the server; and rails are switched per country by settings the model cannot change. Changes are tested against recorded multi-turn conversations and recorded real store pages.

### 7.4 Open source and upgradeability

The app, backend, assistant, shopping agent, contracts, deployment records, and tests are public, and deployed contracts are source-verified. Security relies on unit, fork, invariant, adversarial, and upgrade-rehearsal tests, multi-party governance, bounded fees, non-sweepable backing, oracle guards, pauses, replay protection, and staged rollout. No review method eliminates smart-contract or operational risk. <sup>[15, 19, 20]</sup>

| Component | Upgradeable? | By whom |
| --- | --- | --- |
| cUSD and cUSD+ vaults | Yes (UUPS) | 3-of-5 Safe, with public implementations and storage-layout checks |
| Stock router, swap router, Comprar escrow, heartbeat | Yes (proxies) | 3-of-5 Safe |
| Cuenta inteligente factory | Yes (UUPS) | 3-of-5 Safe; can add an implementation for new or migrating accounts and pause hands-off or card paths, cannot change an existing account |
| Cuenta inteligente accounts | No (immutable clones) | Moving versions is an owner-signed `migrate()` |
| Purchase spender, fee collector, batch delegate, $CONFIO token, presale curve | No | — |

The vaults stay upgradeable because cUSD+ depends on external Ondo contracts that may change and cUSD is the shared fee perimeter. The accepted consequence is the trust assumption in section 5.3.

## 8. Users and distribution

| Metric | Snapshot | Date | Definition |
| --- | ---: | --- | --- |
| Users who completed sign-up | 10,886 | 25 Nov 2026 | Active accounts, other than platform test accounts, that finished onboarding by any sign-up method (14,440 registered accounts). |
| Push-reachable devices | 3,407 | 25 Nov 2026 | Devices currently addressable through push notifications. |
| Used in the last 30 days | 3,402 | 25 Nov 2026 | Push-reachable devices recorded as used within the preceding 30 days; not a standardized MAU figure. |
| Didit-verified users | 177 | 23 Jul 2026 | Users who submitted a government-issued identity document and completed live-selfie liveness and face matching. |
| Identity-verification completion | 61.5% | 23 Jul 2026 | Share of users who completed the Didit flow among those who started it. |

These internal metrics are unaudited. Since late October 2026, sign-up no longer requires a phone number, so users are counted by completed onboarding; the 23 July 2026 figure (8,004) counted phone verification and is not directly comparable. The metrics do not imply that users are funded, active, or eligible for every product. <sup>[31]</sup>

Confío’s founder-led Spanish-language audience is approximately 480,000 across social platforms, with effectively zero paid-media spend to date. <sup>[32]</sup> That channel is how a new behavior — letting an assistant pay — gets explained, repeatedly and publicly, in the user’s language. The agreed success measure is the share of people who let Confío IA pay once and let it pay again within 30 days. Rollout is country by country and follows verified provider capabilities, not a country flag on a marketing page.

## 9. Business model

The assistant’s paid execution and the rails network are the revenue lines. Talking to Confío IA, searching, building carts, and priced reviews are free; executing on the person’s behalf is paid by Cuenta inteligente; moving money across the dollar perimeter onto a local rail pays the 0.9% fee.

| Revenue line | Current policy |
| --- | --- |
| Cuenta inteligente | US$149.99 per year (default) or US$14.99 per month, taken from inside the account; no refunds. Includes Confío IA+ (store purchases, hands-off trades, rule changes by chat), automation, and the beneficiary. |
| Leave the Confío dollar system | 0.9% when cUSD or cUSD+ becomes external USDT, including every local-rail payment and every assistant purchase. |
| Enter the Confío dollar system | 0.9% when USDT becomes cUSD or cUSD+, from a ramp or an on-chain transfer. |
| Transfers and internal conversion | 0%; network fees are sponsored. |
| Merchant payments and payroll | 0.9% flat platform fee, enforced on-chain. |
| Comprar | 8% marketplace fee paid by the seller. |
| cUSD+ yield share | 15% of positive USDY appreciation; variable, not guaranteed. |
| Stocks, Oro y Bitcoin, Futuros | The same 0.9% perimeter fee; no separate trading or builder fee. Third-party spreads and venue costs may apply. |
| Fiat-rail economics | Provider pricing and any local-account fees are shown in the live quote. |

The public rule is **0.9% to enter, 0% to move inside, 0.9% to leave**; Cuenta inteligente does not waive it. Network sponsorship and model usage are product costs.

## 10. Compliance and operating model

Confío separates wallet-key custody from product and provider obligations. Fiat custody, currency conversion, identity verification, and permissioned-asset access are performed by the relevant providers; this describes the operating design and is not a claim that Confío has no legal or compliance obligations.

- Didit runs identity verification (government document, live selfie, liveness, face match). Users under 18 are declined.
- Fiat providers apply their own identity, address, eligibility, sanctions, and transaction controls; Didit verification alone does not guarantee provider approval.
- USDY minting and Ondo Stocks access follow Ondo eligibility and geographic requirements. <sup>[21, 23, 25]</sup>
- A Cuenta inteligente beneficiary must be a Didit-verified Confío user, designated only through Confío’s sponsor gate, and must accept; U.S.-resident beneficiaries are blocked.
- Comprar requires Didit verification for buyers and sellers.
- The shopping agent never works around a site’s block and refuses countries without a rail that pays the exact order amount.
- New countries and rails launch only after legal, operational, and provider checks.

## 11. Risks and mitigations

No financial product, and no AI agent, is risk-free. This table is not exhaustive.

| Risk | Current mitigation | Residual exposure |
| --- | --- | --- |
| **AI misunderstanding or model error** | Models propose; code asks amounts, validates payees, prices, and draws the confirmation; tool and page text are data; tests against recorded conversations. | A model can misread a request, pick the wrong product, or answer wrongly; a person can confirm without reading. |
| **Wrong or failed store purchase** | Choice approves a top total; a higher total returns the order card; two models must read the same total, which must appear on the page; one approval, one order; server caps; payment from a capped account rule. | Stores change pages, cancel, mis-ship, or delay refunds; the person may have to deal with the store. The agent is not yet proven across many stores. |
| **Local-rail payment errors** | Checksum-validated identifiers, exact-amount quotes, provider status tracking, no “paid” before the rail confirms. | Providers can fail, delay, reverse, or pause; a store payee read from a checkout can still be wrong. |
| **Hands-off and smart-account trust** | Immutable accounts; on-chain caps; buys and sells counted; price bands; fee bound; alerts; Safe kill switches; separate order-signer key; internal review with regression tests. | Hands-off actions trust Safe-upgradeable routers and escrow; relayer compromise plus a malicious upgrade could sell stock at a forged price; operator compromise is bounded by each cap. Rules execute as signed. |
| **Competition** | Combination of errands, multi-country rails, and self-custody limits; open source. | Global assistants or regional banks may add local-rail payments; Brazilian banks already offer agentic Pix to their own customers. |
| **Fiat rails and paused corridors** | Live switches per country and provider; pauses on incidents or fraud signals (Colombia top-up and Bre-B paused). | Coverage, pricing, and provider availability can change without notice. |
| **Underlying assets** | cUSD backed by USDT; cUSD+ holds USDY with public accounting. | Depeg, issuer, custody, reserve, and redemption risks for USDT and USDY. |
| **Smart contracts and oracle** | Open source, verified deployments, layered tests, bounded controls, oracle guard. | Bugs, integration or upgrade errors; bad oracle data can delay deposits and redemptions. |
| **Liquidity and redemption** | Permissionless fee-bearing redemption; Emergency Exit broadcasts through public BSC nodes. | InstantManager liquidity, providers, network conditions, or compliance actions may delay exits. |
| **Investing and leverage** | Verified routers, direct delivery, fee and slippage bounds, eligibility and country gates. | Market, issuer, venue, bridge, liquidation, and total-loss risks, especially for Futuros. |
| **Key recovery** | Device keys and personal-cloud recovery. | Loss of device or cloud access, or recovery defects, can affect access. |
| **Governance and BNB Smart Chain** | 3-of-5 Safe, public upgrade records, storage checks; multiple RPC paths. | Signers could make a harmful change; network interruption or policy changes affect the whole product. |
| **Regulatory and financial crime** | Identity checks, provider screening, geofencing, legal review, bans of abusive accounts. | Providers or authorities may restrict activity; rules for AI agents that pay are still developing. |
| **Token and rewards** | Fixed supply, immutable curve, public contracts, separate tokenomics. | Founder concentration, liquidity, volatility; rewards depend on treasury funding. |
| **Metrics** | Definitions, dates, and unaudited status disclosed. | Early usage may be concentrated and may not predict adoption. |

## 12. Roadmap and current status

| Workstream | Completed / current | Next verifiable gate |
| --- | --- | --- |
| Confío IA | Chat-first home and onboarding; payment, trade, and top-up cards with code-asked amounts; doors to every job; memory. | Repeat assistant payers; the pending independent review of chat payments. |
| Errand connections | WhatsApp, Gmail, and phone calendar deployed on the server. | Released in app builds; Google verification for Gmail beyond the limited group. |
| Shopping agent | Cloud-browser purchases with model judges and code-checked facts; multi-store search; SPEI, Pix, and Pago Móvil; Bolivia with the person paying the QR. | Reliable completion across more stores; exact-amount payouts for Argentina’s fixed QR. |
| Cuenta inteligente | Factory, v1 and v2 accounts, fee collector, purchase spender verified; inheritance on; hands-off trades, Comprar, and store purchases live since 25 November 2026. | Carry send, payout, and card rules through migration; paying subscribers. |
| Rails | Live in Mexico, Brazil, Venezuela, Bolivia, Argentina, Chile, and Peru as in section 4.5; Colombia paused. | Re-open Colombia; QR Bolivia payments; additional verified providers. |
| Foundation | cUSD/cUSD+ perimeter, sponsored transactions, payments, payroll, invitation escrow, stock and swap routers, Futuros on Android, $CONFIO vaults. | Reconciliation and exit monitoring; legal review for Oro y Bitcoin and Futuros on iOS. |
| Comprar | Escrow upgraded for account purchases; Bolivia pilot. | Sellers and repeat buyers. |
| Distribution | 10,886 users who completed sign-up; ~480,000 founder audience; no paid media. | Funded users, repeat assistant payments, country cohorts. |

Confío measures sign-ups, verified, funded, and active users separately, along with repeat assistant payers, completed and failed agent purchases, Cuenta inteligente subscribers, conversion fees, net inflow, and country cohorts; revenue is reported excluding banned and founder accounts.

> **The next proof point**
>
> People who let Confío IA run an errand and pay for it once, and do it again within 30 days, across several Latin American countries.

## 13. Legal disclaimer

This document is provided for informational and technical-reference purposes only. It is not investment, legal, tax, accounting, or financial advice; it is not a prospectus, offer, solicitation, recommendation, or promise of returns. Product descriptions reflect the status as of 25 November 2026 and may change. Descriptions of third-party products are based on the cited public sources as of their access dates and may be incomplete or out of date.

Confío IA is an automated assistant. Its answers may be incomplete or wrong and are not personalized financial advice. Purchases made by the shopping agent are contracts between the person and the store; Confío does not guarantee a store’s products, delivery, returns, or refunds. Actions executed by a Cuenta inteligente follow the rules and caps its owner signed.

USDT, cUSD, and cUSD+ are not bank deposits and are not insured by a deposit-insurance scheme. Stablecoins, tokenized notes, smart contracts, blockchains, oracles, fiat providers, market makers, custodians, and other infrastructure can fail, be suspended, lose value, or become subject to new rules. Any cUSD+ yield is variable and not guaranteed; USDY access is subject to Ondo eligibility and applicable law.

Ondo Stocks are tokenized financial instruments, not bank deposits. Gold and bitcoin tokens and leveraged perpetual futures can lose value rapidly, and Futuros can lose the entire margin. $CONFIO is separate from USDT, cUSD, cUSD+, and USDY and provides no claim on Confío’s backing, revenue, equity, assets, or profits unless definitive terms expressly state otherwise.

Readers should review definitive product terms, risk disclosures, smart contracts, provider terms, and local law before using any service.

## Endnotes

Third-party sources accessed 25 November 2026.

1. Meta, “Introducing Muse: The World’s First Personal AI Agent Built for Everyone,” 8 September 2026: U.S. rollout; email, travel, forms; checkout through Stripe’s Link with one-time cards; approval before purchases. https://about.fb.com/news/2026/09/introducing-muse-personal-ai-agent/

2. OpenAI, “Introducing ChatGPT Wallet,” 13 November 2026: agent purchases with network payment tokens, built with American Express, Chase, Mastercard, and Visa; initially through dots, U.S.-issued cards only. https://openai.com/index/introducing-chatgpt-wallet/

3. Al Jazeera, “OpenAI launches ‘dots,’ personal AI assistant ‘built to handle everything’,” 30 September 2026. https://www.aljazeera.com/economy/2026/9/30/openai-launches-dots-personal-ai-assistant-built-to-handle-everything

4. Asia Economy, “Privacy Control Concerns Become Reality Amid Craze for ‘Pickle,’ the AI That Acts on Its Own,” 9 November 2026: Korean agent handling everyday tasks across KakaoTalk, Coupang, Government24, and Google; reported phone calls. https://view.asiae.co.kr/en/article/2026110909414917294

5. Zapia, “Zapia: the AI agent built for Latin American life,” 18 May 2026: WhatsApp, app, and web; contacting businesses, scheduling, replying, price tracking. https://zapia.com/blog/zapia-ai-agent-built-for-latin-american-life?lang=en

6. Xataka Colombia, “Luzia quiere ser la inteligencia artificial que todo el mundo sabe usar… y que te contesta por WhatsApp,” 10 October 2023. https://www.xataka.com.co/robotica-e-ia/luzia-quiere-ser-inteligencia-artificial-que-todo-mundo-sabe-usar-que-te-contesta-whatsapp

7. Banco Central do Brasil, “Pix.” https://www.bcb.gov.br/en/financialstability/pix_en

8. Banco de la República (Colombia), “Bre-B.” https://www.banrep.gov.co/es/bre-b

9. Superintendencia de Banca, Seguros y AFP del Perú, *Carpeta de Información del Sistema Financiero*, February 2026. https://intranet2.sbs.gob.pe/estadistica/financiera/2026/Febrero/SF-2102-fe2026.PDF

10. Inter-American Development Bank, “Remittances to Latin America and the Caribbean Ease After 2025 Surge,” 16 June 2026: US$173.7 billion in 2025. https://www.iadb.org/en/blog/migration/remittances-latin-america-and-caribbean-ease-after-2025-surge

11. Chainalysis, “Latin America Emerges as Crypto Powerhouse Amid Volatile Growth,” 2 October 2025. https://www.chainalysis.com/blog/latin-america-crypto-adoption-2025/

12. Nubank, “Nubank leverages AI to scale Pix operations,” 10 December 2024: Pix by voice, text, or image in the app and on WhatsApp. https://nu.com/en/newsroom/consumers/nubank-leverages-ai-to-scale-pix-operations

13. iProfesional, “Mercado Pago relanza Mago con IA para gestionar las finanzas,” 30 September 2026: transfers prepared from a conversation, confirmed by the user (Argentina). https://www.iprofesional.com/finanzas/465587-mercado-pago-relanza-mago-con-ia-para-gestionar-las-finanzas

14. Iniciador, “Iniciador launches Brazil’s first agentic payments MCP on Pix,” 19 May 2026: for regulated institutions and fintechs; the agent proposes, the user approves with biometrics. https://iniciador.com.br/en/conteudos/iniciador-anuncia-pagamentos-agenticos-full-stack-ai-toolkit

15. Confío public GitHub repository: app, backend, assistant (`assistant/`), shopping agent (`agent_tasks/`), WhatsApp link (`whatsapp_link/`), marketplace, perpetual futures, contracts. https://github.com/caesar4321/Confio

16. Confío, assistant design records: `docs/designs/confio-assistant.md`, `assistant-first-steps-guide.md`, `assistant-mail-calendar.md`. https://github.com/caesar4321/Confio/tree/main/docs/designs

17. Confío partner records and production configuration, 25 November 2026: local top-up, withdrawal, and payout rails through Koywe, Infinia, Pago ASAP, and VEXPay, with per-country switches and pauses.

18. Confío, Cuenta inteligente specification, hands-off account design, and hands-off v2 deployment record (addresses, Safe batches, transaction hashes, review regression tests): `docs/designs/cuenta-inteligente-spec.md`, `docs/designs/hands-off-account.md`, `docs/deploy/hands-off-v2-deploy.md`, `contracts/smart_account/`. https://github.com/caesar4321/Confio/tree/main/contracts/smart_account

19. Confío, “cUSD+ deployment record - BSC mainnet,” updated November 2026. https://github.com/caesar4321/Confio/blob/main/contracts/cusd_plus/DEPLOYMENT.md

20. Confío BSC contracts: `ConfioToken.sol`, `ConfioPresaleVault.sol`, `ConfioRewardVault.sol`, `ConfioVestingVault.sol`, `ConfioInviteEscrow.sol`, `ConfioBatchDelegate.sol`, `ConfioStockRouter.sol`. https://github.com/caesar4321/Confio/tree/main/contracts/cusd_plus and https://github.com/caesar4321/Confio/tree/main/contracts/ondo_stocks

21. Ondo Finance, “USDY Basics.” https://docs.ondo.finance/general-access-products/usdy/basics

22. BscScan, Confío Dollar+ proxy `0x3C29417eb4314155e63d4C7D4507852b87763Ed1`. https://bscscan.com/address/0x3C29417eb4314155e63d4C7D4507852b87763Ed1#code

23. Ondo Finance, “Integrating with the USDY InstantManager contract.” https://docs.ondo.finance/developer-guides/usdy-instant-manager-integration

24. Confío, `CusdPlusVault.sol`: accounting, redemption, oracle guard, and 15% yield share. https://github.com/caesar4321/Confio/blob/main/contracts/cusd_plus/CusdPlusVault.sol

25. Ondo Finance, “Ondo Stocks” and Global Markets API documentation. https://ondo.finance/ondo-stocks and https://docs.ondo.finance/api-reference/quickstart

26. Confío, `ConfioSwapRouter` source and notes. https://github.com/caesar4321/Confio/tree/main/contracts/crypto_swap

27. BNB Chain, BNB Smart Chain introduction and finality. https://docs.bnbchain.org/bnb-smart-chain/introduction/

28. BNB Chain, transaction fees and network concepts. https://docs.bnbchain.org/bnb-smart-chain/

29. BNB Chain, ecosystem and developer documentation. https://www.bnbchain.org/en/developers

30. Confío, “Por qué Confío no guarda tu dinero - y por qué eso importa,” project source.

31. Confío internal product analytics: 25 November 2026 for users who completed sign-up (onboarding finished, any method; platform test accounts excluded), registered accounts, and FCM push-reachable devices (active device tokens; used within 30 days by last recorded use); 23 July 2026 for Didit verification and its completion rate. Unaudited.

32. Confío internal founder-channel analytics, 23 July 2026. Approximate; changes over time.

### Document provenance

Version 4.5 (25 November 2026; revised the same day for hands-off results in the chat, Comunidad sharing of hands-off trades, and voice requests) restates Confío around one thesis: a personal assistant for Latin America that finishes errands by paying on local rails from self-custody dollars within enforced limits. It adds a competitive landscape drawn only from cited public sources, Cuenta inteligente, the shopping agent, Oro y Bitcoin, Futuros, and Comprar; condenses the dollar, investing, and token infrastructure into foundation subsections; refreshes the contract table against BscScan verification and on-chain state; and refreshes operating metrics from read-only production queries. Earlier market-thesis material on dollarization was removed with its endnotes.
