# Infinia name admission audit — 2026-09-16

Scope: the local name-based fiat admission change, its documentation, and the
automatic-deposit/journey/submission integration. Document type, number and
jurisdiction are deliberately excluded by product instruction. No production
changes or payment operations were performed.

## Findings and fixes

- Corrected obsolete account-field help text claiming an empty document country
  disables same-owner admission. Migration 0024 preserves the field and changes
  metadata only; `sqlmigrate` produces a no-op.
- Corrected rollout documentation: existing pending automatic-pay-in jobs are
  re-evaluated and may become eligible. There is no historical sweep or restart
  of review jobs.
- Added a worker regression for a name-only receipt with reordered name components,
  absent document type, a differing identifier and no document jurisdiction. It
  verifies one journey despite repeated processing, and rejection before provider
  submission after same-name capability revocation.

## Review loop

The parent reviewed ownership snapshot provenance, normalization, third-party
approval gates, webhook/quote/journey/submission enforcement and pending-job
behavior. An independent in-host reviewer completed two passes, including the
final fixes, and reported no remaining actionable findings in this scope.
The external Claude review adapter was unavailable: the installed gstack runtime
lacks `lib/claude-bin.ts`. No external review was completed.

## Verification

- Final focused suite: 212 tests passed (admission, automatic pay-in, journeys,
  webhooks and local-money integration).
- Full payment-account suite: 619 tests, one error in concurrently introduced
  `IncomingSenderSchemaTests.test_sender_fields_are_scoped_to_owned_journey`:
  the test did not enable Infinia payment accounts. This is outside the scoped
  change; the full suite is not green.
- Offline harness uses isolated PostgreSQL, mocks external services, disables
  unrelated historical migrations and explicitly seeds eligibility policies.
  Ambient iOS attestation configuration was disabled in the temporary harness
  to avoid affecting Android configuration assertions.
- Migration consistency check: no missing migrations. Migration 0024 SQL: no-op.
- Diff whitespace check passed.

Name matching cannot distinguish unrelated people sharing the same normalized
full name; this is the accepted name-based policy. Existing account-wide guards
can block otherwise admitted funds when another credit is held. Automatic returns
and deposit-level balance isolation remain outside this change. Changes are local
and have not been deployed.

## Isolated shipping verification

On `codex/infinia-name-admission`, based on `88f861e0`, all 615 payment-account
tests passed from the isolated worktree. Concurrent incoming-details changes were
not included. External services were mocked; the database was isolated PostgreSQL.
