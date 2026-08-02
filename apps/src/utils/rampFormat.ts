// Money grammar for the ramp screens.
//
// The dollar leg gets written two different ways depending on the slot it
// lands in. `US$` is a PREFIX symbol for amounts (US$20,00) — a bare `$` reads
// as the local peso in MX/AR/CL/CO, per DESIGN.md. But a rate is a ratio of
// units, and a ratio pairs codes with codes: `COP/USD`, never `COP/US$`.
// Everything here exists so a caller can pass one unit and get the right shape
// in either slot.

export const USD_UNIT = 'US$';

// Provider-side names for the same thing users know as cUSD.
const UNIT_ALIASES: Record<string, string> = {
  'USDC-a': 'cUSD',
  'USDC Algorand': 'cUSD',
};

const normalizeUnit = (unit?: string | null) => (unit ? UNIT_ALIASES[unit] || unit : '');

// Symbols lead the number; codes trail it.
const isSymbolUnit = (unit: string) => unit === USD_UNIT;

// The unit as it reads in a code slot — opposite a fiat code in a rate ratio
// (`COP/USD`) or as the left side of `1 USD = ...`.
export const rampUnitCode = (unit?: string | null) => {
  const normalized = normalizeUnit(unit);
  return isSymbolUnit(normalized) ? 'USD' : normalized;
};

export const formatRampMoney = (value?: string | number | null, unit?: string | null) => {
  const parsed = Number(value || 0);
  if (!Number.isFinite(parsed)) {
    return '--';
  }
  const normalized = normalizeUnit(unit);
  const amount = parsed.toLocaleString('es-AR', {
    minimumFractionDigits: parsed >= 100 ? 0 : 2,
    maximumFractionDigits: 2,
  });
  return isSymbolUnit(normalized) ? `${normalized}${amount}` : `${amount} ${normalized}`.trim();
};

export const formatRampRate = (value?: string | number | null, unit?: string | null) => {
  const parsed = Number(value || 0);
  if (!Number.isFinite(parsed)) {
    return '--';
  }
  const amount = parsed.toLocaleString('es-AR', {
    minimumFractionDigits: parsed >= 100 ? 2 : 4,
    maximumFractionDigits: 4,
  });
  // A rate is always read as "<amount> <fiat code>", so the unit stays a code.
  return `${amount} ${rampUnitCode(unit)}`.trim();
};
