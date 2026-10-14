# Provider routing for local money rails (design)

**Status**: draft 2026-10-13, for review before any code.
**Why now**: several provider candidates (Mesa de pagos, PagoASAP, DePay, Cobre)
differ on exactly *who* they accept, and their production keys arrive over the
next weeks. Swapping a rail's provider per user must be configuration, not a
rewrite. Provider API clients wait for KYB and production keys (sandboxes are
broken or not issued); this design only prepares the seam they plug into.

## Where the code is today (audited 2026-10-11)

Mostly provider-shaped already:

- The app's rail list (`apps/src/config/localRails.ts`) is provider-neutral:
  users pick a rail, the backend picks the provider.
- `payment_accounts/providers/base.py` defines `PaymentAccountProvider`
  (provisioning, funding instructions, pay-ins, payouts, transfers, webhooks);
  Infinia and Cobre implement it; `providers/registry.py` looks one up by name.
- `EligibilityPolicy` answers "may this person use provider X for scope Y"
  (nationality, residence, document, destination country), and
  `{PROVIDER}_PAYMENT_ACCOUNTS_ENABLED` flags exist per provider.
- The BSC↔Polygon funding leg is generic at its core: quotes key on a
  `FundingInstruction` and its Polygon address; routing (Relay / NEAR Intents)
  and chain proofs are provider-independent.

What is hardcoded:

- **No rail → provider map.** `local_money.py` (status, account lookup,
  activation, payout destinations, quotes) and `receiving_rails.py` use the
  literal `'infinia'`.
- `Provider` choices hold only `COBRE` and `INFINIA` (a new provider needs a
  migration).
- Bridge: a `{'cobre','infinia'}` allowlist in four places, an Infinia legacy-fee
  lookup that runs for any provider, `funding_mode` limited to
  `wallet`/`infinia`, per-provider credit matching, and the provider-funded
  direction (`infinia_bridge.py`) is Infinia-only.
- Journeys are per-provider models/modules with no shared interface.
- `ramps/` (Koywe, Guardarian) is a separate silo; not in scope here.

## Routing model

A provider is chosen per **(rail, direction, user)**, not per country:

    route(rail, direction, user) -> provider | None

Inputs that matter:

| Input | Why |
|---|---|
| rail + direction | e.g. Bre-B receive (personal key) vs Bre-B send are different products |
| account country | where the rail lives |
| **user nationality** | providers differ on nationals: a Venezuelan in Colombia may be refused by one provider and accepted by another for the same Bre-B rail |
| user residence / documents | already modeled by `EligibilityPolicy` rules |

Resolution: an ordered **candidate list per (rail, direction)**, evaluated in
order; the first provider that is enabled (flag), supports the shape, and whose
`EligibilityPolicy` accepts this user wins. No match = the rail shows as
unavailable (or stays a waitlist probe), never a silent fallback to a provider
that would refuse later.

This reuses the existing eligibility engine instead of inventing a second rules
system: routing = ordered candidates + existing per-provider eligibility, which
already evaluates nationality and residence.

### Provider landscape (as of 2026-10-13, to keep current)

| Provider | Status | Notes |
|---|---|---|
| Infinia | live | does not accept Venezuelan nationals (any residence); US/EU accounts beta, not live for us |
| Koywe | live | Mexico |
| Cobre | candidate | personal Bre-B receiving keys |
| Mesa de pagos | candidate (KYB) | Bolivia; other LATAM local accounts per sales, unconfirmed; VE nationals unanswered |
| PagoASAP | candidate (KYB) | VES on/off-ramp; Bre-B Móvil is one-way COP→VES, no personal keys |
| DePay | candidate | outbound QR/transfer payouts AR, BR, PE, CO, BO, PY, VE; prefunded; accepts VE nationals |
| VEXPay | on hold (sandbox) | VES and COP collection → USDT BEP20; Confío does the KYC (omnibus), so VE nationals are not refused by the provider; Bre-B needs no buyer document; ~7–8% all-in, held as the COP↔VES corridor fallback |

## First code step (proposed, small, no behavior change)

1. `payment_accounts/routing.py`: `ROUTES = {(method_id, direction): ['infinia']}`
   and `route(method_id, direction, user) -> str | None` using the existing
   flags and `evaluate_active_policy` per candidate.
2. Replace the literal `'infinia'` in `local_money.py` / `receiving_rails.py`
   with the routed provider. With Infinia as the only candidate everywhere,
   behavior is identical; tests pin that.
3. Tests: nationality routing (a VE national skips a provider whose policy
   refuses VE nationals and lands on the next candidate; none left = unavailable).

Deferred until the first real provider (its actual API decides the shape):
`Provider` choices + migration, removing the bridge allowlists, a generic
`funding_mode`, a shared journey interface, the provider-funded bridge
direction for non-Infinia providers.

## Open questions

- ~~Eligibility rows for nationality~~ — confirmed 2026-10-13: Infinia's seeded
  policy already refuses `VEN` nationals (`infinia_nationality_not_supported`,
  `payment_accounts/migrations/0002_seed_initial_eligibility_policies.py`), and
  Cobre's rows cover Venezuelans resident in Colombia (`0017_cobre_breb_outside_venezuela`).
  Nationality routing therefore needs no new rules engine, only ordered candidates.
- Do quotes need routing too (a rail's quote must come from the provider that
  will execute)? Assumed yes: quote and execute through the same `route()`.
