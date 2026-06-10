// Financieras directory — shared types, matching the GraphQL API shape.
//
// Confío does NOT intermediate these exchanges. We only list local financieras
// (casas de cambio) with their WhatsApp, location and community ratings so users
// can convert USDC to physical USD cash with someone they can verify and,
// if they want, visit in person.
//
// One rail at launch: USDC on Algorand, shown as a single friendly tag.

export const USDC_ALGORAND_TAG = 'USDC-Algorand';

// Anonymous review by an identity-verified user, backed by a real transaction.
// Decimal fields arrive as strings over GraphQL.
export interface FinancieraReview {
  id: string;
  rating: number;
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
  helpsWithConfio: boolean;
  homeService: boolean;
  openWeekends: boolean;
  isVerified: boolean;
  isActive?: boolean; // only fetched on owner-facing queries
  avgRating: number | null;
  reviewCount: number;
  avgReceivedPer100: number | null; // derived from reviews, never set by the financiera
  reviews?: FinancieraReview[];
}

// Optional-service badges shown on cards/detail (the mandatory USDC-Algorand
// rail is rendered separately as the primary tag).
export const serviceBadges = (f: Financiera): string[] => {
  const badges: string[] = [];
  if (f.helpsWithConfio) badges.push('Ayuda con Confío');
  if (f.homeService) badges.push('A domicilio');
  if (f.openWeekends) badges.push('Fines de semana');
  return badges;
};

// Registration checklist. Supporting USDC-Algorand is mandatory — a financiera
// cannot register without committing to it; the rest map to optional flags on
// the registerFinanciera mutation.
export interface FinancieraServiceOption {
  id: 'usdc_algorand' | 'help_confio' | 'home_service' | 'weekends';
  label: string;
  mandatory?: boolean;
}

export const FINANCIERA_SERVICES: FinancieraServiceOption[] = [
  { id: 'usdc_algorand', label: 'Soporta USDC por la red Algorand', mandatory: true },
  { id: 'help_confio', label: 'Ayuda a los nuevos a usar Confío' },
  { id: 'home_service', label: 'Atención a domicilio' },
  { id: 'weekends', label: 'Abierto fines de semana' },
];

export const MANDATORY_SERVICE_ID = 'usdc_algorand';
