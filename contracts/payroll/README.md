Payroll Escrow Contract (Single-Recipient Version)

Overview
- Dedicated payroll escrow separate from the merchant payment app.
- Owner funds escrow and configures delegate allowlist + per-period spend cap.
- Delegated managers execute single-recipient payouts; 0.9% fee is skimmed from gross so recipients always get the requested net.
- Writes a small receipt box keyed by payroll_item_id for on-chain auditability.

Entry Points
- `create`: sets admin = deployer; initializes fee_recipient/sponsor empty and required globals.
- `setup_asset(asset_id)`: owner-only; sets the payroll asset and opts the app into it.
- `set_fee_recipient(address)`: owner-only.
- `set_sponsor(address)`: owner-only (optional fee-sponsor for Algo fees).
- `fund(amount)`: owner-only; requires preceding AXFER to the app for the payroll asset.
- `set_delegates(add[], remove[])`: owner-only; maintains allowlist via boxes (address -> 1).
- `set_cap(period_seconds, cap_amount)`: owner-only; defines spend cap per rolling window.
- `payout(recipient, net_amount, payroll_item_id)`: delegate-only; enforces cap + balance, computes gross = ceil(net/0.991), fee = gross - net, transfers net to recipient and fee to fee_recipient, updates period spend, records receipt box payload: recipient|net|fee|gross|sender|ts.

Group Expectations
- Fund: [AXFER(owner→app, payroll_asset), AppCall(fund)]
- Payout: [AppCall(payout)] with a fee-covered transaction group (sponsor pattern can be added similar to payment app).

Notes
- Recipient opt-in to asset must be ensured off-chain in the transaction builder before submission.
- This is a lean scaffold to iterate; batch payouts can be added later via a `payout_batch` entry point.
