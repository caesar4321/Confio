# Movido conversion audit — 2026-09-26

Status: deployed to production at commit `299ab8939` via PR #4. Final independent
review found no further substantiated counting defects in the reviewed paths.

## Scope and context

Read README.md, CLAUDE.md, Claude Code project memory, and the latest relevant
Claude session. The session supersedes the memory's open item for conversion
961: Claude recorded that it repaired the row in production after checking
the receipt. The subsequent release verification below independently checked production receipts without changing records.

Website and Home Movido both read `fundFlowStats`. The metric counts completed,
non-deleted perimeter entries and exits, excludes internal cUSD/cUSD+ moves,
and keeps fiat payout timing separate. Historical raw USDT never converted
into Confío dollars remains outside this definition.

## Fixed

- Finalized event recovery now completes entries as well as exits, including
  failed rows and arrived sagas. Replays preserve completion timestamps.
- Client completion reports only acknowledge already settled rows with matching
  hashes; they cannot turn an arrival or quote into a completed conversion.
- Event matching handles hash case, prefers the bound log index, and writes
  canonical hashes for newly recovered rows.
- Saga recovery validates the wallet and uses the signed request's conversion
  ID for new clients. Equal-sized arrivals cannot consume each other's mint.
- An arrived savings saga can settle into universal cUSD without creating a
  second operation or leaving the original saga waiting.
- Mint retries preserve identity for uncertain outcomes and receive a new
  identity only after proven non-execution. The new query is isolated so older
  servers do not break the original in-flight query.
- Movido uses exact gross entry and net exit amounts, falling back to the
  historical six-decimal fields where exact values are absent.
- The fee scanner reuses adaptive log-fetch chunking, including the 50-block
  fallback, instead of indefinitely retrying oversized requests.

## Verification

Before fixes, regression tests reproduced missing completion, duplicate
mixed-case event rows, and discarded exact precision. Further review exposed
and corrected the equal-arrival retry issue. A fresh independent pass made
no edits and found no further substantiated defects.

- 297 backend tests passed: public metrics/GraphQL, perimeter reconciliation,
  saga persistence, historical backfill, deposits, sponsored batches, local
  transfer activity, Infinia fee collection, and Algorand reaper scope.
- 29 app tests passed: mint retries, Home stats, and FundFlow screen.
- 17 website tests passed: stats query/formatting, hero, and testimonials.
  The normal hero suite cannot load because `ConfioHomeDemo.jpeg` was already
  deleted in the working tree before this audit. Website verification used a
  temporary Jest asset stub outside the repository; the deletion was preserved.
- Scoped `git diff --check` passed.

## Operational limits and learning

These changes do not replay historical scanner ranges or repair historical
production rows automatically. Old pre-fee sagas without finalized-event
evidence still require receipt-backed reconciliation. No migration is needed.

Stable request identity and ledger ownership must agree: assigning a mint to
the oldest equal-sized arrival is unsafe once retries are keyed to a specific
conversion. A finalized scanner must also complete the recovered ledger row,
not merely save amounts and advance its cursor.

## Release verification

The release review also closed a race between delayed mint attempts and newer
retry generations: a saga row lock now reserves each signed mint before
broadcast, rejecting overlapping live attempts. Eight additional regressions pass.

Read-only production reconciliation checked 237 historical BSC conversion
batches: 235 finalized receipts, two reverted receipts, and 155 fee events.
Every fee event matched its conversion record; there were no repair proposals
or receipt errors. The historical pre-fee backfill dry run found zero missing
entries or exits, and completed conversion hashes had no duplicates.

Before deployment, Movido was US$211,343.567051 across 721 operations. Exact
amount aggregation over the same records is US$211,343.567059544017175121, a
change of US$0.000008544017175121, leaving the whole-dollar display unchanged.

The clean release checkout passed all 17 website tests without an asset stub.
App sources match the previously verified 29-test run byte-for-byte.

The additional Claude Code outside review was unavailable: its authenticated
run timed out after 180 seconds. It is not counted as a passing review.

## Deployment result

PR: https://github.com/caesar4321/Confio/pull/4

Production dependencies and Django checks passed; no migrations were pending.
Daphne, Celery, and Celery Beat were restarted and are active. Historical
backfill ran with `--apply`: zero entries, zero exits, no skipped candidates.
The public stats cache was refreshed. Live HTTPS GraphQL returned
US$211,343.56705954403 across 721 operations (437 entries, 284 exits).
The audit changes only precision, leaving the displayed total unchanged.

Backend safeguards are live. Mobile retry changes are merged in source and
will reach devices with the next mobile release; no app-store build was published.
