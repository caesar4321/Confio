# Bridge and provider orchestration audit

Date: 2026-09-05. Scope: NEXT BSC/Polygon bridge, Infinia and Cobre journeys,
shared provider submission/webhook/reconciliation paths, and their mobile review
and recovery screens. Repeated review/fix passes ended with no further verified
actionable findings in this scope. This is a code audit, not provider certification.

## Fixes verified

- Provider reconciliation uses an atomic submission-snapshot comparison after
  remote lookup, so a late lookup cannot overwrite a newer webhook or retry a
  changed instruction.
- Operation row locks permit foreign-key references, and submission locks the
  journey before its source financial account. This avoids refund/retry deadlocks.
  Late HTTP handlers and result application use the same compatible row locks.
- Balance updates compare timestamps atomically. A delayed conversion credit
  settles only an operation still in `settling`; it cannot overwrite a failure.
- Late HTTP responses retain newer terminal evidence while binding a previously
  unknown provider ID. Contradictory terminal statuses or changed operation IDs
  require review instead of silently replacing verified identity/state.
- Infinia rechecks early refunds by provider operation ID. Result binding also
  rechecks refunds, including on a previously completed journey.
- Malformed FX quotes and invalid Infinia wallet receipt amounts enter review.
  An attached pending Infinia return bridge retains the `bridging` stage.
- Return-bridge request IDs are deterministic per provider/journey. Lost prepare
  and attach responses recover the same transfer across app restarts. A saved
  preparation can be recovered after its short pricing quote expires; its own
  signing deadline still applies.
- Resumed approval shows the immutable destination summary, authorized FX
  minimum, amount and fee. Merely resuming never signs a transaction.
- Split outbound bridge delivery enters review: the current single-credit
  provider binding cannot treat one installment as payment for the whole transfer.

## Validation

- 272 backend tests passed: `payment_accounts` and `cusd_plus.tests.test_sponsor_7702`.
- 17 app tests passed across the payment bridge service and three screen suites.
- A real PostgreSQL transaction/thread regression exercised refund versus retry,
  including deferred ledger foreign-key checks and bounded lock timeouts.
- New tests cover stale lookups, stale balances/credits, late result binding,
  early refunds, malformed quotes, split delivery, expired pricing recovery,
  lost app responses and resumed approval details.
- Payment-account migration state matches models; whitespace checks passed.
- Full-app TypeScript checking still reports existing errors outside the bridge
  and orchestration files. No errors were reported in these feature files.

Tests used an isolated local PostgreSQL instance and mocked provider calls.
No live transfers, deployment, commits or pushes were performed. Both provider
orchestrators remain disabled pending their documented sandbox certification
and resource setup. The isolated database was stopped after validation.
