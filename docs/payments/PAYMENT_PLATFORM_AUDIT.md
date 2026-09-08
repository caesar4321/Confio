# Institutional payment platform — audit and fix record

Date: 2026-09-04 (America/Lima)

Scope: implemented institutional billing changes in the working tree, including
the existing BSC payment rail and reconciliation integration. Review included
financial/backend, API/privacy/connector, member/mobile, operator controls, and
cross-component integration passes. No production database, deployment, real
payment, commit, or push was performed.

## Corrected findings

- Financial safety: preserve prepared server-authorized calls and funding units;
  prevent account switches from replacing an outstanding authorization; serialize
  preparation/expiry with finalization; prevent late broadcast responses from
  reverting confirmed payments; validate receipt/log provenance before journaling.
- Isolation: test/live subject, schedule, obligation, and import identities are
  separate. API queries, imports, checkout, allocation, and institution dispatch
  enforce mode and merchant boundaries. Deleted merchants cannot authenticate.
- Identity: enforce one-use session ownership, current manifests and grants,
  field-limited disclosure, and transactional claim rollback. Redact membership
  tokens from GraphQL and Apollo logs. Public application DTOs and new events
  expose only reviewed institution status codes, never free-form provider status
  text. The simple membership claim rejects flows
  requiring identity-field consent until the dedicated consent UX exists.
- API reliability: validate amounts and timestamp filters; rollback partial
  operations; preserve idempotent terminal responses; encrypt cached webhook
  secrets; return safe structured unexpected errors. OpenAPI now describes all
  18 implemented paths and 27 schemas, with response-schema regressions.
- Delivery: pin HTTPS to validated public IPs with hostname-verified TLS and no
  redirects/proxies; bound responses; recover abandoned delivery leases; stop
  disabled endpoints; serialize replay numbering. Finalization uses durable
  events/outbox rather than synchronous webhook fanout.
- Scheduling/imports: reject lossy amounts and conflicting debts; respect
  schedule limits and mode; keep pending-payment reminders retryable; create
  durable live-member reminders with retryable pushes and no sandbox pushes.
- Member UX: fix the claim loading loop; refresh after Recarga/authentication;
  suppress actions for noncollectible debts; distinguish payment confirmation
  from institution acknowledgment and say not to pay again while pending.
  Both notification entry points route to memberships. Existing Recarga remains
  the funding path; there is no Yape-specific billing implementation.
- Operations: financial evidence is read-only in admin; application actions
  require change permission and preserve lease safety/audit history. Sandbox
  seeding cannot silently replace a receiver wallet or select another merchant.

The 0.9% fee remains deducted from the receiver. Receiver-net targeting uses
gross-up; recurring dues remain reminders requiring the payer's signature.

## Verification

- Combined backend regression suite: **235 tests passed** (29.092 seconds).
- After the final public-status privacy fix: **33 journal/API tests passed**
  (8.915 seconds), including public-response schema validation.
- Membership runtime UI suite: **4 tests passed**.
- Migration drift: **no changes detected**; Django test system check: **no issues**.
- OpenAPI: **18 paths / 27 schemas validated**, including actual API response
  schema checks in the backend suite.
- Python compilation and `git diff --check`: passed.

Tests use local PostgreSQL with pgvector and synthetic fixtures, never the
production database. Startup emits missing AWS credential warnings; sponsor
unit tests also exercise caught failures. These logs do not represent failed
test assertions. Full-repository checks were not claimed or substituted for the
targeted suites above.

Reproducible checks (supply local database settings and test-only keys):

```sh
myvenv/bin/python manage.py test billing payments.test_bsc_flow cusd_plus.tests.test_sponsor_7702 --noinput --verbosity 0
myvenv/bin/python manage.py makemigrations --check --dry-run
cd apps
./node_modules/.bin/jest --config jest.config.js src/screens/__tests__/MembershipsScreen.test.tsx --runInBand --watch=false --watchman=false
```

## Remaining release gates, not certified by this audit

- Supported correction/refund execution and corresponding operator drills are
  not implemented merely because compensating journal types exist.
- Dedicated identity-field consent UX is not implemented; private-field claims
  fail closed. Real CIP verification/application requires CIP's future API,
  agreed authority, and acceptance testing; the simulator is not that API.
- Physical-device accessibility, real BSC end-to-end certification, 400,000-member
  load/outage exercises, and commercial/settlement sign-off remain necessary.
- Full-repository TypeScript checking has existing errors; the targeted runtime
  tests and changed-line checks are not a claim of a clean repository-wide build.
- Migration 0013 defaults existing rows to live. Before upgrading any nonempty
  staging installation, classify previous synthetic rows as described in the
  operations runbook. The migration was not applied to production.

Passing regressions and repeated reviews provide bounded evidence, not a proof
that no future defect is possible. `billing_readiness` checks configuration and
queue ages only; it is not production-release certification.

Audit stopping condition: all reproduced findings in the implemented scope were
fixed, affected regressions passed, and follow-up reviews identified no further
concrete defect. Future acceptance-plan features remain outside that claim.
