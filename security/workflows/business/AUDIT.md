# KYB activation audit — 2026-09-15

## Corrections made

- Removed cross-account verification-status fallbacks and business-to-personal
  approval cloning. Company approval cannot change the owner's personal name.
- Bound session sync and resume to the authenticated user and business. Business
  verification uses the hosted company flow and a validated session URL.
- Removed short-lived questionnaire media URLs from persisted decisions.
- Mapped reviewed business questionnaires, company evidence and all declared
  UBOs to Infinia. Rejected skipped/deleted UBO checks and incomplete evidence.
- Corrected ignored Didit role flags, omitted role defaults, document-group
  casing and impossible document requirements. Published business version 3
  with the original stable workflow ID.
- Blocked Koywe business orders before its personal-profile adapter runs.

Independent code reviews repeated after repairs found no further supported KYB
findings. The optional outside Claude review was unavailable because its local
CLI authentication failed; it is not counted as completed coverage.

## Scope and evidence

Tests cover account separation, safe hosted links, pending-session behavior,
actual model saves, evidence approval and media restrictions, UBO completeness,
provider payloads and workflow policy. Backend tests use isolated PostgreSQL
and mock secrets/KMS and provider calls. The broad run uses actual migrations.
No real company/identity documents were submitted to Didit or either partner.

The affected backend suite passed: **705 tests**, including actual migrations.
Django model/migration drift checks found no missing migrations.

The final full mobile suite passed: **82 suites / 732 tests**. Jest used `--forceExit`
because the repository has existing open handles. A native device build and
the full applicant journey have not been validated by this audit.

The broader workspace review also covered the concurrent EDD automation and
Bre-B changes. A display-snapshot race was corrected. Actual migration tests
found the historical missing Guardarian withdrawal column; migration 0009 adds
it only if missing. Existing databases retain the current column and data.

Production read-only checks confirmed the Didit webhook is enabled and found
one approved business with no matching generated personal clone. These counts
do not prove that every historical profile attribute is correct.

## Activation boundaries

The backend defaults to the published KYB workflow. Mobile launch/UI changes
require an updated app build. Koywe company provisioning and partner acceptance
remain separate gates; no partner approval is inferred from this deployment.
See README for the provisional policy and source documentation.
