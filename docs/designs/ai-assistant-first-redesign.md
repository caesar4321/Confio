# Design: Confío as an AI assistant that pays (assistant-first redesign)

Date: 2026-11-21
Status: DESIGN BRAINSTORM, nothing built. Recommendations below are proposals for the founder to decide.
Builds on: [`confio-assistant.md`](confio-assistant.md), [`confio-assistant-three-jobs.md`](confio-assistant-three-jobs.md), [`assistant-first-steps-guide.md`](assistant-first-steps-guide.md), [`cuenta-inteligente-spec.md`](cuenta-inteligente-spec.md).

The repository is public. This document contains no user identifiers, names, chat excerpts, counts of users or revenue, and none may be added. Evidence is described qualitatively.

---

## 0. Summary

**North Star.** Confío becomes a general-purpose assistant for Latin America whose edge is that it can actually pay, with the user's self-custody dollars, on the national instant rails (Pix, Bre-B, QR interoperable in Argentina, Pago Móvil, Bolivia QR, Yape/Plin later). The first job done end to end is **"pagá este QR con mis dólares"**. Everything else widens from it.

**Recommendations, one line per stage.**

| Stage | Recommendation |
|---|---|
| 0, now | Fix what blocks the shipped QR payment before promoting it (Pix charges are refused on prod today, section 2.3), accept a pasted Pix "copia e cola", and make QR payment one step of the existing first-steps guide. No new money flow |
| Approval UX | **Option C: a payment card in the chat plus a system-owned signing sheet.** The card shows only what the server resolved and the rail validated; tapping "Revisar y pagar" opens a native sheet the model cannot draw; Confío Face/biometrics, then the existing EIP-712 sign flow. The chat never contains a pay button |
| 1 | The assistant can prepare a payment from the chat (QR shared or pasted into the chat, a saved payee) using that card. One job only: QR payments on the live Infinia rails |
| 2 | **The conversation is the home, no tab bar** (DECIDED 2026-11-21, section 7): Pagar is the primary round button at the composer's right (➤ when typing); header with the one-line money summary, QR Cobrar and the bell; a drawer with the money block, Invertir, Comunidad, Comprar, Cuenta inteligente, Recientes and the profile merged with the account switcher; onboarding becomes the assistant's first messages. No A/B: ship with the old tabs behind a flag, compare before and after. Free = Confío prepares, you sign each time. Paid = Confío does it when it's due, inside limits you signed |
| 3+ | Widen by **paying other people's checkouts** (bus tickets, delivery, bills) through the QR or Pix code they already show, not through merchant integrations. Family abroad on rails that validate the payee. Tasks get a status, a receipt with the rail's reference, and refunds |

**Success metric (agreed, all stages).** Among people who let the assistant pay once, the share who let it pay again within 30 days ("repeat assistant payers"). Section 9 defines it.

---

## 1. Why this direction

- Agentic payments in rich countries run on cards (Meta's assistant pilots pay with Stripe Link; Pickle in Korea pays through a card issuer). A stablecoin there has to answer "why not my card". In Latin America everyday payments increasingly run on national instant rails that governments push over card networks. An assistant that holds a self-custody balance and has payout access to those rails can pay where a card-based assistant cannot follow.
- Zapia (Uruguay, very large user base, its own app since WhatsApp stopped allowing general-purpose AI bots on its Business API in January 2026) executes tasks but has no published payment rail. Mercado Pago's assistant is a financial helper inside its own ecosystem. Neither pays a third party's local QR from dollars.
- "Confío" means trust; a trustworthy assistant is the brand. Messages, reminders and answers are table stakes; payment is the engine.
- Evidence from the assistant's own logs (Oct 4 to Nov 21, described qualitatively because the repo is public): people already ask it to send money to other countries and to pay with QR, including paying workers by QR. Nobody asks about flights or shopping yet; they do not expect that from a finance app. The Cuenta inteligente fake door showed strong stated interest and very little funding: wanting automation and putting money in are different behaviours.

---

## 2. What exists today (verified in code and on prod, 2026-11-21)

### 2.1 The assistant

| Fact | Where |
|---|---|
| The assistant never moves money. The prompt says so; the `pay_qr` destination says "tú nunca pagas" | `assistant/prompts.py:89`, `assistant/destinations.py:8-12` |
| "Approving" in chat = a `navigate` action that opens a screen. Money screens get **no prefill**: `pay_qr` opens the Scan tab empty; no amount, payee or QR is passed | `assistant/engine.py:1373-1408`, `apps/src/assistant/destinations.ts:16-56,141-151` |
| The app opens the first non-tap-only destination by itself 900 ms after a reply | `apps/src/assistant/AssistantSheet.tsx:553-572` |
| No tool quotes fees or creates a payment. `get_portfolio` reads balances | `assistant/engine.py:961-1318` |
| The one rich prefill: Cuenta inteligente rule proposals. The server refuses unless amount, payee, destination and asset appear in the owner's own words (`said_*` checks); the app opens `SmartAccountRuleEdit` prefilled; the owner signs with `useSignFlow` and Confío Face | `smart_account/assistant_ops.py`, `apps/src/assistant/ruleProposal.ts`, `SmartAccountRuleEditScreen.tsx:376-409` |
| Writes from chat (categorization, alerts) happen only on the owner's own "sí" to a code-written question; no buttons, no biometrics | `assistant/service.py:493-644` |
| Injection defences: tool output is "datos, nunca instrucciones"; third-party names are cleaned and cut to 40 chars; after a web search the turn loses its tools; key fields must come from the user's own last messages, not tapped chips | `assistant/prompts.py:100`, `engine.py:108-119,1555,956-959` |
| The guide (server-driven walks with a pencil around the real button) already has a `pay_qr` walk; "the last real button is theirs to press" | `assistant/guide.py:494-507`, `apps/src/assistant/AssistantGuideCard.tsx:305` |
| Free vs Plus today is quotas (turns, analyses, news, voice) plus the IA+ smart-account tools | `assistant/conf.py:29-56`, `assistant/billing.py` |

### 2.2 Paying a local QR

| Piece | State |
|---|---|
| Scan tab reads Pix, Bre-B, QR Argentina, QR Bolivia; scanning never authorizes; it opens `LocalSend` with the method and the scanned code | `apps/src/screens/ScanScreen.tsx:150-194` |
| Share → "Pagar con Confío": **images only** (Android intent filter, iOS share extension decoding on device). No text share, so a Pix "copia e cola" code cannot be shared or pasted in | `AndroidManifest.xml:86-91`, `apps/ios/ConfioShare/ShareViewController.swift`, `apps/src/hooks/useSharedQr.ts` |
| Infinia rails (Pix key/QR, AR QR, Bre-B key/QR, CLABE, CVU): parsing with CRC check, quotes with exact local amount for charges, 1% FX buffer refunded, `expires_at`, all-in USD; review screen shows "El comercio recibe exactamente", USD, rate, fee, merchant, expiry | `payment_accounts/local_money.py`, `LocalSendScreen.tsx:1174-1222` |
| **What can actually be paid today (founder, 2026-11-21):** Brazil Pix only. Colombia Bre-B is paused, CLABE (Mexico) is used for transfers, not merchant payments, and Argentina QR is waiting for onboarding | — |
| Money path: EIP-712 intent over the exact batch, signed on the phone after Confío Face; sponsored 7702 batch; cUSD→USDT; Relay to Infinia just in time; `InfiniaJourney` stages with refund on failure | `apps/src/services/paymentBridge.ts:128-170`, `payment_accounts/bridge_execution.py:240-287`, `infinia_journeys.py` |
| Bolivia QR (Mesa de pagos): provider decodes the QR and returns the holder; **off on prod** (`BOLIVIA_QR_SEND_ENABLED=False`) | `ramps/bolivia_qr_send.py` |
| Venezuela Pago Móvil send (Pago ASAP): **live**; no payee name lookup | `ramps/pagoasap_send.py` |
| Dinaria: only implemented as an alternative Pago Móvil sender; no AR/BR/MX/CL/PE/EC payout code exists; KYB not done. No Peru (Yape/Plin) or Ecuador code anywhere | `ramps/dinaria_send.py` |

### 2.3 Two findings that change Stage 0

1. **Merchant Pix charges are refused on prod today.** A Pix QR with an amount is payable only when the bank validation answered `VERIFIED` (`local_money.py:991,1029`). The validation runs only when `INFINIA_ACCOUNT_VALIDATION_ENABLED` is on (`local_money.py:811`); on prod it is **False** (checked in the running settings), so every charge gets "No pudimos confirmar este cobro con el banco." Promoting "pagá el QR del comercio" before switching validation on would send people into a refusal.
2. **Without validation, the name shown is self-reported.** For a static Pix key or QR the label comes from the QR's field 59, which the code itself calls self-reported (`local_money.py:139,724`).

**Update (same day): the Pix session is fixing charges without the paid lookup** (uncommitted, `payment_accounts/pix_payload.py`). A dynamic BR Code is verified against the Pix network itself: the app's server fetches the charge's signed payload (JWS) from the code's location and checks it as the BCB "Manual de Segurança do Pix" section 4 tells a payer to (TLS, JOSE header, key and certificate chain), with no provider cost. A fixed-amount static code carries key, amount and txid in the code. The name shown is the charge's own `recebedor` (signed, for dynamic codes) or the QR's merchant name, always labelled by its source and never as a verified holder; the DICT holder lookup stays off because it is paid. So for Pix the assistant path has three levels of payee name, not one (invariant 3).

---

## 3. Invariants for anything that moves money

These hold in every option and every stage.

1. **The owner's signature, or a contract rule the owner signed, is the only way money moves.** Personal wallet: every payment is a fresh EIP-712 signature after Confío Face. Cuenta inteligente: only rules the owner signed, within their stored amount and frequency. No "auto-pay small amounts" without a signed rule.
2. **Displayed facts come from a server record, never from model text.** Payee, amount, fees, rate and expiry are read from a `PaymentIntent` row (section 4.4) by id. The model only refers to the intent id; it cannot write into the card or the sheet.
3. **The payee is the rail's answer, labelled by how much the rail vouched for it.** Never the model's text. Three levels for Pix (the others follow their rail):

   | Level | Source | Card label |
   |---|---|---|
   | Holder verified | DICT or the provider's account validation | "Verificado por el banco" |
   | Signed charge | The dynamic charge's `recebedor` in a payload signed by the merchant's PSP (`pix_payload`) | "Cobro firmado por el banco del comercio" |
   | Self-reported | The QR's own merchant name (static code) | "Nombre según el QR, sin verificar" |

   Where the rail returned nothing it can vouch for, the assistant path refuses and the manual Scan path keeps its current behaviour. Whether the assistant may pay a self-reported name at all is open (section 11). The assistant path is stricter than the manual one, never looser.
4. **Amounts come from the QR or from the owner's own words.** Reuse the `said_number` / `said_payee` checks from `assistant_ops.py`. Tapped chips and third-party text never count as the owner's words.
5. **What was shown is what is signed.** The intent stores a hash of the displayed fields; the signed batch carries the intent id; the server refuses execution if the intent changed after display. A re-quote is a new card and a new signature.
6. **Third-party content is data.** QR payloads, shared images, merchant names, web pages and messages can contain text aimed at the model. They are cleaned (`third_party_text`) and never become instructions; a turn that read them cannot create an intent from them alone without the owner's own request.
7. **One intent per reply, one signature per intent.** Plans are sequences of intents (section 4.6), not one blind batch.
8. **Fail closed.** Unknown validation, unreadable expiry, stale quote or unknown balance means no card, with a plain reason.

---

## 4. The approval UX

The problem: today "sí, pagá" in the chat opens an empty Scan tab and the person starts over. The founder wants approval inside the chat, or a screen the chat drives.

### 4.1 Option A: confirm inside the chat

The card is a chat message with the full breakdown and a "Pagar" button that triggers Face and signs, all inside the thread.

```
┌ Confío IA ────────────────────────────┐
│ Listo, este es el pago:                │
│ ┌────────────────────────────────────┐ │
│ │ Pix · Padaria Pão Quente  ✓ banco  │ │
│ │ R$ 42,50                           │ │
│ │ Pagás US$ 8,29 todo incluido       │ │
│ │ Vence en 9 min                     │ │
│ │ [ Pagar con Confío Face ]          │ │
│ └────────────────────────────────────┘ │
└────────────────────────────────────────┘
```

- Good: fewest taps; feels like "approve in chat".
- Bad: the pay button lives inside a stream of model text. The model can write text that imitates a card ("Pagado a …"), and people learn to trust anything card-shaped in the chat. A long, streaming, scrolling list is the worst place for screen-reader focus, large Dynamic Type and a countdown. A second "Pagar" in the thread can be tapped on a stale card.

### 4.2 Option B: a screen the chat drives

The chat opens a payment screen and fills it step by step as the assistant resolves things (payee looked up, quote fetched); the user watches and confirms at the end. The chat stays docked like the guide card.

```
┌ Pagar ─────────────────────────────────┐
│ 1 Destino   ✓ Padaria Pão Quente       │
│ 2 Monto     ✓ R$ 42,50                 │
│ 3 Cotización … calculando              │
│ [ Confirmar ]                          │
├────────────────────────────────────────┤
│ 💬 "Ya tengo el destino, cotizo…"      │
└────────────────────────────────────────┘
```

- Good: the confirm happens on a real payment screen; multi-step fits a checklist.
- Bad: two surfaces kept in sync by a model; watching a form fill itself is slow and feels like a trick; every new job needs a chat-drivable screen; the person still ends on a form, which is the thing the founder wants to remove.

### 4.3 Option C (recommended): card in the chat + system signing sheet

The chat shows a **summary card** rendered from the intent record, with "Revisar y pagar". Tapping it opens a **native sheet owned by the app** (not a chat message, visually distinct, impossible for model text to produce) with the full breakdown and the signing step. After signing, the sheet closes and the card updates in place with live status and the receipt.

```
Chat                                   Sheet (system)
┌ Confío IA ───────────────────────┐   ┌──────────────────────────────────┐
│ Encontré el cobro. Revisalo:     │   │ Pagar con Pix                    │
│ ┌──────────────────────────────┐ │   │ Padaria Pão Quente               │
│ │ 🟢 Pix · Padaria Pão Quente  │ │   │ Cobro firmado por su banco · Itaú│
│ │ Cobro firmado por su banco   │ │──▶│ El comercio recibe  R$ 42,50     │
│ │ R$ 42,50 · US$ 8,29 total    │ │   │ Tipo de cambio      5,20         │
│ │ Vence en 9 min               │ │   │ Comisión Confío     US$ 0,07     │
│ │ [ Revisar y pagar ] Cancelar │ │   │ Procesador          US$ 0,05     │
│ └──────────────────────────────┘ │   │ Pagás               US$ 8,29     │
└──────────────────────────────────┘   │ Vence 14:32 · si sobra, vuelve   │
                                       │ [ Pagar con Confío Face ]        │
After signing, the same card:          └──────────────────────────────────┘
│ ⏳ Pagando… (enviando dólares)    │
│ ✓ Pagado 14:24 · Comprobante E2E… │
```

Why C:

| Criterion | A | B | C |
|---|---|---|---|
| Owner's signature only | Yes | Yes | Yes |
| Spoofing by model text | Card-shaped text can imitate it | Low | **None: the signing step is a native sheet the model cannot draw** |
| Taps for the person | 2 (pay, Face) | 3+ | 3 (review, pay, Face) |
| Reuses existing pieces | New confirm in chat | New chat-driven screens per job | **The review block and sign flow of `LocalSendScreen` move into a sheet** |
| Accessibility | Hard (streaming list) | Good | **Good: the sheet is a modal with focus trap, scrolls at large type** |
| Multi-step plans | A stack of pay buttons | Checklist | Plan card, one sheet per step (4.6) |
| Stale-tap risk | High | Low | **Low: the sheet re-reads the intent and refuses expired or changed ones** |
| Feels like "approve in chat" | Yes | No | **Yes: the decision starts and ends in the chat** |

Amounts in the sketches are illustrative (R$ 42,50 at 5,20 is US$ 8,17, plus the two fees, US$ 8,29).

The founder asked for (a) or (b). C is (a) with the signing moved into a sheet the chat opens: approval stays in the chat, and the screen that moves money is not a chat message.

### 4.4 The record behind the card

A new server model, one row per prepared payment. Identifiers in English; copy in Spanish.

```
PaymentIntent
  id (opaque), owner account, created_by ('assistant' | 'scan' | 'share')
  source: shared_qr | pasted_code | saved_payee | owner_words
  rail_method_id (e.g. br_qr, ar_qr, co_qr, ve_pagomovil_send)
  destination_snapshot   # from resolve_destination(); masked key, institution
  validation             # rail's answer: state, holder_name, document (masked), checked_at
  amount_local, currency, amount_usd_debit, fee_confio_usd, fee_provider_usd, fx_rate, fx_buffer_usd
  quote_expires_at, charge_expires_at
  display_hash           # hash of every field the card and sheet show
  state: quoted → awaiting_signature → submitted → paying → paid
                         ↘ expired | cancelled | refused | failed → refunded
  journey_id / order_id  # link to InfiniaJourney or ve_send order once signed
  message_id             # the assistant reply that showed it
```

- The assistant gets one tool, `prepare_payment(source, …)`. It resolves, validates and quotes, creates the row, and returns the facts plus the id. It moves no money and has no side effect beyond a quote and a validation call (rate-limited per owner).
- The app reads the card with an isolated query `assistantPaymentIntent(messageId)`, the same pattern as `assistantRuleProposal`, so the shared thread query is unchanged on older builds.
- The sheet calls the existing `preparePaymentBridge` with the intent id; the server refuses if `display_hash` no longer matches or the intent is not `awaiting_signature`.
- The card's status comes from the journey; it never says "Pagado" until the rail's completion arrives.

### 4.5 Failure and expiry states (card copy)

| State | Card says | Action |
|---|---|---|
| Validation not verified | "El banco no confirmó este destino. No puedo pagarlo desde el chat." | "Abrir en Pagar" (manual path, current rules) |
| Charge expires in under 10 min | "Este cobro vence muy pronto. Pedile al comercio un QR nuevo." | none |
| Quote expired before signing | "La cotización venció." | "Cotizar de nuevo" → new figures, new signature |
| Not enough balance | "Te faltan US$ X. ¿Recargás?" | Recargar walk (existing) |
| Paying, rail slow | "Pagando… puede tardar unos minutos." | Ver estado |
| Failed, refunded | "No se pudo pagar. Te devolvimos US$ X a tu saldo." | Ver comprobante |
| Under review | "Estamos revisando este pago. Tu dinero está seguro." | Ver estado |
| Already paid | "Ya pagaste este cobro." | Ver comprobante |

### 4.6 Multi-step plans

"Pagá la luz y mandale 50 a mamá" becomes a **plan card** listing the steps. Each step is its own intent with its own sheet and signature, in order ("1 de 2"). Different rails have different expiries, so v1 never signs several rails in one batch. Anything repeating ("cada mes") is not a plan: it is a Cuenta inteligente rule proposal (existing, paid).

### 4.7 Accessibility

- The card has one accessible summary: "Pago con Pix a Padaria Pão Quente, verificado por el banco, 42 reales con 50, total 8 dólares con 29, vence en 9 minutos".
- The sheet is a modal: focus moves to its title, the breakdown is read before the pay button, it scrolls at the largest Dynamic Type (the known Confío Face pop-up scroll issue must not repeat), and it respects reduce-motion.
- The countdown is announced at 5 and 1 minutes, never every second.
- The Face step keeps its existing fallback.

---

## 5. Stage 0: now (make what shipped work and discoverable)

### Directions considered

| Direction | What | Verdict |
|---|---|---|
| 0a Promote now | Push "pagá cualquier QR con tus dólares" to funded users in Brazil | Not before the Pix fix lands: charges are refused today (2.3) |
| 0b Guide step | Add "Pagar un QR" to the first-steps ladder where a QR rail is live; the `pay_qr` walk exists | **Yes** |
| 0c Paste code | Scan accepts a pasted Pix "copia e cola"; share accepts text, not only images | **Yes**: checkouts show copy-paste codes more than printable QRs |
| 0d Assistant answers | When asked to pay, the assistant opens Scan in "pagar" mode with the walk, and says which countries work | **Yes**, copy change only |

### Recommendation

1. Land the Pix session's fix (charges verified through the Pix network's signed payload, no paid lookup), then test one real dynamic and one static merchant Pix charge end to end on prod.
2. Accept pasted and shared text codes (server `pix_code` and `normalize_value` already parse them; this is an app change: a "Pegar código" button on Scan and a text share target).
3. Add the ladder step and fix the assistant copy (`destinations.py` `pay_qr`, `prompts.py`) to name where QR payment works today: Brasil (Pix) only, until Argentina QR is onboarded and Colombia Bre-B resumes.

Reuses: Scan, `LocalSend`, Infinia journeys, the guide. Backend: one flag plus a validation-cost check. Contract: none.

- **Metric:** repeat QR payers (people who paid a QR once and paid another within 30 days), split by entry: guide, assistant, share, camera.
- **Riskiest assumption:** people holding dollars in Confío want to spend them at local merchants, not only hold or send them.
- **Cheapest test:** the ladder step plus one push to funded users located in Brazil, plus the founder and a few Spanish-speaking testers there; count first and second QR payments over 30 days.

---

## 6. Stage 1: the assistant prepares a payment in the chat

### Directions considered

| Direction | Verdict |
|---|---|
| 1a The chat accepts a QR (camera button, shared image, pasted code) and returns a payment card | **Yes**, the first job |
| 1b The chat pays saved payees by name ("pagale a la panadería") | Later in this stage, once payees exist (Stage 2 memory) |
| 1c The chat pays new people from typed details | No: no name validation on Pago Móvil; typos lose money |

### Recommendation

Ship option C for QR payments on the live Infinia rails only:

- A camera/paste button in the chat composer. A QR shared into Confío while the chat is open goes to the chat.
- The tool `prepare_payment`, the `PaymentIntent` model, the card, the sheet, the status updates (sections 4.3 to 4.5).
- Venezuela Pago Móvil, Bolivia QR and any rail without name validation stay on the manual screens until their rail can verify the payee.

Reuses: `resolve_destination`, quotes, `require_payable_charge`, the bridge sign flow, the journey stages, the rule-proposal pattern (isolated query, message-bound proposal). New: the intent model, the tool, the card, the sheet (built from the `LocalSendScreen` review block), `display_hash` checking in the bridge prepare.

- **Metric:** repeat assistant payers (section 9). Secondary: card-to-paid conversion; time from card to signed.
- **Riskiest assumption:** people trust confirming a payment that started in a chat. The verified-by-bank badge must carry that trust.
- **Cheapest test:** behind a flag for a small tester group in Brazil; compare completion and abandonment of card payments with the same people's manual Scan payments.


### 6.1 Language: Spanish only for now (recommendation, 2026-11-21)

Brazil Pix being the only payable rail raises the question of Portuguese. Recommendation: **no Portuguese UI yet.**

- **Who pays Pix with Confío dollars:** most plausibly Spanish speakers in Brazil (Argentine visitors, Venezuelan and Bolivian residents), for whom spending dollars locally is the point. A Brazilian already has Pix and a real account, and Brazilian residents cannot use Dollar+ or stocks.
- **Evidence (aggregate, prod):** people located in Brazil are a small share of monthly actives, and the ones who talk to the assistant write mostly in Spanish; very few write in Portuguese.
- **The merchant never sees the app.** Only the payer's language matters.
- **Cost:** the app's copy is Spanish inline in every screen; Portuguese means every screen, the assistant prompts, the store listing, legal documents and support. The assistant already answers in the language it is asked in, which covers the few Portuguese speakers by conversation. The conversation-first home (section 7) shrinks the fixed UI copy, so a later translation gets cheaper.
- **Revisit when:** repeat Pix payers turn out to be mostly Brazilians.
- **Brazil's virtual-asset rules (checked 2026-11-21): not a blocker.**
  - Resolutions BCB 519, 520 and 521 (Nov 2025, in force since 2 Feb 2026) regulate virtual-asset service providers.
  - Res. 521 treats stablecoin trades and international payments with virtual assets as FX operations.
  - Res. 520 art. 91 (since 6 Nov 2026) bars BCB-authorized institutions from serving unauthorized virtual-asset providers.
  - Confío's Pix rail runs through authorized partners (Infinia, Dinaria and their Brazilian institutions). The Pix account is opened in the person's own name, and the wallet is self-custodial, so the partner's counterparty is the person, not Confío.
  - Brazil Pix top-ups kept completing after 6 Nov 2026.

---

## 7. Stage 2: Home and navigation

The founder's point (2026-11-21): the largest design decision is not the chat card, it is Inicio and the navigation. Home today carries several balances, a month line, network stats and a list of wallets, and the Pagar button sits in the centre of the tab bar so a person can pay without the assistant. "The balance is one tap away" does not describe that Home. This section analyses Home block by block and compares three navigation structures.

### 7.1 What Home shows today

Inventory from `apps/src/screens/HomeScreen.tsx` (personal account; business, employee, Cuenta inteligente and inherited accounts differ, 7.5).

| # | Block | What it is | Tap | Evidence of use |
|---|---|---|---|---|
| H | Header | "Confío" title, Cobrar QR icon (personal only), bell with unread badge, avatar letter that opens the profile menu, where the account switcher lives | Charge, Notification, ProfileMenu | Not tracked |
| 1 | Hero total | "Mi Saldo Total": Confío Dollar(+), legacy cUSD, USDT, CONFIO (incl. locked presale and bonuses, at the curve price) and investments. Eye and USD/local toggles. **Does not include Cuenta inteligente** | none | Not tracked |
| 2 | Month line | "Entró US$X · Salió US$Y" inside the hero | MonthSummary (Tu mes) | **The most-tapped tracked element on Home**; Tu mes is opened by a large share of monthly actives |
| 3 | Enviar / Recibir | The two verbs; the filled one switches with the balance | Send, Receive | Not tracked; few people send in a month |
| 4 | One promo slot | Pending incoming, invite claim, payroll, presale claim or humanitarian banner, one at a time | various | Not tracked |
| 5 | Membership dues | Linked billing obligation | Memberships | Few people |
| 6 | Stats row | Network figures: Usuarios, Ahorros, Movido, Invertido, Preventa. Social proof about Confío, not about the person | community and breakdown screens | Not tracked |
| 7 | Mis Billeteras | Confío Dollar(+); legacy cUSD (when non-zero); **Cuenta inteligente (an offer door for non-subscribers)**; CONFIO; Inversiones | AccountDetail, SmartAccount*, Invest | Not tracked; the Cuenta inteligente row is the main source of its door impressions |
| 8 | Referral link | "¿Tienes un código de invitación?" | modal | Not tracked |
| B | Assistant bubble | Floats on every screen | AssistantSheet | Organic bubble use is mostly started from Home; most assistant users first meet it through the onboarding guide card, which opens by itself |

Evidence (30 days to 2026-11-21, prod, described qualitatively because the repo is public):

- **Usage.** A clear majority of monthly actives talked to the assistant, but most of them through the onboarding guide card. Opening the bubble on one's own reaches a smaller but still large share; Home is where most of those conversations start, then Invertir.
- **Money actions.** Every money action is done by a low single-digit share of monthly actives in a month: sends, stock buys, crypto, futures, presale, Comprar. Local QR payments: none.
- **Tu mes.** Opened by many more people than any money action.
- **Business.** A handful of actives have a business account.
- **Tracking.** Taps on tabs, the two verbs, stat tiles and wallet rows are not recorded on our server; screen views go only to Firebase.

What this says about Home:

1. **Home answers "how much" three times and "what now" once.** The total, the wallet list and the Inversiones row are three views of the same money; Enviar and Recibir are the only actions, and they are used rarely.
2. **The month line is the part people use.** "What came in and went out" beats "how much is there" as a reason to tap.
3. **The stats row is about Confío, not about the person.** It is social proof for new users and takes prime space from everyone else.
4. **The wallet list mixes kinds.** Balances (Dollar, legacy cUSD, CONFIO), a portfolio (Inversiones) and a sales door (Cuenta inteligente for non-subscribers) look identical. A door dressed as a balance erodes trust in the list.
5. **The total and the wallet list will disagree** once Cuenta inteligente has money: the hero excludes it.
6. **The account switcher is hidden** behind the avatar, though the account changes everything on Home.

### 7.2 Navigation structures considered

| | Structure | Outcome |
|---|---|---|
| N1 | Keep the five tabs, rebuild Inicio | Chosen first, then replaced the same day: the money block plus a composer left too little room for the conversation |
| N2 | No tabs, like Claude: the conversation is the home, everything else in a drawer | **Chosen (2026-11-21)**, with Pagar kept as the primary button (7.3) |
| N3 | Three tabs, like ChatGPT's bottom bar (Inicio, Pagar, Explorar) | Not chosen: a bar for one button and one catch-all tab adds little |

Why N2 holds up against the evidence in 7.1: the only tab with a job nothing else can do is Pagar (paying at a counter, without the assistant). Comprar and the investing surfaces are used by few people in a month; the conversations people start themselves start from Home. The cost of N2 is that it is harder to undo, so the current tab navigator stays behind a flag for one release.

### 7.3 Decision (2026-11-21): the conversation is the home

1. **No tab bar.** Inicio is the assistant conversation.
2. **Pagar is the primary button**, where WhatsApp puts its mic/send button: the round button at the right of the composer.
   - With the field empty it is **Pagar** (opens Scan directly, no AI). Once the person types it becomes **send (➤)**.
   - The mic moves inside the field, on its right, where WhatsApp puts its camera.
   - On screens opened from the drawer (Invertir, Comunidad, Comprar…) a floating **Pagar** button sits at the bottom right. Pagar is one tap from every screen.
3. **Header:** ☰, the one-line money summary, the QR **Cobrar** icon and the notifications bell (both kept as today).
4. **Drawer** (☰, or a tap on the money line): the money block on top, the product items, "Recientes", and the profile at the foot.
5. **Profile and account switching merge** at the drawer's foot (avatar, name, current account ▾), as in Claude. Today's Perfil tab content opens from there.
6. **The active account is always visible.** Whenever it is not the personal account, the chat header shows it ("Negocio · Panadería"). Every payment card and signing sheet names the account the money leaves from.
7. **Comunidad is its own drawer item** (today it is a segment inside Invertir). New posts put a dot on it and on ☰: it is the only tab with a badge today, and the badge must survive.
8. **Rollback:** the five-tab navigator stays behind a flag for one release.

### 7.4 The home and the drawer

```
Home (the conversation)                     Drawer
┌──────────────────────────────────────┐   ┌───────────────────────────────┐
│ ☰•  US$ 254,30 · ↓340 ↑185  ⊞QR  🔔  │   │ US$ 254,30                👁  │
├──────────────────────────────────────┤   │ Entró 340 · Salió 185  Tu mes▸│
│                                      │   │ ┌──────┐┌──────┐┌────┐┌╌╌╌╌╌┐ │
│   Hola, Julian.                      │   │ │Dólar+││Invers││CONF│╎C.I. ╎ │
│   ¿Qué querés que haga por vos hoy?  │   │ │210,10││40,20 ││4,00│╎Activ╎ │
│                                      │   │ └──────┘└──────┘└────┘└╌╌╌╌╌┘ │
│  (Pagar un QR) (Mandar a mamá)       │   │ [ Enviar ]       [ Recibir ]  │
│  (¿Cómo me fue este mes?)            │   ├───────────────────────────────┤
│                                      │   │ ↗ Invertir                    │
│ ⏳ Pago a Padaria · pagando…          │   │ 👥 Comunidad              •   │
├──────────────────────────────────────┤   │ 🛍 Comprar                     │
│ ( Escribí o hablá…            🎤 )  (▣)│   │ ⟳ Cuenta inteligente          │
└──────────────────────────────────────┘   ├───────────────────────────────┤
          (▣) = Pagar; becomes ➤ when typing│ Recientes (pagos y chats)     │
                                            │ ✓ Pix · Padaria     hoy       │
                                            │ 💬 ¿Conviene NVIDIA?  ayer    │
                                            ├───────────────────────────────┤
                                            │ (J) Julian · Personal ▾   [+] │
                                            └───────────────────────────────┘
```

| Today | Where it goes | Why |
|---|---|---|
| Hero total + month line | One line in the header (total, ↓ in, ↑ out, eye); full block at the drawer's top. The total now includes Cuenta inteligente | The most-used numbers stay visible with zero taps; the conversation keeps its room |
| Mis Billeteras | Account strip in the drawer; full list on tap | Several balances, one place |
| Cuenta inteligente door | Last tile of the strip, drawn as an offer (dashed, "Activar", no amount) until the person subscribes; also a drawer item and a third account in the switcher | Discoverable without a tab; a door never looks like a balance |
| Enviar / Recibir | Drawer, under the money block; also the empty-state chips and the conversation itself | The two verbs, one swipe away |
| Payments in flight | One line above the composer, never hidden in the drawer | Money on its way must stay visible |
| Invertir tab | Drawer item | Browsing surface |
| Comunidad (segment) | Drawer item with the new-posts dot | Keeps its badge |
| Comprar tab | Drawer item (or out, if the pilot fails) | Few users |
| Perfil tab | Avatar at the drawer's foot, merged with the account switcher | As in Claude |
| Stats row | Top of Comunidad (decided). The website already shows these figures | Social proof, not daily information |
| Referral link | Profile's invite card (exists) | Rarely relevant after signup |
| Membership dues | An item in "Recientes" / the in-flight line | It is a task |
| Promo slot | A message from the assistant in the conversation, same priority rules | One voice |
| Assistant bubble | Gone on the home (the home is the assistant); stays on other screens | One entry per screen |

Interaction rules:

- The drawer opens from ☰ or a tap on the money line, **not from an edge swipe**: Android's back gesture owns the left edge.
- The empty state shows the greeting and chips from the person's own history and country; once there is history, the last conversation shows.
- "+ Nueva" starts a new conversation; "Recientes" mixes payment tasks and conversations by time.

### 7.5 Onboarding becomes the conversation

Decided 2026-11-21: the separate guide card goes away. Today it is where most people first talk to the assistant (it opens by itself), so its job moves into the home conversation instead of disappearing.

- **Kept on the server:** the stage computation of [`assistant-first-steps-guide.md`](assistant-first-steps-guide.md) (verify, verifying, top_up, awaiting_payment, first_action, done) and its country routing.
- **Changed:** the assistant speaks first in the home conversation, with the stage's step as a message and one or two chips ("Verificar mi identidad", "Recargar ahora"). A chip opens the real screen directly; nothing to point at, because there are no tabs to find.
- **Removed:** the guide card, the pencil pointer and the `tab_*` anchors. Walks that point at buttons inside a screen (for example the confirm button of a buy) can stay where they still help.
- **Measured:** each stage's next step reached, from `AssistantGuideEvent`, before and after, so the card's removal is visible if it hurts first deposits.

### 7.6 Other account kinds

| Account | Home |
|---|---|
| Business owner | Same structure; the primary button is **Cobrar** instead of Pagar, and the header QR icon is not shown (Cobrar is the button) |
| Employee | Same structure; the primary button follows permissions (Cobrar, or Pagar with `sendFunds`, or none); balances follow `viewBalance` |
| Cuenta inteligente | Its own home (`SmartAccountHomeTab`) opened from the switcher, with the same header and drawer |
| Inherited account | The withdraw-only box, opened from the switcher |

### 7.7 How today's verbs fold into tasks

| The person says | Becomes | Surface |
|---|---|---|
| "Pagá este QR" | Payment intent | Card + sheet |
| "Mandale 20 a Ana" (Confío user) | Send intent (internal, cheap, name from the account) | Card + sheet |
| "Mandale a mamá por Pago Móvil" | Manual screen until payee validation exists | Walk (existing) |
| "Quiero recargar" | Provider checkout is outside the app | Walk (existing) |
| "Comprá 10 de NVIDIA" | Stock buy has disclosures and market hours | Opens the stock screen prefilled (ticker already supported) |
| "Cada mes mandale 50 a mamá" | Cuenta inteligente rule | Rule proposal (existing, paid) |
| "Recordame pagar la luz el 5" | Reminder (no money) | Thread note; on the day, a prepared card |

### 7.8 Free advice vs paid execution

- **Free:** ask, advise, and **prepare any one-off payment that you sign each time** (a QR, a send). A single payment is a wallet function; putting it behind a subscription would kill the core loop and the metric. Also free: the assistant's actions that move no money (Calendar, Gmail, WhatsApp) and questions about a purchase already made.
- **Paid (Cuenta inteligente, IA+ inside it):** "lo hago por vos cuando toca", meaning recurring and conditional payments, plans that run on their own, target splits and the monthly review. All of it runs inside limits the owner signed.
- **Paid, from 2026-11-24: purchases by the assistant.** The agent searching, filling the cart and showing the priced order is free for everyone; buying it and paying the store is Cuenta inteligente's, paid from the account within a cap the owner signs once. Not a one-off payment the person signs: the assistant executes it. Full rules: [`cuenta-inteligente-spec.md`](cuenta-inteligente-spec.md) decisions 37 to 41, section 3.6.
- The offer appears only when the person asks for repetition or a condition ("cada mes", "siempre que", "si baja"), never on a one-off. Copy contrast: "Lo hacés vos con un toque" (free) and "Lo hago yo, cuando toca, dentro de lo que firmaste" (paid). This matches App Review framing: paid is the execution of a real financial service, not more AI.

- **Metric:** repeat assistant payers; guardrails: Tu mes opens, sends, and assistant conversations started without the guide must not drop.
- **Riskiest assumption:** a home without tabs does not bury the month line, the two verbs, Invertir and Comunidad, and losing the guide card does not lower first deposits.
- **Cheapest test:** instrument today's Home and tab taps for two weeks before the release, ship the new home to everyone with the old tabs behind a flag, compare the two weeks after (no A/B).

---

## 8. Stage 3+: wider jobs

### 8.1 Directions considered

| Direction | Verdict |
|---|---|
| Merchant integrations (bus companies, delivery apps, utilities) | Later, only after repeat behaviour is proven; each integration is sales and support work |
| **Pay other people's checkouts** | **Recommended**: most Brazilian and Argentine checkouts already show a Pix or QR code. The person buys on the merchant's site, picks Pix or QR, and shares or pastes the code into Confío. Bus tickets, delivery and many bills work this way with no integration |
| Browse and buy for the person (agent fills checkouts) | No: fragile, App Review risk, and the payee would come from a web page |
| Family payments abroad | Yes, but only on rails that validate the payee; Dinaria needs KYB and payout code that does not exist yet (Peru Yape/Plin, Ecuador, Mexico, Chile) |

### 8.2 What a task needs

- **Status timeline** from the journey: preparado, firmado, enviando dólares, pagando, pagado (or devuelto).
- **Receipt** with the rail's own reference (the Pix end-to-end id, the Pago Móvil reference), the verified payee, the amounts and the time, shareable as an image.
- **Refunds:** a rail failure refunds to the wallet automatically (today's journey behaviour). A merchant problem (the bus didn't come) is the merchant's; the receipt is the person's proof. The card says which case applies.
- **History:** tasks appear in the existing movements list, marked as prepared by Confío IA.
- **Trust signals:** the payee level ("Verificado por el banco", "Cobro firmado por el banco del comercio", or a visible "sin verificar"), "Confío nunca paga sin tu Face", the all-in cost before signing, and the rail's receipt after.

### 8.3 Economics to state plainly

Paying from dollars costs the 0.9% exit conversion fee, the provider's fee and the FX spread (the 1% buffer is refunded). For someone whose money is in dollars (Venezuela, Argentina, savers anywhere) this is the cost of spending dollars locally without first selling them on their own. It is not cheaper than paying from a local bank account, and the copy must never imply it is.

- **Metric:** repeat assistant payers per job type.
- **Riskiest assumption:** people will bring a third party's checkout code to Confío instead of paying it in their bank app.
- **Cheapest test:** an intent-probe chip in the assistant for Brazilian users, "Pegá el código Pix de tu compra", following the fake-door rule (Próximamente, Sí avísame / Solo miraba) until the paste path ships; then count checkout codes paid.

---

## 9. Measurement

- **Repeat assistant payers (primary).** Denominator: people whose first assistant-prepared payment reached `paid` in the period. Numerator: those with a second assistant-prepared `paid` within 30 days of the first. Reported weekly by rail and country.
- **Funnel events** (FunnelEvent, one row each): `intent_prepared`, `card_shown`, `sheet_opened`, `signed`, `paid`, `failed`, `refunded`, `expired`, `cancelled`, and the refusal reason.
- **Guardrails:** refunds and reviews per 100 payments; time from card to paid; Tu mes opens, sends and self-started assistant conversations, two weeks before and after the new home.

---

## 10. Risks and constraints

| Risk | Mitigation |
|---|---|
| Wrong payee via a forged QR or injected text | Rail validation required on the assistant path; payee rendered from the intent only; `display_hash` |
| Validation cost or latency at scale | Measure before enabling; cache a verified result for 24 h as today |
| App Review (assistant moving money) | Every payment is owner-signed in a native sheet; paid tier is the account service; no store billing |
| Rail coverage gaps (Peru, Ecuador, Bolivia off, Pago Móvil without validation) | The assistant names where it can pay; manual paths stay for the rest |
| The tab-less home hurts core use or first deposits | Instrument first, compare two weeks before and after (incl. guide stages), keep the five-tab navigator one release behind a flag to roll back |
| WhatsApp distribution | Out of scope (constraint) |
| Lending, custody | Out of scope (constraints) |

---

## 11. Open questions for the founder

1. Merchant Pix charges: the Pix session is making them payable through the Pix network's signed payload instead of the paid Infinia validation (2.3). Keep `INFINIA_ACCOUNT_VALIDATION_ENABLED` off, and use the paid holder lookup only where no signed or verified source exists?
2. Accept option C, the card plus a system sheet, instead of a pay button inside the chat?
3. On the assistant path, which payee levels may be paid: verified holders and signed charges only, or also a static QR's self-reported name with an explicit warning?
4. Stage 1 country: settled by availability. Brazil Pix is the only rail that can be paid today (2.2).
5. Is the Dinaria KYB worth starting now, given that no Dinaria payout code exists beyond Pago Móvil?
6. In Stage 2, may Inicio's chips include a task the person has never done (for example "Pagar un QR"), or only their own history?

Decided 2026-11-21: the conversation is the home with no tab bar (N2), Pagar as the composer's primary button and a floating button elsewhere, Cobrar and the bell kept in the header, Invertir/Comunidad/Comprar/Cuenta inteligente/Recientes in a drawer, profile merged with the account switcher at the drawer's foot; onboarding moves into the conversation (guide card, pencil and tab anchors removed); no A/B (old tabs behind a flag for one release, compare before and after); the network stats row moves to the top of Comunidad; no Inteligente tab exists, so the Cuenta inteligente door is the strip's last tile, drawn as an offer.
