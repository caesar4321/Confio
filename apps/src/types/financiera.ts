// Financieras directory — shared types.
//
// Confío does NOT intermediate these exchanges. We only list local financieras
// (casas de cambio) with their WhatsApp, location and community ratings so users
// can convert their balance to physical USD cash with someone they can verify
// and, if they want, visit in person.
//
// For launch we support exactly one rail: USDC on the Algorand network. There is
// no USDT and no Solana yet, so the whole directory is implicitly "USDC-Algorand"
// and we show it as a single tag — never as separate token/network jargon.

export const USDC_ALGORAND_TAG = 'USDC-Algorand';

// One anonymous review left by an identity-verified user. The exchange rate is
// never registered by the financiera itself — it is derived from what real users
// report sending vs. receiving, e.g. "envié 100 USDC, recibí $98".
export interface FinancieraReview {
  id: string;
  rating: number; // 1-5 stars
  sentUsdc: number; // USDC the user sent (always USDC-Algorand for now)
  receivedUsd: number; // physical USD received
  comment?: string;
  createdAt: string; // ISO date
}

// Services a financiera can offer. Supporting USDC-Algorand is mandatory — a
// financiera cannot register without committing to it. The rest are optional and
// shown as small badges in the directory.
export interface FinancieraService {
  id: string;
  label: string; // first-person label used in the registration checklist
  badge: string; // short label shown on directory cards
  mandatory?: boolean;
}

// "Dólares en efectivo" is the baseline premise of the whole directory, so we
// don't list it as a peer service — it's reinforced directly on the rate figure
// instead. These are the genuinely optional extras a financiera can offer.
export const FINANCIERA_SERVICES: FinancieraService[] = [
  { id: 'usdc_algorand', label: 'Soporta USDC por la red Algorand', badge: USDC_ALGORAND_TAG, mandatory: true },
  { id: 'help_confio', label: 'Ayuda a los nuevos a usar Confío', badge: 'Ayuda con Confío' },
  { id: 'home_service', label: 'Atención a domicilio', badge: 'A domicilio' },
  { id: 'weekends', label: 'Abierto fines de semana', badge: 'Fines de semana' },
];

export const MANDATORY_SERVICE_ID = 'usdc_algorand';
export const OPTIONAL_SERVICES = FINANCIERA_SERVICES.filter((s) => !s.mandatory);

export const serviceBadge = (id: string): string =>
  FINANCIERA_SERVICES.find((s) => s.id === id)?.badge || id;

export interface Financiera {
  id: string;
  name: string;
  verified: boolean; // identity verified (shown to users as "Verificado")
  countryIso: string; // e.g. 'VE', 'AR'
  state: string; // estado / provincia
  city: string;
  barrio: string;
  whatsapp: string; // digits only, E.164 without '+'
  services: string[]; // service ids; always includes 'usdc_algorand'
  avgRating: number;
  reviewCount: number;
  reviews: FinancieraReview[];
}

// Average USD received per 100 USDC sent, across all reviews. This is the
// headline figure we show: "100 USDC → $98 promedio según reseñas".
export const avgReceivedPer100 = (f: Financiera): number | null => {
  if (!f.reviews.length) return null;
  const ratios = f.reviews.map((r) => r.receivedUsd / r.sentUsdc);
  const avg = ratios.reduce((a, b) => a + b, 0) / ratios.length;
  return Math.round(avg * 100 * 10) / 10; // one decimal
};
