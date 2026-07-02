// Financieras directory — shared types, matching the GraphQL API shape.
//
// Confío does NOT intermediate these exchanges. We only list financieras and
// liquidity providers with their WhatsApp, service area and community ratings
// so users can convert USDC with someone they can verify.
//
// One rail at launch: USDC on Algorand, shown as a single friendly tag.

export const USDC_ALGORAND_TAG = 'USDC-Algorand';

import { getCurrencyByCountry } from '../utils/currencies';

// Short display label for a country's local currency ('Bs.' for VE, 'S/' for
// PE, ISO code where the symbol is the ambiguous '$'). The payout flags are
// currency-neutral (cash_local / digital_local); only the label localizes.
export const localCurrencyShort = (countryIso: string): string => {
  const cur = getCurrencyByCountry(countryIso);
  if (!cur || cur.code === 'USD') return 'moneda local';
  return cur.symbol && cur.symbol !== '$' ? cur.symbol : cur.code;
};

// Anonymous review by an identity-verified user, backed by a real transaction.
// Decimal fields arrive as strings over GraphQL.
export interface FinancieraReview {
  id: string;
  rating: number;
  direction: 'sent' | 'received';
  sentToken: 'USDC' | 'CUSD'; // token of the backing transaction, both $1-pegged
  sentUsdc: string;
  receivedUsd: string;
  comment?: string;
  createdAt: string;
}

// Display label: the app brands Confío Dollar as 'cUSD'.
export const tokenLabel = (token: 'USDC' | 'CUSD'): string =>
  token === 'CUSD' ? 'cUSD' : 'USDC';

export interface Financiera {
  id: string;
  name: string;
  countryCode: string;
  state: string;
  city: string;
  neighborhood: string;
  whatsapp: string; // digits-only E.164 without '+'
  supportsUsdcAlgorand: boolean;
  hasPhysicalLocation: boolean;
  cashUsd: boolean;
  cashLocal: boolean;
  digitalLocal: boolean;
  helpsWithConfio: boolean;
  homeService: boolean;
  openWeekends: boolean;
  isVerified: boolean;
  isActive?: boolean; // only fetched on owner-facing queries
  avgRating: number | null;
  reviewCount: number;
  // Sell-side reviews behind the public rate; buy-side reviews only add stars.
  rateReviewCount: number;
  avgReceivedPer100: number | null; // derived from reviews, never set by the financiera
  reviews?: FinancieraReview[];
}

// Optional-service badges shown on cards/detail (the mandatory USDC-Algorand
// rail is rendered separately as the primary tag).
export const serviceBadges = (f: Financiera): string[] => {
  const badges: string[] = [];
  // Always state the attention mode: a plain factual chip, never an alarm.
  // Absence of a positive badge is invisible; digital-only must be explicit.
  if (f.hasPhysicalLocation) badges.push('Local físico');
  else badges.push('Atención digital');
  const local = localCurrencyShort(f.countryCode);
  if (f.cashUsd) badges.push('Efectivo USD');
  if (f.cashLocal) badges.push(`Efectivo ${local}`);
  if (f.digitalLocal) badges.push(`${local} digital`);
  if (f.helpsWithConfio) badges.push('Ayuda con Confío');
  if (f.homeService) badges.push('A domicilio');
  if (f.openWeekends) badges.push('Fines de semana');
  return badges;
};

// Registration checklist. Supporting USDC-Algorand is mandatory — a financiera
// cannot register without committing to it; the rest map to optional flags on
// the registerFinanciera mutation.
export interface FinancieraServiceOption {
  id:
    | 'usdc_algorand'
    | 'physical_location'
    | 'cash_usd'
    | 'cash_local'
    | 'digital_local'
    | 'help_confio'
    | 'home_service'
    | 'weekends';
  label: string;
  mandatory?: boolean;
  group?: 'location' | 'payout' | 'support';
}

export const FINANCIERA_SERVICES: FinancieraServiceOption[] = [
  { id: 'usdc_algorand', label: 'Soporta USDC por la red Algorand', mandatory: true, group: 'support' },
  { id: 'physical_location', label: 'Tengo un local físico', group: 'location' },
  { id: 'cash_usd', label: 'Entrego dólares en efectivo', group: 'payout' },
  { id: 'cash_local', label: 'Entrego moneda local en efectivo', group: 'payout' },
  { id: 'digital_local', label: 'Entrego moneda local digitalmente', group: 'payout' },
  { id: 'help_confio', label: 'Ayuda a los nuevos a usar Confío', group: 'support' },
  { id: 'home_service', label: 'Atención a domicilio', group: 'location' },
  { id: 'weekends', label: 'Atiende fines de semana', group: 'support' },
];

// Registration labels localize to the country being registered: 'Entrego
// efectivo en Bs.' for VE, '... en COP' for CO, generic when unknown.
export const financieraServiceLabel = (
  option: FinancieraServiceOption,
  countryIso?: string | null,
): string => {
  if (!countryIso) return option.label;
  const local = localCurrencyShort(countryIso);
  if (local === 'moneda local') return option.label;
  if (option.id === 'cash_local') return `Entrego efectivo en ${local}`;
  if (option.id === 'digital_local') return `Entrego ${local} por transferencia digital`;
  return option.label;
};

export const MANDATORY_SERVICE_ID = 'usdc_algorand';
export const PAYOUT_SERVICE_IDS = ['cash_usd', 'cash_local', 'digital_local'] as const;
