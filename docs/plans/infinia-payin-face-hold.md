# Infinia pay-in hold until Confío Face

Status: decided 2026-09-29 (Julian). Backend: Codex. App UI/UX: Claude Code session.
This file is the contract between the two; change it here first if either side needs to.

## Why

Recruited-identity rings (Colombia case, Sept 2026) KYC a holder once and run the
account alone. Outbound gates are not enough: once USDT reaches the non-custodial
wallet, the emergency exit can move it without Confío (block `confio.lat` and the
status Worker with a VPN, wait 72h). The last point where Confío controls the money
is the automatic Infinia local-currency → USDT conversion and wallet drop. Hold it
there until the account's person proves presence with Confío Face.

- Funds stay in the user's own Infinia virtual account, in their name, at the
  provider: a "confirm to receive" step, not Confío custody.
- While held (still local currency, never converted) a fraud report can still be
  returned to the payer.
- Koywe needs no hold: its on-ramp only exists after an order, and every deposit
  order already spends a face check.

## Scope

- Personal accounts only. Business accounts stay automatic (cashiers, API payers,
  CIP); they are governed by KYB and limits.
- All Infinia countries, Bolivia included (our account is on the 0.5% processing
  option, which allows holding BOB; the fixed-fee option would demand instant
  conversion).
- Only while `FACE_STEP_UP_ENABLED` is on.

## Backend (Codex)

1. **Hold** — `payment_accounts/auto_payin.process()` → `payin_hold.py`: for a
   personal owner the face gate applies to (`step_up_applies`), if no
   `payin_release` check passed in the last 15 minutes, do not create the
   `to_wallet` journey. The check is not spent: money arriving inside the window
   is released too. Mark the pay-in `awaiting_face` with `awaiting_since`, and push:
   "Tienes {amount} por recibir. Confirma con tu rostro para recibirlo."
   (deep link `confio://pending-incoming`). No review queue: the person clears it.
2. **Release** — new mutation `releasePendingPayins` (below). Requires a passed
   check in the window, else returns the standard step-up answer
   (`nextStep: 'face_check'`, error = `FACE_STEP_UP_MESSAGE`). Releases every
   `awaiting_face` pay-in of the caller's personal account (one face releases the
   whole queue; the 24h return caps how much can be batched) by running the normal
   `process()` path. `reconcile()` must also release them when a window is open.
3. **Face purpose** — add `payin_release` to `FaceCheck.PURPOSE_CHOICES`
   (and to `start_face_check`'s accepted purposes).
4. **Return after 24 hours** unconfirmed (reconcile, every 30s), per pay-in — **as built**:
   - **Infinia's native deposit refund** (`POST /v1/accounts/movements/refund/`,
     same idempotency key on every attempt). It returns the whole movement to the
     payer on the same rail and needs no payer account details — our Colombian
     pay-ins carry an account number without a bank code, and Brazilian ones lack
     the branch and account type that an `ACCOUNT_BRAZIL` payout requires.
   - The refund has no amount field, so nothing can be deducted from it. Decision
     (option B, 2026-09-30): deduct only where a partial payout is possible, i.e.
     **Mexico** (CLABE + name are complete): `returned = received − Confío fee
     (INFINIA_UNCONFIRMED_PAYIN_RETURN_FEE_BPS, 90) − Infinia pay-in processing −
     Infinia return-payout processing`. **Not built yet**: Confío has no Infinia
     account of its own (no `platform_liquidity` account exists in prod) to receive
     the deduction. Until one exists, Mexico also gets the full refund.
   - Infinia can turn a SUCCESS refund into FAILED later; SUCCESS rows are
     re-checked every 15 minutes for 3 days.
   - Race with release: the row is locked; once `returning`, a face pass no longer
     releases it.
   - Contract: §7.8 (Confío bears return costs), §7.10 (meet Infinia's and the
     regulator's deadlines for fraudulent returns: 24h is well inside).
5. **States** — `awaiting_face` → `releasing` → (journey takes over), or
   `awaiting_face` → `returning` → `returned` | `return_failed`.
   `return_failed` must not loop silently: log and surface it in admin.

## GraphQL contract (the app reads exactly this)

Isolated operations (never merged into a shared query).

```graphql
type PendingIncomingPayin {
  id: ID!                 # stable id of the held pay-in
  state: String!          # awaiting_face | releasing | review | returning | returned | return_failed
  amount: String!         # decimal string, as received
  asset: String!          # local currency code, e.g. "COP"
  country: String!        # ISO-2
  payerName: String       # as reported by the rail; null if unknown
  receivedAt: DateTime!
  returnsAt: DateTime!    # 24h after the hold started (awaiting_since), server clock
  returnAmount: String    # server-computed amount the payer would get back
  returnDeduction: String # server-computed total deducted (fee + Infinia costs)
  journeyId: ID           # set once released, for the transfer status screen
}

type Query {
  pendingIncomingPayins: [PendingIncomingPayin!]!   # caller's personal account only;
                                                    # awaiting/releasing/returning,
                                                    # plus returned/return_failed
                                                    # from the last 7 days
}

type ReleasePendingPayinsResult {
  success: Boolean!
  error: String
  nextStep: String        # 'face_check' when a fresh Confío Face is needed
  released: [PendingIncomingPayin!]!
}

type Mutation {
  releasePendingPayins: ReleasePendingPayinsResult!
}
```

## App (Claude Code session)

- Home promo slot, top priority (unclaimed money that expires): "Tienes dinero por
  recibir" card with the total, payer, and time left.
- Pending incoming screen: each pay-in, countdown to `returnsAt`, one
  "Confirmar con mi rostro" button for the whole queue, then the transfer status.
  Returned items say "Devuelto al remitente" with `returnAmount`.
- Needs from the shared files Codex is editing (add when convenient, or the app
  session will after Codex commits):
  - `apps/src/services/faceStepUp.ts`: add `'payin_release'` to `FaceCheckPurpose`.
  - `apps/src/components/FaceCheckProvider.tsx`: `PURPOSE_COPY.payin_release =
    'Tienes dinero por recibir. Confirma con tu rostro que eres tú para recibirlo.'`
