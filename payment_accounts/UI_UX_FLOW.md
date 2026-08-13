# Local money UI/UX

Status: product design specification  
Scope: Cobre Bre-B (Colombia), Cobre Virtual CLABE (Mexico), and future Infinia
local pay-in/pay-out rails

## Product decision

Do not add `Cobre`, `Infinia`, `Bre-B`, or `CLABE` as primary navigation items.
They are implementation rails. Users should enter through four stable intents:

- `Enviar`: money to another person, business, bank, wallet, alias, key, or QR.
- `Recibir`: reusable local receiving details for salary, clients, friends, or the
  user's own transfers.
- `Recargar`: turn the user's own local money into Confío Dollar/cUSD+.
- `Retirar`: move Confío Dollar/cUSD+ to a payment method owned by the user.

This distinction is important:

- `Enviar` may be a third-party payout.
- `Retirar` is a same-owner cash-out.
- `Recibir` may accept third-party pay-ins only when the account capability allows it.
- `Recargar` is an own-funds on-ramp and should not imply that third parties can fund it.

## Amendments from the first implementation slice (2026-08-12)

Three recommendations below were **not** implemented, deliberately. The shipped
code is the source of truth where they disagree.

1. **`Pagar` stays on Home.** Paying is a daily verb; receiving a bank transfer
   is monthly at best, so trading one for the other inverts frequency-based IA.
   The `Escanear` tab is a camera icon, not a label anyone reads as "Pagar", and
   Home's employee branch gates `pay` on the `sendFunds` permission — removing it
   has permission-model ripples unrelated to this feature. `Recibir` reaches
   local accounts through Contacts and, later, `AccountDetail`'s existing
   `Recibir` button.
2. ~~The `Contactos` → `Transferir` tab rename is deferred.~~ **Done** — Julian
   called it while the user base is still small enough that relearning the tab
   costs little, which is the one window where this is cheap. Renamed further
   than originally specced: the internal route is `Transfer` too (not just the
   label), and `ContactsScreen` is now `TransferScreen`. Analytics screen names
   come from route names (`App.tsx`), so funnels split at this commit —
   `Contacts` before, `Transfer` after. The business tab is untouched and stays
   `Employees` / `Empleados`.
3. **No segmented `[Enviar] [Recibir]` control.** With two rows per mode it
   hides half the surface to save two rows. Section headers
   (`TRANSFERENCIAS LOCALES` / `CRIPTO`) do the same grouping with no
   interaction cost and keep both halves scannable.

Also implemented differently: corridors we cannot open yet are **demand probes**
(the two-stage `local_rail_interest` funnel), not "próximamente" screens. Every
corridor is a probe today because both provider flags default to `False`, so the
probes are what carries the sheet — and which corridor people ask for is the
evidence for which virtual accounts are worth paying to open.

## App Review note (paste into App Store Connect / Play Console at submission)

The unavailable corridors are a deliberate demand probe, and how they are worded
decides whether a reviewer reads them as a roadmap or as an unfinished build.
Apple Guideline 2.1 rejects submissions carrying placeholder or temporary
content; 2.3.1 rejects UI implying functionality the app does not provide.
The defence is that these rows never claim to be usable and cannot start a
transfer — so the copy says `Próximamente · Toca para recibir un aviso`
(a published roadmap entry) rather than `Aún no disponible` (a broken control),
each probe row carries a clock icon, and tapping one only opens a waitlist
opt-in. Submit with this text in the review notes rather than hoping it goes
unnoticed:

> Some local transfer rails shown under "Transferencias locales" are marked
> "Próximamente." They are not presented as currently available payment
> functionality. Tapping them allows users only to opt in to an availability
> notification, which helps us determine which country rails to prioritize.
> No payment or financial transaction can be initiated through these entries.

If Apple rejects under 2.1 anyway, hide the `status: 'probe'` rows on iOS only
(a single filter in `getSendRails`/`getReceiveRails`) and resubmit; keep them on
Android, where the rows are responsive and clearly labelled and the Broken
Functionality policy is aimed at controls that fail or hang.

Unrelated but the same risk, and worse: `handleToggleEmployee` and
`handleRemoveEmployee` in `TransferScreen`, and one path in `PayeeDetailScreen`,
still raise `Funcionalidad Pendiente · estará disponible pronto`. Those are true
dead ends — no waitlist, no action, a TODO behind a live-looking control — and
they are a cleaner 2.1 target than anything in this document. Fix or hide before
submitting.

## Entry points

### Home

For personal accounts, replace the duplicated `Pagar` quick action with `Recibir`.
`Pagar` already has the central `Escanear` tab.

Recommended order:

1. `Enviar`
2. `Recibir`
3. `Recargar`
4. `Retirar`
5. `Efectivo`

Do not add a sixth action. Do not replace `Recargar` with `Recibir`; they communicate
different ownership and conversion expectations.

### Bottom-sheet rule

A bottom sheet is a chooser, not the destination for persistent account information.
Use one only when the user has two or more immediately usable choices:

- `Recibir por cuenta local`: one active local account goes directly to its
  receiving-detail screen; multiple active accounts open `¿Dónde quieres recibir?`.
- `Enviar a banco o billetera`: recipient selection begins in Contacts. Tapping it
  opens a method sheet only when two or more destination methods are currently usable.
- Activation, KYC, account details, amount entry, review, processing, and receipts are
  full screens because they are durable, resumable tasks.

Do not show a one-option sheet. Navigate directly, matching the existing Recargar/Retirar
rule.

For business accounts, `Cobrar` remains the merchant checkout/invoice surface.
`Recibir` on Home opens reusable account details for transfers. The distinction is:

- `Cobrar`: request a particular payment, normally with an amount or invoice.
- `Recibir`: share permanent local account details.

Employees see actions only when their canonical payment-account capability and Confío
role permission both allow them. Only the business owner can activate a country account
or accept compliance terms.

### Dollar account detail

Keep `Enviar`, `Recibir`, `Recargar`, and `Retirar` on the Confío Dollar/cUSD+ detail
screen. They should enter the same flows as Home, preselecting that dollar balance as the
source or destination.

### Profile

Add `Cuentas locales` under the money/account settings section. This is the management
surface, not the primary transactional entry point. It contains:

- Active and pending country accounts
- Receiving identifiers
- Capability and limit status
- Saved payout methods
- Enhanced-verification status
- Disable/close actions when the provider supports them

## Local accounts hub

Screen title: `Cuentas locales`

Each country account is a product card, independent of provider:

```text
🇨🇴  Pesos colombianos                         Activa
Bre-B
Saldo: COP 842.500
Llave: @CONFIO••••91

[ Ver datos para recibir ]       [ Enviar ]
```

```text
🇲🇽  Pesos mexicanos                         Activa
Transferencias SPEI
CLABE: •••• •••• •••• 0182

[ Ver datos para recibir ]       [ Enviar ]
```

Use the consumer rail name (`Bre-B`, `Transferencias SPEI`, `Alias`, `Yape`, `Pix`),
not the infrastructure provider. Provider attribution belongs in legal disclosures and
support diagnostics.

Account states:

- `available`: eligible but not activated
- `needs_kyc`: standard identity verification required
- `needs_enhanced_kyc`: enhanced verification required for the requested capability
- `provisioning`: account creation accepted and processing
- `active`: usable
- `restricted`: active, but one or more operations unavailable
- `action_required`: user must submit or update information
- `rejected`
- `suspended`
- `closed`

Never render a country card just because a provider technically supports that country.
The server must return it as eligible for this user, residence, nationality, owner type,
KYC tier, and current provider contract.

## Account activation

Activation is explicit and per country. Do not pre-provision every possible virtual
account at signup. This avoids unnecessary account-creation cost and compliance records.

### Screen 1 — Value

Title examples:

- Colombia: `Recibe pesos con tu llave Bre-B`
- Mexico: `Recibe pesos con una CLABE`
- Generic: `Activa tus datos locales para recibir`

Explain only verified properties:

- Reusable or one-time
- Supported sender types
- Expected arrival time
- Currency
- Limits
- What beneficiary name the sender will see

Primary CTA: `Continuar`

If Confío charges an activation fee, disclose the exact amount here and again on the
confirmation screen. If Confío absorbs a provider's account-creation cost, do not show it
as a user fee.

### Screen 2 — Intended use

Ask only when it affects capability or verification:

`¿Quién te enviará dinero?`

- `Solo yo, desde mis cuentas`
- `Personas o empresas` — salary, clients, family, customers

If the second option requires enhanced KYC, explain that before launching verification.
Do not provision a same-name-only account and surprise the user later when salary is
rejected.

### Screen 3 — Verification gate

- Existing approved standard KYC: continue without repeating it.
- Existing approved business KYB: use the exact active business verification.
- Enhanced KYC required: show a short checklist and launch the upgrade.
- Ineligible: show the stable eligibility reason and safe alternatives.

Provider names and internal KYC modes must not appear in this screen.

### Screen 4 — Review and consent

Show:

- Country and currency
- Receiving rail
- Allowed sender types (`A tu nombre` or `También de terceros`)
- Limits and fees
- Beneficiary-name behavior
- Consent to share required verification information with the regulated provider

CTA: `Activar cuenta local`

### Screen 5 — Provisioning

Creation can be asynchronous. Leave the user on a durable status screen and notify them
when ready. Never spin indefinitely.

```text
Estamos creando tus datos para recibir
Normalmente tarda unos minutos. Puedes salir; te avisaremos.
```

The activation request must be idempotent even when the provider operation is not.

## Revised Contacts screen

Contacts already contains `Enviar con dirección` and `Recibir con dirección`. It should
be treated as Confío's unified `personas y rutas` surface, not only as an address book.
Preserve those actions and add their local-money counterparts.

Because the screen now contains contacts, crypto routes, and local payment methods,
rename the personal bottom-tab label from `Contactos` to `Transferir`. IMPLEMENTED, and the internal
route name `Contacts` during migration to avoid breaking deep links. The business variant
continues to be labeled `Empleados`.

For a personal account, the header above search/recent contacts becomes a mainstream-
first ordered list:

```text
Otras formas de transferir

TRANSFERENCIAS LOCALES
[ bank ] Enviar a banco o billetera
         CLABE, Bre-B, Alias, QR y más

[ key ]  Recibir por cuenta local
         Comparte tu Bre-B, CLABE o datos locales

CRIPTO
[ ↗ ] Enviar con dirección
      A una dirección cripto

[ ↙ ] Recibir con dirección
      Comparte tu dirección cripto
```

Recommended production copy:

- `Enviar a banco o billetera`
- `Recibir por cuenta local`
- Current `Enviar con dirección` remains `Enviar con dirección`
- Current `Recibir con dirección` remains `Recibir con dirección`

This order is deliberate. Local payment methods are the default consumer use case;
external crypto addresses are an advanced path. Keep crypto below a clear `Cripto`
section label rather than giving both groups equal visual priority.

Do not use `wallet` or `billetera` as shorthand for a blockchain address. Across Latin
America, `billetera` commonly means a local fintech account or app. Use `dirección` for
the advanced crypto path and make the subtitle explicit: `dirección cripto`.

On narrow devices, render all four actions as full-width rows in the exact stable order
shown above, grouped visually as `Transferencias locales` first and `Cripto` second. Do
not squeeze the verbose labels into a 2×2 grid. Existing accessibility labels should
state the complete intent.

The contact list remains below this block:

```text
Buscar contactos…

Amigos en Confío
...

Invita a tus amigos
...
```

### Entry behavior

- Home `Enviar` → Contacts and focuses/highlights `Enviar a banco o billetera` plus the
  normal Confío contact list. It does not automatically open a sheet.
- Home `Recibir` → Contacts and focuses/highlights `Recibir por cuenta local`. It does
  not automatically open a sheet.
- Bottom-tab `Transferir` → the stable local-first order above.
- Returning from a child flow preserves search text and scroll position.

Do not reorder all four rows by entry intent. Stable positions build recognition; use a
brief focus highlight and accessibility focus for the deep-linked row instead.

For business accounts, keep employee management separate from money routing. The
`Empleados` bottom tab should not acquire these four personal transfer rows. Business
local accounts are entered from Home `Enviar`/`Recibir`, `Cobrar`, or Profile
`Cuentas locales`, subject to owner/employee permissions.

## Receive flow

Entry: Contacts `Recibir por cuenta local`, Home `Recibir` → Contacts receive intent,
account detail `Recibir`, or local account card `Ver datos`.

```text
Recibir
  ├─ active account exists
  │    ├─ one account → receiving detail
  │    └─ several accounts → choose country/currency → receiving detail
  └─ no active account
       └─ eligible country offer → activation flow
```

`Recibir con dirección` preserves today's crypto-network RouteSheet. `Recibir por cuenta
local` starts the separate local-account branch below; it does not mix Bre-B/CLABE rows
into the crypto network list.

### Receiving detail

The first viewport contains the shareable value and actions; it should not begin with an
educational article.

Colombia:

```text
Tu llave Bre-B
@CONFIOABC123

[ Copiar ]   [ Compartir ]   [ Mostrar QR ]

El remitente verá: Ana Pérez
Institución de destino: <provider-returned institution>
Recibes COP en tu cuenta de Confío.
```

Mexico:

```text
Tu CLABE para recibir
646 180 123456789 0

[ Copiar ]   [ Compartir ]

Banco/institución: <provider-returned institution>
Beneficiario que verá el remitente: <provider-returned value>
Concepto: opcional
```

The copy/share payload must include the institution and beneficiary exactly as returned
by the provider. Do not call a Virtual CLABE `una cuenta bancaria a tu nombre` unless
the contractual/product response confirms that. A Cobre Virtual CLABE can be a unique
receiving reference mapped to an omnibus Cobre Balance; uniqueness does not itself imply
legal account ownership.

Below the details, show a capability strip:

- Green: `Puedes recibir de cualquier persona o empresa`
- Neutral: `Recibe solo desde cuentas a tu nombre`
- Upgrade: `Activa pagos de terceros` → enhanced-KYC flow
- Pending: `Estamos revisando pagos de terceros`

Then show limits, fees, expected timing, and `Cómo hacer la transferencia` instructions.

Do not ask `¿Quién enviará?` on every receive. Once activated, the account detail is the
fast path. Ask during activation or only when the user requests a capability upgrade.

## Send flow

Entry: Home `Enviar`, local account card `Enviar`, or account detail `Enviar`.

### Screen 1 — Contacts and destination family

Use the existing Contacts screen as the canonical recipient picker. Its local send row
appears first, while the advanced address row stays in the lower Crypto section:

```text
[ bank icon ]  Enviar a banco o billetera
               CLABE, Bre-B, Alias, QR y más

...

[ arrow icon ] Enviar con dirección
               A una dirección cripto
```

Contacts remain normal Confío recipients. Route rows are not fake contacts and do not
move with alphabetical sorting. `Escanear QR` may be exposed from the local method sheet
when an eligible rail exists; avoid a fifth pinned action when the central Scan tab is
already prominent.

The receive routes are `Recibir por cuenta local` first and `Recibir con dirección` in
the lower Crypto section. Receiving does not treat the contact list as selectable
recipients.

### Screen 2 — Country and method

Default country from the recipient/detected identifier or user's active local account.
Only ask for country if it cannot be inferred.

After `Enviar a banco o billetera`:

- Exactly one usable method: navigate directly to its entry/scanner screen.
- Two or more methods: open a bottom sheet titled `¿Cómo quieres enviar?`.
- No methods: show the eligibility/availability screen, not an empty sheet.

Example sheet:

```text
¿Cómo quieres enviar?

Recomendado para ti
🇨🇴 Llave Bre-B

Otros destinos disponibles
🇲🇽 CLABE
🇦🇷 Alias, CBU o CVU
🇵🇪 QR compatible
🇧🇴 QR compatible
```

Do not render one global list of every country for every user. The first section contains
eligible methods for the inferred/home country. `Otros destinos disponibles` contains
only contracted cross-border payout corridors the user is allowed to use.

Server-driven method examples:

- Colombia: `Llave Bre-B`, later bank account/QR if contracted
- Mexico: `CLABE`
- Argentina: `Alias o CVU/CBU`
- Peru: `Yape QR` or supported bank details
- Bolivia: provider-supported QR/bank detail type
- Brazil: `Pix`

The server supplies method schema, validation, limits, and availability. The app renders
fields; it does not hard-code a provider-country matrix.

### Country ordering source

Phone country code is a weak onboarding hint, not the authorization or permanent sorting
source. A Venezuelan number may belong to a Colombian resident; a Colombian number may
belong to someone living elsewhere.

Use this priority:

1. Destination inferred from a pasted/scanned identifier
2. User's currently selected or last-used eligible local account country
3. Verified residence country from KYC/KYB
4. Active account/corridor country
5. Phone country only before verification, as a non-authoritative suggestion
6. Remaining eligible destinations ordered by recent use, then locale name

Eligibility and blocking always come from the server's evaluated policy. Phone country
must never unlock or block a method.

### Screen 3 — Recipient resolution

Enter, paste, select a saved method, or scan. Resolve and display the beneficiary before
the user can confirm:

```text
María Rodríguez
Llave Bre-B · @MARIA123
Colombia
```

If ownership/name validation is unavailable, say so explicitly and require an additional
confirmation. Never manufacture a beneficiary name from the user's contact book.

### Screen 4 — Amount and quote

Show:

- User pays in Confío Dollar/cUSD+
- Recipient receives local currency
- Exchange rate and expiry
- Confío fee
- Provider/network cost if passed through
- Total debit
- Expected delivery time

The local virtual account and any pre-funding/internal-transfer operation are invisible
implementation steps. The user approves one end-to-end transfer.

### Screen 5 — Review and authorization

Repeat recipient name and identifier in a high-salience block. Third-party payout needs
standard KYC; if the user lacks it, gate here before creating a provider operation.

CTA: `Enviar <amount>`

### Screen 6 — Processing and receipt

Use the canonical money-flow state, not the intermediate provider operation state:

- `Preparando fondos`
- `Enviando`
- `En proceso en la red local`
- `Completado`
- `Necesita revisión`
- `Falló` with retry-safe guidance

The receipt includes the local rail, recipient, amount, rate, fees, timestamps, provider
reference, and Confío operation ID.

## Recargar and retirar

Keep the current concepts and fold local accounts in as better rails.

### Recargar

The route sheet becomes:

- `Transferir desde mi banco` — same-name local pay-in instructions
- `Comprar dólares` — existing on-ramp provider flow
- Existing legacy cUSD drain option only where needed

If third-party funding is attempted, route to `Recibir`, not `Recargar`.

### Retirar

The route sheet remains source-first (`Desde cUSD`, `Desde Confío Dollar+`) and then shows
only destinations owned by the user. Third-party destinations belong to `Enviar`.

Saved own-name payout methods can be shared between `Retirar` and `Enviar`, but the
ownership intent must remain explicit in the operation.

## Capability-driven UX contract

The backend should expose a presentation-safe product descriptor per account/corridor:

```ts
type LocalMoneyProduct = {
  country: string;
  currency: string;
  ownerType: 'individual' | 'business';
  accountStatus: string;
  ownershipStructure: 'provider_named' | 'omnibus_subledger';
  railLabel: string;
  receivingInstructionKinds: string[];
  payoutDestinationKinds: string[];
  capabilities: {
    receiveSameName: Capability;
    receiveThirdParty: Capability;
    sendSameName: Capability;
    sendThirdParty: Capability;
    sendQr: Capability;
  };
  requiredVerificationLevel: {
    accountOpening: 'none' | 'standard' | 'enhanced';
    receiveThirdParty: 'none' | 'standard' | 'enhanced';
    sendThirdParty: 'none' | 'standard' | 'enhanced';
  };
  limits: Limit[];
  fees: FeeDisclosure[];
  beneficiaryDisplayName?: string;
  institutionDisplayName?: string;
};

type Capability = {
  status: 'enabled' | 'pending' | 'disabled' | 'not_applicable';
  reasonCode?: string;
  upgradeAvailable: boolean;
};
```

The app must not infer capability from provider name, nationality, or country. It renders
the server's evaluated result and stable reason code.

## Provider-specific launch behavior

### Cobre Colombia / Bre-B

- Present as `Llave Bre-B`.
- Use the end user's returned beneficiary display name.
- One key per underlying Cobre Balance means retries and replacement need deliberate
  lifecycle handling.
- Creation is asynchronous; show `provisioning` until registered.
- Salary/client use belongs to `Recibir`, with third-party receiving disclosure.
- Do not promise a bank ownership certificate.

### Cobre Mexico / Virtual CLABE

- Present as `CLABE para recibir` or `Transferencias SPEI`.
- Treat it as a per-user receiving reference over the contracted Cobre Balance unless
  written product terms confirm a named account.
- Always show the provider-returned beneficiary and institution in share instructions.
- It is a receiving identifier, not a standalone user balance in the UI.
- Disable rather than silently replace it; a disabled Virtual CLABE cannot be reactivated.

### Future Infinia accounts

- Account creation is user-triggered and per country; do not pre-create accounts.
- Standard KYC unlocks account opening and eligible third-party payouts.
- Third-party pay-in displays `Solicitar activación` when the capability is pending and
  launches enhanced verification only when the user wants that capability.
- Use the same screens for Bre-B, CLABE, Alias/CVU, Pix, QR, and bank details.
- Capability status is immutable for an already-created Infinia account according to the
  current provider documentation. If an upgrade requires a different account, explain
  this before provisioning and never imply that a toggle can modify the existing one.

## Analytics

Minimum events:

- `local_money_entry_opened` with intent and source surface
- `local_account_offer_viewed`
- `local_account_activation_started`
- `local_account_activation_completed`
- `local_account_activation_failed` with safe reason code
- `receiving_details_viewed`
- `receiving_details_copied`
- `receiving_details_shared`
- `enhanced_kyc_offer_viewed`
- `enhanced_kyc_started`
- `local_destination_started`
- `local_destination_resolved`
- `local_transfer_quote_viewed`
- `local_transfer_submitted`
- `local_transfer_completed`
- `local_transfer_failed`

Do not send account numbers, keys, CLABEs, names, identity numbers, or signed document
URLs to analytics.

## Launch order

1. Add `Recibir` to Home and build the provider-neutral local accounts hub.
2. Launch Cobre Bre-B receiving with activation, detail, sharing, and status handling.
3. Launch Cobre Virtual CLABE using the same receiving components but its distinct
   ownership disclosure.
4. Add `Enviar a banco o billetera` and typed local payout destinations.
5. Add capability-upgrade UX for Infinia third-party pay-in and enhanced KYC.
6. Add new countries only through server-provided product descriptors.
