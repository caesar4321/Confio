# Hands-off Cuenta inteligente (account v2) — decisions 2026-11-25

Chat trades (Ondo stocks, Oro y Bitcoin) and Comprar purchases made from the Confío IA chat are Cuenta
inteligente perks, executed by the person's account without a signature per trade. What the chat buys is held in
the account. The Acciones, Oro y Bitcoin and Comprar screens stay free and self-directed from the personal wallet.

## Product
- Non-subscribers: the chat guides to the priced proposal, then offers "Activa Cuenta inteligente" or "Hazlo tú"
  (the screen, prefilled). No balance: Koywe top-up; money already in the personal wallet: a move into the account.
- Trade cap: chosen at the first hands-off trade and signed once with Face: US$250 / 1,000 / 2,500 per week or
  another amount, preselected from the person's own history (about twice their biggest week). Above it, the chat
  offers raising it (Face), never a bare refusal. Prod, 120 days to 2026-11-25: largest single buy US$300;
  biggest 7-day buys US$1,500 / 765 / 393; median trader US$28.
- Buys AND sells count in the cap (audit H1/M1). It is a leaky bucket: one cap at any instant, one cap per week on
  average, at most `cap·(1 + d/gap)` over any span d (just under two caps within one week). The copy says
  "en promedio".
- Oro y Bitcoin is never offered or executed for iOS clients.
- Every hands-off trade notifies the owner; one without a chat proposal behind it is a security alert to the
  owner and to ops.
- Migration to v2 is opt-in, one Face batch: cancel the old subscription if active, `factory.migrate()`, withdraw
  everything to the owner, transfer it to the new account, re-sign the buy rules plus the Trade rule (cUSD+),
  subscribe only if no paid period carries over. Send, bank-payout and card rules are re-created from the new
  account. Old accounts keep working; only hands-off needs v2.
- Liga, Rentabilidad and the portfolio sum the personal wallet and every account the person owns; moves between
  them and the migration are internal, never deposits or gains.

## Contracts
- `ConfioSmartAccountV2` (new implementation; v1 bytecode unchanged): RuleKind Trade (4) and Purchase (5),
  relayer-only `relayTrade` and `relayPurchase`, per-rule leaky bucket (`bucketOf`), minimum gap between relay
  trades, swaps within 1.5% of the feed, stock fee bound 90 bps, sells must return their value within the band.
- Factory (UUPS, Safe): implementation per generation, `migrate()`, `tradePaused` (stops every hands-off path).
- `ConfioMarketEscrow` (UUPS, Safe): `depositFrom` by an account, its own payer-bound digest, the owner recorded as
  buyer (keeps confirm/dispute/reclaim), refunds to the paying account.

## Trust assumption (amends invariant 16)
Hands-off trades and purchases trust ConfioStockRouter, ConfioSwapRouter and ConfioMarketEscrow, which the Safe
can upgrade — as v1 Buy rules already trust the routers. A compromised relayer key ALONE cannot move value out of
an account. A compromised relayer key TOGETHER with a malicious Safe upgrade of the stock router can sell stock at a
forged price (the account cannot verify Ondo's quote signature itself). Escrow: relayer + order-signer compromise
can pay an attacker merchant up to the Purchase cap; the arbiter and the order signer must be separate KMS keys,
Purchase caps stay small, and every relay purchase notifies the owner.

## Deploy (Safe)
One batch: v2 implementation + factory `upgradeToAndCall(initializeV2)` with `setTradePaused(true)`; escrow
`upgradeToAndCall(setAccountFactory)`. The server stays dormant until `SMART_ACCOUNT_V2_IMPLEMENTATION_ADDRESS`
is set; unpause after a canary.

## Not built yet
- The server side of `relayPurchase` (hands-off Comprar from the chat).
- Carrying send/payout/card rules through migration.
