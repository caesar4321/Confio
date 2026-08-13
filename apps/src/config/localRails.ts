// Local money rails — the networks people actually NAME in LATAM: "mándamelo
// al Bre-B", "pásame tu CLABE", "te lo mando al Yape", "cuál es tu alias".
//
// Deliberately provider-neutral. A user never picks "Cobre" or "Infinia";
// they pick the rail their money already moves on, and the backend decides
// which provider serves it. Renaming a provider must never change this file.
//
// This is a CLIENT catalog for now, on purpose. The server knows which
// destination types each provider accepts (INFINIA_DESTINATION_REQUIREMENTS,
// payment_accounts/services.py) but exposes no "corridors I could use"
// query — `myPaymentAccounts` returns only the accounts a user ALREADY has,
// which is empty for everyone until a provider flag flips. So the picker is
// driven from here, and anything not wired end to end stays a demand probe
// (same two-stage pattern as the crypto receive sheet) instead of becoming a
// dead end. Replace with a server query once corridors are queryable.

import { getCountryByIso } from '../utils/countries';

/**
 * `live` rails navigate into a real flow. `probe` rails record demand and
 * say so out loud — never a silent no-op, never a fake "próximamente" screen.
 */
export type LocalRailStatus = 'live' | 'probe';

export interface LocalRail {
  /** Stable analytics id. Never renamed — funnel history hangs off it. */
  id: string;
  /** ISO-2. Used for ordering and the flag; NEVER for authorization. */
  country: string;
  /** What the user calls the rail in that country. */
  title: string;
  subtitle: string;
  status: LocalRailStatus;
}

// Order matters only as a tie-break once the user's own country is hoisted
// to the top: biggest LATAM corridors first, so a user with no resolved
// country still sees a sensible list rather than alphabetical noise.
const SEND_RAILS: LocalRail[] = [
  {
    id: 'send_co_breb',
    country: 'CO',
    title: 'Llave Bre-B',
    subtitle: 'Nequi, Bancolombia, Daviplata y más',
    status: 'probe',
  },
  {
    id: 'send_mx_clabe',
    country: 'MX',
    title: 'CLABE',
    subtitle: 'Transferencia SPEI a cualquier banco',
    status: 'probe',
  },
  {
    id: 'send_ar_alias',
    country: 'AR',
    title: 'Alias, CBU o CVU',
    subtitle: 'Mercado Pago, Ualá, Naranja X y bancos',
    status: 'probe',
  },
  {
    id: 'send_pe_qr',
    country: 'PE',
    title: 'QR o cuenta',
    subtitle: 'Yape, Plin y bancos',
    status: 'probe',
  },
  {
    id: 'send_bo_qr',
    country: 'BO',
    title: 'QR simple o cuenta',
    subtitle: 'QR interoperable y bancos',
    status: 'probe',
  },
  {
    id: 'send_br_pix',
    country: 'BR',
    title: 'Pix',
    subtitle: 'Llave Pix o código QR',
    status: 'probe',
  },
  {
    id: 'send_cl_bank',
    country: 'CL',
    title: 'Cuenta bancaria',
    subtitle: 'Transferencia en pesos chilenos',
    status: 'probe',
  },
  {
    id: 'send_py_bank',
    country: 'PY',
    title: 'Cuenta bancaria',
    subtitle: 'Transferencia en guaraníes',
    status: 'probe',
  },
  // Uruguay and the United States: RECEIVE is documented, SEND is not.
  // Infinia's Create Payout reference (fetched 2026-08-12, page updatedAt
  // 2026-05-27) defines payout schemas for ARGENTINA, BOLIVIA, BRAZIL, CHILE,
  // COLOMBIA, EUROPE, MEXICO, PARAGUAY, PERU and GLOBAL only — no Uruguay and
  // no US, and `ACH` there is BoliviaACH, not US ACH. Julian was told
  // otherwise on an Infinia call, and this provider's docs have lagged its
  // API before, so treat it as unconfirmed rather than settled: ask Infinia
  // for a Uruguay and a US payout destination schema. Either way these stay
  // probes, and flipping one to `live` needs the destination type added
  // server-side first — `_validate_infinia_destination` rejects unknown types.
  {
    id: 'send_uy_bank',
    country: 'UY',
    title: 'Cuenta bancaria',
    subtitle: 'Transferencia en pesos uruguayos',
    status: 'probe',
  },
  {
    id: 'send_us_bank',
    country: 'US',
    title: 'Cuenta en Estados Unidos',
    subtitle: 'ACH o transferencia bancaria en dólares',
    status: 'probe',
  },
  // SEPA is the one rail that is a REGION, not a country: one IBAN format
  // covers the whole euro area, so it gets a single row instead of one per
  // country. `EU` is not an ISO-2 country code — countryFlag/countryName
  // resolve it through the pseudo-entries below.
  {
    id: 'send_eu_sepa',
    country: 'EU',
    title: 'Cuenta en euros (SEPA)',
    subtitle: 'Transferencia SEPA con IBAN',
    status: 'probe',
  },
  // The UK rides Infinia's EuropePayout schema (country EUROPE, currency GBP,
  // destination ACCOUNT_UNITED_KINGDOM_CHAPS_FPS) — a separate rail from SEPA
  // with its own sort-code format, so it gets its own row rather than hiding
  // inside "Europa".
  {
    id: 'send_gb_fps',
    country: 'GB',
    title: 'Cuenta en Reino Unido',
    subtitle: 'Transferencia FPS o CHAPS en libras',
    status: 'probe',
  },
];

// Receiving is a much shorter list than sending, and stays that way: issuing
// someone an account costs real money per account (~US$1 at Infinia), so a
// corridor only appears here once we can actually open one.
//
// COPY RULE — "tu propio/tu propia", never "a tu nombre".
// The point to land is that this is a PERSONALISED, PERMANENT identifier the
// user owns and shares, not a generic "receive money" button. But legal
// titling is a different claim, and Infinia's coverage table marks only
// Argentina B2C as a "Named account" for consumers; every other consumer row
// is a plain funding instruction, and Cobre's Mexican virtual CLABE is a
// reference onto a shared balance. Confío's own `ownership_structure` says
// the same thing — Cobre accounts are `omnibus_subledger`. So promise
// permanence and exclusivity, which is true everywhere, and never imply the
// account is titled in the user's name, which is not.
const RECEIVE_RAILS: LocalRail[] = [
  {
    id: 'receive_co_breb',
    country: 'CO',
    title: 'Llave Bre-B',
    subtitle: 'Tu propia llave, siempre la misma',
    status: 'probe',
  },
  {
    id: 'receive_mx_clabe',
    country: 'MX',
    title: 'CLABE',
    subtitle: 'Tu propia CLABE, siempre la misma',
    status: 'probe',
  },
  {
    // The only consumer corridor Infinia documents as a Named account, and
    // the only one with a user-chosen alias — so it can promise the most.
    id: 'receive_ar_cvu',
    country: 'AR',
    title: 'CVU y alias',
    subtitle: 'Tu propio CVU con alias personalizado',
    status: 'probe',
  },
  {
    id: 'receive_pe_qr',
    country: 'PE',
    title: 'Cuenta y QR',
    subtitle: 'Tu propio QR para que te paguen',
    status: 'probe',
  },
  {
    id: 'receive_bo_qr',
    country: 'BO',
    title: 'Cuenta y QR',
    subtitle: 'Tu propio QR para que te paguen',
    status: 'probe',
  },
  {
    id: 'receive_br_pix',
    country: 'BR',
    title: 'Llave Pix',
    subtitle: 'Tu propia llave Pix, siempre la misma',
    status: 'probe',
  },
  {
    id: 'receive_cl_bank',
    country: 'CL',
    title: 'Cuenta bancaria',
    subtitle: 'Tus propios datos para recibir en Chile',
    status: 'probe',
  },
  {
    id: 'receive_py_bank',
    country: 'PY',
    title: 'Cuenta bancaria',
    subtitle: 'Tus propios datos para recibir en Paraguay',
    status: 'probe',
  },
  {
    id: 'receive_uy_bank',
    country: 'UY',
    title: 'Cuenta bancaria',
    subtitle: 'Tus propios datos para recibir en Uruguay',
    status: 'probe',
  },
  // Unlike the send side, these ARE openable — Infinia's coverage table lists
  // US (ACH/FedWire, ABA routing + account number), GB (FPS/CHAPS) and LU
  // (SEPA), the last three "beta, upon request". So receiving dollars, pounds
  // or euros is a UI build plus an enablement ask, not a provider gap. Of
  // everything here, the US account — dollars from American clients, paid to
  // a number the user keeps — is the one worth building after Colombia.
  {
    id: 'receive_us_bank',
    country: 'US',
    title: 'Cuenta en Estados Unidos',
    subtitle: 'Tu propio número de cuenta y routing',
    status: 'probe',
  },
  {
    id: 'receive_eu_sepa',
    country: 'EU',
    title: 'Cuenta en euros (SEPA)',
    subtitle: 'Tu propio IBAN para recibir euros',
    status: 'probe',
  },
  {
    id: 'receive_gb_fps',
    country: 'GB',
    title: 'Cuenta en Reino Unido',
    subtitle: 'Tu propio IBAN y sort code en libras',
    status: 'probe',
  },
];

// The two halves of the app disagree on country codes and always will:
// `payment_accounts` stores ISO-3 ('COL', 'MEX' — see FinancialAccount.country
// and PROVIDER_ACCOUNT_SHAPES), while the app's country table is keyed on
// ISO-2. Comparing them raw fails silently in the worst way — no flag renders
// and a corridor the user already owns still shows up as "not available yet",
// inviting them to request what they already have. Only the corridors this
// file actually lists need to map, so the table is explicit and auditable
// rather than a general-purpose dependency.
const ISO3_TO_ISO2: Record<string, string> = {
  ARG: 'AR', BOL: 'BO', BRA: 'BR', CHL: 'CL', COL: 'CO',
  MEX: 'MX', PER: 'PE', PRY: 'PY', URY: 'UY', VEN: 'VE',
  GBR: 'GB', USA: 'US',
  // Infinia opens the euro account in Luxembourg, but nobody thinks of their
  // IBAN as "a Luxembourg account" — the product is the euro area. Presenting
  // LUX as EU keeps one row instead of a country the user did not choose.
  LUX: 'EU',
};

/** Accepts either ISO-2 or ISO-3 and always returns ISO-2 (or '' if unknown). */
export const toIso2 = (code: string | null | undefined): string => {
  const raw = String(code || '').trim().toUpperCase();
  if (raw.length === 2) return raw;
  return ISO3_TO_ISO2[raw] || '';
};

// SEPA is a currency area, not a country, so it has no ISO-2 entry in the
// app's country table. It gets a pseudo-entry rather than a special case at
// every call site — the alternative was a blank flag and the literal string
// "EU" rendering as the country name in the picker.
const PSEUDO_REGIONS: Record<string, { flag: string; name: string }> = {
  EU: { flag: '🇪🇺', name: 'Zona euro' },
};

export const countryFlag = (iso: string): string => {
  const code = toIso2(iso);
  return PSEUDO_REGIONS[code]?.flag || getCountryByIso(code)?.[3] || '';
};

export const countryName = (iso: string): string => {
  const code = toIso2(iso);
  return PSEUDO_REGIONS[code]?.name || getCountryByIso(code)?.[0] || String(iso || '');
};

/**
 * Hoist the user's own country to the top of the list.
 *
 * Ordering ONLY — this must never decide what a user is allowed to do.
 * Phone country is not residence: the seeded Cobre policy exists precisely
 * for Venezuelan nationals resident in Colombia, whose phone country is very
 * often +58. Entitlement comes from `paymentAccountEligibility`, which reads
 * verified KYC nationality and residence. Passing `null` here is fine and
 * just leaves the default order — a wrong country is worse than none, the
 * same rule `useRampCountry` locks for ramps.
 *
 * `selectedCountry` from CountryContext must NEVER be passed in: it is
 * global picker state written by Exchange, Crear oferta and Nómina, so
 * browsing offers from another country would silently reorder this list.
 */
const orderForUser = (rails: LocalRail[], userCountry: string | null): LocalRail[] => {
  const iso = toIso2(userCountry);
  if (!iso) return rails;
  const mine = rails.filter(rail => rail.country === iso);
  if (mine.length === 0) return rails;
  return [...mine, ...rails.filter(rail => rail.country !== iso)];
};

export const getSendRails = (userCountry: string | null): LocalRail[] =>
  orderForUser(SEND_RAILS, userCountry);

export const getReceiveRails = (userCountry: string | null): LocalRail[] =>
  orderForUser(RECEIVE_RAILS, userCountry);

/**
 * The one line under each menu row. Deliberately GENERIC and country-agnostic.
 *
 * An earlier version named the reader's own methods ("Nequi, Bancolombia,
 * Daviplata y más"). That solved the wrong problem: the sheet one tap away
 * already lists every rail with its own description, so the row was
 * duplicating detail the user is about to see anyway. The row's job is to say
 * what KIND of thing is behind it, once.
 *
 * Both lines carry the same kind of fact — WHOSE account is at the other end —
 * because that is the one thing the titles do not say and the sheet cannot fix:
 *
 *   Recibir → an account of YOURS       ("tu propia cuenta")
 *   Enviar  → an account of THEIRS      ("de otra persona o negocio")
 *
 * The send line is doing real work beyond symmetry: it draws the boundary
 * against `Retirar`. Enviar is a third-party payout; Retirar is the same-owner
 * cash-out to a method the user already holds. Naming the recipient in the
 * subtitle sends someone moving money to their OWN bank to the right door
 * instead of the one whose title happens to mention a bank.
 *
 * Neither line says "a tu nombre": see the copy rule on RECEIVE_RAILS for why
 * legal titling is a claim we cannot back in most corridors.
 */
/**
 * The availability line on every rail we cannot serve yet.
 *
 * Wording matters beyond tone. Apple's Guideline 2.1 rejects builds carrying
 * placeholder or other temporary content, and 2.3.1 rejects UI that implies
 * functionality the app does not provide. "Aún no disponible" reads like a
 * broken or un-enabled button — exactly the thing 2.1 is aimed at.
 * "Próximamente" reads as a deliberately published roadmap with a waitlist
 * opt-in, which is what this actually is: tapping one registers interest and
 * can never start a transfer.
 *
 * Shared by the local rails and the crypto receive rails so the two sheets
 * cannot drift apart — a reviewer seeing two different phrasings for the same
 * state is the impression to avoid. Paired with a clock icon on every probe
 * row, so the state is legible before anyone taps.
 */
export const COMING_SOON_NOTE = 'Próximamente · Toca para recibir un aviso';

export const SEND_ROW_SUBTITLE = 'A la cuenta de otra persona o negocio';
export const RECEIVE_ROW_SUBTITLE = 'Tu propia cuenta local para que te paguen';
