# Ledger amounts: who reads what

`UnifiedTransactionTable` is the single history table behind every account
screen. One row can mean two different numbers — the payer is debited
`amount`, the recipient is credited `amount - fee_amount` — and on 2026-08-02
a change to how that was resolved broke a screen nobody had inventoried. This
is that inventory.

Read it before changing `amount`, `fee_amount`, `display_amount`, or anything
that renders them.

## The model

| Field | Meaning | Set by |
|---|---|---|
| `amount` | **Gross.** What left the payer / what the invoice was for. | each feature's writer in `users/signals.py` |
| `fee_amount` | Deducted before the recipient was credited. `''` = no fee. | `_payment_fee_amount`, `_payroll_fee_amount` |
| `amount_denomination` | `TOKEN_UNITS` \| `USD_VALUE` \| `SHARES`. cUSD+ rows are `USD_VALUE`. | `save()` |
| `token_type` | Canonicalised on `save()`; a DB constraint rejects anything else. | `canonical_token_type` |

`amount_for_direction(direction)` (`users/models_unified.py`) is the **only**
place that knows the netting rule. Everything that needs a per-side figure
should call it rather than subtracting a fee itself.

Fee-bearing flows today: **payments** (0.9%) and **payroll** (platform fee, plus
redemption slippage for recipients paid in USDT). Every other row — send,
conversion, presale, ramp, P2P, humanitarian — has a blank fee, so both sides
see the same number and nothing below applies.

## Backend consumers

| Consumer | Reads | Semantics |
|---|---|---|
| `users/graphql_views.py` `resolve_display_amount` | `amount` | **Gross**, signed by direction. The app's detail screen depends on this being gross. |
| `users/graphql_views.py` `resolve_fee_amount` | `fee_amount` | Raw fee, `''` when none. |
| `users/graphql_views.py` `resolve_net_amount` | `amount_for_direction('received')` | Authoritative net. **Nothing renders this yet.** |
| `users/admin.py` `UnifiedTransactionAdmin` | `amount` | Gross, ops view. Also shows retraction state. |
| `users/management/commands/debug_transactions.py` | `amount` | Gross, diagnostic. |
| `users/migrations/0035` | `amount` | One-off backfill of `fee_amount` on payment rows. |
| `UnifiedTransactionTable.__str__` | `amount` | Gross. |

There are **no aggregations** over `amount` in `config/admin_dashboard.py` — the
business dashboards aggregate source tables, not this one. Balances come from
`BalanceService` (chain state), never from this table. Both were checked; both
mean a display change here cannot move a balance or a dashboard total.

## App consumers

Only three screens read `displayAmount`:

| Screen | Uses | Notes |
|---|---|---|
| `AccountDetailScreen.tsx` (~800) | `displayAmount`, falls back to `amount` + sign | Builds the history card and passes the value on as `amount` to the detail screen. |
| `RampHistoryScreen.tsx` (~147) | `displayAmount \|\| amount` | Ramp rows carry no fee. |
| `FriendDetailScreen.tsx` (~224) | `displayAmount \|\| amount` | Send rows carry no fee. |

**`TransactionDetailScreen.tsx` computes the fee itself** — `computeConfioFee`
(line 173) hardcodes `amt * 0.009`, called at lines 1641 and 1658. It receives
`currentTx.amount` from `AccountDetailScreen` and treats it as **gross**:

```
Monto cobrado        100.00      <- currentTx.amount
Comisión Confío       -0.90      <- computeConfioFee(amount)
Total recibido        +99.10     <- gross - fee
```

That breakdown is correct **only while `displayAmount` is gross**. Netting it
server-side made this screen subtract the fee a second time and show `98.21`.

Payroll screens (`PayrollPendingScreen`, `PayrollRunsHistoryScreen`) read
`netAmount`/`grossAmount`/`feeAmount` from **`PayrollItem`**, not from this
table. They are a separate surface and are unaffected by changes here.

## Changing the history card to net

The card currently shows gross. If it should show net:

1. Replace both `computeConfioFee` call sites with the server's `feeAmount`,
   and delete the helper. The hardcoded `0.009` is wrong the moment a rate
   changes or a flow prices differently.
2. Only then switch the card to `netAmount`.
3. Ship both in the same release. Doing (2) without (1) double-subtracts, and
   **old builds in the field will double-subtract regardless** — which is why
   the server must keep sending gross in `displayAmount` until the fleet has
   moved.

Worth questioning first: the card showing gross matches the invoice's face
value and matches the detail screen's first line. The defect found on
2026-08-02 was arguably never the card — it was the hardcoded rate and the
notification. Step 1 alone may be the whole fix.

## Rules

- One row, two truths. `amount` is always gross; per-side figures come from
  `amount_for_direction`.
- Never subtract a fee at a render site. Ask the server.
- A new fee-bearing flow sets `fee_amount` in its writer; it does not invent a
  parallel field.
- Changing `display_amount` changes **every shipped app build immediately**.
  Check this file first.
