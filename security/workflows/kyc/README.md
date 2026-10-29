# Confío general personal KYC workflow

Created and published on 2026-10-29 through Didit's management API.

| Resource | ID |
| --- | --- |
| Confio General KYC + AML | `f1f13336-99ad-48f5-aba8-77c92194d3b4` (version 1, Didit default) |

`general-kyc-workflow.json` is the exact request body that was POSTed to `/v3/workflows/` as a draft. The workflow was then PATCHed to `{"status": "published", "is_default": true}`.

## What it is

The same feature chain and settings as the per-country "<Country> KYC + AML" workflows. The source was a copy of Argentina, `34134808`:

- **Graph:** OCR → LIVENESS → FACE_MATCH → AML → status. Every node config is identical to Argentina's on readback (0 graph differences outside `documents_allowed`).
- **AML:** ongoing monitoring on. NFC off.
- **Documents:** ID, passport (P) and residence permit (RP), wherever Didit supports them. That is 228 countries, taken from the additional-document workflow `ecfcc905` with every other type (DL, HIC, SSC, TC, PSC, FIREARM) left out.
- **Price:** $0.57, the same as Argentina.

## Why it accepts every passport

This workflow answers "is this a real, live person with a real document". It does not answer "can this person use rail X".

If it refused passports, a person whose only document is a passport could never pass first KYC. They also could never reach the additional-document step, which requires a verified person.

Rail requirements are enforced at the rail. Koywe, for example, refuses passports except in Colombia (`ramps/koywe_client.py` `_resolve_document_type`). The rail then asks for the document it needs through the additional-document workflow (`ecfcc905`, `expected_details`), which binds it to the same person.

## Known readback quirk

`GET /v3/workflows/{id}/` reports `is_liveness_enabled: false` and `is_face_match_enabled: false`, even though:
- `features` reads `OCR + LIVENESS + FACE_MATCH + AML`,
- the graph has both nodes,
- the price matches Argentina, where both flags read true.

The EDD workflow showed the same quirk for proof of address. Confirm liveness and face match on the first real session (its `features` list in `/v3/sessions/`) before relying on it.

## Changing it

Do not POST a replacement. Use Didit's draft/version lifecycle on this `workflow_id` (see `security/workflows/business/README.md`, "Later changes without replacing the workflow").

The country restriction lives in `workflow_graph.nodes.ocr.config.documents_allowed`. The top-level `documents_allowed` is always null and means nothing.
