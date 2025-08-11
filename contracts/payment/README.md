Payment Contract — Usage and Groups

Overview
- Processes ASA payments (cUSD or CONFIO) to a recipient, collecting a 0.9% fee.
- Optionally writes a fixed-size receipt box funded by the payer to enable on-chain auditability.

Transaction Groups
- No receipt: [AXFER(payer→app, asset=cUSD/CONFIO), AppCall(pay_with_* )]
  - The app transfers net amount (amount − fee) to the recipient.
- With receipt: [Payment(payer→app, amount=MBR), AXFER(payer→app, asset=cUSD/CONFIO), AppCall(pay_with_* )]
  - The app computes MBR = 2500 + 400*(key_len + value_len) and requires the Payment to cover it.
  - Receipt value is fixed-size: payer(32)|recipient(32)|amount(8)|fee(8)|ts(8)|asset_id(8) = 96 bytes.

Safety Checks
- Binds the payment to the app call: the `payment` transaction’s sender must equal the app call sender.
- Verifies recipient opt-in to the asset before transferring.
- Inner transactions set fee to 0; callers should provide sufficient outer fees or include fee-bump payments.

Notes
- Receipts are permanent and funded by the payer’s MBR Payment; there is no MBR refund in payment flows.
- For atomic payments without receipts, no permanent ALGO is locked.

