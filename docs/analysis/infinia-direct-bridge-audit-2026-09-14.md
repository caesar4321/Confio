# Infinia direct bridge audit — 2026-09-14

Scope: Infinia USDC payouts directly funding Allbridge NEXT Polygon deposits, with USDT delivered to the user's Confío BSC wallet. Review covered the working-tree implementation, provider contracts, authorization, reconciliation, retries, and app confirmation/signing behavior.

## Findings fixed

1. **Independent receipt minimum:** New inbound journeys require a user-authorized minimum BSC USDT receipt, separate from the FX minimum. The built bridge must meet it before payout creation. Rejected preparation rolls back its quote and transfer. Existing journeys without this field retain the legacy wallet flow.
2. **Prerequisites before conversion:** Execution flags, the bridge limit, and an active crypto funding instruction are checked before FX submission and again before bridge/payout submission. Permanent post-FX failures enter review instead of retrying indefinitely.
3. **Late delivery recovery:** Delayed deposits and delayed source confirmations can complete from verified delivery evidence. Recovery observes the existing payout and bridge; it cannot create another payout or clear unrelated review/refund failures.
4. **Provider amount validation:** Invalid numeric payout serialization becomes a handled capability error, leaving an unsent operation failed instead of submitted. Legacy Polygon destination payloads are normalized to the current provider structure.
5. **Stale status reservation:** A completed journey releases its account reservation even if Infinia's payout status webhook lags behind verified delivery. Completed-journey submission guards still prevent replay.

## Verification

- Full `payment_accounts.tests`: **221 passed**, using a fresh isolated PostgreSQL test database and mocked provider/AWS calls.
- App bridge service, existing payment screen, and new direct payment screen suites: **15 passed** across three suites.
- Django migration consistency check: **no changes detected** after migrations 0012 and 0013.
- Independent contract and race/recovery reviewers re-audited the fixes; neither reported unresolved findings. A final narrow review also cleared the late-status reservation and delayed-confirmation recovery changes.
- Existing app lint tooling remains incompatible with its installed ESLint version; it was not changed as part of this audit.

No known actionable findings remain within this review's scope. This is not a live provider settlement test: actual fees, timing, and live delivery still require operational validation. Automatic refund handling remains deferred as requested. Changes are not deployed; deployment requires migrations through 0013.
