# Infinia activation audit

Scope: the uncommitted US$10 account-opening flow, collector contract, payment
preparation/submission, unpaid-account API gates, reconciliation, and mobile retry
controls. Existing unrelated workspace changes were outside this audit.

## Outcome

Three review passes completed. The final pass found no remaining actionable
issues within this scope. Nothing was deployed or broadcast.

## Fixes

- Reused payments and submission both recheck account readiness and the stored
  token/network. A closed account cannot use previously prepared payment calls.
- Readiness requires active provider profiles and unexpired local and crypto
  instructions, in addition to active accounts.
- Terminal unpaid openings release the unfinished-opening allowance when there
  is no potentially executable payment. Prepared or uncertain payments retain
  their original records; confirmed settlement takes precedence.
- Reconciliation refreshes unready unpaid accounts using their existing provider
  IDs. The periodic task also includes accounts awaiting payment.
- Cancelling consent/payment or encountering a payment error refreshes mobile
  state and leaves an explicit retry action on the send screen.
- A sufficient total balance split below the savings conversion minimum now
  explains the top-up needed instead of incorrectly reporting a total shortfall.

## Verification

- 368 payment-account and send backend tests passed against isolated PostgreSQL.
  The test harness disabled unrelated historical migrations and loaded the
  initial eligibility-policy seed explicitly.
- 12 mobile service and rendered-screen tests passed, including retry after
  declined consent, declined payment, and payment failure.
- 4 collector contract tests passed, including 512 fuzz cases for fixed treasury
  sweeping and rejection of refund/arbitrary-withdrawal/upgrade calls.
- Model/migration consistency and diff whitespace checks passed.
- Whole-project TypeScript checking still reports existing errors; no diagnostics
  refer to the activation files changed in this audit.

Collector deployment/configuration, production migration execution, provider
integration validation, and mobile rollout remain deployment work. This audit
does not establish their completion or guarantee absence of undiscovered bugs.
