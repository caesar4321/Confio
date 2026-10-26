# QR Bolivia: receive and pay with Bolivian QR codes (design)

**Status**: building for app 5.2.9 (2026-10-26). Both directions dark behind
explicit switches until a provider is live.

## Product

- **Recibir con QR Bolivia**: the person enters an amount in bolivianos and
  gets an interoperable QR any Bolivian bank app can pay (one QR per amount;
  no provider offers a fixed QR). The dollars arrive in their Confío balance.
- **Pagar con QR Bolivia**: the person scans or imports any Bolivian QR, sees
  who receives and how much, and pays it from their Confío balance.
- Provider-neutral, like Venezuelan Pago Móvil: the app only knows
  "QR Bolivia"; no provider name reaches it.

## Switches (`ramps/bolivia_qr.py`)

| Setting | Meaning |
|---|---|
| `BOLIVIA_QR_{RECEIVE,SEND}_ENABLED` | the explicit switch per direction |
| `BOLIVIA_QR_{RECEIVE,SEND}_PROVIDER` | adapter for NEW orders (`stereum`, `mesadepagos`) |
| `BOLIVIA_QR_{RECEIVE,SEND}_MIN_APP_VERSION` | app floor; empty = shown to nobody |
| `BOLIVIA_QR_SEND_*_USD`, `BOLIVIA_QR_RECEIVE_MAX_USD` | caps; empty = none |

While a direction is on (and the build has the screens), Koywe's matching
row is replaced for Bolivian users, server-driven: Recibir hides "Recargar
ahora", Enviar hides "A mi propia cuenta" (`koyweReplaced` query).

## Money movement

Neither provider settles on BSC; both work on Polygon. The person only ever
signs on BSC; Polygon is between the provider and Relay. Every order is
funded just in time for that order; Confío holds no float.

**Recibir**
1. The adapter creates the provider's QR for the amount. Where the provider
   pays the converted dollars is a Relay deposit address (POL:USDC ->
   BSC:USDT) whose recipient is the person's BSC wallet, the Infinia receive
   pattern. Mesa de pagos fixes that address when the QR is created, so the
   QR's expiry is kept short (a late deposit is repriced by Relay, not lost);
   Stereum sends after payment, so the address is made at that moment.
2. The payer pays from any bank app; the provider converts and pays the Relay
   deposit address; Relay delivers USDT to the person's BSC wallet.
3. The order completes on the BSC arrival, proven like other ramp arrivals.

**Pagar**
1. The adapter decodes the QR (who, bank, amount) and prices the payment.
2. The adapter creates the provider's payment and returns its funding: a
   Polygon address and the amount.
3. The person approves once (Face check) and signs one BSC batch: from their
   balance to a Relay deposit address (BSC:USDT -> POL:USDC) whose recipient
   is the provider's funding address, the Pago ASAP pattern.
4. When the delivery is proven, the provider pays the QR (Mesa de pagos
   executes on funding; Stereum converts the order's dollars and we call its
   QR payment).

The debit is sized so Relay's guaranteed minimum always covers the provider's
amount; Relay usually delivers a little more. That surplus stays in our
balance at the provider (decided 2026-10-26) and is recorded on each order
(`provider_surplus_units`). Only a production provider order is ever funded
with real dollars, never one past its expiry, and never above the debit the
person approved on screen.

The VE send core (`ramps/ve_send.py`) already does the BSC funding claim,
finalized-block proof, Relay settlement, payout lease, attempt fencing and the
ops console; QR Bolivia sends reuse it with the Bolivian adapters.

## Adapters

Each implements: `quote`, `create_receive(order)` → QR payload/image + expiry,
`receive_status(order)`, `decode(qr)`, `create_payment(order)` → funding
(address, amount, deadline), `payment_status(order)`. Provider specifics:

| | Stereum | Mesa de pagos |
|---|---|---|
| Recibir | charge, then a per-order BUY to the person's Polygon address | `deposit/qr` with `fundingSource=conversion` |
| Pagar | decode-qr; per-order SELL funded by the person; then send-qr | `payouts/validate/qr` + `payouts/qr` with `fundingSource=conversion` |
| QR input | the QR text | a QR image (rendered from the text if needed) |

## Open with providers

- Both: that an order funded with a little more than asked still executes.
- Stereum: a SELL response example; our corporate BOB account number and
  bank type; whether OTC quotes may use the company (SELF) or need each
  person registered as a customer; production credentials.
- Mesa de pagos: production credentials; webhook signing; when the converted
  dollars are sent on a receive; the QR payout's funding window.
