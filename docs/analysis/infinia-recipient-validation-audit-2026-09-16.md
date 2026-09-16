# Infinia recipient validation audit

Scope: the uncommitted server switch disabling paid Infinia account-owner
lookups, the `not_checked` API state, and the local-send recipient/review UI.
This audit does not change payout fees or deploy code.

## Follow-up correction: recipient entry

The user's subsequent UI check exposed a gap missed by the first two passes:
the typed/pasted entry path still had a `Revisar` action and could start a
recipient request before Continue. The earlier clean result did not cover that
path adequately. The source now defers typed, pasted, and scanned recipients
until Continue, removes the `Revisar` action, and bounds the entire recipient
request (including location retry) to 20 seconds. The action button owns the
loading state; typing does not start a lookup spinner. Added component tests
exercise entry, timeout recovery, and late responses after edits. These changes
still require an updated app build and server deployment; they are not evidence
of what is running on the user's device.

## Audit-and-fix passes

Pass 1 found and fixed two concrete issues:

1. **Indistinguishable QR recipients.** With lookup results absent, saved
   Argentina QR recipients and final review displayed only `QR`. Labels now
   include merchant text from the QR and a stable short reference derived from
   its payload. This text does not populate the verified holder-name field or
   display a verified-owner badge. Identical merchant names still have distinct
   references when their QR payloads differ.
2. **Truncated destination keys.** Bre-B accepts keys longer than the persisted
   label's 100-character limit. The API now derives the full display label from
   stored destination details; database labels retain their existing size limit.
   Old truncated labels therefore do not truncate the final-review destination.

Updated the configuration documentation to describe paid lookups being off by
default, cached verification expiry, and old-mobile behavior.

Pass 2: primary source review and independent Codex adversarial source review
found no remaining actionable issues within this scope. Reviewed status consumers,
both provider validation endpoints, saved-recipient refresh, final-review
invalidation, and setting transitions. The independent reviewer inspected test
changes in summary mode; the primary reviewer inspected and ran the tests.

## Validation

- 60 backend tests passed: `payment_accounts.tests.test_local_money` and
  `payment_accounts.tests.test_validation_timeout`.
- Backend tests ran against isolated temporary PostgreSQL 17 with migrations,
  mocked AWS secrets/KMS, an ephemeral wallet-encryption key, and local-memory
  cache. No production database or live payout was used.
- 15 React Native UI tests passed in `LocalSendActivation.test.tsx`, using
  `jest --config jest.config.js --runInBand --watchman=false`.
- Regressions cover paid-call blocking, pending-check release, fresh cached
  results, expired names, re-enabling lookups, QR distinction, full long keys,
  normal review for skipped lookups, warning behavior for actual failed lookups,
  and invalidating review when the recipient is edited.
- `git diff --check` passed.

## Coverage limits and release notes

- Claude Code outside review was attempted but unavailable due to authentication.
  This is missing coverage, not a clean outside-review result.
- UI validation used component tests, not an on-device visual review.
- Older mobile versions still interpret `not_checked` through their existing
  unverified-warning/checkbox fallback. The updated app is needed for the neutral
  recipient-details UX.
- Not deployed. Live Infinia billing mechanics, including Colombia's blockchain
  fee, remain outside this code audit and require provider confirmation.
