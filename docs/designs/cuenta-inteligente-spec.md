# Cuenta inteligente: final specification

Date: 2026-11-20
Status: FINAL for the decisions in section 2 (rows 1 to 15 from the decision session, rows 16 to 32 from the founder's answers to the drafts, same day; rows 33 to 35 from 2026-11-21). What is still open is listed in section 9.3.
Supersedes: the section "For Build B (launch only; nothing below is built for the probe)" and every other launch-only note in [`cuenta-inteligente-fake-door.md`](cuenta-inteligente-fake-door.md). That document remains the record of the waitlist probe (2026-10-11 to 2026-11-20). Where the two disagree, this document wins. In particular the probe's merchant subscriptions and debit control, its price (US$9.99), its "cUSD+ is unwrapped to cUSD to pay the charge" rule and its `ConfioPayrollVault`-style shared escrow are all replaced.

The repository is public. This document contains no user identifiers, names, interview material, revenue or user counts, and none may be added.

Reading guide: sections 1 to 3 say what the product is; 4 to 6 are the contract; 7 and 8 are the backend and the app; 9 lists what was verified in code, what was not, the conflicts found between the decisions and the code, and the open points; 10 and 11 are rollout, tests and exclusions.

---

## 1. Summary

**What it is.** Cuenta inteligente is a paid account inside Confío. Technically it is a separate smart contract, one per user, owned by the user's personal wallet. The user moves assets into it. Assets inside it can be moved by rules the user sets (automation) and can pass to one named beneficiary if the user stops using the account (inheritance, "Herencia Digital"). Assets in the personal wallet are not affected by either.

**Price.** US$149.99 per year (default selection) or US$14.99 per month. One tier. No refunds.

**Included.**

| Benefit | What the user gets |
|---|---|
| Automatic payments and transfers | Recurring rules executed by the contract, daily, weekly, every two weeks or monthly: sends to another Confío user, and payments to a saved bank destination (CLABE, Pix, Bre-B) |
| Automatic investing | Periodic buys (DCA) of stocks, bitcoin and gold on the same schedules |
| Confío IA+ | The assistant operates the account for the owner (decision 34): the owner creates, changes or stops rules by talking, keeps a target split of investments with new buys, sets alerts, and gets a monthly review. Every change takes effect only after the owner reviews and signs it. Free Confío IA answers and advises; Confío IA+ executes on the owner's own account, always with the owner's confirmation. Never described as more usage, a better model or "unlimited" |
| Beneficiary | One named beneficiary who can take ownership of the account after a long challenge window during which the owner can cancel with any signed action |

**Explicitly not included.**

- No discount or waiver of the 0.9% entry/exit conversion fee.
- No coverage of assets in the personal wallet ("Inversiones", Confío Dollar+ held there).
- No futures/perps inside the account.
- No locked presale CONFIO and no presale purchases from the account.
- No second tier, no separate "Bóveda" brand.
- No more than one beneficiary and no percentage splits.
- No store billing and no in-app purchase.
- No beneficiary coverage after the subscription lapses, and no settlement fee at claim.
- No automatic "saving" and no cUSD/cUSD+ conversion inside the account. A user holds one Confío dollar, cUSD or cUSD+, according to Ondo eligibility, never both.
- No merchant subscriptions.
- No refunds, monthly or annual.

---

## 2. Decisions (all FINAL)

| # | Decision | Reason (one line) | Status |
|---|---|---|---|
| 1 | One tier, brand "Cuenta inteligente". No "Bóveda" brand. A second tier only after 50 paying users | One name and one price keep the offer readable; a second tier needs evidence first | FINAL |
| 2 | US$14.99/month or US$149.99/year, annual preselected. The probe showed US$9.99. (Revised by the founder after the first draft: was US$149 with monthly preselected) | Payment, not a waitlist tap, is now the demand signal; the annual plan is the one to push | FINAL |
| 3 | The 0.9% entry/exit conversion fee stays. No waiver or discount for subscribers | The conversion fee is existing revenue and must not be discounted by a membership | FINAL |
| 4 | Included: (a) contract automation: scheduled sends, automatic payments to bank destinations, DCA of stocks, bitcoin, gold (revised by rows 17 and 18: "saving" removed, bank payments added); (b) IA+ as part of the account service; (c) one family beneficiary ("beneficiario" in store and legal copy) | These three are the paid job; IA+ is part of the account service | FINAL |
| 5 | A separate smart-contract account owned by the user's personal wallet (EOA with the EIP-7702 `ConfioBatchDelegate`, Confío's KMS sponsor as `tx.origin`). Only assets inside it are automated and inheritable. Rejected: ERC-20 approvals from the personal wallet; inheritance logic in the 7702 delegate | A separate contract bounds what automation and inheritance can touch; the delegate stays minimal and immutable | FINAL |
| 6 | The fee is taken from inside the account: cUSD first, then cUSD+ shares in kind (no conversion to cUSD first). If neither covers it, the contract sells stock/bitcoin/gold: one period's fee only, after several days of notices, proceeds land only inside the contract | Taking the user's own dollar avoids a conversion step in the account (cUSD↔cUSD+ is itself free, but `unwrapToCusd` is sponsor-gated); forced sale closes free riding for non-dollar holders | FINAL |
| 7 | Cancellation is user-signed. At the end of the paid period every asset returns to the owner's personal wallet. A failed payment or failed sale never returns assets: it pauses automation and retries. The expiry return is callable by anyone, destination fixed to the owner's wallet, executable per asset. Futures/perps are excluded from the account | A dead owner's assets must not bounce back to a wallet nobody can open; one failing token must not block the rest | FINAL |
| 8 | No free riding: no "beneficiary stays after lapse", no settlement fee at claim | Forced sale (6) makes the subscription the only way to keep coverage | FINAL |
| 9 | Inheritance is an ownership transfer of the account. Beneficiary initiates, a challenge window runs (default 180 days, user-selectable), beneficiary executes and becomes owner. No heartbeat, no Confío liveness ping. Any owner-signed transaction cancels a pending claim; the relayer's fee deduction does not. Cooldown after a cancel; the owner can remove the beneficiary. The beneficiary can call the functions directly on-chain | Ownership transfer avoids per-token logic; only the owner's own signature proves the owner is alive | FINAL |
| 10 | After execution the account is a withdraw-only box: no fee, no automation, no beneficiary designation, no relayer authority, no authority for the previous owner's key. The new owner can only move assets out, to their own Cuenta inteligente or personal wallet, with no deadline | Keeps one Cuenta inteligente per user and removes any need for subscription consent on an inherited account | FINAL |
| 11 | One beneficiary in v1. Must be a Didit-verified Confío user, checked and notified at designation. US-resident beneficiaries are blocked at designation | Ondo's continuing no-US-person representation covers cUSD+ and stock tokens; checks at designation avoid a failed claim years later | FINAL |
| 12 | Relayer limits are enforced in the contract: at most one fee per period; forced-sale proceeds stay in the contract; assets leave only to the owner's wallet or, by ownership transfer, to the registered beneficiary (extended by rows 16 and 29: owner-registered send payees and owner-registered payment rules) | A server-only rule does not survive a relayer key compromise | FINAL |
| 13 | Locked presale CONFIO is out of scope; no presale purchases from the account. `ConfioPresaleVault` is not changed and not made upgradeable. Claimed CONFIO is inheritable once moved in. `uncreditMigrated`/`creditMigrated` is not an inheritance mechanism | The presale vault has no transfer function and must not gain an owner-driven one for this feature | FINAL |
| 14 | UI: a third account in the existing personal/business switcher, an inherited-account view, a "move everything" action. Offer: automation first ("Confío lo hace por ti, cuando toca", the paid execution promise of the assistant-first redesign 7.8), then a dedicated Herencia card right after the benefits (amended 2026-11-21 by the founder; was "depends on balance"). The app ignores the server's headline order; the account home keeps Herencia at the top | Reuses the account model users already know | FINAL |
| 15 | Rollout: automation + IA+ first with small amounts; the founder runs the full claim and return flow with his own funds; then the beneficiary feature is switched on. The Codex audit loop applies, with a separate pass for the inheritance path | The inheritance path is the one that cannot be fixed after a user dies | FINAL |
| 16 | A scheduled send is allowed as an exit from the account when its payee, token, amount and schedule were stored on-chain by an owner-signed call. The relayer can only trigger that exact transfer | Reconciles decisions 4 and 12 (former conflict C1) | FINAL |
| 17 | No automatic "saving" and no cUSD/cUSD+ conversion in the account. A user holds cUSD or cUSD+ by Ondo eligibility and sees one dollar balance, never both. Automation means payments, transfers and investing. One narrow exception: a cUSD+ `Payout` run unwraps 5 bps more than it redeems, so up to `grossCusd * 5 / 10000 + 2 wei` of cUSD dust can stay in a cUSD+ account; it is counted in the one dollar balance, used first by `collectFee`, withdrawable, and never makes the account's dollar cUSD | There is nothing to convert between; income cannot be pulled from the personal wallet under decision 5 (former conflict C3) | FINAL |
| 18 | Automatic payments to a saved bank destination (CLABE, Pix, Bre-B) are included, daily, weekly, every two weeks or monthly. Merchant subscriptions are not | The probe promised automatic payments; that promise is kept. Merchant subscriptions need merchants (former conflict C5) | FINAL |
| 19 | Stock tokens and cUSD+ in a Cuenta inteligente are held at the user's own account address, with the relayer limited as in decision 12. A new owner who is not eligible can only withdraw | Closes former open point O1 | FINAL |
| 20 | The move from US$9.99 to US$14.99 is not announced separately to waitlist members | The launch price is simply the price shown (former O2) | FINAL |
| 21 | The product is a financial account: payments, investing and a beneficiary. IA+ is a minor benefit inside it, not the product. No store billing | Closes former open point O3 | FINAL |
| 22 | No refunds. A cancelled annual plan runs to its expiry | One rule for both plans (former O5) | FINAL |
| 23 | Account instances are immutable. No upgrade path | An upgrade path would make a compromise of Confío's side a risk to every account (former S1) | FINAL |
| 24 | A price change applies to an existing subscriber from the next renewal, as store subscriptions do | No snapshot is needed (former S3) | FINAL |
| 25 | While a claim is pending, rules keep executing, the fee keeps being charged and forced sales keep happening | Pausing any of them would open a loophole (former S4, S5) | FINAL |
| 26 | A beneficiary can be designated only through Confío's sponsor gate; a direct on-chain designation is impossible. The beneficiary must accept, and the server records the time of designation and of acceptance | The KYC and residence checks must not be bypassable; acceptance gives the beneficiary knowledge and consent (former S6, S8) | FINAL |
| 27 | Waitlist rows and answers are kept. The probe plan's "deleted 90 days after the decision" line is withdrawn | They are funnel data for later comparison | FINAL |
| 28 | No rule is imposed on "works even if Confío disappears" copy; the facts in section 6.7 stay as engineering reference. Legal review is outside this document | Closes former S7, O7 | FINAL |
| 29 | Bank payment rules are bound on-chain by the rule the owner signed (token, amount, frequency) and nothing else. No address allowlist, no extra monthly cap | The BSC-side recipient is a per-transfer bridge address; the exposure is what each owner chose to automate (former C7) | FINAL |
| 30 | Presale CONFIO is not a fee source; it cannot be inside the account at all (decision 13), so the question does not arise for it. CONFIO that has been unlocked and moved into the account is an ordinary asset of the account: it passes with an ownership transfer and it is a fee source by forced sale like stocks, bitcoin and gold. CONFIO has no DEX market today, so v1 cannot sell it; the contract must be built so that CONFIO sales can be switched on later without replacing accounts (section 5.5). (Corrected by the founder: an earlier version of this row excluded all CONFIO from fees) | Unlocked CONFIO is the user's liquid asset like any other; only the locked allocation is outside | FINAL |
| 31 | USDT that reaches the account is converted automatically into the owner's Confío dollar (cUSD+ if Ondo-eligible, cUSD otherwise), as in the personal wallet | A user never holds raw USDT in Confío; the same rule applies inside the account | FINAL |
| 32 | `CusdVault` is changed so that a Cuenta inteligente can arm the fee referral for its owner. Automated activity (rules, forced sales, USDT conversion) then pays the referrer's share like owner-signed activity | The referral share should not depend on whether the owner or the relayer triggered the conversion (former C4) | FINAL |
| 33 | An owner whose account passed to a beneficiary can open a new account from the same wallet; the factory keeps one current account per owner (generation in the CREATE2 salt) | A living owner who missed the window must be able to start again | FINAL |
| 34 | Confío IA+ means "the assistant executes", not "more AI". Free Confío IA answers and advises. For a subscriber, the assistant proposes rule changes the owner asks for (create, change, stop; send, bank payment, buy), keeps an owner-set target split of investments by new buys only (never by selling), produces the monthly review (in the thread every month and on request), and keeps owner-set alerts on prices and exchange rates. Every rule change takes effect only after the owner reviews it on the rule screen and signs it through the existing prepare and sign flow; an alert only tells the owner. The assistant never moves money on its own judgement and never chooses what to buy, how much, a split or an alert level. No contract change (section 3.5) | The paid benefit is the account operated for the owner, with the owner's signature on every change; usage-based benefits read as an AI unlock | FINAL |
| 35 | A Card rule (`RuleKind.Card`, appended) lets a future Confío Card issuer pull approved amounts from the account (founder, 2026-11-21: "Add the card allowance rule before deploy"). The owner creates and stops it like any rule: `payee` is the issuer's spender, `amountUsd` the most it may take per period, `frequency` the period, `tokenIn` the dollar spent. The spender must be allowlisted by the Safe in the factory at creation and on every pull; the Safe can also stop all cards at once (`cardPaused`). The spender calls `cardPull(ruleId, usdtOut)` and receives exactly `usdtOut` USDT, pushed in the same call through the normal 0.9% exit; the gross (USDT plus the exit fee) counts against the cap. Periods are fixed, one minimum gap of the frequency long (1, 7, 14, 28 days), from the rule's first run; many pulls per period up to the cap; no carry-over. Gates as a rule run: Active and Current; a pending claim does not block (decision 25); an executed claim ends every card for good. The relayer pause does not apply. No standing allowance is ever given. Card pulls pay no subscription fee | An issuer settles card spending by pulling; the owner's signed cap per period, not the issuer, bounds the exposure, and the Safe can cut a compromised issuer instantly | FINAL |
| 36 | The processor's fixed Pix and CLABE fee is outside a rule's 1.5% cost limit (founder, 2026-11-22: "Outside"). The limit still measures Relay's whole cost, fixed part included; its value and the FX tolerance are unchanged. The owner sees the fee before signing (US dollars, per payment, how it is collected) and it is stored with the Face-bound standing authorization as a ceiling. A run never charges above it: a higher tariff skips the run, tells the owner and asks for a new signature; a lower one charges the lower. Maintenance and earlier debt are never part of a rule's per-payment fee. A payment must still cover its costs and the rail's minimum | A fixed fee inside a percentage limit refused ordinary amounts (CLABE under about US$42, Pix under about US$12); shown and capped by the owner's consent, it needs no percentage bound | FINAL |

---

## 3. Account model

### 3.1 Three kinds of account

| | Personal wallet | Cuenta inteligente | Inherited account |
|---|---|---|---|
| What it is | The user's EOA (7702-delegated to `ConfioBatchDelegate`) | A `ConfioSmartAccount` contract whose `owner` is that EOA | A `ConfioSmartAccount` whose ownership was transferred by an executed claim |
| Who signs | The user's key | The same key (the contract has no key) | The new owner's key |
| Subscription fee | None | Yes | None |
| Automation | No | Yes | No |
| Beneficiary | No | Yes (one) | No |
| Relayer authority | Executes only user-signed batches | Fee, notice, forced sale, USDT conversion, user-registered rules (section 4.6) | None |
| Assets leave to | Anywhere the user signs | `owner` wallet; send-rule payees the owner registered; payout destinations for payment rules the owner registered; fee collector; by ownership transfer | New owner's wallet or the new owner's own Cuenta inteligente |
| How many per user | One per account context (existing) | One current account | Any number (one per inheritance received) |

One Cuenta inteligente per user means one current account per owner address, enforced by the factory (`accountOf[owner]`). An inherited account does not count: it is not the new owner's Cuenta inteligente and never becomes one.

An owner whose account passed to their beneficiary through an executed claim can open a new one from the same wallet (decision 33). The factory deploys it one generation on (section 4.3) and `accountOf[owner]` then points at it. The inherited account stays the heir's. While the owner's current account is still theirs (never subscribed, active, cancelled, expired, or with a claim pending or executable) no second account can be opened.

### 3.2 Assets that can be inside

| Asset | Inside the account | Automated | Used for the fee | Returned on expiry | Notes |
|---|---|---|---|---|---|
| cUSD | Yes | Yes | First | Yes | Held by users who are not Ondo-eligible. Transfers revert while cUSD is paused (`CusdVault._update`) |
| cUSD+ (shares) | Yes | Yes | Second, in kind | Yes | Held by Ondo-eligible users. Transfers revert while the vault is paused or either address is `frozen` (`CusdPlusVault._update`) |
| Ondo GM stock tokens | Yes | DCA buys | By forced sale | Yes | |
| Catalog crypto/metals tokens (BTCB, XAUt at launch) | Yes | DCA buys | By forced sale | Yes | |
| CONFIO (unlocked, moved in) | Yes | No | By forced sale once a market exists (decision 30, section 5.5); not sellable in v1 | Yes | Inheritable once moved in. Locked presale CONFIO is never inside |
| USDT | Transient | — | After conversion | Yes | Converted automatically to the owner's dollar by `convertUsdt` (decision 31). Arrives as redemption excess from `ConfioStockRouter.buyWithSavings`, or by direct transfer |
| USDon | Dust only | No | No | Yes | GM's refund from stock buys, sent to `msg.sender`. Amounts are tiny; withdraw and return accept any ERC-20 |
| Locked presale CONFIO | No | — | — | — | Ledger entry in `ConfioPresaleVault.purchased[address]`; not transferable |
| Futures/perps positions | No | — | — | — | Excluded (decision 7) |
| BNB | No | — | — | — | The account has no `receive()`; it never needs gas |

A given user holds one of the two dollars, not both (decision 17), except for the cUSD dust a cUSD+ payout's unwrap margin leaves (4.7). The contract still handles both tokens, in the order of decision 6, because it cannot know the owner's eligibility and eligibility can change; it never converts one into the other.

The account does not keep an on-chain list of tokens. Every asset function takes the token address as a parameter; the backend enumerates what the account holds (section 7.6).

### 3.3 Moving assets in and out

- **In.** A plain ERC-20 `transfer` from the personal wallet to the account address, inside a normal user-signed 7702 batch. No approval from the personal wallet to the account ever exists (decision 5). Moving cUSD+ or cUSD between a user's own two addresses is a transfer, not a conversion, so no 0.9% fee.
- **Out (owner).** `withdraw(token, amount)` sends to `owner` only. There is no destination parameter in `Active` state.
- **Out (rules).** A send rule pays the payee the owner registered on-chain. A payment rule exits dollars to USDT and pays a payout destination (section 4.7, conflict C7).
- **Out (expiry).** After a user-signed cancellation and the end of the paid period, anyone may call `returnAsset(token)`; the full balance of that token goes to `owner`.
- **Out (inherited).** The new owner calls `withdraw(token, amount, to)` where `to` is the new owner's address or the new owner's own Cuenta inteligente (in practice `factory.accountOf(owner)`; the rule is in 6.6).

### 3.4 "Move everything"

- **Into the account.** One user-signed batch of `transfer(account, balance)` calls, one per asset held in the personal wallet that the account supports (cUSD, cUSD+, each stock token, each catalog crypto token, liquid CONFIO). The server builds the list from stored balances and re-reads balances at build time; the app shows the list before signing. If the list exceeds the gas budget for one batch it is split into several batches, each signed.
- **Out of the account.** `withdrawAll(tokens[])`, owner-signed, sends each listed token's full balance to `owner`.
- **Out of an inherited account.** `withdrawAll(tokens[], to)` with the same destination rule as `withdraw`.
- Not moved in either direction: locked presale allocations, perps positions, and any asset the account does not support.

### 3.5 Assistant operation (Confío IA+, decision 34)

Who: a subscriber (current subscription, IA+ entitlement through `assistant/billing.has_plus`) in a personal or `smart` context, never an employee or a business context, on a build at or above `SMART_ACCOUNT_MIN_APP_VERSION`. Non-subscribers who ask for automation get the existing Cuenta inteligente offer chip.

What the assistant does:

| It can | How |
|---|---|
| Read the rules | Kind, amount, frequency, next run, last run and why it did not run; saved bank destinations; the target split |
| Propose a rule change | Create, change or stop a rule. The proposal is validated like the prepare it leads to (payee by the same handle resolution, asset among the buyable assets, bank destination among the viewer's saved destinations (or a CLABE, Pix key or Pago Móvil account in the owner's own words, saved as the last step of the proposal; a failure after that write can leave the saved row, and the reply says so) whose rail is enabled for payouts and whose payment could run today, amount limits including the stock minimum, frequency, first run date). It is shown in plain Spanish with one chip that opens the rule screen prefilled. Nothing is prepared or signed by the assistant |
| Keep a target split | The owner states the split and the total per period ("70/30 entre SPY y bitcoin con 100 al mes"). It is saved as the owner's preference and becomes one Buy rule per asset, amount = total × weight, each signed by the owner. When holdings drift from the split by more than `SMART_ACCOUNT_ALLOCATION_DRIFT_PP` (default 5 points), the assistant proposes re-splitting the next buys toward the underweight assets, same total, every asset keeping at least its minimum. Never a sale. If the total is too small to move the split in a reasonable time, it says so |
| Review a month | Plan charges, signed moves in and out, what each rule executed or skipped and why, balances now, target versus actual. Posted in the assistant thread once a month and produced on request |
| Keep alerts | "Avísame si TSLA baja 5% y prepárame una compra de 100". Price drop or rise by a percentage, price below or above, exchange rate below or above. At most 10 active per account, at most one trigger per alert per 24 hours. A trigger sends a push and a thread note; a buy the owner attached arrives as a chip that opens it prefilled for review and signature |

Limits that do not move:

- **The signature proves intent.** For a payout create or update the prepare summary, which the sheet shows verbatim, is built from exactly what is bound and signed: the whole destination (CLABE's 18 digits grouped; Pix type and key; Pago Móvil phone, bank and cédula), the bank-verified holder being pinned or "no verificado" with what the owner typed, the dollars, what comes out of them at today's prices (the vault's exit fee, the sending cost, a cUSD+ unwrap margin that stays in the account) and the approximate local amount of the rest at the reference rate, frequency, first run after any floor, a change of destination, the rate floor (for Pago Móvil after the provider's payout cost, as the run checks it) and the fee. A rule that could not run at today's prices is refused at prepare, before Face, on every payout rail. The stored copy of the summary keeps only the end of the destination. The assistant's sentence names the same amount, destination and first run.
- **The chat proves provenance, never intent** (`smart_account.assistant_ops`, "provenance"). It reads no negation. **Not in this release:** chat payment rules are paused (`PAYING_RULES_PAUSED`), so this bullet and the ones under it describe the withheld rewrite, not what is live.
  - Window: the owner's own messages (`assistant.engine.owner_words`: at most 10, within an hour, never tapped text, tool or web data or assistant text), each kept separate. A voice note proves nothing for a payout.
  - A value is a whole token of a known written shape, with ASCII digits and exact equality. A masked, partial or look-alike value proves no identifier.
  - Per slot the newest message with any candidate decides, and only with exactly one. Otherwise the assistant asks, and the plain answer (the number, the key, "mensual") is accepted. The slots of a payout are destination (all types, saved tails and names together), amount, frequency and schedule, plus cédula, bank and name for Pago Móvil.
  - A saved account is chosen by its whole identifier, by a fresh bank-verified full name, or by a tail with a marker ("termina en", "cuenta", "la de", "a la") or as the whole message (a Pago Móvil payee also by the cédula, whole or its tail). Exactly one row. A bare number in a sentence never chooses one, and neither does a name the owner typed.
  - Eleven digits are a CPF or a phone by their written form, the word next to them, or an answer that is only "CPF" or "celular".
  - One amount reader serves payouts, sends, buys, target totals and alerts (founder, 2026-11-22): one reading per token (a thousands separator has three digits after it), dollars only, and another currency, a percentage, a multiplier or asset units are asked in dollars. A closed list of currency words, nationalities and fixed phrases ("en moneda local", "no son dólares") names another currency. In a message after the amount's it unsets that amount, marked as dollars or not, until a newer message states it again (a bare number or one in dollars), and "sí" does not. An exchange-rate alert's level keeps its own currency.
  - Percentages are their own slot (written with %, as "70/30", or as the plain answer). An alert's level and its buy amount are two slots.
  - A plain number that is the day the model passed is that day, not money, once the amount itself is written beside or before it. A number marked as money never is.
  - Frequency and schedule come from a small keyword table. A monthly rule starts on days 1 to 28.
  - An update needs no words only for values identical to that rule's own.
  - An alert level whose separator is followed by three digits (36,505) reads two ways and is asked.
  - An asset is its ticker or name in the owner's words, never what the model looked up. A send's payee is the exact @usuario or the full phone in the owner's words. A full name selects only one person among those the owner chose before (a confirmed send by them, a saved recipient, a rule's payee), because anyone picks their own name. That rule's own payee needs no words on an update. Payee and asset are read over the same window as amounts.
  - For sends and buys, frequency and schedule are refused only when the owner's words contradict them; their sentence and summary name the first run after the edit floor.
- An alert is saved only after the owner answers "sí" to a confirmation question written by code (the same pattern as categorizing movements). It moves no money, so it needs no signature.
- One proposal and one chip per reply. Proposals are data; the server's prepare re-validates everything and the owner signs.

How requests map to what the contract has (no new contract capability):

| The owner says | It becomes |
|---|---|
| "compra US$10 de bitcoin cada mes" | `Buy` rule, monthly |
| "manda US$50 a mamá el día 1" | `Send` rule, monthly, `firstRunAt` on the next 1st (days 1 to 28 only, so the day repeats every month) |
| "págale 100 dólares a mi casero por Bre-B cada mes" | `Payout` rule to a saved Bre-B destination |
| A weekday ("los viernes") | Weekly or every-two-weeks rule with `firstRunAt` on that weekday |
| "pausa la regla" | Stop (`cancelRule`). There is no pause; the owner can create the rule again. The assistant says so |
| "guarda / ahorra US$X al mes" | Not possible: there is no saving rule (decision 17). The owner's dollar already is the balance; the assistant offers what exists |
| "mantén 70/30" | Target split kept by new buys only, as above |
| "vende cuando…" | Not possible: the account does not automate sales |

`firstRunAt` is an existing field of the rule tuple. The prepare mutations take an optional `firstRunAt`; it must be between now and 62 days ahead, is refused for daily rules, and on an edit is moved on by whole periods so it is never earlier than the rule's current next run (an edit never runs a rule twice in one period).

---

## 4. Contract specification

Three new contracts (factory, account, and the fee collector of 4.2), in a new package `contracts/smart_account/` (Foundry, same layout as `contracts/crypto_swap/`):

- `ConfioSmartAccountFactory`: deploys one current account per owner and holds the global configuration. UUPS-upgradeable, `Ownable2StepUpgradeable`, owned by the Confío Safe, `renounceOwnership` disabled (as in `CusdVault` and `CusdPlusVault`).
- `ConfioSmartAccount`: the per-user account, deployed by the factory as an EIP-1167 minimal clone at a CREATE2 address derived from the owner and a generation (salt `keccak256(abi.encode(owner, generation))`, section 4.3). Instances are immutable (decision 23): no owner-of-code, no upgrade function, no delegatecall to a changeable target. A new version is a new factory with its own implementation; v1 has no in-place migration. An owner moves by withdrawing to their wallet and depositing into an account of the new factory, both signed. "One current account per owner", `accountOf`, `generationOf`, `predictAddress` and the inherited-withdraw destination are all per factory; a later version must say how an inherited v1 account may pay into a newer account, since v1's check knows only its own factory. `CusdVault` keeps a set of recognised factories rather than one address (7.4). Because the factory itself is upgradeable, every limit an account relies on is hard-coded in the account implementation (maximum fee per plan, minimum notice, minimum rule gap) and the account clamps whatever the factory returns to those limits.

One contract per user is required here, unlike `ConfioMarketEscrow`, which deliberately uses one shared contract (`ConfioMarketEscrow.sol:17-21`): both routers deliver bought assets and sale proceeds to `msg.sender`, ownership must be transferable as a unit, and each user's assets sit at that user's own address (decision 19).

### 4.1 Roles

| Role | Who | How it is recognised |
|---|---|---|
| Owner | The user's personal wallet | `msg.sender == owner`. Under 7702 the delegate's `execute` calls the account as the EOA, so `msg.sender` is the EOA whether the transaction was sponsored or self-sent |
| Beneficiary | The registered beneficiary's personal wallet | `msg.sender == beneficiary` |
| Relayer | Confío's KMS sponsor | `CUSD_PLUS.isSponsor(msg.sender)` **and** `msg.sender == tx.origin`. The second condition matters: the sponsor set also contains contracts (the stock and swap routers are sponsors so they can mint to users), and a contract must never hold the relayer role on an account. Note that `CusdVault` keeps its own separate sponsor set, used by `mintWithFee` and `armReferral`; the relayer key must be in both |
| Anyone | Any address | No check |
| Safe | Confío Safe | Owner of the factory. Has no function on an account. It can change factory configuration and pause relayer functions (4.3) |

A call arriving through the owner's 7702 batch has `tx.origin` equal to the sponsor and `msg.sender` equal to the owner. It is an owner call, not a relayer call: roles are decided by `msg.sender` only.

### 4.2 Immutable configuration (account implementation)

`FACTORY`, `CUSD`, `CUSD_PLUS`, `STOCK_ROUTER`, `SWAP_ROUTER`, `FEE_COLLECTOR`, and one price-feed pair per crypto token the account can force-sell: `BTCB` with the Chainlink `BTC / USD` feed and `XAUT` with the Chainlink `XAU / USD` feed. These addresses are constants of the implementation, not entries in a Safe-maintained list: no one can repoint them, and adding a token means a new implementation version. The single exception is CONFIO, whose sale venue and price reference are set once later through the factory (section 5.5, decision 30). `USDT` and `CONFIO` token addresses are immutables too.

`FEE_COLLECTOR` follows `AccountActivationCollector`: no key, no owner, no upgrade path, anyone may sweep, only an immutable treasury receives. It must sweep two tokens (cUSD and cUSD+) rather than one, so it is a new contract of the same shape.

### 4.3 Factory state

| Variable | Type | Meaning |
|---|---|---|
| `accountOf` | `mapping(address => address)` | Owner wallet to their current account. One per owner. Moves to a new account only when the current one has been inherited (or is no longer owned by that wallet), through `createAccount` |
| `generationOf` | `mapping(address => uint64)` | Generation of `accountOf[owner]`: 0 for the first account, plus one for each account opened after the previous one was inherited. Part of the CREATE2 salt |
| `monthlyFeeUsd`, `annualFeeUsd` | `uint256` (18 decimals) | Current list prices. Changed only by `scheduleFee(plan, newFee, effectiveAt)`, Safe-only, with `effectiveAt` at least `FEE_CHANGE_DELAY` ahead, so every subscriber can be told before a renewal at the new price. Accounts clamp to their own hard-coded maximum |
| `allowedChallengeWindows` | `mapping(uint64 => bool)` | Selectable windows: 90, 180, 365 days |
| `claimCooldown` | `uint64` | Wait after a cancelled claim before the same beneficiary may claim again: 30 days |
| `forcedSaleNotice` | `uint64` | Minimum time between `startPaymentNotice` and `forcedSale`: 7 days, with hard-coded floor |
| `confioSale` | struct (venue, price reference) | Empty at launch. The Safe can set it once; after that it cannot be changed or cleared. Read only by `forcedSale` when `tokenIn` is CONFIO (section 5.5) |
| `isAccount` | `mapping(address => bool)` | True for every account this factory ever created, inherited ones included; never cleared. Read by `CusdVault.armReferral` (decision 32) |
| `FEE_CHANGE_DELAY` | constant | 30 days |
| `inheritanceEnabled` | `bool` | One-way switch, Safe-set. `setBeneficiary` reverts while false (rollout step 3) |
| `relayerPaused` | `bool` | Safe-set. Blocks relayer functions on every account. Never blocks owner, beneficiary or permissionless functions |
| `isCardSpender` | `mapping(address => bool)` | Card issuers' spenders allowed as a Card rule's payee (decision 35). Safe-set with `setCardSpender(spender, allowed)` (zero refused), at any time; a removal stops that spender's pulls on every account at once. Appended storage (slot 11) |
| `cardPaused` | `bool` | Safe-set with `setCardPaused`. Stops every card pull, and Card rule creation, on every account; nothing else. Appended storage (slot 12). Accounts read both through one view, `cardSpenderAllowed(spender) = isCardSpender[spender] && !cardPaused`; an unreadable factory fails closed for cards only |

Factory functions:

- `createAccount()`: the caller becomes the owner. With no account it deploys generation 0. It reverts with "account exists" while `accountOf[msg.sender]` is still the caller's (not `inherited` and `owner()` is the caller: never subscribed, active, cancel pending, expired, claim pending or executable). Once that account is inherited (or its `owner()` is someone else) it deploys a new clone at `generationOf[msg.sender] + 1`, increments `generationOf` and points `accountOf[msg.sender]` at the new account. Emits `AccountCreated(owner, account)` every time.
- `predictAddress(owner)` (view): where the owner's account is or will be. `accountOf[owner]` while it is still theirs; `predictAddressAt(owner, 0)` with no account; `predictAddressAt(owner, generationOf[owner] + 1)` once the current one is inherited. The backend signs a subscribe against exactly this address.
- `predictAddressAt(owner, generation)` (view): the CREATE2 address for salt `keccak256(abi.encode(owner, generation))`.
- The Safe-only setters for the variables above, `pause`/`unpause` of account creation.

An account snapshots its challenge window at the owner-signed designation; a later Safe change does not alter it. The fee is not snapshotted: each renewal charges the factory's price for the account's plan in force at that moment (decision 24), clamped to the account's hard-coded maximum.

### 4.4 Account state

| Variable | Type | Meaning |
|---|---|---|
| `owner` | `address` | Current owner wallet. Changes only in `executeClaim` |
| `inherited` | `bool` | Set once by `executeClaim`. Terminal |
| `plan` | `enum {None, Monthly, Annual}` | The plan of the current period. The period length is a constant of the plan (30 days, 365 days), not a separate stored value |
| `nextPlan` | `enum {None, Monthly, Annual}` | Set only by owner-signed `changePlan`. Applied at the next renewal |
| `feeUsd()` | view | Fee for the next charge: the factory's current price for the renewal plan (`nextPlan` when set, otherwise `plan`), clamped to `MAX_MONTHLY_FEE_USD` / `MAX_ANNUAL_FEE_USD` (constants in the implementation), 18 decimals. Not stored. Every use of the fee (the coverage check in `collectFee`, `startPaymentNotice` and `forcedSale`, the shortfall and its cap, and the amount collected) reads this one view, so they can never disagree about which plan is being renewed |
| `periodSeconds()` | view | 30 days for `Monthly`, 365 days for `Annual` |
| `paidUntil` | `uint64` | End of the paid period |
| `cancelRequested` | `bool` | Set by owner-signed `cancelSubscription` |
| `noticeStartedAt` | `uint64` | Non-zero while a payment notice runs for the current unpaid period |
| `forcedSaleForPeriod` | `uint64` | The old `paidUntil` of the unpaid period for which a forced sale succeeded. Because a successful sale also collects the fee and moves `paidUntil` on, this is a record and a second guard, not the only one |
| `pendingBeneficiary` | `address` | Named by the owner, not yet accepted. Cannot claim. Lapses 30 days after naming (`pendingBeneficiaryExpiresAt`): `acceptBeneficiary` reverts after that and the owner names again |
| `beneficiary` | `address` | Accepted beneficiary. Zero when none |
| `challengeWindow` | `uint64` | The accepted beneficiary's window |
| `pendingChallengeWindow` | `uint64` | Chosen by the owner when naming; becomes `challengeWindow` only when the named person accepts, so an unaccepted designation never changes the current beneficiary's window |
| `pendingBeneficiaryExpiresAt` | `uint64` | 30 days after naming |
| `claimStartedAt` | `uint64` | Non-zero while a claim is pending |
| `claimExecutableAt` | `uint64` | Set in `initiateClaim` to `block.timestamp + challengeWindow` as it stands then. Nothing changes it afterwards; a later change of window applies only to later claims |
| `claimCooldownUntil` | `uint64` | Earliest time the current beneficiary may claim again |
| `rules` | `mapping(uint256 => Rule)` | Automation rules |
| `nextRuleId` | `uint256` | |
| `confioSaleVenue`, `confioSalePriceRef` | `address` | Zero until latched from the factory, then fixed (section 5.5) |
| `subscriptionEpoch` | `uint64` | Zero until the first subscription. Every `subscribe` adds one (it is allowed only once the previous subscription has ended: `Unsubscribed` or `Expired`); renewals, fee collection, forced sales, `changePlan`, `cancelSubscription` and `undoCancel` never change it. A rule lives only in the epoch it was stored in, so a re-subscription never revives an ended subscription's rules (P3-1) |

`Rule { kind (Send, Payout, Buy, Card), tokenIn, tokenOut, payee, payoutRef, amount, frequency (Daily, Weekly, Biweekly, Monthly), nextRunAt, active, epoch }`. `epoch` is `subscriptionEpoch` when the rule was created or last updated. A rule runs (`executeRule`, `cardPull`) and can be updated or cancelled only while `active` and `epoch == subscriptionEpoch`; `rule(id)` reports `active` as that effective value, so a rule of an ended subscription reads inactive. `payoutRef` is the hash of the saved bank destination a `Payout` rule pays; the bank details themselves are never on-chain. `amount` is always in US dollars with 18 decimals, never in token units. When `tokenIn` is cUSD the token amount equals it. When `tokenIn` is cUSD+ the account converts at execution: shares = `ceil(amount * 1e18 / pPlus)` after `CUSD_PLUS.accrue()`, the same arithmetic as the fee (5.1), and that share count is the spending limit for the run. A rule therefore moves the same dollar value every time, whatever the share price. The contract enforces a minimum gap per frequency (1, 7, 14 and 28 days); the backend schedules on the calendar within that.

Card rules (decision 35) use the same struct. `payee` is the card issuer's spender (allowlisted in the factory), `tokenOut` and `payoutRef` are zero, `amountUsd` is the most the spender may take per period, gross of the exit fee, and `nextRunAt` is the start of the current period, which ends one minimum gap of `frequency` later. Periods are fixed from the first run: a pull after the period ended moves `nextRunAt` to the start of the period containing now (missed periods are skipped, nothing carries over) and resets the count. The count is `cardSpentUsd(id)`; once `block.timestamp >= nextRunAt + gap` it is stale and in effect zero. `updateRule` keeps the count and restarts the period at the update's first run, so an update never gives the spender more room than it had; `createRule` gives a new id a fresh count. A 28-day "monthly" card period is the contract's period; the app shows the reset date from `nextRunAt`.

### 4.5 Derived states

The account has three independent dimensions. The functions check them with internal views.

| Dimension | States | Definition |
|---|---|---|
| Lifecycle | `Unsubscribed` | `plan == None` |
| | `Active` | `plan != None`, not `inherited`, not `Expired` |
| | `CancelPending` | `Active` and `cancelRequested` and `block.timestamp < paidUntil` |
| | `Expired` (shown to users as "Returned" once emptied) | `cancelRequested` and `block.timestamp >= paidUntil` |
| | `Inherited` | `inherited == true` |
| Billing (only in `Active`) | `Current` | `block.timestamp < paidUntil` |
| | `PaymentDue` | `block.timestamp >= paidUntil` and not `cancelRequested`. Automation is paused |
| | `Notice` | `PaymentDue` and `noticeStartedAt != 0` |
| | `SaleAllowed` | `Notice` and `block.timestamp >= noticeStartedAt + forcedSaleNotice` |
| Claim | `NoClaim` | `claimStartedAt == 0` |
| | `ClaimPending` | `claimStartedAt != 0` |
| | `Executable` | `ClaimPending` and `block.timestamp >= claimExecutableAt` |

### 4.6 External functions

"Touch" means the function calls the internal `_ownerTouch()`, which cancels a pending claim (section 6.4). Every function with caller "Owner" touches.

**Owner (user-signed).**

| Function | Preconditions | Effect |
|---|---|---|
| `subscribe(plan, maxFeeUsd)` | `Unsubscribed` or `Expired`; not `inherited`; `feeUsd()` for `plan` `<= maxFeeUsd` | Sets `plan`; clears `nextPlan`; clears `cancelRequested`, `noticeStartedAt` and `forcedSaleForPeriod` (a notice from an earlier subscription must never count for a later one); adds one to `subscriptionEpoch`, which kills every rule of the ended subscription (Send, Payout, Buy and Card, with its old `cardSpentUsd`); clears the accepted beneficiary, `challengeWindow`, `claimCooldownUntil` and any pending designation, emitting `DesignationWithdrawn` / `BeneficiaryRemoved` when there was one (a new subscription needs a new designation and acceptance; a claim still pending on the `Expired` account has already been ended by the touch, with `ClaimCancelled`); takes the first fee (section 5.1) in the same call, reverting if dollars are short; sets `paidUntil` |
| `changePlan(plan)` | `Active`, `Current` | Sets `nextPlan`. `paidUntil` is unchanged. At the next renewal the fee collection charges the new plan's price and starts a period of the new plan's length (Annual to Monthly: US$14.99 for 30 days; Monthly to Annual: US$149.99 for 365 days), then sets `plan = nextPlan` |
| `cancelSubscription()` | `Active` | Sets `cancelRequested`. Automation keeps running until `paidUntil`. If the period has already ended unpaid (`PaymentDue`, `Notice`, `SaleAllowed`) the account is `Expired` at once: the return opens immediately and the lapsed period is not charged |
| `undoCancel()` | `CancelPending` | Clears `cancelRequested` |
| `withdraw(token, amount)` | Not `inherited` | Transfers to `owner` |
| `withdrawAll(tokens[])` | Not `inherited` | Transfers each full balance to `owner` |
| `trade(venue, data, tokenIn, tokenOut, maxIn, minOut)` | `Active`, `Current`; `venue` is `STOCK_ROUTER` or `SWAP_ROUTER`; `data` selector is one of the allowed buy/sell selectors; through `SWAP_ROUTER` the traded token must be one with a feed constant in the implementation (BTCB, XAUt), so the account never acquires through its own functions a token it could not sell for a fee. A catalog token listed later needs a new implementation version | Approves `tokenIn` to the venue for `maxIn`, calls it, resets the approval to zero, requires `tokenOut` balance to rise by at least `minOut` and `tokenIn` to fall by at most `maxIn` |
| `createRule(rule)`, `updateRule(id, rule)` | `Active`; not `inherited`; for `updateRule`, the rule is live (active and of the current epoch) | Stores the rule with the current `subscriptionEpoch` |
| `cancelRule(id)` | Not `inherited`; any other lifecycle and billing state (`Expired` and payment due included: stopping a rule is always safe); the rule is live | Sets `active = false` |
| `setBeneficiary(addr, window)` | `Active`; `factory.inheritanceEnabled`; a live factory approval for exactly this designation, `factory.designationApprovedUntil(this, keccak256(abi.encode(addr, window))) > now` (decision 26). The relayer records it with `factory.approveDesignation` after the server's identity and residence checks; it expires after one hour. (An audit showed a `tx.origin` sponsor check is not enough: it proves a sponsor started the transaction, not that the relay checked this designation; an owner could re-delegate their EOA between the relay's check and inclusion.); `addr` not zero, not `owner`, not `address(this)`; `factory.allowedChallengeWindows[window]` | Sets `pendingBeneficiary`, `pendingChallengeWindow`, `pendingBeneficiaryExpiresAt`. `window` must also be at least the account's hard-coded minimum (90 days), whatever the factory allows. The current accepted beneficiary, if any, stays until the new one accepts |
| `removeBeneficiary()` | Not `inherited`. No sponsor gate: the owner can always remove | Clears `pendingBeneficiary`, `pendingChallengeWindow`, `pendingBeneficiaryExpiresAt`, `beneficiary`, `challengeWindow`, `claimCooldownUntil` |
| `withdrawDesignation()` | Not `inherited`; `pendingBeneficiary` set | Clears only `pendingBeneficiary`, `pendingChallengeWindow` and `pendingBeneficiaryExpiresAt`. The accepted beneficiary, their window and their cooldown are untouched. (Like every owner function it cancels a pending claim with cooldown.) |
| `cancelClaim()` | Not `inherited` | Explicit touch. Succeeds (no-op) when no claim is pending so that it can be appended to any batch |

After `executeClaim`, the owner functions that remain are the inherited forms only:

| Function | Preconditions | Effect |
|---|---|---|
| `withdraw(token, amount, to)` | `inherited`; `to == owner`, or `to` is a clone of the account implementation (its code hash), reports `owner() == owner` and is not itself `inherited` (an account the caller once opened may since have passed to someone else). In practice that is `FACTORY.accountOf(owner)` | Transfers |
| `withdrawAll(tokens[], to)` | Same | Transfers each full balance |

**Beneficiary.**

| Function | Preconditions | Effect |
|---|---|---|
| `acceptBeneficiary()` | `msg.sender == pendingBeneficiary`; a live factory approval `factory.acceptanceApprovedUntil(this, msg.sender) > now`, recorded by the relayer after re-running the checks; `Active`; not `inherited` | Requires `block.timestamp < pendingBeneficiaryExpiresAt`. Moves `pendingBeneficiary` to `beneficiary` and `pendingChallengeWindow` to `challengeWindow`; if the accepted address changes, clears `claimCooldownUntil` and, if the replaced beneficiary had started a claim after the naming, ends that claim and emits `ClaimCancelled` for it (the owner chose this replacement by signing `setBeneficiary`; the acceptance only completes it); if the owner re-named the same person (to change the window), the cooldown is kept, so re-designation can never shorten it; emits `BeneficiaryAccepted` |
| `initiateClaim()` | `msg.sender == beneficiary`; `Active` (including `CancelPending` and any billing state); `NoClaim`; `block.timestamp >= claimCooldownUntil`. No sponsor gate (decision 9) | Sets `claimStartedAt` and `claimExecutableAt`; emits `ClaimInitiated` with that execution time, which is final for this claim |
| `executeClaim()` | `msg.sender == beneficiary`; `Executable`; lifecycle not `Expired`. No sponsor gate | Section 6.5 |

**Relayer.** All five revert when `inherited`, when `factory.relayerPaused`, and when the lifecycle is not `Active`. None of them touches.

| Function | Preconditions | Effect |
|---|---|---|
| `collectFee()` | `PaymentDue` (so `block.timestamp >= paidUntil`); cUSD plus cUSD+ cover `feeUsd()` | Section 5.1. If `nextPlan` is set, charges and renews on that plan and makes it the current one (this is the owner's signed instruction taking effect, not a relayer choice). Sets `paidUntil = block.timestamp + periodSeconds()` of the plan charged; clears `noticeStartedAt` |
| `startPaymentNotice()` | `PaymentDue`; dollars do not cover `feeUsd`, and neither do dollars plus the account's USDT net of cUSD's entry fee (`usdt * (10000 - feeBps) / 10000 >= feeUsd - dollars` reverts: the relayer runs `convertUsdt` first; USDT short of the gap, dust, does not block); `noticeStartedAt == 0` | Sets `noticeStartedAt`; emits `PaymentNoticeStarted` |
| `forcedSale(legs[], minDollarsOut, referrer, shareBps)` where each leg is `(venue, data, tokenIn, maxIn)` | `SaleAllowed`; `forcedSaleForPeriod != paidUntil`; every leg's `tokenIn` is not cUSD or cUSD+ and has a price reference (a listed stock via its Ondo quote, BTCB, XAUt, or CONFIO once switched on); dollars do not cover `feeUsd()`, and neither do dollars plus the USDT net of the entry fee (same test as `startPaymentNotice`) | Section 5.3. One atomic operation: runs the legs in order (several are needed when no single holding covers the fee, for example two positions each smaller than an annual fee), then collects the fee in the same transaction. The notice, the proceeds cap and the one-per-period rule apply once to the whole operation, and the price check applies to each leg. If the dollars still do not cover the fee the whole call reverts, so nothing is sold without the fee being paid by it. On success sets `forcedSaleForPeriod` to the `paidUntil` value read at the start of the call (the period that was unpaid, not the new one), advances `paidUntil` and clears `noticeStartedAt` exactly as `collectFee` does, so the next missed payment needs a fresh notice |
| `executeRule(id, data, referrer, shareBps)` (the per-run `minOut` is inside `data`; see the interface file) | `Active` (including `CancelPending`), `Current`; rule active and of the current `subscriptionEpoch`; `block.timestamp >= rule.nextRunAt` | Runs the rule (4.7); sets `nextRunAt = block.timestamp + minimum gap of the rule's frequency` (missed runs are not caught up). Runs whether or not a claim is pending (decision 25) |
| `convertUsdt(dest, minDollarsOut, referrer, shareBps)` | Not `inherited`; lifecycle `Active` (any billing state, so a deposit of USDT can cure a missed payment); USDT balance above zero; `dest` is cUSD+ or cUSD | Converts the whole USDT balance through the normal entry, paying the 0.9% entry fee as any deposit does: `CUSD.mintWithFee(usdt, minDollarsOut, address(this))`, or `CUSD_PLUS.subscribeAndMint(usdt, 0, address(this))`. The vault's own floor argument is in USDY units, so it is passed as zero (as both routers do) and the account enforces the floor itself: the dollar value received (cUSD at par; cUSD+ shares gained times `pPlus`) must be at least `minDollarsOut`, and `minDollarsOut` must be no lower than the USDT amount less the live fee and a small tolerance. Recipient is fixed to the account. The relayer picks `dest` from the owner's eligibility, as the server does for the personal wallet. Emits `UsdtConverted` |

**Card spender (decision 35).**

| Function | Preconditions | Effect |
|---|---|---|
| `cardPull(ruleId, usdtOut)` | Rule active, of the current `subscriptionEpoch` and of kind `Card`; `msg.sender == rule.payee`; lifecycle `Active` (including `CancelPending`) and billing `Current`, as `executeRule`; `factory.cardSpenderAllowed(msg.sender)` (read on every pull); `usdtOut > 0`; `block.timestamp >=` the first period's start; gross plus what was already taken in this period `<= amountUsd`. Claim state does not matter (decision 25). `factory.relayerPaused` does not apply. Not callable by the relayer: `executeRule` on a Card rule reverts | `gross = ceil(usdtOut * 10000 / (10000 - feeBps))`, the smallest gross whose net after cUSD's ceil-rounded fee is exactly `usdtOut`. The count is updated before any token moves (nonReentrant as well). cUSD: `CUSD.redeemWithFee(gross, usdtOut, account)`. cUSD+: `CUSD_PLUS.redeemToUsdt(ceil((gross + gross * 5 / 10000 + 10) / pPlus) shares, usdtOut, account)`, because `unwrapToCusd` (the Payout path) is sponsor-gated and a spender's transaction has no sponsor as origin; `redeemToUsdt` is cUSD+'s own exit through the same 0.9% fee. The account's USDT must have risen by at least `usdtOut`, exactly `usdtOut` is transferred to the spender and the spender's USDT must rise by exactly that. The cUSD+ excess (about 5 bps of the pull) stays as USDT and is converted by `convertUsdt` like any USDT (it pays the entry fee on that dust: about 0.9% of 5 bps). USDT the account already held is never used. No allowance is given. Emits `CardPulled(id, spender, usdtOut, gross)`. Pays no subscription fee |

**Anyone.**

| Function | Preconditions | Effect |
|---|---|---|
| `returnAsset(token)` | `Expired`; not `inherited` | Transfers the full balance of `token` to `owner`. A failing token reverts only its own call |
| `latchConfioSale()` | Not `inherited`; `factory.confioSale` non-empty; not yet latched | Copies the venue and price reference into the account's own storage (`confioSaleVenue`, `confioSalePriceRef`); emits `ConfioSaleLatched`. Moves nothing. Reverts on an inherited account, which never sells |
| Views | — | `status()`, `billingStatus()`, `claimStatus()`, `claimExecutableAt()`, `feeUsd()`, `dollarsUsd()`, `rule(id)` (with `epoch`; `active` is effective), `cardSpentUsd(id)`, `subscriptionEpoch()` |

### 4.7 Rule execution

| Kind | What the relayer may do | Enforced on-chain |
|---|---|---|
| `Send` | Deliver `amount` dollars from `tokenIn` (cUSD or cUSD+) to `payee`, in the payee's own dollar. The existing send flow already follows this rule (`send/bsc_flow.py`: eligible recipients receive cUSD+, ineligible ones cUSD through the fee-free wrap/unwrap). The relayer passes which dollar the payee holds; the account then either transfers `tokenIn` in kind, or calls `CUSD_PLUS.unwrapToCusd(shares, minOut, payee)` / `CUSD_PLUS.wrapCusd(cusd, minOut, payee)` so the converted dollar is minted straight to the payee. The account itself never ends up holding the other dollar, so decision 17 stands | `payee`, `tokenIn`, `amount` and `frequency` come from the stored rule (decision 16). The relayer chooses only the delivery form; the recipient of every form is the stored `payee`, the conversion is the vault's fee-free one, and `tokenIn` falls by at most the token equivalent of `amount` |
| `Payout` | Exit up to `amount` dollars' worth of `tokenIn` to USDT with the USDT sent to the address the relayer names for this run; the bridge and the provider then pay the destination behind `payoutRef` (CLABE, Pix, Bre-B, Venezuelan Pago Móvil). cUSD exits through `CUSD.redeemWithFee(amount, minUsdtOut, destination)` (the normal 0.9% exit fee; `minUsdtOut` is a floor). cUSD+ exits through the fee-free `CUSD_PLUS.unwrapToCusd` of `ceil((grossCusd + grossCusd * 5 / 10000) / pPlus)` shares (capped at the run's share limit) and then `CUSD.redeemWithFee(grossCusd, usdtOut, destination)` with an **exact** `usdtOut = grossCusd - CusdVault.feeFor(grossCusd)`: one wei under and the account refuses, one over and the vault does. The exact amount lets a fixed-amount bridge order (Pago Móvil) take a cUSD+ run like a cUSD one. The backend keeps `grossCusd + grossCusd * 5 / 10000 <= amount`, so the unwrap never reaches the share limit wherever pPlus lands, and picks the smallest `grossCusd` whose net equals the target USDT (the largest allowed net floored to six decimals). The unwrap margin left over stays as cUSD dust (decision 17) | `tokenIn`, `amount`, `frequency` and `payoutRef` come from the stored rule; `tokenIn` falls by at most the token equivalent of `amount`; at most one run per minimum gap; the event carries `payoutRef` and the destination. The destination address itself is **not** bound: it is a bridge deposit address created per transfer (section 9.2, C7). There is no allowlist |
| `Buy` | Spend up to `amount` dollars' worth of `tokenIn` on `tokenOut`: a stock through `STOCK_ROUTER.buyWithSavings`, which takes cUSD+ only, or bitcoin or gold (the tokens with a feed constant, nothing else) through `SWAP_ROUTER.buy`, which takes cUSD+ or cUSD | Venue and selector fixed; `tokenIn` falls by at most the token equivalent of `amount`; `tokenOut` rises by at least the relayer-supplied `minOut` and by more than zero; no other token balance passed in the check list falls. Worst case per run is the rule's `amount` |

| `Card` | Nothing: the relayer cannot run it (`executeRule` reverts `BadRule`). The allowlisted spender pulls (4.6, decision 35) | Spender, dollar, cap and period come from the stored rule; the factory allowlist and card pause are read on every pull; exact USDT pushed in the call; gross per fixed period at most `amountUsd` |

There is no saving rule and no conversion function (decision 17).

`executeRule` `data` by rule kind (`IConfioSmartAccount.executeRule`):

| Kind | `data` |
|---|---|
| `Send` | `abi.encode(uint8 payeeDollar, uint256 minOut)` |
| `Payout`, cUSD rule | `abi.encode(address destination, uint256 minUsdtOut)`; `minUsdtOut` is a floor |
| `Payout`, cUSD+ rule | `abi.encode(address destination, uint256 usdtOut, uint256 grossCusd)`; `0 < grossCusd <= amount`, `usdtOut == grossCusd - CusdVault.feeFor(grossCusd)` exactly. The two-word form reverts on a cUSD+ rule |
| `Buy` | `abi.encode(address venue, bytes venueCalldata, uint256 minOut)` |

`Buy` through the stock router needs an Ondo-signed quote in `data`; the relayer obtains it (section 7.5).

### 4.8 Events

`Subscribed(plan, feeUsd, paidUntil)` (every one starts a new `subscriptionEpoch`: the backend marks all earlier rules inactive and the beneficiary and designation cleared), `PlanChanged`, `SubscriptionCancelled(paidUntil)`, `CancelUndone`, `FeeCollected(cusdAmount, cusdPlusShares, pPlus, paidUntil)`, `PaymentNoticeStarted(saleAllowedAt)`, `ForcedSale(tokenIn, amountIn, dollarsOut, forPeriod)` (emitted once per leg of the operation), `Withdrawn(token, to, amount)`, `AssetReturned(token, amount)`, `Traded(venue, tokenIn, tokenOut, amountIn, amountOut)`, `RuleCreated`, `RuleUpdated`, `RuleCancelled`, `RuleExecuted(id, tokenIn, tokenOut, amountIn, amountOut)`, `UsdtConverted(dest, usdtIn, dollarsOut)`, `PayoutSent(id, payoutRef, destination, tokenIn, amountIn, usdtOut)`, `BeneficiaryNamed(pendingBeneficiary, challengeWindow)`, `BeneficiaryAccepted(beneficiary)`, `BeneficiaryRemoved`, `ConfioSaleLatched(venue, priceRef)`, `ClaimInitiated(beneficiary, executableAt)`, `ClaimCancelled(beneficiary, cooldownUntil)`, `ClaimExecuted(previousOwner, newOwner)`, `CardPulled(id, spender, usdtOut, usdSpent)` (decision 35; `usdSpent` is the gross counted against the cap).

Factory: `AccountCreated(owner, account)`, and one event per setter (`CardSpenderSet(spender, allowed)` and `CardPausedSet(paused)` for decision 35).

Every state change in the tables above emits at least one of these (an owner call that also cancels a pending claim emits `ClaimCancelled` as well). The backend reconciles from events and never from its own writes (section 7.6).

### 4.9 State machine

Who may trigger each transition: **U** user-signed (owner), **B** beneficiary-signed, **R** relayer-only, **P** permissionless, **T** time passing (no transaction).

Lifecycle:

```
Unsubscribed --subscribe (U)--> Active
Active --cancelSubscription (U)--> CancelPending
Active with payment due (PaymentDue, Notice, SaleAllowed) --cancelSubscription (U)--> Expired, immediately
CancelPending --undoCancel (U)--> Active
CancelPending --paidUntil reached (T)--> Expired
Expired --returnAsset per token (P)--> Expired (emptied = "Returned")
Expired --subscribe (U)--> Active
Active or CancelPending --executeClaim (B)--> Inherited   [terminal]
```

Claim:

```
no beneficiary --setBeneficiary (U, relay-originated only)--> pending acceptance
pending acceptance --acceptBeneficiary (B, relay-originated only)--> beneficiary set (NoClaim)
ClaimPending by the old beneficiary --a different named person accepts (B, relay-originated only)--> NoClaim for the new beneficiary; ClaimCancelled emitted for the old one
ClaimPending --the same person accepts a re-designation--> ClaimPending, execution time unchanged
pending acceptance --withdrawDesignation (U)--> as before the naming (the accepted beneficiary, if any, stays)
pending acceptance --removeBeneficiary (U)--> no beneficiary at all, accepted one included
NoClaim --initiateClaim (B)--> ClaimPending
ClaimPending --any owner function, or cancelClaim (U)--> NoClaim + cooldown   ("Cancelled")
ClaimPending --removeBeneficiary (U)--> NoClaim, no beneficiary
ClaimPending --challengeWindow elapsed (T)--> Executable
Executable --any owner function (U)--> NoClaim + cooldown
Executable --executeClaim (B)--> Inherited (withdraw-only)
ClaimPending or Executable --lifecycle reaches Expired (T)--> claim cannot execute (see C6)
```

The claim dimension does not affect the other two: fees, notices, forced sales and rules run the same with or without a pending claim (decision 25).

Billing (inside `Active`; in `CancelPending` the period is already paid and no further fee falls due):

```
Current --paidUntil reached (T)--> PaymentDue            [automation paused]
PaymentDue --collectFee (R), dollars cover--> Current
PaymentDue --startPaymentNotice (R), dollars short--> Notice
Notice --owner adds dollars, then collectFee (R)--> Current
Notice --forcedSaleNotice elapsed (T)--> SaleAllowed
SaleAllowed --forcedSale succeeds (R): sells and collects in one transaction--> Current
SaleAllowed --forcedSale reverts--> SaleAllowed            [retry; nothing returned]
SaleAllowed --nothing sellable--> SaleAllowed              [stays paused; nothing returned]
```

No transition out of `PaymentDue`, `Notice` or `SaleAllowed` returns assets to the owner. Only `Expired`, which requires the owner-signed `cancelSubscription`, opens `returnAsset`.

### 4.10 Invariants

Each is a testable statement. Section 10.2 maps them to tests.

1. A token balance of the account decreases only through: a transfer to `owner`; a transfer to `FEE_COLLECTOR` inside `collectFee`, `subscribe` or `forcedSale`; a transfer to a `Send` rule's stored `payee` inside `executeRule`, or a burn by `CUSD_PLUS.unwrapToCusd` / a pull by `CUSD_PLUS.wrapCusd` in that rule whose minted dollar goes to the same stored `payee`; a burn by `CUSD.redeemWithFee` (after, for cUSD+, a burn by `CUSD_PLUS.unwrapToCusd` minting cUSD back to the account) inside a `Payout` rule, limited to the rule's stored amount and frequency, whose USDT goes to the address the relayer names for that run (the one exit whose destination the contract does not fix; C7); a pull by `STOCK_ROUTER` or `SWAP_ROUTER` inside `trade`, `executeRule` or `forcedSale`; a pull of CONFIO by the `confioSale` venue inside `forcedSale`, once that venue is set; a pull of USDT by `CUSD_PLUS` or `CUSD` inside `convertUsdt`, which mints the owner's dollar back to the account; inside `cardPull` (decision 35), a burn by `CUSD.redeemWithFee` or `CUSD_PLUS.redeemToUsdt` to USDT paid to the account, and a transfer of exactly the requested USDT to the Card rule's stored, allowlisted `payee`, the caller. In `Inherited` state only: a transfer to `owner` or to a clone of the account implementation (same code hash) that `owner` owns and that is not inherited (in practice `FACTORY.accountOf(owner)`).
2. `owner` changes only in `executeClaim`, and only to the `beneficiary` stored at that moment.
3. `collectFee` succeeds at most once for any value of `paidUntil`, and each success moves `paidUntil` forward by exactly the period length of the plan charged, from the block time. The total collected by one success never exceeds `feeUsd()` in value (cUSD at par, cUSD+ at `pPlus`, rounding up by at most one share unit), and `feeUsd()` never exceeds the implementation's hard-coded maximum for the plan whatever the factory returns.
4. The relayer cannot change the fee, `plan` (it changes only to the `nextPlan` the owner signed, at renewal), `nextPlan`, `owner`, `pendingBeneficiary`, `beneficiary`, `challengeWindow` or any rule field other than `nextRunAt`, which `executeRule` advances. A card spender can change only its own rule's `nextRunAt` (to the start of the current period) and `cardSpentUsd`. The price changes only through the factory's delayed `scheduleFee`, which is Safe-only. The 30-day delay lives in the factory, which the Safe can upgrade; what the account itself enforces is the hard-coded maximum per plan. An upgraded factory could raise a renewal to that maximum without notice.
5. `forcedSale` (one atomic operation of one or more sale legs) succeeds at most once per unpaid period, only after `forcedSaleNotice` has elapsed since an on-chain `startPaymentNotice` for that period, and only while cUSD plus cUSD+ do not cover `feeUsd`.
6. After `forcedSale`, the gross proceeds (the rise in the account's cUSD plus cUSD+ value measured before the fee is taken in the same call) are at least the shortfall and no more than the cap in section 5.3; the fee is collected in that call; each sold token's balance fell by at most its leg's `maxIn`; no other checked balance fell; no token left to any address other than the venue and, for the fee, `FEE_COLLECTOR`.
7. `returnAsset` reverts unless `cancelRequested` is true and `block.timestamp >= paidUntil`. Its only destination is `owner`.
8. No relayer function, no permissionless function and no card pull changes `claimStartedAt`, `claimCooldownUntil` or `beneficiary`.
9. Every owner function sets `claimStartedAt` to zero. If a claim was pending, it also sets `claimCooldownUntil = block.timestamp + claimCooldown`, except `removeBeneficiary`, and `subscribe` after an ended subscription, which end the designation and clear the cooldown with it. `claimCooldown` is read from the factory and clamped to hard-coded bounds in the account (1 to 90 days), and a failing factory read falls back to 30 days, so no factory value can remove the cooldown or make an owner call revert.
10. `executeClaim` reverts before `claimExecutableAt`, the time fixed and announced when the claim was initiated (no later call, including an acceptance that changes the window, can move it), reverts for any caller other than `beneficiary`, and reverts if `claimStartedAt == 0`.
11. `initiateClaim` reverts while `block.timestamp < claimCooldownUntil`.
12. After `executeClaim`: `plan == None`, `beneficiary == 0`, `pendingBeneficiary == 0`, `claimStartedAt == 0`, no rule executable and no card pull possible, and every relayer function, `cardPull`, `subscribe`, `setBeneficiary`, `acceptBeneficiary`, `createRule` and `trade` revert forever.
13. After `executeClaim` the previous owner address has no function it can call successfully other than views.
14. The account never holds a non-zero allowance to any address at the end of a transaction.
15. `factory.relayerPaused` blocks only relayer functions (not `cardPull`; `factory.cardPaused` and the spender allowlist block only `cardPull` and Card rule creation). `withdraw`, `withdrawAll`, `cancelSubscription`, `returnAsset`, `cancelClaim`, `removeBeneficiary`, `initiateClaim` and `executeClaim` work while it is set.
16. The Safe has no function that moves an account's assets, changes its `owner` or changes its `beneficiary`. The one indirect power is `confioSale`: until an account has latched it (5.5) the Safe decides which venue and price reference that account will use for CONFIO forced sales; after the latch it cannot. The card allowlist (decision 35) only withholds: the Safe can stop a spender or all cards, but a pull still needs a Card rule the owner signed naming that spender, and its cap and period are the owner's.
17. `factory.accountOf[owner]` names at most one current account per owner. It is overwritten only by `createAccount` from that owner, and only when the account it names is `inherited` or no longer owned by that owner; the new account is at the next generation. `isAccount` stays true for every account ever created. This holds per factory; a later version is a separate factory.
18. `setBeneficiary` and `acceptBeneficiary` revert unless the factory holds a live (under one hour old) relayer approval for exactly that designation or acceptance. A transaction the relay did not approve, self-sent or forwarded, cannot create or accept a designation.
19. `initiateClaim` and `executeClaim` succeed only for the accepted `beneficiary`. A `pendingBeneficiary` who is not also the current accepted beneficiary cannot claim. When the owner re-names the current beneficiary, that person keeps their standing and their cooldown; only the window changes, on acceptance.
20. The implementation has no function that changes code and contains no `DELEGATECALL`, `CALLCODE` or `SELFDESTRUCT`; each account's runtime code is exactly the EIP-1167 pattern pointing at that implementation (the clone's one fixed `DELEGATECALL`). The account has and no dependency on the factory for moving assets to `owner`: `withdraw`, `withdrawAll`, `returnAsset` and the claim functions succeed even if every factory call reverts (factory reads used by them are wrapped and fall back to the hard-coded limits).

21. A Card rule never moves more than its `amountUsd` (gross: USDT delivered plus cUSD's exit fee) in any of its fixed periods, across any number of pulls, in one transaction or several, re-entrant or not. Each successful pull delivers exactly the requested USDT to the stored spender and only while that spender is allowlisted and cards are not paused.

22. `subscriptionEpoch` changes only in `subscribe` (from `Unsubscribed` or `Expired`), by one. No rule stored under an earlier epoch is executed, pulled or updated again, and no beneficiary or designation survives into a new epoch.

What the invariants do not cover: the Safe can upgrade `ConfioStockRouter`, `ConfioSwapRouter`, `CusdVault` and `CusdPlusVault`, can pause them and can freeze addresses. Those powers predate this feature. The limits above bound the relayer key, not the Safe.

---

## 5. Billing

### 5.1 Fee source order

`collectFee` (and the first charge inside `subscribe`) does, in order:

1. Take `min(feeUsd, cUSD balance)` in cUSD, transferred to `FEE_COLLECTOR`.
2. If a remainder `r` is left, call `CUSD_PLUS.accrue()` (ignoring a revert), read `pPlus`, and transfer `ceil(r * 1e18 / pPlus)` cUSD+ shares to `FEE_COLLECTOR`.
3. If the shares needed exceed the balance, revert. Nothing is taken partially.

The shares are transferred, not redeemed: the account needs no conversion call (moving between cUSD and cUSD+ is free anyway, but `unwrapToCusd` is sponsor-gated and would add a dependency). The user pays no fee on the subscription fee beyond the fee itself. The collector sends what it receives to the Safe, which converts cUSD+ on Confío's side when it wants.

In practice a user holds only one of the two dollars (decision 17), so one of the two steps does all the work; the order matters only if an account ever holds both.

Units: the fee, cUSD and cUSD+ are treated as 18-decimal; `pPlus` is the USD value of one share in 18 decimals (`CusdPlusVault.pPlus`, used as `shares = usdValue / pPlus` in `_mintAgainstUsdy`). The contract tests must assert the decimals of both tokens rather than assume them.

### 5.2 Payment failure

When the period ends and dollars do not cover the fee:

1. Automation stops (`executeRule` requires `Current`). `trade` also stops. `withdraw`, deposits by plain transfer, and all inheritance functions keep working.
2. The backend notifies the owner (section 7.7) and calls `startPaymentNotice`.
3. If the owner adds dollars, `collectFee` succeeds and the account is `Current` again. The new period starts at the payment time; lapsed days are not charged.
4. If not, after `forcedSaleNotice` the relayer may run one forced sale (5.3), which also collects the fee in the same transaction.
5. If the sale fails or nothing can be sold, the account stays paused and the backend retries on a schedule. Assets are never returned (decision 7).

An account whose total assets are worth less than one fee stays in `SaleAllowed` indefinitely with its beneficiary still registered. In assets the contract can sell, the value that can sit in that state is less than one period's fee. Assets it cannot sell are not bounded this way: CONFIO until 5.5 is switched on, a token Confío does not handle, or a stock whose sale keeps failing (halted, no quote). Such an account pays nothing while it stays that way and keeps its beneficiary.

### 5.3 Forced sale rules and on-chain caps

| Rule | Where enforced |
|---|---|
| Only when cUSD plus cUSD+ do not cover the fee | Contract |
| Only after `forcedSaleNotice` since `startPaymentNotice` for this period | Contract |
| At most one successful sale operation per unpaid period. An operation may have several legs, because the fee can exceed any single holding; the legs together obey one cap | Contract (`forcedSaleForPeriod`) |
| Venue is `STOCK_ROUTER.sellToSavings` (proceeds always in cUSD+; the stock router has no cUSD leg) or `SWAP_ROUTER.sell` (proceeds in cUSD+ or cUSD), or for CONFIO the `confioSale` venue once set (5.5). Nothing else | Contract (address and selector) |
| Proceeds land in the account | Structural: both functions pay `msg.sender`, which is the account. The contract also asserts its own dollar balance delta |
| Proceeds are at least the shortfall and at most `shortfall * (1 + FORCED_SALE_MARGIN) + FORCED_SALE_ROUNDING` | Contract. Margin 5%, rounding US$1. The margin exists because the 0.9% entry fee is taken from the proceeds and stock notional rounds |
| Amount of the asset sold is consistent with a reference price | Contract. Stocks: the Ondo-signed quote (the router takes price and quantity from it). Bitcoin and gold: the Chainlink feed fixed in the implementation; the sale reverts if the feed is older than its maximum age or if dollars received per unit sold are more than the tolerance below the feed price after the 0.9% entry fee. A reverted sale is retried later like any failed sale |
| Which asset is sold first when several are held | Backend picks the largest position by dollar value first. CONFIO joins that order once its sale is switched on (5.5) |
| Several days of notices before the sale | On-chain minimum (`forcedSaleNotice`) plus backend notifications (7.7) |

The sale pays the normal 0.9% entry fee when proceeds re-enter cUSD+ or cUSD (decision 3). Ondo's minimum order is about US$0.98. A sale covers the shortfall, which can be smaller than that when the account holds some dollars; the US$1 rounding allowance in the cap is what lets such a sale meet the minimum.

### 5.4 Annual plan

`plan = Annual`, fee `annualFeeUsd` (US$149.99), period 365 days. One charge at subscribe and one per year. The failure path is identical. The annual plan is the preselected one on the sign-up screen (decision 2).

No refunds (decision 22). A cancelled plan, monthly or annual, runs to `paidUntil` and then returns the assets. There is no refund function.

Price changes (decision 24): the Safe schedules a new price in the factory at least `FEE_CHANGE_DELAY` ahead. Each account pays the price in force at its own next renewal. A monthly subscriber sees it within a month; an annual subscriber at the next anniversary. The backend notifies every subscriber when a change is scheduled and again before their renewal. The first charge is protected by `maxFeeUsd` in the signed `subscribe`; later charges are bounded by the hard-coded maximum in the account.

### 5.5 CONFIO as a fee source (switched on later)

Decision 30 makes unlocked CONFIO a fee source, and decision 23 makes accounts immutable. CONFIO has no DEX market and no price reference today, so v1 ships with CONFIO sales off. To switch them on later without replacing accounts, the implementation carries one extension point, limited to CONFIO:

- The factory holds `confioSale`: a sale venue and a price reference for CONFIO, empty at launch.
- Each account copies the venue and the price reference into its own storage the first time it reads a non-empty value (`latchConfioSale()`, callable by anyone, also run inside `forcedSale`), and never reads the factory for them again. From that moment the values are as fixed as the account's code. Before that moment they are only as fixed as the factory, which the Safe can upgrade; that is stated here rather than hidden. The backend latches every account as soon as the slot is set.
- The Safe can set it once. After it is set it cannot be changed or cleared. Until it is set, `forcedSale` with `tokenIn = CONFIO` reverts.
- The account applies to a CONFIO sale every rule of section 5.3 unchanged: one sale per unpaid period, after the notice, for one fee, proceeds only into the account, amount checked against the price reference.
- Nothing else in the account reads this slot. It cannot add any other token, change a destination or change a fee.

Confirmed by the founder on 2026-11-20. This is the only place where an existing account's behaviour depends on a value set after it was created. The alternative, a new implementation that owners move to by signing, was not used here because an owner who has died cannot sign, and those are the accounts a later CONFIO sale matters for.

Until CONFIO sales are switched on, an account holding only CONFIO cannot pay, stays paused, and keeps its beneficiary. That gap closes when the slot is set.

---

## 6. Inheritance

### 6.1 Designation

Two steps: the owner names, the beneficiary accepts. Before each, the relayer records a one-hour approval for exactly that step in the factory, and the contract refuses the step without it (decision 26, invariant 18).

Step 1, owner-signed `setBeneficiary(addr, window)`. The backend prepares and relays the call only after these checks pass, all at designation time:

| Check | Source |
|---|---|
| The beneficiary is a Confío user with a personal account and a BSC address | `users.Account` |
| The beneficiary's identity is verified | `security.identity_status.is_identity_verified` |
| The beneficiary is not a US resident | The Ondo policy used for cUSD+ (`cusd_plus/eligibility.py`) |
| The beneficiary is not the owner and not an account under an identity hold | Existing identity-reuse checks |
| `factory.inheritanceEnabled` | Chain |
| The owner has seen and accepted the residual-risk disclosure (8.3) | `SmartAccountBeneficiary.disclosure_accepted_at` |

The server records `designated_at`. The named person is notified (push and in-app) that they were named, by whom, and the challenge window, and is asked to accept.

Step 2, beneficiary-signed `acceptBeneficiary()`. The backend re-runs the identity and residence checks at acceptance, relays the call, and records `accepted_at` (the block time of `BeneficiaryAccepted`) next to `designated_at`. Only after acceptance can the beneficiary claim. The acceptance screen shows the account address and chain; that is the beneficiary's record for the direct path (6.7). A designation that is not accepted has no effect and the owner sees it as pending; the owner can withdraw it with `withdrawDesignation`, which leaves the current accepted beneficiary in place; `removeBeneficiary` is different and removes the accepted beneficiary as well. The previous accepted beneficiary, if there was one, stays in place until the new one accepts.

The contract cannot verify KYC or residence. It does not need to: it refuses any designation or acceptance that Confío's relay did not originate, and the relay originates one only after the checks above. `removeBeneficiary`, `cancelClaim`, `initiateClaim` and `executeClaim` carry no such gate.

If the beneficiary's registered wallet address changes after designation (account migration, re-keying), the backend notifies the owner that the designation points at the old address and must be signed again.

### 6.2 Claim

The beneficiary calls `initiateClaim()`. Normally the Confío app builds a sponsored batch from the beneficiary's wallet. It also works as a direct transaction (6.7).

The backend sees `ClaimInitiated` and starts the owner notification schedule (7.7). Notices go out for the whole window through every channel the owner has.

### 6.3 Challenge window

Chosen by the owner at designation from the factory's allowed set. Default 180 days; options 90, 180 and 365 days. There is no heartbeat and no periodic check-in. Nothing Confío does extends or shortens the window.

During the window the account behaves normally: fees are collected, rules run, forced sales happen (decision 25). Nothing is paused because a claim is pending.

### 6.4 Cancellation and cooldown

- Any owner-signed function on the account cancels a pending claim (`_ownerTouch`). Precisely: the contract sees only calls made to it. Activity elsewhere cancels a claim only through the next bullet; a self-sent transaction to another contract, a business-account batch or an off-chain action does not.
- While a claim is pending, the backend appends `account.cancelClaim()` to every sponsored batch the owner signs for any purpose from the personal wallet (a send, a payment, a trade). The owner's signature covers the call list, so this is an owner-signed transaction as decision 9 requires. The app tells the owner it is doing so.
- `collectFee`, `startPaymentNotice`, `forcedSale`, `executeRule`, `convertUsdt` and `returnAsset` do not cancel a claim. They are not owner-signed.
- A cancel sets `claimCooldownUntil`. The same beneficiary cannot call `initiateClaim` before it. Length: 30 days.
- `removeBeneficiary()` ends the designation and any pending claim.
- `setBeneficiary` with a new address (being an owner function) cancels any pending claim. The new person replaces the old one when they accept.

### 6.5 Execution and reset

`executeClaim()`, beneficiary only, after the window. In one transaction:

| Field | After execution |
|---|---|
| `owner` | The beneficiary's address |
| `inherited` | `true` |
| `plan`, `nextPlan`, `paidUntil` | Cleared |
| `cancelRequested`, `noticeStartedAt`, `forcedSaleForPeriod` | Cleared |
| `beneficiary`, `pendingBeneficiary`, `challengeWindow`, `pendingChallengeWindow`, `pendingBeneficiaryExpiresAt`, `claimStartedAt`, `claimCooldownUntil` | Cleared |
| Every rule | Dead without iteration: `executeRule`, `createRule` and `updateRule` revert when `inherited`. `executeClaim` never loops over rules, so no number of rules can make it run out of gas |
| Token balances | Unchanged. Nothing moves |
| `factory.accountOf` | Unchanged at execution for both parties. The previous owner's entry keeps pointing at this account until they open a new one: their next `createAccount` deploys a new account one generation on and moves `accountOf` to it (decision 33). The new owner's own entry is untouched |

No fee is charged at execution (decision 8).

### 6.6 The withdraw-only box

In `Inherited` state the only state-changing functions are `withdraw(token, amount, to)` and `withdrawAll(tokens[], to)`, callable by the new owner, with `to` restricted to the new owner's wallet or the new owner's own Cuenta inteligente: a clone of the account implementation (checked by code hash) whose `owner()` is the new owner and which is not itself inherited. In practice that is `factory.accountOf(newOwner)`, which the backend uses and re-checks. There is no deadline. The relayer has no function. The previous owner's key has no function. The new owner cannot trade, automate, subscribe or name a beneficiary on this account; to do any of those they move the assets into their own Cuenta inteligente.

Selling an inherited stock position therefore happens after moving it out. A new owner who is not Ondo-eligible can only withdraw (decision 19).

### 6.7 Direct on-chain path (without Confío's server)

A beneficiary can complete a claim with no Confío service running. They need:

| Need | Where it comes from |
|---|---|
| The account address and chain (BNB Smart Chain) | The acceptance screen and its notification; also `factory.accountOf(ownerWallet)` until the claim executes |
| The contract ABI | This public repository and the BscScan-verified source |
| Their own wallet key | It lives on their device in the Confío app. Confío does not export keys |
| BNB for gas at their wallet address | Bought and sent by the beneficiary |
| A way to sign and broadcast | The app's Emergency Exit transport (`apps/src/services/emergencyExit/`: `bscRpcs.ts`, `gatedTx.ts`, `bscExit.ts`) already signs on the device and submits through bundled public RPCs. A serverless "claim" action must be built on it (see N3). As built, that transport wraps every transaction in `execute([assertSilent(), leg])` (`apps/src/services/emergencyExit/gatedTx.ts`), so it works only after Confío's heartbeat has gone silent; the claim action must be sent without that gate, or it would not work in an ordinary outage or in rollout step 2 |

Steps: (1) `initiateClaim()` from the beneficiary wallet; (2) wait `challengeWindow`; (3) `executeClaim()`; (4) `withdraw(token, amount, to)` per token.

Designation and acceptance are not part of the direct path: they need Confío's relay by design. Only an already accepted beneficiary can claim without Confío.

What works in that situation and what does not (engineering reference; no copy rule is attached, decision 28):

| Action without Confío | Works |
|---|---|
| Claim and ownership transfer | Yes |
| Moving cUSD, cUSD+, stock tokens, crypto tokens, CONFIO to the new owner's wallet | Yes, subject to the vaults not being paused and neither address being frozen |
| Exiting cUSD+ to USDT (`CusdPlusVault.redeemToUsdt`) and cUSD to USDT (`CusdVault.redeemWithFee`) from the wallet | Yes, both are sponsor-less |
| Selling crypto tokens | Yes, on any DEX from the wallet. Not through `ConfioSwapRouter`, which requires a sponsor origin |
| Selling stock tokens | Only with an Ondo-signed quote. `sellToUsdt` has no sponsor gate, but today only Confío's backend obtains the quote |

---

## 7. Backend

A new Django app `smart_account/` (models, services, schema, admin, tasks), following the layout of `payment_accounts/`. English identifiers throughout.

### 7.1 Models

All soft-deletable where they represent user-visible records, and all registered on `confio_admin_site` in `config/admin_dashboard.py` (never the default admin).

| Model | Key fields | Notes |
|---|---|---|
| `SmartAccount` | `owner_user`, `owner_account` (the personal `users.Account`), `account` (the `users.Account` row of the new type, 7.2), `contract_address` (unique), `status`, `billing_status`, `plan`, `paid_until`, `cancel_requested_at`, `inherited_from_user` (nullable; the previous owner), `inherited_at`, `created_tx`, timestamps | At most one row per user with `status` other than `inherited` (the user's own account); any number of inherited rows. On `ClaimExecuted` the same row changes `owner_user` and becomes `inherited`. The fee is not stored: it is read from the factory |
| `SmartAccountEvent` | `smart_account`, `tx_hash`, `log_index`, `name`, `args`, `block_number`, `block_time` | Append-only mirror of contract events; unique on (`tx_hash`, `log_index`). This is the audit trail for financial operations |
| `SmartAccountCharge` | `smart_account`, `period_start`, `period_end`, `fee_usd`, `cusd_amount`, `cusd_plus_shares`, `p_plus`, `tx_hash`, `status` | One per collected fee |
| `SmartAccountForcedSale` | `smart_account`, `period_end`, `notice_started_at`, `dollars_out`, `fee_collected`, `tx_hash`, `status`, `attempts`, `last_error` | One operation per period at most in `succeeded` state |
| `SmartAccountForcedSaleLeg` | `forced_sale`, `position`, `asset`, `amount_in`, `dollars_out`, `quote_ref` | One row per sale leg of the operation |
| `SmartAccountRule` | `smart_account`, `onchain_id`, `kind` (`send`, `payout`, `buy`), `token_in`, `token_out`, `payee_address`, `payee_user` (nullable), `payout_method` (nullable FK to the user's saved bank destination), `payout_ref` (its hash, as stored on-chain), `amount`, `frequency` (`daily`, `weekly`, `biweekly`, `monthly`), `next_run_at`, `active` | Mirror of on-chain rules. A `payout` rule whose saved destination is edited or deleted is deactivated until the owner signs it again |
| `SmartAccountPayout` | `rule_run`, `ramp` (FK to the off-ramp order), `provider`, `rail`, `usdt_amount`, `fiat_amount`, `fiat_currency`, `status` | One per executed payment rule; links the on-chain `PayoutSent` to the provider order |
| `SmartAccountRuleRun` | `rule`, `scheduled_for`, `tx_hash`, `status`, `amount_in`, `amount_out`, `error` | |
| `SmartAccountBeneficiary` | `smart_account`, `beneficiary_user`, `beneficiary_address`, `challenge_window_seconds`, `verified_at_designation`, `residence_check`, `disclosure_accepted_at`, `designated_at`, `designated_tx`, `accepted_at`, `accepted_tx`, `declined_at`, `removed_at`, `state` (`pending_acceptance`, `active`, `declined`, `stale_address`, `removed`) | Never deleted; replaced rows are closed. `designated_at` and `accepted_at` are both required by decision 26 |
| `SmartAccountClaim` | `beneficiary_row`, `initiated_at`, `executable_at`, `initiated_tx`, `cancelled_at`, `cancelled_tx`, `executed_at`, `executed_tx`, `state` | |
| `SmartAccountRelayTx` | `smart_account`, `kind`, `calldata`, `signed_tx_hash`, `status`, `source_id`, timestamps | Durability row for relayer-originated transactions (7.4) |

Added for decision 34:

| Model | Key fields | Notes |
|---|---|---|
| `SmartAccountTargetAllocation` | `smart_account`, `weights` (list of `asset_key`, `weight_bps`, summing to 10000), `total_usd`, `frequency`, timestamps, soft delete | The owner's split, one live row per account. A preference, not chain state: it moves no money. Executed only through owner-signed Buy rules |
| `SmartAccountWatch` | `smart_account`, `user`, `kind` (`asset_price_drop_pct`, `asset_price_rise_pct`, `asset_price_below`, `asset_price_above`, `fx_rate_below`, `fx_rate_above`), `asset_key` or `currency`, `threshold`, `reference_price` (base of the percentage kinds, reset at each trigger), `action` (an owner-chosen buy: asset and amount, or empty), `active`, `cooldown_hours` (24), `last_triggered_at`, `last_value`, timestamps, soft delete | Prices from existing sources only: Ondo GM market data for stocks, the crypto snapshot prices for bitcoin and gold, the reference exchange rate Home shows (refused when older than two days) |

IA+ entitlement: `assistant/billing.py:has_plus` returns true when an `AssistantSubscription` is entitled. A current Cuenta inteligente subscription must make `has_plus` true. Either issue an `AssistantSubscription` row with a source marking it as coming from the account and an expiry equal to `paid_until`, renewed on each `FeeCollected`, or have `has_plus` consult `SmartAccount`. The first keeps one entitlement source. The entitlement ends at `paid_until` and is not granted on an inherited account.

### 7.2 Account context

The project rule stands: account context comes from the JWT only, never from client parameters.

- `users.Account.ACCOUNT_TYPE_CHOICES` (`users/models.py:594-597`) has two values. Add a third, `smart` (the field is `max_length=10`), with `account_index = 0` for the user's own account. Its `bsc_address` is the contract address, so address-keyed balance reads (stored balances, holdings, history) can be reused. The correctness checks around them cannot be reused as they are: in-flight detection for stocks (`cusd_plus/gm_holdings.py`) and crypto (`cusd_plus/crypto_holdings.py:69`, `batches_in_flight`) and the confirmation invalidation in `cusd_plus/tasks.py` look only at existing `SponsoredBatch` kinds at the signer's address. They must be extended to the new owner-signed kinds (whose effect lands at the contract address, not the signer's) and to `SmartAccountRelayTx`, for broadcast, confirmation and reorg, or the account's holdings will be shown as current while a trade is in flight.
- `SwitchAccountToken` (`users/schema.py:4030`) issues a token with `account_type = 'smart'` after verifying the caller owns that `SmartAccount`. An inherited account is switched to the same way, identified by its `account_index` (0 for the user's own, 1 and up for inherited accounts in order received).
- The signer for a `smart` context is the user's personal account key. Every place that today resolves "the JWT account's registered BSC key" (`cusd_plus/sponsor_7702.py`, the `validate_policy` path) must resolve to `owner_account.bsc_address` when the context is `smart`.
- Risk: many code paths branch on `account_type == 'business'` and treat everything else as personal. Each must be reviewed so that a `smart` context is neither treated as the personal wallet (wrong address for balances) nor allowed into flows the account does not support (P2P, payroll, presale, perps, ramps, Comprar). The default for an unreviewed flow is to refuse a `smart` context.
- Employees and business accounts: Cuenta inteligente is personal-only in v1. Mutations refuse a business JWT context.

### 7.3 GraphQL

New fields live in their own isolated queries (one unknown field fails a whole shared query on older builds). Complex fields use proper object types, never `JSONString`.

Types: `SmartAccountType`, `SmartAccountPlanType`, `SmartAccountAssetType`, `SmartAccountRuleType`, `SmartAccountChargeType`, `SmartAccountBeneficiaryType`, `SmartAccountClaimType`, `InheritedAccountType`, `SmartAccountPreparedBatchType` (the calls, nonce, deadline and intent id the app must sign), `SmartAccountOfferType` (prices and the headline ordering).

Queries (viewer-scoped from the JWT):

| Query | Returns |
|---|---|
| `smartAccountOffer` | Monthly and annual prices from the factory (settings as display fallback), the default plan, whether the viewer may subscribe, headline order (`beneficiary_first` when the viewer has a balance, else `automation_first`) |
| `smartAccount` | The viewer's account, plan, billing state, assets, rules, beneficiary, pending claim |
| `smartAccountCharges` | Paginated |
| `inheritedAccounts` | Accounts the viewer owns by inheritance |
| `beneficiaryDesignations` | Accounts on which the viewer is the named beneficiary, with claim state |

Mutations. Each validates the JWT context, refuses employees and business contexts, checks the identity-hold rules that apply to outgoing money, and returns a typed payload. Each state-changing action is two steps like the existing sponsored flows: `prepare…` returns a batch to sign, `submit…` takes the signature.

| Mutation | Signed by | Contract call |
|---|---|---|
| `prepareSmartAccountSubscribe(plan)` / `submit…` | Owner | `factory.createAccount()` if needed, deposit transfers if chosen, `subscribe(plan, maxFeeUsd)` |
| `prepareSmartAccountDeposit(assets)` | Owner | `transfer` per asset |
| `prepareSmartAccountMoveEverything(direction)` | Owner | Transfers in, or `withdrawAll` out |
| `prepareSmartAccountWithdraw(asset, amount)` | Owner | `withdraw` |
| `prepareSmartAccountTrade(...)` | Owner | `trade` |
| `prepareSmartAccountRule(...)`, `…UpdateRule`, `…CancelRule` | Owner | `createRule`, `updateRule`, `cancelRule` |
| `prepareSmartAccountPayoutRule(payoutMethodId, amount, frequency)` | Owner | `createRule` with kind `Payout`. `payoutMethodId` is the opaque id of a bank destination the viewer already saved; the server verifies it belongs to the viewer and that the rail supports unattended payouts |
| `prepareSmartAccountPlanChange(plan)` | Owner | `changePlan` |
| `prepareSmartAccountCancel` / `…UndoCancel` | Owner | `cancelSubscription`, `undoCancel` |
| `prepareBeneficiaryDesignation(beneficiaryHandle, windowDays, disclosureAccepted)` | Owner | `setBeneficiary`. The beneficiary is named by Confío handle or contact; the server resolves the address. The client never sends an address |
| `prepareBeneficiaryAcceptance(designationId)` / `declineBeneficiaryDesignation(designationId)` | Named beneficiary | `acceptBeneficiary`; declining is server-only and records `declined_at`; the owner is told, and the on-chain pending entry lapses by itself after 30 days |
| `prepareBeneficiaryRemoval` | Owner | `removeBeneficiary` |
| `prepareClaimCancel` | Owner | `cancelClaim` |
| `prepareBeneficiaryClaim(designationId)` | Beneficiary | `initiateClaim` |
| `prepareBeneficiaryClaimExecute(designationId)` | Beneficiary | `executeClaim` |
| `prepareInheritedWithdraw(inheritedAccountId, assets, destination)` | New owner | `withdraw` / `withdrawAll` with `destination` an enum (`wallet`, `smart_account`), never an address |

Where a mutation needs to name an account the viewer owns other than the JWT's active one (a designation, an inherited account), it takes a server-issued opaque id and the resolver verifies ownership against the JWT user. It never takes a raw account id or address as authority.

### 7.4 Relayer submission path for a contract account

Today's flow (`cusd_plus/sponsor_7702.py`) builds one shape: a sponsor-signed transaction to the user's EOA that runs `ConfioBatchDelegate.execute` over user-signed calls. `validate_policy` (lines 616-800) allowlists the destinations of those calls and ends in `destination_not_allowed` for anything else, so a call to an account contract is refused today. Three shapes are needed.

| Shape | Sender | Target | Used for | Change |
|---|---|---|---|---|
| Owner-signed batch | Sponsor, executing the owner's signed intent | Owner EOA, inner calls to the account | Every owner and beneficiary function; deposits | New policy branch `_validate_smart_account_batch`: the inner `to` must equal the `contract_address` registered for the signer (or for a designation or inherited account the signer holds); selector allowlist per `kind`; for `trade`, decode the wrapped router call with the existing `_decode_stock_call` / `decode_crypto_call` and apply the same quote and slippage checks; for deposits, `transfer` recipient pinned to the signer's own account. New `kind` values (`smart_subscribe`, `smart_deposit`, `smart_withdraw`, `smart_trade`, `smart_rule`, `smart_cancel`, `smart_beneficiary`, `smart_claim`, `smart_inherited_withdraw`) added to `classify_calls_kind` and to the identity-restriction list in `send_sponsored_batch` as appropriate (withdrawals to the owner's own wallet are not outgoing transfers) |
| Relayer call | Sponsor | The account directly | `collectFee`, `startPaymentNotice`, `forcedSale`, `executeRule`, `convertUsdt` | New `send_relayer_call(account, calldata, kind, source_id)`: a plain type-2 transaction from the KMS sponsor signer. It must take the shared sponsor nonce lock (`acquire_sponsor_nonce_lock`) and renew it while broadcasting (a killed worker leaves it for at most 15 seconds), simulate under the real gas budget (a node that does not answer is not a revert), apply the gas-price cap, and write a `SmartAccountRelayTx` row with the deterministic signed hash before broadcast, the same durability rule as `SponsoredBatch` |
| Keeper call | Sponsor (anyone could) | The account | `returnAsset` per token after expiry | Same function as the relayer call, `kind = smart_return` |

While a claim is pending on the signer's account, every prepare step appends `account.cancelClaim()` to the calls it returns for that owner to sign (6.4), and the policy check before `send_sponsored_batch` refuses a batch from that owner that lacks it. It must be part of the prepared call list the user signs, not added after signing.

Fee referral: `CusdVault.armReferral` requires the caller to be a 7702-delegated EOA (`_isConfioAccount`, `CusdVault.sol:282-284, 315-319`). In an owner-signed batch the server keeps placing the arm as the first call, made by the owner's EOA, exactly as today; fees charged later in that transaction pay the referrer even though the account is the one converting. Relayer calls cannot arm today; decision 32 changes that:

- `CusdVault` (UUPS, Safe-owned) gains one appended storage variable, a Safe-maintained set of recognised factories (`isSmartAccountFactory`), and `armReferral` accepts a caller that is either a 7702-delegated EOA (as today) or an account that reports its factory, where that factory is recognised and confirms `isAccount(msg.sender)`. Every other check in `armReferral` and `_payReferral` is unchanged: sponsor as `tx.origin`, one arm per transaction, share within the owner cap, the arm lives only for the transaction.
- The factory exposes `isAccount(address)`.
- The account's relayer functions that convert (`executeRule`, `forcedSale`, `convertUsdt`) take an optional `(referrer, shareBps)` and, when present, call `CUSD.armReferral` first. The account requires `referrer` to differ from `owner`.
- Who the referrer is and the share stay a server decision (`cusd_plus/fee_referral.py`): the referee is the account's owner, with the same conditions as today (both verified, neither banned, referral within its window). The scanner that records `ReferralPaid` maps the account address to its owner.
- What a compromised relayer key could do with this: name itself as referrer and take up to the capped share of Confío's own fee on those transactions. The user's cost is unchanged. The same is already true for sponsored batches.
- This is a change to a live vault. It ships as its own upgrade with its own Codex audit pass, storage layout checked as append-only, before rollout step 1.

### 7.5 Quotes for automation and forced sales

- **Stocks.** `cusd_plus/gm_api.py:binding_attestation(symbol, side, notional_value)` returns the Ondo-signed quote. Today it is requested when a user confirms a trade. For `executeRule` (buy) and `forcedSale` (sell) a Celery task requests it with no user present, builds the router calldata, and submits inside the quote's expiry. The quote's `userId` is Confío's router identity, as for every trade. Market sessions and per-asset halts (`market_status`, `asset_statuses`) must be checked first; a rule that falls in a closed session runs at the next open one.
- **Retries (buys, sends and payouts).** A monthly rule skipped for `insufficient_balance` is retried for up to 3 days (founder, 2026-11-22: "Only monthly"); a wait that follows keeps that deadline. Daily, weekly and biweekly rules, and every other code at any frequency, give the slot up after 24 hours. No slot is retried past the next calendar slot (`automation.retry_deadline`). The deadline is asked before anything is built, for a wait as for a skip or a failure; only a market wait (closed, or a session that could not be read) goes beyond it, up to the next slot, and the waits that follow one keep that deadline. A dropped transaction keeps the deadline of the wait before it; a real revert does not. An owner banned, disabled or held, before signing or when a payment adapter asks, is a wait: nothing is signed, and a slot given up says why, with "Escríbenos por soporte" (a minor, a deleted account and one that is not personal stay final). A slot never looked at because Confío or billing was paused through it gets one attempt. A refusal that passes (a busy sponsor lock, a node that does not answer, a rolling limit, a reservation refused) is a wait, so it never ends a monthly rule's 3 days by itself; a real revert or failure keeps 24 hours. A run waits while the owner's update of the rule is on chain and not mirrored. Every gate is asked again on a late attempt. The contract's gap counts from execution, so a late weekly or biweekly run moves its later dates by as much for good, which is why those keep 24 hours; a late monthly one moves the next date only where fewer than 28 days would remain (February), and returns to its own day afterwards.
- **Crypto.** The route is the catalog route (`cusd_plus/crypto_tokens.json`) and the floors come from a live requote within `CRYPTO_MAX_SLIPPAGE_BPS` (`cusd_plus/crypto_policy.py`). These are server-side checks today; see conflict C2 for what the contract must add.
- Forced-sale sizing: notional = shortfall grossed up for the 0.9% entry fee and the venue's rounding, within the contract's cap.
- **Bank payouts.** Verified in code: Pix, Bre-B and CLABE sends are all served by one provider through `payment_accounts/local_money.py` (methods `br_pix`, `co_breb`, `mx_clabe`). The money path is: USDT on BSC, bridged to the user's own reusable Polygon USDC funding address at the provider (`payment_accounts/bridge.py:66-86`), converted, and paid to a `PayoutDestination` that belongs to the user (`payment_accounts/infinia_journeys.py:88-95`). On BSC the USDT is paid to a bridge deposit address created for that one transfer (`payment_accounts/relay.py`, `deposit_address=True`). A `Payout` rule run therefore: opens the journey for the rule's saved destination, obtains the bridge quote, and calls `executeRule` naming that quote's deposit address. Two things must change for a run with no user present: (1) each outgoing journey today claims a Face step-up grant (`payment_accounts/services.py:37`, `require_outgoing_face`); a payment rule needs a standing authorization given once, with Face, when the owner creates the rule, bound to that destination, amount and frequency; (2) the bridge and FX quotes are accepted today against limits the user approved on screen; a rule stores its own limits (maximum bridge cost, minimum FX rate tolerance) and a run outside them is skipped and notified, never forced. The rule's dollar amount is fixed; the local-currency amount follows the day's rate and the bridge cost, and the notification says so.

**Bank payouts as built (2026-11-22; tested with Relay, Infinia and both chains mocked, never run with real money).** Where this differs from the paragraph above, this is what the code does (`payment_accounts/contract_funding.py`, `smart_account/infinia_payouts.py`).

- **Rails.** `mx_clabe` and `br_pix` (keys) have an adapter. Nothing else does: no setting can offer `co_breb` (paused, and it needs a device location pass per operation), `ar_cvu` or any QR. An offered rail also needs the provider switches a manual send needs.
- **One run, one bridge, one journey.** The run prices a Relay one-time deposit (`strict`, `EXACT_INPUT`) whose source and refund address are the account contract and whose recipient is the owner's own Infinia Polygon USDC address. Bridge, journey and payout row are written in one transaction, before `executeRule`. A retry reuses them. An order that nothing was broadcast for closes after its deadline and stops holding the owner's accounts.
- **Saving for a rule.** The owner's own active account, an adult sender, and for CLABE and Pix the gates of Enviar (`require_rail`: identity, eligibility, document, region) before any lookup or write; a cap per rail and an hourly limit on paid lookups. An e-mail key is one key in any case. A name the owner typed is never returned as `holderName`: the label carries it, marked.
- **Holder checks.** A verified holder older than the TTL, or a row never checked while the lookup is on, is offered as not verified and asked again before Face; the result is what is labelled and signed. With the lookup off a stale answer is an unverified one for a new signature, and saving again never replaces a bank's answer. A row recorded as never checked runs only while the lookup is off. An authorization pinned to a verified holder keeps requiring that holder verified.
- **Editing.** A payment rule cannot be updated while a run of it is in flight (sent, an open order, or a relayer transaction that may land); it can be stopped. Funding enforces the same.
- **Authority.** A server object built from the run re-reads the live standing authorization, run, destination, amount and bridge at each use. No GraphQL argument reaches it, and the owner's quote, prepare, submit and journey mutations refuse these rows. Every check of a manual send that does not need a request is applied. Those that do (IP block and reputation, session, device, app version) cannot be.
- **Funding proof.** Only the reported `executeRule` hash and its final receipt: USDT from `CusdVault` to that deposit, at least the quoted amount. No log scan, no match by amount. Money reported for a closed order is followed to where it lands and goes to review; it never pays.
- **Single-use address.** Pago Móvil runs ask for one too (`strict`), and an address already given to another order is refused. It fills whoever pays first, whatever the amount, and refunds later deposits. So settlement follows only the Relay request whose `depositTxHash` is the run's proven funding hash (`GET /requests/v3`, which needs `RELAY_API_KEY`; the rail is not offered without it), never the quote's request id or an amount. The request found is stored with that deposit and hash and then followed by `GET /intents/status/v3`; while it is not final it is looked up again every 5 minutes (a regenerated fill, a child refund). Lookups share one App-wide budget (`RELAY_REQUESTS_PER_MINUTE`, 60 by default); after a 429 every worker slows to 2 a minute for 5 minutes, and whoever waited longest goes first. A rate limit is never evidence: the payment waits, is never parked or failed for it, and ops hear 2 hours after the deposit's deadline. A front-run run ends as a verified refund to the contract. `refundFailReason` (`MANUAL_REFUND_REQUIRED`) goes to review with an ops alert.
- **Limits.** Prepare stores the day's FX rate as the rule's reference and the signed summary names the floor it gives. A run is refused over the rule's cost limit (Relay's whole expected cost, not its worst-case slippage, and not the processor's fixed fee: decision 36), when what Relay would deliver does not exceed that fee, or under its FX floor. A cost or rate refusal at run time is today's, not the month's: the slot is asked again, hourly, inside its 24 hours; the owner is told when it is given up, ops are not. For Pago Móvil the cost limit is asked again of the deposit route that gets the money, not only of the estimate. The journey's minimum conversion is the higher of the manual send's tolerance and that floor. After delivery nothing is forced: a rate under the minimum waits up to an hour (a rate back inside the limit restarts that hour) and then goes to review, as a refused payout or a return does, and ops are told where the money is.
- **Processor fee.** The contract pays one address, so the run cannot collect it. When `INFINIA_PASS_THROUGH_FEE_COUNTRIES` lists the country, a paid run records the fee (processing plus blockchain, never maintenance or older debt) as the existing carry-forward debt, collected with the owner's next signed fee-enabled local transfer. An owner who never signs one never pays it. The prepare summary and the assistant's proposal show the fee. The authorization stores it as `max_processor_fee_usd`, inside the Face binding hash; it is not in the on-chain calldata. A run checks the day's tariff against it before pricing and again in the transaction that records the order: above it, the run is skipped with `processor_fee_increased` and the rule stays active. An empty ceiling authorizes no fee.
- **The owner's own sends.** A run waits, untold, while the owner's journey or just-prepared bridge holds the accounts, and gives the slot up after 24 hours (after the 3 days of Retries above, when the wait follows a monthly rule's skip for no balance). While a run is under way the owner's next local send waits as it would for their own.
- **Providers busy.** A 429 from Pago ASAP on the payout, and from Infinia on a contract-funded conversion or payout, is replayed under the same key; a payout token that could not be had means nothing was sent, and is tried again. A replay asks the owner and the payee again; refused for 24 hours from the first refusal (a bank check still pending is a wait, not a refusal), the leg and its journey are parked and ops told once. A Pago ASAP 429 took nothing, so the key's replay window (`PAGOASAP_IDEMPOTENCY_REPLAY_MINUTES`) does not run on it unless an earlier answer of that key was lost; a key refused only for rate is replayed for 2 hours from its first dispatch, then goes to review with an ops alert. A contract-funded deposit Relay never binds, or leaves in a failure that is not final, goes to review an hour past its deadline and is still followed. A manual Infinia send is unchanged: its 429 goes to review.
- **What the owner sees of a payment in trouble.** A Pago Móvil payment sends no generic withdrawal push. It is told once when it goes to review (parked, refused by the bank, unknown) and once when it is refunded. For every bank rail the run's own line follows: a refund or a review no longer reads "Pago en camino.". A Pago Móvil rule's orders send Pago ASAP the name its authorization was signed with (`holder_name`; for one signed before it was kept, the name its first order carried): saving the beneficiary again under another name renames no signed rule's payee. Ops hear of one on its way for more than 2 hours. An executed-rule event not mirrored yet is waited for, never read as changed terms; late funding is returned by hand only.
- **What the owner sees of retries.** An order closed unfunded to be tried again is not pushed as a failed withdrawal and leaves history when a fresh one replaces it. A slot overtaken while its payment may have left is told as under review (do not repeat it), and ops are alerted.
- **Refunds.** Back to the contract, verified by receipt, then converted by `convertUsdt` (which charges the entry fee).
- **Not verified with the providers.** That Relay gives a one-time address for a contract `user`, accepts a deposit sent by a token contract (the cUSD vault), and fills in `depositTxHash` for both; that Infinia credits such a deposit with the transaction hash; Infinia's minimums per rail; X9.

### 7.6 Reconciliation

A Celery task reads account and factory events from the chain and writes `SmartAccountEvent`, then updates the mirror tables. Mirror state is never written from a mutation's optimistic result. The task also enumerates each account's token balances through the existing stored-balance pipeline keyed on `Account.bsc_address`.

### 7.7 Notifications

All through the existing notification service, user-facing copy in Spanish.

| Trigger | To | Timing |
|---|---|---|
| Fee collected | Owner | At collection |
| Fee due and dollars short | Owner | At period end, then daily until paid |
| `PaymentNoticeStarted` | Owner | Immediately; states the earliest sale date and which asset or assets would be sold |
| Day before a forced sale | Owner | Once |
| Forced sale done / failed | Owner | At event |
| Rule executed / skipped / failed | Owner | One notice per transition: pending with the date it is retried until, then done (buys and sends; a payout at delivery) or given up with the next date. Never one per attempt |
| Named as beneficiary, acceptance requested | Named person | At `BeneficiaryNamed`, with reminders while pending |
| Beneficiary accepted / declined | Owner | At event |
| Price change scheduled | Every subscriber | When scheduled, and again before that subscriber's renewal |
| Payment rule sent / failed | Owner | At event, with the fiat amount delivered |
| Beneficiary removed or replaced | Previous beneficiary | At event |
| Beneficiary's wallet address changed | Owner | At detection |
| `ClaimInitiated` | Owner | Immediately, then on a fixed schedule across the whole window through push, in-app, email and the assistant thread; frequency rises near the end |
| `ClaimInitiated` | Beneficiary | Confirmation with the executable date |
| `ClaimCancelled` | Both | At event; the beneficiary sees the cooldown end |
| Claim executable | Beneficiary | At `executableAt` |
| `ClaimExecuted` | Both | At event |
| Cancellation signed | Owner | At event; states the return date and that the beneficiary designation stops applying |
| Assets returned | Owner | When the account is empty |

Review flags must not gate users: a notification failure or a pending review never blocks an owner's next action.

### 7.8 Celery tasks

| Task | Schedule | Does |
|---|---|---|
| `smart_account.reconcile_events` | Frequent | 7.6 |
| `smart_account.collect_due_fees` | Hourly | `collectFee` for accounts in `PaymentDue` with enough dollars |
| `smart_account.start_payment_notices` | Hourly | `startPaymentNotice` where dollars are short |
| `smart_account.run_forced_sales` | Hourly, market-aware | One `forcedSale` per eligible account (it sells and collects in one transaction); records attempts; alerts the team after repeated failures |
| `smart_account.convert_usdt` | Every few minutes | `convertUsdt` for accounts holding USDT, with the destination dollar from the owner's eligibility; reads the balance fresh, as the personal-wallet auto-mint does (`cusd_plus/schema.py:239`, `_sweepable_usdt_wei`) |
| `smart_account.run_rules` | Every few minutes | `executeRule` for due rules on `Current` accounts |
| `smart_account.return_expired` | Hourly | `returnAsset` per token for `Expired` accounts until empty; a failing token is recorded and retried without blocking others |
| `smart_account.claim_notices` | Daily | The owner notice schedule for pending claims |
| `smart_account.sync_entitlements` | On `FeeCollected` and daily | IA+ entitlement in line with `paid_until` |
| `smart_account.monthly_review_notes` | 1st of each month | Decision 34: last month's review as a thread note (`assistant.service.post_system_note`) for each subscriber whose IA+ is current. Idempotent per account and month by the note's tag. Behind `SMART_ACCOUNT_ENABLED` |
| `smart_account.evaluate_watches` | Every 5 minutes | Decision 34: evaluates active alerts of current subscribers; a trigger is a compare-and-set on `last_triggered_at`, so two workers never notify twice; then a push and a thread note. An unknown price is skipped and counted, never read as a trigger. Behind `SMART_ACCOUNT_ENABLED` |

Every task that sends a transaction is idempotent on (`account`, `kind`, period or rule run) and fails closed: an exception leaves state unchanged and is retried. A catch that turns an error into "nothing to do" is a defect.

### 7.8a Assistant tools (decision 34)

In `assistant/engine.py`, available only to the viewers listed in 3.5 and never while the team owns the thread. Logic in `smart_account/assistant_ops.py` and `smart_account/watches.py`.

| Tool | Arguments | Returns / effect |
|---|---|---|
| `smart_account_rules` | none | Rules (`regla_id`, kind, amount, frequency, active, next run, destination, last run with status and reason), saved bank destinations (`cuenta_id`, whether payouts are enabled for the rail, a fresh bank-verified holder's name), the target split. Rows are left out whole, and counted, above the tool's size limit |
| `propose_smart_account_rule` | `action` (`create`, `update`, `cancel`), `kind`, `rule_id`, `payee`, `payout_method_id`, or a new destination in the owner's words (`clabe`, `pix_key`, `pagomovil_phone`, `pagomovil_bank`, `pagomovil_cedula`, `holder_name`), `asset`, `amount_usd`, `frequency`, `weekday` (0 = Monday), `day_of_month` (1 to 28), `start_date` | A proposal of one step (`action`, `kind`, `rule_id`, `amount_usd`, `frequency`, `first_run_at`, payee, destination or asset, and a Spanish sentence). Stored on the reply message's metadata; adds the chip |
| `propose_target_allocation` | `action` (`set`, `next_split`, `delete`), `assets` (asset and percent), `total_usd`, `frequency`, first-run fields | `set` saves the split and proposes one Buy step per asset; `next_split` proposes the drift re-split with its estimated periods; `delete` forgets the split (rules stay) |
| `smart_account_review` | `months_back` | The month's review (3.5) |
| `smart_account_alerts` | `action` (`create`, `list`, `delete`), `kind`, `asset`, `currency`, `threshold`, `action_asset`, `action_amount_usd`, `alert_id` | `create` drafts the alert; the reply ends with a code-written confirmation question and the alert is saved on the owner's "sí". `delete` acts on the owner's own alert by opaque id |

A proposal's arguments are stored in `AssistantTurn.tools` without destination, cédula or names, refused calls included. A delivery push shows a destination masked.

The chip is `{type: navigate, target: smart_account_rule, destination: cuenta_inteligente}`: builds that know `smart_account_rule` open the proposal; older builds open the Cuenta inteligente door. It replaces any offer chip in that reply (one chip per reply). The app reads the steps with the isolated query `assistantRuleProposal(messageId)` (owner's own messages only; marked expired after 7 days), so the shared thread query is unchanged. Alerts are listed with `smartAccountWatches` and deleted with `deleteSmartAccountWatch(watchId)`.

Copy: `offer.BENEFITS['assistant']`, `assistant/prompts.py` (`IA_PLUS_IN_SMART_ACCOUNT`, the Confío IA+ waitlist section, and `SMART_ACCOUNT_OPS_SECTION` for subscribers) and the `ia_plus` destination describe the assistant operating the account with the owner's confirmation; never more usage, a better model or "unlimited".

### 7.9 Changes to the probe code

| File | Today | Change |
|---|---|---|
| `config/settings.py:2047-2049` | `SMART_ACCOUNT_PROBE_ENABLED`, `SMART_ACCOUNT_MONTHLY_PRICE_USD` default `'9.99'` | Monthly default `'14.99'`; add `SMART_ACCOUNT_ANNUAL_PRICE_USD` (`'149.99'`) and `SMART_ACCOUNT_DEFAULT_PLAN` (`'annual'`); add `SMART_ACCOUNT_ENABLED`, `SMART_ACCOUNT_ALLOWED_USER_IDS` (canary), `SMART_ACCOUNT_BENEFICIARY_ENABLED`, `SMART_ACCOUNT_MIN_APP_VERSION`, factory and collector addresses. The app shows the factory's price in force and, when a change is scheduled, the next price and its date; the settings values are the fallback for display only, and a check alerts when they differ from the factory outside a scheduled change |
| `users/paid_offers.py` | Probe rules: flags, `price()`, `available()`, `billeteras_row_visible()`; docstring says nothing is sold | Keep as the rule module for who sees the door. `price()` gains a plan argument. Add `can_subscribe()` (flag, canary list, build floor, personal non-employee, identity rules). The docstring's "nothing is sold, charged or unlocked" is no longer true once the flag is on and must be rewritten |
| `users/models_product_waitlist.py` | `ProductWaitlistEntry` with `would_pay`, `volume_range`, `notified_at` | No new waitlist joins after launch for users who can subscribe. `notified_at` records the launch message. Rows and answers are kept as funnel data (decision 27); the fake-door plan's "deleted 90 days after the decision" line is withdrawn and no deletion job is built |
| `scripts/ops/paid_offer_funnel.py` | Counts probe stages and waitlist answers | Add the paid funnel: `subscribe_opened`, `subscribe_signed`, `subscribed`, `first_deposit`, `rule_created`, `beneficiary_set`, `cancelled`, by plan. Aggregate counts only, as today |
| `users/funnel_schema.py`, `TrackFunnelEvent` / `CLIENT_EMITTABLE_EVENTS` | `paid_offer_interest` stages | Add the stages above as a new event name; keep `paid_offer_interest` for history |
| `assistant/prompts.py:146-172` | `PAID_OFFER_SECTIONS['cuenta_inteligente']` lists Pix/Bre-B/CLABE/Alias payments, merchant subscriptions, debit control, "todavía no está disponible", "nunca digas que se puede pagar" | Keep automatic payments to CLABE, Pix and Bre-B and scheduled transfers; remove merchant subscriptions and debit control; add automatic investing and the beneficiary; both prices from the server; say it can be opened now. Only rails confirmed for unattended payouts are named. `IA_PLUS_IN_SMART_ACCOUNT` already frames IA+ as account service and stays |
| `assistant/destinations.py`, `assistant/paid_chips.py` | `cuenta_inteligente` destination opens the pitch | Opens the subscribe screen for those who can subscribe; the existing chip caps stay |
| `apps/src/screens/PaidOfferScreen.tsx`, `apps/src/services/paidOffers.ts` | Pitch with "Sí, avísame" / "Solo miraba" and the would-pay question | Becomes the entry to the subscribe flow (8.1). The would-pay and volume questions are removed |

Waitlist members get the launch message with the current prices. The change from US$9.99 is not announced separately (decision 20).

---

## 8. App

React Native, no Expo. Identifiers in English; every user-facing string in Spanish.

### 8.1 Where the account lives

| Existing piece | Change |
|---|---|
| `apps/src/utils/accountManager.ts:3` `AccountType = 'personal' \| 'business'` and the id formats `personal_0`, `business_{id}_{index}` | Add `'smart'` with ids `smart_0` (own) and `smart_1…` (inherited). A `smart` context has no key of its own: signing uses the `personal_0` key |
| `apps/src/hooks/useAccountManager.ts` (`switchAccount`), `apps/src/hooks/useAtomicAccountSwitch.ts`, `apps/src/contexts/AccountContext.tsx` (`useAccount`) | Accept the new type. `authService.switchAccount` must not derive a new address for a `smart` context; the address is the contract address from the server |
| `apps/src/components/AccountSwitchOverlay.tsx`, `apps/src/components/ProfileMenu.tsx` | Show "Cuenta inteligente" as a third entry, and each inherited account as its own entry with an "heredada" label |
| `apps/src/screens/HomeScreen.tsx` Billeteras row with `CuentaInteligenteMark` | For a subscriber the row shows the account's balance and opens the account; for others it opens the subscribe flow |
| `apps/src/services/sponsored7702.ts` | Build and sign batches whose inner calls target the account; sign with the personal key when the context is `smart` |
| `apps/src/navigation/MainNavigator.tsx`, `apps/src/types/navigation.ts` | New routes below |
| Tabs and features in a `smart` context | Only what the account supports is shown: balance, assets, rules (including automatic buys), beneficiary, plan. Manual buy and sell inside the account is not in the first app build: the contract (`trade`) and the server (`prepareSmartAccountTrade`) support it, but the app's trade screens are not wired to it yet; a user trades by moving the asset to the personal wallet. P2P, payroll, presale, Futuros, ramps and Comprar are hidden, and the server refuses them (dual enforcement) |

### 8.2 Screens and flows

| Flow | Screens | Notes |
|---|---|---|
| Subscribe | `SmartAccountOfferScreen` (benefits, annual/monthly selector with annual preselected, disclosures) → `SmartAccountFundScreen` (choose what to move in; at least the first fee in cUSD or cUSD+) → confirm and sign → `SmartAccountHomeScreen` | One signature creates the account, deposits and pays the first period. Headline order from `smartAccountOffer` |
| Move assets in / out | `SmartAccountMoveScreen` with a per-asset list and "Mover todo" | Shows the exact list before signing; shows what is not moved (locked presale, Futuros) |
| Automation | `SmartAccountRulesScreen`, `SmartAccountRuleEditScreen` | Kinds: send to a Confío user, pay a saved bank destination (CLABE, Pix, Bre-B), buy. Frequencies: daily, weekly, every two weeks, monthly. Each shows amount, frequency, next run, and where the money goes. A bank payment shows that the dollar amount is fixed and the local-currency amount follows the day's rate |
| Beneficiary (owner) | `BeneficiarySetupScreen` (pick a Confío contact, choose the window, accept the disclosure) → sign → `BeneficiaryStatusScreen` (pending acceptance, then active with both dates) | Hidden until `SMART_ACCOUNT_BENEFICIARY_ENABLED`. Shows eligibility failures plainly (not verified, not eligible by residence) |
| Beneficiary (named person) | `BeneficiaryInviteScreen` (who named them, what it means, the window) → accept and sign, or decline | After acceptance shows the account address and chain to keep |
| Claim pending (owner side) | A blocking banner on every screen of the app, in every account context, with one button that signs `cancelClaim` | The owner must not be able to miss it while using the app |
| Cancel | `SmartAccountCancelScreen` | States the return date, that every asset returns to the personal wallet, that automation stops and the beneficiary designation stops applying |
| Claim (beneficiary side) | `BeneficiaryClaimScreen` (start), `BeneficiaryClaimStatusScreen` (countdown, executable date), execute | Also reachable when the server is unreachable, through the Emergency Exit transport without its heartbeat gate (6.7). This is new work, not an existing path |
| Inherited account | `InheritedAccountScreen` | Shows assets and two actions: move to my wallet, move to my Cuenta inteligente (offered only if the user has one). No trade, no rules, no plan |
| Payment problem | Banner and `SmartAccountBillingScreen` | Shows the amount due, the notice date, which asset would be sold and when, and an "add dollars" action |
| Assistant proposal (decision 34) | Chip "Revisar y firmar" in the assistant thread → `SmartAccountRuleEditScreen` prefilled | The chip is opened by a tap only, never by an answer moving the app. The proposal (kind, rule id for an edit, payee handle, saved destination id or asset key, amount, frequency, first run) fills the form; every field stays editable; the proposal's sentence is shown above the form; the first run is shown and can be removed. A stop proposal opens that rule's stop confirmation. A proposal of several steps (a target split) is signed one screen at a time. The normal Face and signing flow applies; the prepare re-validates everything |
| Alerts (decision 34) | `SmartAccountWatchesScreen` (from the account's Automation card) | Lists the owner's alerts in the server's words, with delete. A trigger notification opens it (`screen: SmartAccountWatches`) |

### 8.3 Copy constraints

- Product name: "Cuenta inteligente". No "Bóveda". The benefit may be called "Herencia Digital" in marketing; store listings, terms and legal text use "beneficiario".
- Confío IA+ is described as the assistant operating the account for the owner, who confirms every change (decision 34). Never as more usage, a better model, new chat features or "unlimited". Account screens may call it "el asistente de tu cuenta"; they do not use the word IA.
- Screens describe financial functions only. "Inteligente" must not read as an AI unlock. No violet, sparkle or padlock marks (carried over from the probe's design review).
- Nothing the product cannot deliver: no merchant subscriptions and no debit control in copy; a bank rail is named only where payment rules are live for it.
- No "saving" benefit and no mention of converting between dollars. The user sees one dollar balance.
- Prices come from the server, never hard-coded. The annual plan is shown first and preselected.
- Standard hashtags only if any sharing surface is added: #Confio #RetoConfio #LogroConfio #AppDeDolares #DolarDigital.

Disclosures that must be on the sign-up screen before the signature:

1. The price, the period, that it renews at the price in force at renewal, that it is charged from inside the account, and that there are no refunds.
2. The order of payment: Confío Dollar, then Confío Dollar+, then, after notices, a sale of investments for one period's fee.
3. Only what is inside the account is automated and covered by the beneficiary. The personal wallet is not.
4. The 0.9% conversion fee applies as everywhere else. There is no discount.
5. Cancelling returns every asset to the personal wallet at the end of the paid period and ends the beneficiary coverage.
6. It is a self-custodial account, not a bank account.

Disclosure that must be on the beneficiary setup screen, with an explicit acceptance:

7. If the named beneficiary starts a claim and the owner does not sign any action on the account for the whole window (Confío adds one automatically to every transaction it relays from the owner's personal wallet), the beneficiary becomes the owner of the account and everything in it. A living owner who misses every notice for the whole window loses the account. (Residual risk; the founder confirmed it goes on the screen.)

### 8.4 React Native rules from `CLAUDE.md` that apply

- Every `FlatList` (assets, rules, charges, contact picker) includes pagination and virtualisation settings (`initialNumToRender`, `maxToRenderPerBatch`, `windowSize`, `getItemLayout`).
- Gradients and marks use `react-native-svg`, not `react-native-linear-gradient`.
- Secure storage uses `react-native-keychain`. No AsyncStorage.
- No account id is passed as a parameter to the API; the context is the JWT.
- UI permission blocks and API permission checks both exist for every action.
- Verification on a real device, not an emulator.
- iOS builds compile without the DEX surfaces (`DEX_TRADING_UI_ENABLED`). Buy rules for bitcoin and gold and the related forced-sale copy must respect that switch on iOS.

---

## 9. Verified facts, conflicts and open points

### 9.1 Verified facts

Carried from the decision session, verified on 2026-11-20:

| # | Fact | Function / location |
|---|---|---|
| V1 | Deployed implementation bytecode matches the repository source, with immutables and metadata masked, for `ConfioStockRouter` (proxy `0x40c8e134BCAf44EEf9e7D184846F36c9862329c3`), `CusdPlusVault` (proxy `0x3C29417eb4314155e63d4C7D4507852b87763Ed1`) and `CusdVault` (proxy `0x6101cC370635cF2c7f2725EaB010aC407A8d543F`) | Not re-run for this document |
| V2 | `ConfioStockRouter.buyWithSavings` and `sellToSavings` treat `msg.sender` as the user and require only `VAULT.isSponsor(tx.origin)`. There is no EOA check, so a contract account can trade. `sellToUsdt` has no sponsor gate but needs an Ondo-signed quote, which today only Confío's backend obtains. Ondo's minimum order is about US$0.98 | `ConfioStockRouter.sol:241-244, 255-304, 316-350, 357-383`; re-read for this document |
| V3 | `CusdPlusVault`: share transfers are blocked for `frozen` addresses and, corrected on re-reading, while the vault is paused (the decision session recorded "only for frozen"); `subscribeAndMint` requires `recipient == msg.sender \|\| isSponsor[msg.sender]` plus a sponsor; `redeemToUsdt` has no sponsor gate; `unwrapToCusd` requires a sponsor. `CusdVault.redeemWithFee` is permissionless | `CusdPlusVault.sol:494-527, 638-657, 685-707, 794-797, 837-839`; `CusdVault.sol:175-193`; re-read for this document |
| V4 | Ondo GM stock tokens transferred freely to never-whitelisted addresses when measured on 2026-08-01; the whitelist gates primary mint and redeem only | Measurement of 2026-08-01, not repeated |
| V5 | `ConfioPresaleVault`: allocations are ledger entries `purchased[address]` with no transfer function; `claim()` pays `msg.sender` only and only after `claimsUnlocked` | `ConfioPresaleVault.sol:121, 352-356`; re-read for this document |

Verified while writing this document, by reading the source in this checkout:

| # | Fact | Location |
|---|---|---|
| N1 | `ConfioSwapRouter.buy` and `sell` treat `msg.sender` as the user. The only caller gate is `onlySponsoredOrigin` (`VAULT.isSponsor(tx.origin)`). There is no EOA check and no 7702-designator check. Bought tokens are delivered to `msg.sender`; sale proceeds are minted to `msg.sender` as cUSD+ (`dest = 0`) or cUSD (`dest = 1`). A contract account can therefore buy and sell bitcoin and gold when the relayer originates the transaction | `contracts/crypto_swap/ConfioSwapRouter.sol:132-135, 143-165, 173-201, 249-274` |
| N2 | `ConfioSwapRouter` has no sponsor-less sell. Without Confío a holder sells on a DEX from their own wallet | `ConfioSwapRouter.sol:26-28, 173-181` |
| N3 | The app's Emergency Exit already signs on the device and submits through bundled public RPCs, without the sponsor endpoint | `apps/src/services/emergencyExit/` (`bscRpcs.ts`, `gatedTx.ts`, `bscExit.ts`); comment at `cusd_plus/sponsor_7702.py:749-753` |
| N4 | `CusdPlusVault.wrapCusd` and `unwrapToCusd` accept a contract caller with `recipient == msg.sender` when a sponsor is `tx.origin` | `CusdPlusVault.sol:553-572, 685-707` |
| N5 | Both dollars stop moving while their vault is paused or either address is frozen. With cUSD+ paused, the in-kind fee, `withdraw`, `returnAsset`, send rules and inherited withdrawals of cUSD+ all revert until unpause; other assets are unaffected | `CusdVault.sol:452-455`; `CusdPlusVault.sol:794-797` |
| N6 | `ConfioStockRouter.buyWithSavings` sends redemption excess in USDT and GM's USDon refund to `msg.sender` | `ConfioStockRouter.sol:412-425, 460-466` |
| N7 | `CusdVault.armReferral` requires the caller's code to be the 7702 designator of the configured delegate | `CusdVault.sol:282-284, 315-319` |
| N8 | The relay policy refuses any call destination it does not list | `cusd_plus/sponsor_7702.py:616-800` (final `destination_not_allowed`) |
| N9 | The account model has two types on the server and in the app | `users/models.py:594-597`; `apps/src/utils/accountManager.ts:3` |
| N10 | The probe prices default to `'9.99'` and come from settings | `config/settings.py:2047, 2049`; `users/paid_offers.py:52-55` |
| N11 | `pPlus` is a public variable of `CusdPlusVault` and is the divisor in share issuance | `CusdPlusVault.sol:159, 603` |
| N12 | The crypto catalog's launch scope is BTCB and XAUt | `cusd_plus/crypto_tokens.json` (header comment) |

Not verified:

| # | Not verified | Why it matters |
|---|---|---|
| X1 | The deployed `ConfioSwapRouter` bytecode against the source. Its address is not in `contracts/cusd_plus/DEPLOYMENT.md`; it is read from the `CRYPTO_SWAP_ROUTER_ADDRESS` setting | N1 and N2 describe the source, not the deployment |
| X2 | That transfers of the catalog crypto tokens (BTCB, XAUt) to and from a contract address carry no restriction or transfer tax | Deposits, returns and forced sales depend on it |
| X3 | That `CONFIO` token transfers to and from a contract address are unrestricted, including under the planned freeze-capable version | Decision 13 makes claimed CONFIO inheritable |
| X4 | Closed: on-chain reference prices for bitcoin and gold exist (measured, see C2) | — |
| X5 | That the Emergency Exit transport can send an arbitrary contract call (it is built for exits and gated by `ConfioHeartbeat.assertSilent()`) | The direct claim path in the app (6.7) |
| X6 | That Ondo's API issues binding quotes on a schedule with no user session, at the rate rules and forced sales need | 7.5 |
| X7 | Decimals of cUSD and cUSD+ (assumed 18) | Fee arithmetic (5.1) |
| X8 | V1 and V4 were not repeated for this document | They are carried as given |
| X9 | Whether the provider's terms allow recurring unattended payouts to third-party bank destinations, and its per-user limits for them | Payment rules (7.5). The code path was read; the commercial terms were not. Infinia's public docs (read 2026-11-22) state a default monthly limit of US$10,000 equivalent per account, enforced at payout (HTTP 409, so after conversion), and are silent on minimums and unattended payouts |

### 9.2 Conflicts found

Each is a place where a decision and the code, or two decisions, did not fit as written. The founder answered the first draft on 2026-11-20; the table records the outcome of each.

| # | Conflict | Location | Outcome |
|---|---|---|---|
| C1 | Decision 4(a) includes scheduled sends; decision 12 says assets leave only to the owner's wallet or by ownership transfer | Decisions 4 and 12 | **Resolved (decision 16).** A send rule's payee, token, amount and schedule are stored on-chain by an owner-signed call; the relayer can only trigger that transfer |
| C2 | Decision 12 wants relayer limits enforced in the contract. For bitcoin and gold, the price protection of a sale exists only on the server: `ConfioSwapRouter` checks the route's two endpoints and takes the floors from the caller. A compromised relayer key could run the one allowed forced sale through a route of its choosing and receive almost nothing for the asset | `ConfioSwapRouter.sol:279-296`, `:173-201`; `cusd_plus/crypto_policy.py` | **Resolved in design; feed addresses to be confirmed.** Measured on BSC mainnet on 2026-11-20: a feed at `0x264990fbd0A4796A3E3d8E37C4d5F87a3aCa5Ebf` reports `description() = "BTC / USD"`, 8 decimals, last update 45 seconds old; a feed at `0x86896fEB19D8A607c3b11f2aF50A0f239Bd71CD0` reports `"XAU / USD"`, 8 decimals, last update about 10 minutes old. Both were within 0.2% of the spot price of the PancakeSwap V3 pools the catalog routes use (USDT/BTCB fee 100, USDT/XAUt fee 500). The account checks every bitcoin or gold forced sale against these feeds (5.3). The addresses are constants of the implementation, not a Safe list. Three caveats: the two addresses were recalled and then checked on-chain, and must be matched against Chainlink's published list before they are hard-coded; BTCB and XAUt are pegged tokens, not the feed's underlying, so the tolerance must allow for a peg gap; the maximum feed age (numbers table) is a few heartbeats: both feeds run a 600-second heartbeat on BSC, and XAU / USD keeps updating on weekends (an earlier version of this row assumed it stopped while the gold market is closed and set 26 hours; corrected 2026-11-21 to 2 hours). If Chainlink ever lengthens a heartbeat past the limit, only that token's forced sales stop, which is fee collection, never user funds; a stale feed refuses the sale and it is retried. A pool TWAP was considered as the reference and rejected: the pool would have to be a fixed address too, and a thin pool's TWAP is cheap to move. `Buy` rules get no feed check; their exposure is bounded by the rule's amount per run |
| C3 | Decision 4(a) included automatic saving; decision 5 rejects approvals from the personal wallet, so nothing can pull income into the account | Decisions 4 and 5 | **Resolved (decision 17).** Saving is removed. There is no cUSD/cUSD+ conversion in the account: a user holds one of the two |
| C4 | The user pays the same 0.9% everywhere; this is only about the referrer's half of it. That share is paid when `CusdVault.armReferral` is the first call of the transaction, and `armReferral` accepts only a 7702-delegated EOA as caller. In an owner-signed batch the owner's EOA can arm before calling the account, so trades and deposits the owner signs still pay the referrer. In a relayer-originated transaction (`executeRule` buys and bank payments, `forcedSale`, `convertUsdt`) no EOA is in the call chain, nothing is armed, and Confío keeps the whole fee | `CusdVault.sol:282-284, 315-319, 330-342`; `cusd_plus/fee_referral.py` | **Resolved (decision 32).** `CusdVault` is extended as described in section 7.4 |
| C5 | The probe told users a different product: bank-rail automatic payments, merchant subscriptions and debit control at US$9.99 | `assistant/prompts.py:155-162`; `apps/src/screens/PaidOfferScreen.tsx`; probe plan "The two offers" | **Resolved (decisions 2, 18, 20).** Automatic payments to CLABE, Pix and Bre-B are built; merchant subscriptions are dropped; the price is the launch price with no separate notice |
| C6 | A user-signed cancellation returns assets to the owner's wallet at period end. If the owner cancels and then dies before the period ends, the assets go to a wallet nobody can open, and a pending claim cannot stop it without letting an unpaid account keep coverage | Decisions 7, 8 and 9 | **Not answered; default kept.** The return wins, which is what decisions 7 and 8 say as written. The cancel screen states that cancelling ends beneficiary coverage |
| C8 | New with decision 34. Owners ask to "pause" a rule; the contract has `cancelRule` and `updateRule`, no pause | `ConfioSmartAccount.sol` (`cancelRule`) | **Mapped, no contract change.** "Pausar" is a stop; the assistant says the rule can be created again |
| C9 | New with decision 34. Owners ask to "save X a month"; there is no saving rule | Decision 17 | **Mapped.** The assistant explains that the owner's dollar already is the balance and offers send, payment or buy |
| C10 | New with decision 34. An alert's attached buy is a one-time intent, but the app has no manual trade inside the account yet (8.1) | Section 8.1; `prepareSmartAccountTrade` exists on the server only | **Open.** The trigger chip opens the rule screen with a monthly Buy prefilled and the note says to stop the rule after the first run if only one purchase was wanted. When the account's trade screen is wired, the chip should open it instead |
| C11 | New with decision 34. A day of the month above 28 does not repeat every month (the backend's calendar clamps to the month's last day and then stays there) | `smart_account/automation.py:next_slot` | **Mapped.** Days 1 to 28 only; the assistant asks for another day |
| C7 | New with decision 18. A payment rule pays a bank account, but the contract can only see an on-chain address, and that address cannot be fixed in advance | Decisions 12 and 18; `payment_accounts/local_money.py`, `bridge.py:66-86`, `relay.py`, `infinia_journeys.py:88-95` | **Resolved (decision 29): option (a).** The BSC-side recipient of a bank payout is a bridge deposit address created for each transfer, so no fixed list of addresses, in the Safe or anywhere, can describe it. What the contract binds is the rule the owner signed: token, amount, frequency. Consequence, stated plainly: for an account that has a payment rule, a compromised relayer key could send up to that rule's amount, once per period, to an address of its choosing. Accounts without payment rules are not exposed, and send rules are not exposed (their payee is fixed). Ways to narrow it that were considered: (a) accept it, with the exposure equal to what each owner chose to automate; (b) the owner also sets a monthly cap for all payment rules together, stored on-chain; (c) replace the deposit-address bridge with a bridge contract call whose Polygon recipient is a call parameter, store the user's own provider funding address in the rule, and have the account build the call, so funds can only reach the user's own provider account. Whether such a bridge call exists for this route was not verified. The founder chose (a); (b) and (c) are not built |

### 9.3 Open points

Closed by the founder on 2026-11-20:

| # | Was | Answer | Recorded as |
|---|---|---|---|
| O1 | Self-custody of stock tokens in a user-owned contract; handling of an ineligible new owner | Closed | Decision 19 |
| O2 | How waitlist members who answered at US$9.99 are told about US$14.99 | No separate notice | Decision 20 |
| O3 | Positioning | Closed | Decision 21 |
| O4 | Residual risk for a living owner who misses every notice | It goes on the screen | Section 8.3, item 7 |
| O5 | Annual plan cancellation | No refund; runs to expiry | Decision 22 |
| R1 | A previous owner who lost the account through an executed claim could never open a new one from the same wallet | Resolved: re-open allowed. The factory keeps one current account per owner, with a generation in the CREATE2 salt; the inherited-withdraw destination is checked by code hash and owner, not by salt (founder, 2026-11-21) | Decision 33 |
| O7 | Scope of "works even if Confío disappears" in copy | No copy rule | Decision 28 |
| S1 | Immutable or upgradeable account instances | Immutable | Decision 23 |
| S3 | How a price change reaches subscribers | From the next renewal | Decision 24 |
| S4, S5 | Rules, fee and forced sales while a claim is pending | All continue | Decision 25 |
| S6 | Designation made directly on-chain | Not possible; sponsor gate | Decision 26 |
| S7 | Legal review | Outside this document | Decision 28 |
| S8 | Beneficiary acceptance | Required; designation and acceptance times recorded | Decision 26 |
| — | Waitlist rows after the probe | Kept | Decision 27 |
| C7 | What the contract binds for a bank payment | The signed rule only | Decision 29 |
| F1 | Free riding with tokens the contract cannot sell | Closed. Confío neither shows nor prices a token it does not handle, so such a token is outside the product; nothing is built for it. (On-chain it would still move with the account on an ownership transfer; accepted.) Presale CONFIO cannot be inside. Unlocked CONFIO becomes sellable under 5.5 | Founder, 2026-11-20 |
| F2 | USDT held in the account | Closed. USDT does not stay as USDT: it is converted into the owner's Confío dollar automatically, as in the personal wallet (`convertUsdt`, section 4.6), and is then an ordinary fee source | Founder, 2026-11-20 |
| C4 | Referral share on automated activity | `CusdVault` is modified | Decision 32 |
| O6 | Exact numbers | Confirmed as listed in the table below | Numbers table |

Still open:

| # | Open point | State | Who decides |
|---|---|---|---|
| C2 | Match the two feed addresses against Chainlink's published list before they are hard-coded | Design resolved (9.2); tolerance and feed age are in the numbers table | Engineering, in the contract audit |
| C6 | A claim pending when a signed cancellation expires | Default kept: the return wins (9.2). Not answered by the founder | Founder, if he wants it otherwise |
| P1 | Which rails are live for payment rules at launch. CLABE and Pix keys have an adapter (7.5, as built); Bre-B has none and stays off. Open: the provider's terms and limits (X9) and one founder-run live payment per rail | Built, not run with real money | Founder |

Positioning for store review (decision 34), stated as facts about the product:

- The free assistant answers questions and gives general guidance. It moves nothing.
- Cuenta inteligente is a paid financial account. Its subscription is charged on-chain from inside the account (section 5), not through the stores. Nothing is sold in the app as a digital unlock and there is no in-app purchase.
- What the subscription adds to the assistant is the execution of automated transactions on the subscriber's own account: rules the owner signs, a target split kept by new purchases, alerts the owner sets, and a monthly review. Every transaction is authorised by the owner's signature.

Numbers (O6), all confirmed by the founder on 2026-11-20:

| Constant | Value | Origin |
|---|---|---|
| Challenge window, default | 180 days | Decision 9 |
| Challenge window, options | 90, 180, 365 days | Decision session |
| Claim cooldown after a cancel | 30 days | Decision session |
| Notice before a forced sale | 7 days | This document |
| Hard-coded floor for that notice in the account | 3 days | This document |
| Sale order when several non-dollar assets are held | Largest position by dollar value first; CONFIO included once its sale is switched on | This document, amended by decision 30 |
| Forced-sale proceeds cap | Shortfall plus 5%, plus US$1 | This document |
| Notice before a price change takes effect (`FEE_CHANGE_DELAY`) | 30 days | This document |
| Hard maximum fee in the account implementation | US$29.99 monthly, US$299.99 annual | This document; it is the ceiling no factory change can exceed for existing accounts |
| Time a named beneficiary has to accept | 30 days | This document |
| Minimum gap per frequency | 1, 7, 14, 28 days | Follows from decision 18's four frequencies |
| Forced-sale price tolerance against the feed (bitcoin, gold) | 3% below the feed, after the entry fee | This document; confirmed |
| Maximum feed age | 1 hour for bitcoin, 2 hours for gold (both feeds beat every 600 s, gold on weekends too); 26 hours for the CONFIO price reference (5.5; none exists yet and it may be a daily reference, the same bound the factory applies when it is set) | This document; gold corrected from 26 hours on 2026-11-21, founder accepted that a lengthened heartbeat stops only gold forced sales |
| Card rule period (decision 35) | Fixed periods of the frequency's minimum gap (1, 7, 14, 28 days) from the rule's first run; many pulls per period; no carry-over | Decision 35 |
| Card rule cap | The owner's `amountUsd` per period, gross of the 0.9% exit fee | Decision 35 |
| Payment rule cost limit | 150 bps of the USDT that leaves: the bridge's cost alone | Decision 36 |
| Payment rule fixed fee | The tariff on the day of signing, as a ceiling (tier 0: CLABE US$0.50, Pix US$0.10 per payment) | Decision 36 |
| Smallest CLABE or Pix rule | Follows the live quote; on the bridge cost measured 2026-09-15 (US$0.043 + 0.19%) about US$3.32, before any provider minimum | Decision 36 |
| Card pull exit | Exact USDT out; gross = `ceil(usdtOut * 10000 / (10000 - feeBps))`; cUSD+ redeems the gross plus 5 bps plus 10 wei, the excess stays as USDT | Decision 35 |
| Card switches | Spender allowlist and a global card pause, Safe-set in the factory, read on every pull | Decision 35 |

---

## 10. Rollout and tests

### 10.1 Rollout

| Step | What is on | Who | Exit condition |
|---|---|---|---|
| 0 | Contracts on BSC testnet and a mainnet fork; full test suite; Codex audit loop on the factory, the account and the collector until clean; a separate audit pass on the inheritance path (`setBeneficiary`, `initiateClaim`, `_ownerTouch`, `cancelClaim`, `executeClaim`, inherited `withdraw`) | Engineering | Both audit passes clean; fork tests green |
| 1 | Mainnet factory deployed by the documented production deploy path (never from a laptop), source verified on BscScan, ownership to the Safe, `inheritanceEnabled = false`. `SMART_ACCOUNT_ENABLED` for the canary list only. Automation and IA+ with small amounts | Canary users | Fee collection, in-kind cUSD+ fee, one rule of each kind, a payment failure with notice, a forced sale of a stock and of a crypto token, and a cancel-and-return all observed on mainnet |
| 2 | The Safe sets `inheritanceEnabled = true` (it is global and one-way, and `setBeneficiary` reverts without it); the relay and `SMART_ACCOUNT_BENEFICIARY_ENABLED` still limit designation to the founder's account. The founder runs the whole claim and return flow with his own funds on mainnet: designation, acceptance, claim, cancel by an unrelated signed action, cooldown, second claim, full window, execution, inherited withdrawal to wallet and to the new owner's own account; and the direct on-chain path with the server not involved. With the 90-day minimum window and the 30-day cooldown this run takes at least about 120 days of chain time. The same sequence is run first on a mainnet fork with time advanced, which takes minutes | Founder | Every step observed on the fork and on mainnet; discrepancies fixed and re-audited. Whether step 3 waits for the mainnet run to finish, or follows the fork run plus the mainnet steps completed so far, is the founder's call |
| 3 | `SMART_ACCOUNT_BENEFICIARY_ENABLED` on for everyone; the beneficiary screens appear | All subscribers | — |

General availability of step 1 (beyond the canary list) is a founder call and does not depend on step 3.

Before any push or deploy at any step: the Codex audit-and-fix loop until clean.

### 10.2 Contract tests

Foundry unit tests plus a BSC fork suite against the live vaults and routers. Derived from the invariants (I-n) and the state machine.

Lifecycle and billing:

| Test | Covers |
|---|---|
| Subscribe takes the first fee in cUSD; in cUSD+ only; split across both; reverts when short | 5.1, I-3 |
| In-kind cUSD+ fee: shares taken equal `ceil(fee / pPlus)`; no conversion fee is charged; user's remaining shares are worth balance minus fee | 5.1 |
| Second `collectFee` in the same period reverts; `collectFee` before `paidUntil` reverts | I-3 |
| Relayer cannot change fee, plan, owner, beneficiary or rules (every setter reverts for the relayer) | I-4 |
| Late payment starts the new period at payment time | 5.2 |
| `PaymentDue` blocks `executeRule` and `trade`; allows `withdraw`, claims, deposits | 4.9 |
| A scheduled price change: a renewal before `effectiveAt` pays the old price, one after pays the new; a factory that returns more than the hard maximum is clamped; a reverting factory does not block `withdraw`, `returnAsset` or claims | Decision 24, I-3, I-20 |
| `forcedSale` before notice, before the notice period ends, twice in one period, with enough dollars present, on cUSD/cUSD+: all revert | I-5 |
| Forced sale of a stock: proceeds land in the account as cUSD+, within the cap, and the fee is collected in the same call | I-6 |
| Forced sale of a crypto token to cUSD+ and to cUSD: same | I-6 |
| Diversified holdings: an annual subscriber with two positions, each worth less than the fee and together worth more, is charged by one operation with two legs; the aggregate cap holds; a second operation in the period reverts; if the legs together still fall short the whole call reverts and nothing is sold | 5.3, I-5, I-6 |
| CONFIO: `forcedSale` reverts while `confioSale` is unset; the Safe can set it once and a second set reverts; once set, a CONFIO sale obeys every cap of 5.3; the slot affects no other token, destination or fee | Decision 30, 5.5 |
| Forced sale of bitcoin or gold through a manipulated route is refused by the feed check; a feed older than its maximum age (2 hours for gold) reverts the sale and a later retry succeeds; fork test reads the two live feeds and asserts both are within their limits | C2 |
| **Failed sale**: the venue reverts (paused router, expired quote, closed market). The account stays `SaleAllowed`, nothing is returned, `returnAsset` reverts, a retry later succeeds | Decision 7, I-7 |
| **Death with only bitcoin**: an account holding only BTCB, owner never signs again. Each period: notice, wait, forced sale of one fee's worth, fee collected. The beneficiary initiates, fees and sales continue through the window without cancelling the claim, the beneficiary executes and withdraws the remaining BTCB. No asset reaches the old owner's wallet at any point | Decisions 6, 7, 8, 9; I-5, I-8 |
| Account worth less than one fee stays paused; nothing is taken partially; nothing is returned | 5.2 |
| Cancel: automation runs until `paidUntil`; `returnAsset` reverts before it and works after it, for any caller, to `owner` only | I-7 |
| Return per asset: a token that reverts on transfer (paused cUSD, paused cUSD+, frozen address, a reverting mock) does not block the others | Decision 7 |
| `returnAsset` without a signed cancellation reverts in every billing state | I-7 |
| `undoCancel`; re-subscribe after `Expired` | 4.9 |
| Re-subscribe after `Expired` (assets returned): old Send, Payout, Buy and Card rules (with their old count) are dead, cannot be updated, and `rule(id)` reads inactive; the old beneficiary and pending designation are gone and a new designation works; new rules work; a renewal by `collectFee` or forced sale, `changePlan`, cancel and undo do not change the epoch; `cancelRule` works while `Expired`, `CancelPending` and `PaymentDue` and stays owner-only; property test tracks the epoch per rule | P3-1, I-22 |
| USDT that covers the fee gap net of the entry fee blocks `startPaymentNotice` and `forcedSale` (one wei less does not); USDT dust does not block a sale | P3-2 |
| `changePlan` in both directions, with a dollar balance between the two prices: annual to monthly renews without a notice or sale when the balance covers US$14.99; monthly to annual starts a notice when it does not cover US$149.99; the current period is untouched; the next renewal charges the new plan's price for the new plan's length; the relayer cannot set or alter `nextPlan` | I-3, I-4 |
| `cancelSubscription` while payment is due makes the account `Expired` at once; `returnAsset` works immediately; no forced sale can follow | 4.9 |
| A payment notice started under one subscription does not survive cancel and re-subscribe: the next missed payment needs a new notice and the full notice period before any sale | I-5 |
| A contract that is a sponsor (a router) calling a relayer function reverts; only a sponsor that is also `tx.origin` passes | 4.1 |
| `forcedSale` sells and collects in one transaction; if the fee rose so that proceeds no longer cover it, the whole call reverts and can be retried | 5.3 |
| No allowance remains after `trade`, `executeRule`, `forcedSale` | I-14 |
| `relayerPaused` blocks only relayer functions | I-15 |
| Referral: an account created by the factory can arm and the referrer is paid on a rule buy, a forced sale and a USDT conversion; an arbitrary contract still cannot arm; a relayer call without the optional referrer keeps the whole fee; `referrer == owner` reverts; existing EOA arming is unchanged | Decision 32 |
| USDT from a stock buy or a direct transfer is converted by `convertUsdt` into cUSD+ or cUSD held by the account, only by the relayer, never to another recipient, never below the fee-adjusted floor; a USDT deposit into an unpaid account converts and then pays the fee; USDon dust is withdrawable and returnable | Decision 31, N6 |

Rules:

| Test | Covers |
|---|---|
| A send rule delivers cUSD+ to an eligible payee and cUSD to an ineligible one from either source dollar; in every form the only recipient is the stored payee and the account holds none of the other dollar afterwards | 4.7, decision 17 |
| A send rule pays only its stored payee, amount and token, at most once per minimum gap of its frequency; the relayer cannot alter any of them | I-1, I-4, decision 16 |
| A payment rule exits at most its amount, at most once per minimum gap, and emits its `payoutRef` and destination; works from cUSD and from cUSD+; an account with no payment rule has no path by which the relayer can send dollars to an arbitrary address | I-1, C7 |
| Each frequency (daily, weekly, biweekly, monthly) enforces its minimum gap | Decision 18 |
| Rule amounts are dollars: with cUSD+ as `tokenIn`, runs before and after a rise in `pPlus` move the same dollar value and a different share count; the share limit is computed in the call, not supplied by the relayer | 4.4 |
| A buy rule spends at most its amount; delivers the asset to the account; reverts if another balance falls | 4.7 |
| Missed runs are not caught up | 4.6 |

Inheritance:

| Test | Covers |
|---|---|
| `setBeneficiary` reverts while `inheritanceEnabled` is false; reverts for self, zero, a disallowed window | 4.6 |
| `setBeneficiary` and `acceptBeneficiary` sent directly (no sponsor as `tx.origin`) revert, from the owner and from the named address | Decision 26, I-18 |
| A claim's execution time is fixed at initiation: re-naming the same person with a shorter window and accepting during a pending claim does not bring execution forward; a different person accepting ends the old beneficiary's claim and emits `ClaimCancelled` | I-10 |
| Re-naming the current beneficiary while their claim is pending cancels the claim and starts the cooldown, and accepting the re-designation does not clear it | 6.4, I-11 |
| A named but not yet accepted beneficiary cannot initiate or execute; after acceptance they can; the previous accepted beneficiary keeps their standing until the new one accepts and loses it at that moment | I-19 |
| Only the beneficiary can initiate and execute; everyone else reverts, including the relayer and the Safe | I-8, I-10, I-16 |
| `executeClaim` one second before the window ends reverts; at the window end succeeds | I-10 |
| **Claim versus cancel ordering**: an owner transaction and `executeClaim` in the same block, in both orders. Owner first: the execution reverts. Execution first: the old owner's transaction reverts and changes nothing | I-9, I-13 |
| Every owner function cancels a pending claim (one test per function), including `withdraw` of a zero-value token and `cancelClaim` appended to an unrelated batch | I-9 |
| **Fee deduction does not cancel a claim**: `collectFee`, `startPaymentNotice`, `forcedSale`, `executeRule`, `convertUsdt` and `returnAsset` each leave `claimStartedAt` unchanged | I-8 |
| Rules, fee collection and forced sales all succeed while a claim is pending | Decision 25 |
| **Repeated claims**: claim, cancel, immediate re-claim reverts during the cooldown; after it succeeds; many cycles do not move any asset and do not shorten the window | I-11 |
| `removeBeneficiary` during a pending claim; `setBeneficiary` naming someone new during a pending claim cancels that claim with cooldown; the old beneficiary keeps standing until the new one accepts and loses it at that moment | 6.4 |
| Execution resets every field listed in 6.5 and moves no token | I-12 |
| After execution: relayer functions, `subscribe`, `setBeneficiary`, `acceptBeneficiary`, `createRule`, `trade` revert; the previous owner's calls revert | I-12, I-13 |
| Inherited withdraw to the new owner's wallet; to the new owner's own account (any generation); to any other address reverts; to a contract that is not a clone of the implementation reverts; to a zero `accountOf` when the new owner has none reverts | I-1 |
| Inherited withdraw to `accountOf(owner)` reverts when that account has itself been inherited by someone else | Decision 10 |
| A pending designation lapses 30 days after naming; `acceptBeneficiary` then reverts | 4.4 |
| `withdrawDesignation` clears only the pending entry and leaves the accepted beneficiary able to claim; `removeBeneficiary` clears both | 4.6 |
| After a successful forced sale `noticeStartedAt` is zero; the next unpaid period needs a new `startPaymentNotice` and the full notice before any sale | I-5 |
| The cooldown is clamped: a factory returning zero, a huge value or reverting neither removes the cooldown nor makes an owner call revert | I-9, I-20 |
| A claim pending when a signed cancellation expires: the return works and the claim cannot execute | C6 |
| Bytecode checks: the implementation contains no `DELEGATECALL`, `CALLCODE` or `SELFDESTRUCT`; a deployed account's runtime code equals the EIP-1167 pattern with the expected implementation address | Decision 23, I-20 |
| The direct path: `initiateClaim`, `executeClaim` and inherited `withdraw` sent as plain self-paid transactions with no sponsor in the call chain | 6.7 |
| Factory: one current account per owner: `createAccount` reverts while the current account is still the caller's (never subscribed, active, cancel pending, expired, claim pending, claim executable); after it is inherited, `createAccount` deploys at generation + 1, moves `accountOf`, keeps `isAccount` true for the old one, and `predictAddress` equals the deployed address before each creation; the Safe has no function over account assets | I-16, I-17, decision 33 |

| Card rule (decision 35): creation needs an allowlisted spender and clean fields; exact USDT out from cUSD and from cUSD+ with the minimal gross for any amount and any fee 0 to 90 bps (fuzz); many pulls per period up to the cap, reset at the fixed boundary, missed periods skipped, no carry-over; the cap holds for any sequence of pulls and waits (fuzz); only the stored spender; the relayer cannot run it; owner cancel stops it, update keeps the count; allowlist removed mid-period stops pulls and re-adding keeps the same cap; card pause stops pulls, the relayer pause does not; unreadable factory fails closed; payment due and expired refuse, cancel pending pulls; a pending claim does not block and is not touched, an executed claim ends every card; a spender re-entering through a token callback is refused; factory setters Safe-only, storage appended at slots 11 and 12; the cUSD+ pull through the live `redeemToUsdt` on the fork | Decision 35, I-1, I-15, I-21 |

Property tests (fuzzed sequences of calls by owner, beneficiary, relayer, a card spender and strangers): invariants 1, 2, 3, 8, 14 and 21 hold after every call.

Code size (EIP-170, 24,576 bytes; `forge build --sizes`, 2026-11-21). The account implementation was 24,543 bytes before decision 35. Measured options:

| Step | Account runtime (bytes) | Change |
|---|---|---|
| Before: optimizer 200 runs, no via_ir | 24,543 | |
| Compiler only, no via_ir: 1 / 50 / 100 runs | 24,292 / 24,338 / 24,347 | −251 at best |
| Compiler only, via_ir: 1 / 50 / 100 / 200 runs | 21,047 / 20,992 / 20,965 / 21,079 | −3,578 at 100 runs (chosen; `evm_version` cancun or prague: no difference) |
| + decision 35 (Card rule, as first written) | 22,691 | +1,726 |
| + calls to the two vaults through one `_call` helper instead of typed calls | 21,290 | −1,401 |
| + balance, `pPlus` and `feeBps` reads through one `_read` helper | 20,640 | −650 |
| + `isSponsor`, clone `owner`/`inherited` and `decimals` reads through `_read` | 20,284 | −356 |
| + card pull redone through each dollar's own exit to the account, then a push (cUSD+ `redeemToUsdt`) | 20,233 | −51 |
| Final (via_ir, 100 runs) | **20,233** | 4,343 bytes of headroom |

Rejected after measuring: factory-read calldata built in assembly (+132 under via_ir); three public limit constants made internal (−126, not needed, kept public so the limits stay readable on chain); a separate immutable helper contract for the forced-sale feed check (about −390 net of the extra call site; not needed, one contract fewer to audit). The `nonReentrant` guards cost 308 bytes over 12 functions and stay. The factory is 10,437 bytes. Tests read time with `vm.getBlockTimestamp()`: under via_ir a `block.timestamp` read after `vm.warp` in the same test can be stale. The implementation must be verified on BscScan with via_ir and 100 runs.

### 10.3 Backend and app tests

- Policy: a batch whose inner call targets an account not registered to the signer is refused; selector outside the allowlist refused; deposit to someone else's account refused; `cancelClaim` is present in prepared batches while a claim is pending.
- JWT: a `smart` context cannot reach P2P, payroll, presale, perps, ramps or Comprar; a business or employee context cannot reach any Cuenta inteligente mutation; no mutation accepts an account id or address as authority.
- Tasks: each is idempotent under a double run and a crash between sign and broadcast; an RPC or quote failure leaves state unchanged.
- Designation: unverified beneficiary refused; ineligible-by-residence refused; disclosure not accepted refused; checks re-run at acceptance; `designated_at` and `accepted_at` both stored; a declined designation records `declined_at` and sends no transaction.
- Payment rules: the standing authorization is created only with Face at rule creation and is bound to destination, amount, frequency and, on Pix and CLABE, the fixed-fee ceiling (decision 36: a raised tariff skips and asks for a signature, a lowered one charges the lower); a run whose bridge cost or FX rate is outside the rule's limits is skipped and notified; a payout method that is not the viewer's is refused; an edited or deleted method deactivates its rule; a rail not confirmed for unattended payouts is not offered.
- Offer: annual is the default plan; prices are 14.99 and 149.99, read from the factory with settings as fallback.
- Entitlement: IA+ on at `FeeCollected`, off after `paid_until`, never on for an inherited account.
- Re-open (decision 33): a previous owner whose account was inherited sees the plans again; the subscribe batch creates the account at `factory.predictAddress(signer)` and the policy accepts exactly that address and refuses the inherited one; reconcile gives the second `AccountCreated` index 0 without an ops alert (an `AccountCreated` while the owner's current account is still theirs on chain is still alerted); the new subscription grants IA+; an inherited withdraw can go to the heir's own new account.
- App: subscribe, move everything, rule creation, cancel, claim and inherited withdrawal on a real device; the claim-pending banner appears in every account context; older builds never receive the new GraphQL fields in shared queries.
- Local tests must patch the Telegram alert path (they otherwise reach the real channel).
- Assistant operation (decision 34), in `smart_account/tests/test_assistant_ops.py`: tools offered only to subscribers, never to employees or free users; one proposal and one chip per reply; amounts, assets and percentages must be the owner's own words (the assistant refuses to choose a split; the provenance table is `smart_account/tests/test_owner_words.py`, the payout sheet and proposal `test_payout_provenance.py`); proposals validate payee, asset, minimums and first-run days; a stop proposal is a cancel; target split: the parts add up to the total, the drift re-split sends new money to the underweight asset, keeps every asset at its minimum, never proposes a sale, and says when the total is too small; nothing inside the threshold proposes nothing; the monthly review counts runs and reasons and the monthly note is posted once per month; both new tasks are off without `SMART_ACCOUNT_ENABLED`; first-run bounds and the edit floor; alerts need the owner's level, are saved only on the owner's "sí" to that message, trigger once per cooldown with a signable prefilled buy and nothing on chain, stay quiet above the level, cap at 10, and delete only for the owner; `assistantRuleProposal` returns only the owner's own message. App: the proposal chip is tap-only with a fallback, the proposal maps to rule-screen params and drops malformed values, the rule screen opens prefilled and editable, passes the first run, drops it for daily rules, opens the stop confirmation, and chains multi-step proposals; the alerts list and the trigger notification route.

### 10.4 Audit gates

| Gate | When |
|---|---|
| Codex audit-and-fix loop on all three contracts until clean | Before testnet deploy and again before mainnet deploy |
| Separate audit pass limited to the inheritance path | Before step 1 (the code ships then even though the switch is off) and again before step 3 |
| Codex audit of the relayer path (`send_relayer_call`, the new policy branch, the tasks) | Before step 1 |
| Codex audit of the `CusdVault` upgrade (`armReferral` caller rule, appended storage), with the storage layout diffed against the live proxy | Before step 1 |
| Re-audit of any change made after step 2 | Before step 3 |
| Bytecode of the deployed factory and implementation matched against the source | At mainnet deploy |
| X1 closed (swap router bytecode matched) and X2, X3 measured | Before step 1 |

---

## 11. Out of scope for v1

- A second tier, a "Bóveda" brand, any fee waiver or discount.
- Automatic saving and any cUSD/cUSD+ conversion inside the account.
- Merchant subscriptions and debit control.
- Refunds.
- Upgradeable account instances.
- More than one beneficiary, percentage splits, contingent beneficiaries, beneficiaries who are not verified Confío users.
- Locked presale CONFIO, presale purchases from the account, any change to `ConfioPresaleVault`.
- Futures/perps inside the account.
- Business accounts and employees.
- Automatic pulls from the personal wallet (decision 5); a card; bank rails not confirmed for unattended payouts.
- Deposits delivered straight from a ramp to the account address.
- Changing the owner wallet of an account other than by an executed claim.
- Trading, automation or a beneficiary on an inherited account.
- A heartbeat or any Confío-run liveness signal.
- A settlement fee at claim; beneficiary coverage after the subscription lapses.
- Store billing or in-app purchase.
- Automated selling of any kind, including to keep a target split (decision 34 keeps it with new buys only); a pause state for rules.
- Portuguese or other non-Spanish UI strings.
- Changes to `CusdPlusVault`, `ConfioStockRouter`, `ConfioSwapRouter` or `ConfioBatchDelegate`. The feature is built on their current interfaces. The one change to an existing contract is `CusdVault.armReferral` (decision 32).
