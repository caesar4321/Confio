# Content polls audit — 2026-09-23

Scope: polls with answer options in Descubrir and Mensajes, shared voting state, Portal authoring/results, backend access control, and alternate Django admin write paths. Unrelated navigation and Invest changes were excluded.

Two audit-and-fix passes were followed by a final review of the updated code. No further actionable poll-scope findings remained in that review.

## Findings fixed

1. Poll results incurred per-item database queries. Feed, Portal, and editorial-message results now aggregate votes in bounded batches, including the viewer's answer in the same query.
2. A reader could combine stale answer labels with a first vote cast after an option edit. The aggregate query now reads the answer configuration and vote counts from the same database snapshot.
3. Stale Django admin forms could overwrite newer Portal poll configuration or closure. Standalone and inline admin saves now lock the content row and preserve the current poll configuration.
4. Normalized Apollo poll updates could reset local message reactions and discard older loaded messages. Inbox hydration now follows network completion while poll fragments update independently.
5. Refreshing a message channel could retain stale older polls when the first-page IDs were unchanged. A completed refresh now resets pagination and replaces the loaded page.
6. A delayed older-message response could append messages after an account or channel change. Pagination requests now check a generation token before applying their results.
7. Portal advanced metadata accepted JSON scalars, arrays, and null, leading to errors or lost poll configuration. Submission now requires a JSON object and displays a validation error otherwise.
8. A failed vote's error could persist when displaying another publication. Voting state now resets when the poll ID changes.

## Final verification

- Backend: 23 tests passed against local PostgreSQL with actual migrations, including concurrency, authorization, aggregation, snapshot consistency, admin preservation, and existing Portal mutation regressions.
- Mobile: 8 tests passed across the shared poll component and inbox integration suites, including duplicate-tap suppression and delayed pagination responses.
- Portal: 9 tests passed for authoring, validation, and results behavior.
- Portal production build compiled successfully.
- Migration consistency check reported no missing inbox migrations.
- `git diff --check` passed.
- Mobile TypeScript diagnostics were compared with the pre-audit baseline: 163 distinct existing diagnostics before and after, with no new diagnostics. The repository-wide TypeScript check still fails on those existing errors.

Commands and rollout instructions are in [the feature documentation](../features/content-polls.md). Test execution used isolated settings with cloud integrations mocked and three unrelated provider-credential checks silenced. Production data was not used.

## Review coverage and limits

Direct review and two independent in-host reviewers covered backend/admin behavior and mobile/Portal integration. Both reviewers rechecked the fixes and reported no remaining concrete findings. The review skill's external-review and evidence-logging modules were missing, so no outside-provider review was completed. Live device/browser interaction was not performed during this audit. No production migration or deployment was performed.

Passing checks and a clean final scoped review do not establish that every possible defect is absent.

## Lessons for future changes

- Do not rehydrate independently mutated or paginated local state on every normalized Apollo cache update.
- Every alternate full-row writer must participate in the poll locking/preservation rules, including Django admin inlines.
- When labels can change before the first vote, vote totals and their answer configuration must come from one consistent database snapshot.

## Pre-push verification

Fresh verification of the final poll styling exposed result animations continuing after their options unmounted. The effect now stops its animation on cleanup. A regression test failed before the fix and passed afterward; the mobile runner also exited cleanly without teardown errors.

The final pre-push runs passed 23 PostgreSQL tests, 10 mobile tests, and 9 Portal tests (42 total), plus the Portal production build and migration consistency check. The feature documentation reflects that mobile results remain hidden until the viewer votes or the poll closes.
