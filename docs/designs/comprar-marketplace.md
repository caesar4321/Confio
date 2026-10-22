# Comprar — Confío Marketplace (Bolivia pilot)

Status: DRAFT 2026-10-22 · Owner: Julian (product/tech) · GTM: Jason (Bolivia)

## Why

Bolivian family and artisan sellers sell through Instagram/WhatsApp and Facebook
Marketplace, where scams are common, and Mercado Libre has not arrived. Comprar gives them
a storefront inside Confío where **both sides are Didit-verified**, paid through an escrow,
delivered by Yango. It also gives people a reason to *spend* Confío dollars, not only
hold them. And the merchants bring their own customers into Confío.

Niche: repeat sellers of physical goods (artesanías, textiles, packaged family foods).
No one-off used-phone sellers. **Physical items only** (no services, digital goods,
gift cards, tickets).

## Navigation change

| Slot | Today | After |
|---|---|---|
| 1 | Inicio | Inicio |
| 2 | Invertir (stocks, crypto, presale) | **Invertir** with a top segment: `Invertir · Comunidad` |
| 3 | Pagar (QR) / Cobrar | unchanged |
| 4 | Descubrir (Para ti · Comunidad · Oficial) | **Comprar** |
| 5 | Perfil | Perfil |

- **Comunidad → Invertir.** Para ti + Comunidad (posts, activity shares, comments,
  reactions, @mentions) move under Invertir's `Comunidad` segment. Activity shares
  (Recargar, Retirar, Acciones, Bitcoin, oro…) sit next to the products they discuss.
  The composer, Mis publicaciones, member profiles and post detail move with it
  unchanged. Only their stack parent changes (`exitToDiscover` → `exitToCommunity`).
- **Oficial → the assistant bubble.** Confío News and Julian's announcements become
  messages in the assistant thread (it already has the inbox and the unread badge), not a
  feed section. Deep links that target `Discover/official` re-route to the bubble.
- **Comprar** shows for every account. During the pilot a city with no stores shows the
  fake door ("Próximamente en tu ciudad · Sí, avísame / Solo miraba"), a demand probe,
  plus "Explorar La Paz". A server flag per country turns live browsing on.
- **Mi tienda opens from a personal account.** No business account and no KYB: a
  business account would push sellers into KYB for Recargar/Retirar (Mesa de pagos,
  Stereum), which Bolivia's informal sellers can't or won't do. A Didit-verified personal
  account can open one store. Business accounts may also open one later. Employees never
  see Mi tienda unless they have an explicit `manage_store` permission (negative-check).

Older servers: every new query (store list, product, orders) gets its own
try/catch query. Nothing joins the shared feed or account queries (see the
"isolate new GraphQL fields" rule).

## Location & delivery

- **Default = GPS city.** On first open, ask for location, reverse-geocode to
  (country, city), and keep it. If permission is denied, use the phone-country capital.
  A picker browses any country → city, the same pattern as the Financieras
  menu. The location is a browsing filter, never a gate.
- **Delivery defaults to city-wide Yango Envío. The buyer pays the courier directly** (QR
  on arrival, or left at the door arranged with the driver through the Yango tracking
  number). Confío never touches the delivery fee and never splits it.
- The **estimate is per city and set in admin** (`MarketplaceCity.delivery_estimate`). La Paz
  starts at **15 Bs**; Jason's target with volume is 10 Bs, and that is an admin edit, not
  a release. Checkout shows: `Producto 100 Bs (pagas con Confío) + Envío ~15 Bs (pagas al
  repartidor) = ~115 Bs`.
- **Other city or country:** not blocked. Checkout shows "Envío a otra ciudad: lo coordina el
  vendedor y cuesta más que ~15 Bs", and the buyer must tick an acknowledgement. Each store
  sets `ships_outside_city` (default off). If it is off, the product shows "Solo entrega en
  La Paz", but the buyer can still message the seller.

## Pricing & revenue split

- **Merchant fee 8% of the product price**, all-in. Confío Pay's 0.9% is **not** added on top:
  marketplace orders settle through the escrow, not ConfioPayContract.
- The fee is a signed per-order parameter, capped on-chain (`MAX_FEE_BPS = 1000`). That
  way country, category or promo pricing never needs a redeploy.
- **The Jason 4% / Confío 4% split lives only in admin.** It is not on-chain and not in the app:
  - `MarketplacePartnerAgreement(partner, country=BO, share_bps=5000 of the marketplace fee,
    active, started_at, ended_at)`. The contract wording: the share accrues **while the partner
    remains engaged in marketplace GTM, expansion and upkeep**. `active=False` stops
    accrual from that date.
  - `MarketplaceFeeLedger` gets one row per released order: gross, fee, partner_share, and
    refunded/clawed-back. Top-ups, withdrawals, conversion and Pay fees never enter it.
  - An admin dashboard card shows GMV, orders, fee, partner share by month and the
    payable balance, with a CSV export for the monthly settlement.
- Bolivian prices are shown in **Bs**, and the merchant sets the price in Bs. At checkout the
  Bs→USD quote is locked into the signed order, and payment is in Confío Dollar on BSC.

## Trust

- **Browse without KYC.** Buying needs `identity_status` verified (Didit). Opening a
  store needs only a Didit-verified personal account (no business account, no KYB).
- Listing photos and text go through the existing UGC AI gate (Luna→Sol,
  fail-closed), with a prohibited-categories list on top (weapons, medicines, alcohol,
  live animals, counterfeit, digital goods).
- Reputation counts only completed escrow orders (ratings are tied to an order and given
  once per order). There are no free-form reviews.

## Escrow: one shared contract, not one per merchant

**Built (2026-10-22): a single UUPS-upgradeable, Safe-owned `ConfioMarketEscrow` on BSC
(`contracts/cusd_plus/ConfioMarketEscrow.sol`), with per-order
isolation inside it.** Per-merchant contracts (EIP-1167 clones from a factory) look safer,
but in practice:

- **They don't isolate the risk that matters.** Every clone runs the *same*
  implementation, so a logic bug can be exploited in every clone at once. Clones isolate
  *storage*, and per-order accounting already isolates storage.
- **They cost real money.** One deploy per merchant is sponsor gas. Deploys were already
  71% of BSC sponsor spend.
- **They multiply operations.** N fee-collection calls, N pause switches, N addresses for the
  indexer and Movido reconciliation, and N contracts to migrate if v2 ever ships.

What actually keeps one merchant's trouble from touching another's money:

1. **Per-order state.** `orders[orderId] = {buyer, merchant, token, amount, feeBps,
   state, deadlines}`. Funds can only ever go to *that order's* merchant (net) and the
   fee pool, or back to *that order's* buyer. No function moves principal anywhere else.
   The owner can collect accrued fees only.
2. **Pause stops new deposits only.** Release, refund and buyer self-reclaim keep working
   while paused, so a pause can never strand funds.
3. **Caps.** A per-order cap (start at ~US$300) and a contract-wide open-escrow cap, both set
   by the Safe. A bug can expose at most the cap, never unbounded TVL.
4. **UUPS, owned by the Safe** (Julian's call). The owner can fix or extend the flow in
   place. That makes the Safe the trust root for escrowed principal. The backend keys
   (`orderSigner`, `arbiter`) are not: a compromised signer can't move existing orders, and
   a compromised arbiter can only choose release or refund on Disputed orders.
5. **Invariant test.** `balance(token) == Σ open order amounts + accruedFees[token]`, fuzzed
   in forge.

Order lifecycle (each step a sponsored tx; the user never pays gas):

```
deposit   buyer; backend-signed {orderId, buyer, merchant, token, amount, feeBps, deadline}
  → markShipped  merchant, on-chain, before shipBy (shipWindow, 3d proposed)
                 past shipBy: reclaim by the buyer, no Confío signature needed
  → confirm      buyer, any time before settlement ──────┐
  → release      anyone, once releaseAt = shipped + releaseWindow (4d proposed) ┤→ net to merchant, fee accrued
  → dispute      buyer, while Funded, or Shipped before releaseAt ──→ arbiter: release OR refund
                 arbiter silent for disputeTimeout (30d) → anyone refunds the buyer
refund    merchant, any time before settlement (cancel, return) — full amount, no fee
```

The buyer's self-refund after the ship deadline needs no Confío signature, so an unshipped
order can always be recovered even if Confío's backend is down. Disputes are the only
place Confío decides, and the arbiter key can only choose between those two
addresses. Gas is two txs per order (deposit and release) against one for Pay, which is
acceptable at 0.05 gwei.

The merchant's cash is delayed by roughly delivery time + confirmation. For same-city Yango
that is the same day if the buyer confirms, and ≤ releaseWindow after shipping if they don't.
The Yango tracking id stays off-chain (in the Order row).

## Data model (Django app `marketplace/`, soft-delete, registered in `confio_admin_site`)

- `Store` (owner account — personal by default, one store per account; city, ships_outside_city, status, approved_by)
- `Product` (store, title, description, price_bob, stock, category, photos, status,
  moderation verdict)
- `MarketplaceCity` (country, city, live flag, delivery_estimate, currency)
- `Order` (buyer account, store, items snapshot, price_bob, usd_amount, quote, fee_bps,
  escrow orderId, chain state, yango_tracking, delivered_at, dispute)
- `OrderRating`, `MarketplaceFeeLedger`, `MarketplacePartnerAgreement`
- Store/order context comes from the JWT (`get_jwt_business_context_with_validation`).
  No account ids come from the client.

## Launch gates (separate from the build)

- **Small top-ups in Bolivia.** With Koywe's 350 Bs minimum, a 60 Bs purchase does not convert.
  Without a small on-ramp, the open launch waits. A closed beta with buyers who already
  have a balance can still run.
- Jason has 20–30 verified La Paz stores with products listed before the tab goes live.
- 20 real orders delivered end to end in a closed beta (merchant → Yango → buyer →
  release) before any public push.
- Metrics: orders per store per month, repeat buyers within 30 days, dispute rate,
  share of buyers new to Confío.

## Build order

1. ✅ `ConfioMarketEscrow.sol` + forge tests (42 incl. 3 invariants), Codex audit clean
   (2026-10-22). Deploy script + KMS command + mainnet-fork rehearsal PASS (REHEARSAL.md).
   Next: prod dry-run → `deploy_confio_market_escrow --broadcast --yes-mainnet` → Safe
   `setTokenLimits(cUSD, 300e18, 10_000e18)`.
2. `marketplace/` models, admin, GraphQL (stores, products, orders, checkout quote/sign,
   ratings), escrow indexer, AI moderation hook.
3. App: tab swap (Comunidad into Invertir, Oficial into the bubble), Comprar browse,
   city picker, product detail, checkout, order tracking, Mi tienda (list/edit products,
   orders, mark shipped).
4. Admin partner dashboard (GMV, fee, 50% partner share, CSV).

## Open questions

- Food: packaged and shelf-stable only at launch? (Recommended: yes. Perishables later.)
- Per-order cap value and the auto-release window (48h proposed).
- Venezuela: Yango there is ride-only and has no Envío confirmed. The delivery partner must
  be pluggable per country (Yummy, PedidosYa), so nothing in the model hard-codes Yango
  beyond the default.
