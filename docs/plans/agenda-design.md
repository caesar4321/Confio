# Agenda: one address book for own and third-party accounts (design)

**Status**: approved 2026-10-25 (name "Agenda"; saved + recents). One provider-neutral list of saved payment
accounts, kept in two-way sync with the legacy models so old app builds keep
working unchanged.

## Today

| | Koywe Retiro ("Mis cuentas") | Infinia send | VE Pago Móvil |
|---|---|---|---|
| Model | `users.BankInfo` | `payment_accounts.PayoutDestination` | none |
| Created by | Add form in Mis cuentas | every recipient typed (`resolve_destination`) | typed each time |
| Provider state on the row | none (Koywe account made at order time) | holder validation; no provider id for Infinia | none |
| Delete / default | soft delete, one default | neither; app shows the last 10 | n/a |
| Own vs third party | not modelled (own in practice) | not modelled (any recipient) | not modelled |
| Also read by | P2P screens, `createRampOrder(bankInfoId)` | journeys/bridge by `destinationId` | n/a |

## Model

`payment_accounts.AgendaEntry`, one row per saved account:

- `internal_id` (public id), `confio_account` (owner; JWT context only)
- `rail`: a registry key (below) naming the country and the payment rail
- `relationship`: `own` | `third_party`
- `label`, `holder_name`, `holder_id_type`, `holder_id_number`
- `details`: the rail's normalized fields (validated by the rail)
- `bank_info` / `payout_destination`: one-to-one links to the legacy row it
  mirrors, when there is one
- `is_default`, soft delete (`deleted_at`), timestamps

## Rail registry

Each rail declares its country, fields and validator, whether third parties
are allowed, and its legacy mirror:

| Rails | Third parties | Legacy mirror |
|---|---|---|
| `ve_pagomovil` (cédula, phone, SUDEBAN bank) | yes | none (new) |
| Infinia local methods (`co_breb`, `mx_clabe`, `ar_cvu`, `br_pix`, …) | yes | `PayoutDestination` |
| Koywe methods (bank accounts, Bre-B via Koywe, Pix, CCI, …) | **no: own only** | `BankInfo` |

## Sync with the legacy models

- **Mis cuentas (`BankInfo`).** Writes keep going through the existing
  `createBankInfo` / `updateBankInfo` / `deleteBankInfo` / `setDefaultBankInfo`
  mutations, from old and new builds alike; a `post_save` mirror keeps one
  entry per row (own account, same default and soft delete). Koywe's Retiro
  and the P2P screens are not changed at all.
- **Infinia recipients (`PayoutDestination`).** Not mirrored automatically:
  every typed recipient becomes a destination today, and an Agenda is a
  deliberate list. Past validated recipients show under "Recientes" with a
  one-tap "Guardar", which links the existing destination to a new entry
  (third party or own, as the user says). Refreshed validations update the
  linked entry; deleting the entry leaves the recipient in recents.
- **VE Pago Móvil.** Agenda only: create, edit, delete through the Agenda
  API, validated exactly like an order (cédula, Venezuelan mobile, SUDEBAN
  bank code).
- Money flows keep reading what they read today (`bankInfoId`,
  `destinationId`, an order's own copy of the details).

## App

- Perfil → **Agenda** (new builds), sections "Mis cuentas" and "Otras
  personas", grouped by country; add/edit/delete/default.
- A picker plus a "Guardar en mi Agenda" toggle in Recargar/Enviar por Pago
  Móvil and in the local send.
- Old builds keep Mis cuentas and the recent-recipients list, unchanged.

## Backfill

One migration creates an entry for every live `BankInfo` row (own; they
stay "Mis cuentas" entries as today). Infinia destinations are not imported
(they are "Recientes"). The 39 legacy VE "Pago Móvil" BankInfo rows (no bank,
mostly no cédula) stay ordinary Mis cuentas entries, not VE Pago Móvil ones.
