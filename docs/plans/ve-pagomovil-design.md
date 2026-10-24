# Venezuelan Pago Móvil: top-ups and sends (design)

**Status**: built (2026-10-24). Top-ups by VEXPay, sends by Pago ASAP; both
dark behind product switches and app floors.

## Provider-neutral by construction

The app only knows "VE Pago Móvil": Recargar con bolívares and Enviar
bolívares. Every GraphQL operation is `vePagomovil…`; no provider name reaches
the client. The information and interaction are the same whoever processes
them (payer or recipient cédula, phone and bank; a Pago Móvil reference or a
bank payment key; the user's dollars sent from their own wallet).

`ramps/ve_pagomovil.py` holds the product rules and picks the provider:

- `VE_PAGOMOVIL_TOPUP_PROVIDER`, `VE_PAGOMOVIL_SEND_PROVIDER` choose the
  adapter for NEW orders. An existing order always stays with the provider
  that made it (`RampTransaction.provider`), so switching never strands one.
- `VE_PAGOMOVIL_{TOPUP,SEND}_ENABLED`, `…_MIN_APP_VERSION` (empty = shown to
  nobody) and `…_{MIN,MAX,USER_DAILY,GLOBAL_DAILY}_USD` are product settings.
- The Venezuelan bank list (SUDEBAN codes) is ours, not a provider's.

Switching a provider is a server change: a new adapter module registered in
`TOPUP_ADAPTERS` / `SEND_ADAPTERS` and the setting flipped.

## Top-up (`ramps/vexpay_topup.py` over `ramps/vexpay.py`)

Each top-up is one VEXPay payment created for one order: C2P (bank payment
key) or Pago Móvil (the user pays from their bank app and enters the
reference). The payment carries `onwardPayout` to the user's BSC wallet, so
VEXPay converts that payment's bolívares and pays the USDT straight to the
wallet; the BSC arrival attribution credits it. Each order spends its own
Confío Face check. Unknown outcomes are never released: a bounded replay
decides, then ops review.

## Send (`ramps/ve_send.py` core + `ramps/pagoasap_send.py`)

1. **Order**: identity-verified personal owner, Face peeked, limits under a
   lock. Pago ASAP's deposit address is shared by every send, so each of a
   sender's sends carries a distinct micro-tag (under one cent) in its USDT
   amount.
2. **Funding**: Pago ASAP takes stablecoins on Polygon only. The single-use
   funding claim takes a Relay quote (the audited `payment_accounts.relay`
   client) whose deposit address on BSC bridges the order's exact USDT to
   native USDC at Pago ASAP's Polygon address, and answers it once with the
   Relay deadline. The app pins the personal wallet and pays with the Retiro
   batch (redeem with fee + exact transfer), signed never to outlive that
   deadline; the sponsor spends the Face approval.
3. **Proof**: the BSC chain decides funding: one USDT Transfer from the
   order's wallet to the deposit address for exactly the order's amount, in a
   finalized canonical block, not claimed by another order. Settlement then
   proves Relay's delivery on Polygon (or a full refund to the user's wallet)
   from finalized receipts (`payment_accounts.relay_settlement`); an order is
   credited at most its own quoted bridge output.
4. **Payout**: priced at payout time from the dollars delivered to Pago ASAP
   and its rate, sent only when the provider balance covers it after payouts
   in flight. A Pago Móvil intent under an idempotency key derived from the
   attempt; polled to completed or failed.
5. **Safety**: every dispatch holds a lease; answers are fenced to their
   attempt; a lost answer is replayed with the same key only inside a short
   window; a refusal after a timeout is never proof of non-payment; definite
   refusals may be retried with a new key (after correcting the destination);
   anything unknown goes to the ops console (`envios-ve/`) and needs a
   confirmed "NO PAGADO" before a new key.

## Webhooks

`api/vexpay/webhook/` (HMAC) and `api/pagoasap/webhook/` (Ed25519) only
enqueue a re-check; a 60 s poll is the source of truth.
