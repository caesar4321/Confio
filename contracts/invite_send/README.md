Invite & Send — Usage and Groups

Overview
- Escrows an ASA (cUSD or CONFIO) for a non-user using a box keyed by an invitation ID.
- The inviter funds the box minimum balance (MBR); on claim/reclaim the box is deleted and the MBR is refunded.

Transaction Groups
- Create: [Payment(inviter→app, amount=MBR), AXFER(inviter→app, asset=cUSD/CONFIO), AppCall(create_invitation)]
  - MBR is computed on-chain as 2500 + 400*(key_len + value_len).
  - The Create call validates the AXFER recipient is the app and enforces the MBR payment.
- Claim: AppCall(claim_invitation) with sufficient fee, or [Payment(fee-bump), AppCall(claim_invitation)].
  - The app transfers the ASA to the verified recipient, writes a compact receipt box, and refunds the original MBR minus the receipt’s MBR to the inviter.
- Reclaim: AppCall(reclaim_invitation) with sufficient fee, or [Payment(fee-bump), AppCall(reclaim_invitation)].
  - The app returns the ASA to the inviter, writes a compact receipt box, and refunds the original MBR minus the receipt’s MBR.

Storage Layout
- Key: `invitation_id` (<= 64 bytes).
- Value: sender(32) | amount(8) | asset_id(8) | created_at(8) | expires_at(8) | is_claimed(1) | is_reclaimed(1) | msg_len(2) | message(<= 256).

Design Notes
- Inner tx fees are set to 0; callers should cover fees in the outer group.
- Recipient opt-in is required for claim.
- A compact receipt box is created on claim/reclaim with key `r:<invitation_id>` and value `status(8)|asset_id(8)|amount(8)|ts(8)`; the receipt’s MBR is withheld from the refund so there is no extra funding required.
