# EDD automation audit — 2026-09-15

## Result

Two audit passes, including an independent in-host adversarial review. No
remaining actionable code findings in the scoped EDD automation and monthly-limit
changes after fixes. Provider-side review initiation remains unverified.

## Fixes

1. **Credential exposure in worker logs:** chained HTTP exceptions could include
   presigned evidence URLs. The worker now raises a fixed, sanitized retry error
   without the underlying chain; reconciliation logs only the request UUID.
   Regression tests inspect formatted exceptions and captured logs.
2. **Manual closure required after automatic handoff:** forwarded requests remained
   pending forever and blocked later submissions. Forwarded now means completed
   document handoff, without claiming provider approval. The UI permits fresh
   evidence, and migration 0022 preserves one pending request while permitting
   completed history. New requests use distinct Didit references; earlier
   forwarded sessions cannot be reassigned.
3. **Limit copy:** Verification now labels the amounts as initial defaults and
   distinguishes personal US$10,000 from business US$100,000 monthly limits.

## Validation

- 171 backend tests passed: EDD, local money, Infinia journeys.
- The backend suite includes applying migration 0022 operations over the previous
  PostgreSQL uniqueness constraint, then checking completed history and rejection
  of a second pending request. Full historical migration replay was not run.
- 27 mobile tests passed: EDD screen, send activation, Verification.
- Python syntax and git diff whitespace checks passed.
- Second independent adversarial review: no additional actionable findings.
- External Claude review unavailable: installed claude-bin.ts helper is missing.
- No live EDD evidence was uploaded and no deployment performed by this audit.

## Deployment and provider boundary

Apply `payment_accounts.0022_edd_forwarded_terminal`, restart Celery workers and
beat for automatic forwarding and five-minute recovery, and release the mobile
changes. Rolling the constraint back requires resolving multiple forwarded rows
per owner before restoring its earlier definition.

The [Infinia owner update API](https://docs.infiniaweb.com/reference/v1_5_update_account_owner)
accepts evidence document IDs and expected monthly volume for SELF_DECLARED owners.
The [published limit-increase process](https://docs.infiniaweb.com/docs/transaction-limits)
still specifies an account-manager request. Document attachment alone is not
confirmed to initiate their compliance review; the app therefore reports documents
sent, not approval. Infinia enforces monthly limits on execution. Provider rejection
after bridging may require recovery of funds held there; no automatic refund was added.

## Durable learnings

- HTTP exception chains can contain short-lived document credentials even when
  the outer error message is sanitized. Background retry logs must suppress them.
- A completed evidence handoff and a provider's approval are different states;
  retaining the handoff as pending creates an unintended operator dependency.
