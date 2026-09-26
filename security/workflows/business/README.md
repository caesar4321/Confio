# Confío business verification — provisional KYB v4

Created on 2026-09-15; updated on 2026-09-26 to business workflow v4, person v2 and questionnaire v3. This is a best-effort policy based
on public provider documentation, not confirmation of partner acceptance.
The user authorized proceeding without a partner-specific checklist and revising
this workflow later.

## Published resources

| Resource | ID |
| --- | --- |
| Business KYB workflow | `8513abf3-95b2-4740-8dda-2d629d0c5d77` |
| Owner / representative KYC workflow | `f3c80006-d551-4fab-9317-46ce9a5236dc` |
| Business evidence questionnaire v3 | `c8adbe87-a226-4093-81e2-6f98803d1213` |
| Person details questionnaire v3 | `75717c86-c42d-40e3-8652-91dfd438fc3e` |

The four request JSON files are the reproducible **current policy** definitions
with draft status for safe initial creation. The parent incorporates the v4 policy below.
Replace `$person_workflow`, `$person_questionnaire`, and
`$business_questionnaire` with the corresponding questionnaire version IDs and the person workflow version UUID
`142a0b57-94b2-4b93-b535-8fb18ccd1006` before submitting.
`published-resources.json` records the published versions (business v4, person
v2 and questionnaires v3), with previous versions retained in the manifest.
Neither workflow is the application default. Personal account KYC workflows were unchanged.
Confío's `DIDIT_BUSINESS_WORKFLOW_ID` defaults to the stable business ID above.
An explicit empty environment override disables business verification safely.

The app uses server-created, business-bound hosted sessions. The generic Didit workflow link is useful for
previewing but does not supply Confío's authenticated `vendor_data` binding.
Do not use that generic link as the in-app launch path.

## Required evidence and source mapping

| Area | Collection | Basis |
| --- | --- | --- |
| Legal company identity | Registry lookup; required registration number, incorporation date, legal address, company type, tax number, activity, email and phone | Infinia organization fields; Koywe entity identification |
| Incorporation | KYB legal-presence documents accept incorporation, tax registration or registry excerpt; Infinia still requires an actual incorporation certificate | Infinia requires a certificate of incorporation |
| Funds | Required questionnaire upload: audited financial statements, company bank statements or tax returns | Infinia organization source-of-funds requirement |
| Company address | Required questionnaire upload: utility bill, bank statement, corporate tax notice or lease; structured address fields | Infinia organization proof-of-address requirement |
| Tax identity | Explicit company `tax_number` plus required tax-registration upload | Koywe company identifiers; Infinia `tax_id` |
| Ownership and control | Required ownership-structure documents, full ownership-chain declaration, key people and percentages | Provisional Confío policy; partner thresholds remain unconfirmed |
| Representative authority | Required authorization document group, representative declaration, linked person verification | Provisional Confío policy |
| Each declared UBO / officer | ID, passive liveness, face match, AML, verified email/phone, proof of address and person questionnaire | Infinia UBO identity requirement plus current Confío adapter and conservative policy |
| Business activity and risk | Business description, operating countries, expected monthly USD volume, source of funds, PEP relationships and regulated activity | Koywe activity/transaction-monitoring needs; provisional risk review |
| Review | Clean completed questionnaires proceed automatically; explicit risk rules and document discrepancies route to review; parent waits for UBO checks | Provisional policy pending provider feedback |

Infinia's [Required Documents](https://docs.infiniaweb.com/docs/required-documents)
page specifically marks incorporation, company source of funds and company
proof of address as mandatory. Its general Account Owners page describes
source-of-funds more broadly as risk-dependent; v1 follows the more specific
organization table. Allowed evidence formats are JPEG, PNG or PDF, up to 10 MB.
The upload labels state this limit; provider handoff must enforce it.

Koywe's [Crypto compliance guide](https://docs-crypto.koywe.com/en/documentation/compliance)
identifies company tax documents as Mexico RFC, Colombia NIT, Peru RUC,
Argentina CUIT and Chile RUT. It also requires activity, contact/address data,
and bank-account ownership checks. Brazil CNPJ and Bolivia NIT are provisional
company identifiers to confirm with Koywe; the cited public checklist does not
specify them. A company registry number must not substitute for its tax ID.
Koywe's separate Payments merchant-onboarding API was not treated as the contract
for Confío's existing Crypto `/rest/accounts` integration.

Infinia's [Account Owners](https://docs.infiniaweb.com/docs/account-owner) guide
requires Compliance approval for a production SELF_DECLARED integration.
Koywe's guide likewise requires review before relying on a partner's own KYC.
Neither approval has been confirmed for this business flow.

## Provisional policy choices

- Registry lookup: Argentina, Bolivia, Brazil, Chile, Colombia, Mexico, Peru,
  Paraguay and Uruguay, basic tier. This is a collection scope, not a claim that
  every provider offers business accounts in each country. Existing eligibility
  policy still applies.
- Every **declared** UBO is subject to KYC: ownership threshold `0`. All 17 supported person roles have explicit non-skippable
  `require_kyc` settings and the same linked person workflow. This is not a legal UBO threshold. A reviewer must
  establish that owners and controllers have actually been disclosed.
- Corporate ownership chains require documentation and manual review through
  to natural persons. Recursive corporate KYB is disabled; the Infinia adapter
  requires natural-person UBOs. No-owner / widely held cases require provider
  guidance rather than inventing an owner.
- Verified-person reuse is disabled for v1 so old, weaker checks are not reused.
- Person IDs: passports where supported by Didit, plus national IDs in the nine
  listed countries. Provider nationality/document eligibility remains a separate
  check. A passport number must not be substituted for a required local tax ID.
- AML approve threshold `1`, review threshold `100`, for business and people.
  Didit uses a strict less-than approval comparison: `0` previously sent even
  score-zero, no-hit screenings to review.
  Potential matches need analyst adjudication; a PEP declaration is not an
  automatic rejection. No ongoing-monitoring subscription was enabled.
- Key-person automatic invitation emails are disabled. No messages were sent.
  The hosted KYB flow exposes linked-person verification steps.
- Supplementary tax-ID answers and Argentine tax jurisdiction route to manual
  review. That review must check conditional evidence, including Argentine
  CUIL, tax IDs absent from the photo ID, authority, ownership completeness,
  document dates, licenses and account ownership.

## Application integration and limits

- Business and personal status are isolated in both the app and the server.
  Business approval never grants the owner personal KYC or changes their name.
  Sync validates user, account type, business ID and Didit session kind.
- Business sessions open Didit's hosted flow using a validated, server-created
  `https://verify.didit.me/.../session/...` URL. Pending sessions resume for the
  same business; signed URLs are not persisted. The return deep link is
  `confio://verification`. Native personal verification is unchanged.
- The installed native SDK predates the current KYB flow. **A new mobile build
  is required for the hosted launch and screen changes**; restarting EC2 only
  deploys backend behavior. No mobile-store release is implied by this deploy.
- Infinia mapping accepts only explicitly allowlisted v1/v2/v3 questionnaire IDs
  and requires both the questionnaire and session to be Approved. Required
  company files, structured address and numeric monthly volume are mapped;
  verified email/phone and approved UBO proof of address are used. Bare tax-ID
  answers never replace verified IDs; supplementary Argentine CUIL requires
  reviewed official evidence. Reviewers must compare the document and answer.
- Both registry-derived and user-entered UBOs are included, with child-session
  deduplication. Skipped/deleted children, corporate UBOs, missing owners and
  incomplete evidence fail closed. Existing host/format/10 MB limits remain.
- Koywe company provisioning is not established by the public Crypto contract.
  Its order mutation therefore blocks business accounts before it can send the
  owner's personal identity. Collecting KYB does not enable Koywe business ramps.
- Partner acceptance remains unconfirmed. Infinia's existing country/policy and
  provider approval gates remain authoritative. No real applicant documents or
  provider account submission were used for this audit.

## Original v3 audit corrections (2026-09-15)

Didit's API accepts unknown nested fields, so saved JSON alone was insufficient.
The public workflow-editor implementation confirmed these corrections:

- `require_kyc` is the effective per-role flag; `require_verification` is ignored.
  Omitted officer roles default to no KYC, so all collected roles are explicit.
- Document-group codes are uppercase. Each required group now has enabled
  subtypes; the original company-details group had none.
- V3 restricted legal presence to incorporation certificates. V4 deliberately
  accepts tax registrations and registry excerpts as local legal-presence
  evidence. The Infinia handoff still separately requires incorporation; it
  never relabels tax or registry documents as incorporation certificates.
- Null document ages use Didit's group default (currently 730 days), rather
  than unlimited age. Reviewers must check jurisdiction-specific freshness.

These policy invariants have regression tests in `security/test_business_workflow.py`.

## Original verification performed (2026-09-15)

- Created all four resources as drafts, then read back their saved configuration.
- Compared requested workflow feature order, required registry fields,
  questionnaire bindings, UBO dependency/wait settings and review flags to the
  persisted graph before publication.
- Published the questionnaires, child workflow and parent workflow in dependency
  order; read back all four as their recorded published versions.
- Confirmed the parent reports `workflow_type=kyb` and both flows use manual
  questionnaire review and `is_default=false`.
- Opened the published KYB link. The hosted page displayed **Verifica tu empresa**
  and the expected company, associated-people, company-document, email, phone and
  questionnaire steps. Visiting the link created an empty preview session.
  No terms were accepted and no identity or company data was submitted.
- The complete applicant journey and Koywe/Infinia acceptance remain untested.
- Confirmed the production Didit webhook is enabled for `status.updated` and
  `data.updated` at `https://confio.lat/api/didit/webhook/`.
- A read-only production audit found one verified business and no matching
  personal clone from the removed legacy signal.

## Later changes without replacing the workflow

Update the existing workflow through Didit's supported draft/version lifecycle.
Keep the stable **`workflow_id`** in application configuration; a version's
**`uuid`** can differ after publishing a new version. Re-read both fields after
updates. Do not POST a replacement workflow to make a policy change.
See [Didit workflow creation/versioning](https://docs.didit.me/management-api/workflows/create)
and [workflow feature configuration](https://docs.didit.me/management-api/workflows/feature-configs).

Linked questionnaires also have their own IDs and versions. Verify the parent
and child graph bindings after changing them. Retain this policy's data-field
IDs so downstream evidence mappings do not silently break.

## V4 automatic decision policy (2026-09-26)

- Required structured choices cover PEP exposure, regulated activity and direct
  natural-person ownership. Missing, unknown or non-clean selections route to
  `In Review`. Existing PEP/regulated free text must also be an explicit negative
  (`None`, `Ninguno`, `No aplica`, etc.); ambiguous narrative still needs review.
- All required non-file questionnaire answers have missing-value review rules;
  uploads remain required in the form. Required consent and verified contact,
  registry, corporate-document and linked-person checks remain enabled.
- Questionnaire approval establishes completeness and risk-declaration checks.
  It does **not** certify the authenticity of bank statements or source-of-funds
  uploads. Provider review and country eligibility remain separate gates.
- Every custom status rule only escalates to review. No rule forces approval of
  another failed check. Both questionnaire blanket-review flags are disabled.
- Company document retries explicitly remain 3; exhaustion routes to review.
  Increasing retries is not a remedy for an unsupported document subtype.
- Published updates retain the stable workflow IDs. The parent explicitly binds
  the new person version UUID. Publishing a questionnaire also automatically
  repoints workflow questionnaire references in Didit; this was observed and
  checked before workflow publication. Old answer versions remain allowlisted.
- The existing pending application still needs its linked-person KYC and review
  of its old document result. No existing decision was approved, no evidence was
  deleted, and no customer notification was sent. Didit's update-status API
  refuses resubmission while the session is `Awaiting User`; after the owner
  completes KYC, an analyst can handle the existing document review. Do not
  change overall status merely to bypass this constraint.
- Read-back validation covered all feature settings and graph order. Didit adds
  default ID-document subtypes and drops disabled phone channels during save;
  enabled country/channel choices were verified unchanged.
- Local verification: 33 policy and provider-handoff tests passed. The old
  handoff rejected a new approved questionnaire fixture; the updated code
  accepted it. EC2 compatibility was deployed and all six services were active.
- Runtime limitation: no real applicant journey was submitted to prove the new
  rules end to end. Saved rules and forms were checked through the live API.


## Audit corrections (2026-09-26, questionnaire v3)

- PEP, regulated-activity and ownership choices use `single_choice`, matching
  the scalar values compared by their status rules. Didit's `multiple_choice`
  returns arrays and also permits contradictory selections. See the
  [questionnaire answer contract](https://docs.didit.me/core-technology/questionnaires/report-questionnaire).
- Questionnaire versions v1 and v2 remain accepted only when individually
  approved; new sessions use v3. Stable workflow IDs are unchanged. Publishing
  questionnaires repoints their workflow bindings; no applicant response or
  document status is manually changed by this release.
- Before Infinia evidence uploads, Brazilian company tax IDs must pass CNPJ
  format and check-digit validation (numeric and alphanumeric). Activity codes
  and personal CPFs are rejected. We never substitute the registration-number
  field to silently repair bad tax data. This validates the identifier only,
  not the company's active registration status.
- Regression tests first reproduced both defects, then passed after correction.

### Document review operations

A Simples Nacional/SIMEI consultation describes tax-regime enrollment; it is not
proof of current active CNPJ registration. Do not approve it as active-registration
evidence solely because the company name and CNPJ match. A sole proprietor's
legal name can be the proprietor's personal name.

The available mobile console was reported to show only Approve/Reject for the
individual document. Although Didit's public docs describe document requests,
replacement/resubmission through those controls has **not been verified** for
this session. Reject must not be assumed to reopen uploads after retry exhaustion.
The generic feature-status API is not a document-item status API: a document may
share `node_id=kyb_registry` with its registry check. Never change the parent or
registry decision to work around unavailable document actions. A replacement
received outside Didit still needs an authenticated attachment and review path;
receiving a file does not itself satisfy the workflow.
