// Display helpers for Cuenta inteligente. Money stays a decimal string from
// the server to the screen: the only arithmetic here is integer (cents or
// token base units), never floats.
import { formatUsdAmount, getSeparators, normalizeAmountInput } from '../../utils/numberLocale';
import { DEX_TRADING_UI_ENABLED } from '../../config/features';

/** Bitcoin and gold are offered only where the build AND the server say so. */
export const cryptoBuyAllowed = (
  serverEnabled: boolean | undefined,
  dexUi: boolean = DEX_TRADING_UI_ENABLED,
): boolean => dexUi && !!serverEnabled;

/** "US$1,234.56" for a server decimal string; "—" when the server has no
 *  price for it (unknown is not zero). */
export function usd(value: string | null | undefined): string {
  if (value === null || value === undefined || value === '') {
    return '—';
  }
  return formatUsdAmount(value, { decimals: 2 });
}

/** A decimal string as integer cents (rounded down), or null if not a number. */
export function toCents(value: string | null | undefined): bigint | null {
  if (value === null || value === undefined) {
    return null;
  }
  const m = /^(\d+)(?:\.(\d*))?$/.exec(String(value).trim());
  if (!m) {
    return null;
  }
  const frac = (m[2] || '').padEnd(2, '0').slice(0, 2);
  return BigInt(m[1]) * 100n + BigInt(frac || '0');
}

export function centsToDecimal(cents: bigint): string {
  const whole = cents / 100n;
  const frac = (cents % 100n).toString().padStart(2, '0');
  return `${whole}.${frac}`;
}

/**
 * How many base units of an asset are worth `amountCents`, from the asset's
 * own server-reported balance and value (no price is assumed here). Rounded
 * down; returns "max" when the amount is the whole position or more.
 */
export function unitsForUsd(
  amountCents: bigint,
  asset: { units: string; valueUsd: string | null },
): string | null {
  const valueCents = toCents(asset.valueUsd);
  if (valueCents === null || valueCents <= 0n || !/^\d+$/.test(asset.units)) {
    return null;
  }
  if (amountCents >= valueCents) {
    return 'max';
  }
  if (amountCents <= 0n) {
    return null;
  }
  return ((BigInt(asset.units) * amountCents) / valueCents).toString();
}

const parseDate = (iso: string | null | undefined): Date | null => {
  if (!iso) {
    return null;
  }
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : d;
};

/** "20 nov 2026" */
export function shortDate(iso: string | null | undefined): string {
  const d = parseDate(iso);
  return d ? d.toLocaleDateString('es', { day: 'numeric', month: 'short', year: 'numeric' }) : '';
}

/** Whole days from now until `iso` (0 when today or past). */
export function daysUntil(iso: string | null | undefined, now: number = Date.now()): number | null {
  const d = parseDate(iso);
  if (!d) {
    return null;
  }
  return Math.max(0, Math.ceil((d.getTime() - now) / 86_400_000));
}

export function daysLabel(days: number): string {
  return days === 1 ? '1 día' : `${days} días`;
}

const FREQUENCY: Record<string, { label: string; every: string }> = {
  daily: { label: 'Diario', every: 'cada día' },
  weekly: { label: 'Semanal', every: 'cada semana' },
  biweekly: { label: 'Quincenal', every: 'cada dos semanas' },
  monthly: { label: 'Mensual', every: 'cada mes' },
};
export const frequencyLabel = (key: string): string => FREQUENCY[key]?.label ?? key;
export const frequencyEvery = (key: string): string => FREQUENCY[key]?.every ?? key;

export const planLabel = (key: string): string =>
  key === 'annual' ? 'Plan anual' : key === 'monthly' ? 'Plan mensual' : 'Plan';
export const planName = (key: string): string =>
  key === 'annual' ? 'Anual' : key === 'monthly' ? 'Mensual' : key;
export const planPeriod = (key: string): string =>
  key === 'annual' ? 'por año' : key === 'monthly' ? 'por mes' : '';

const RAILS: Record<string, string> = { co_breb: 'Bre-B', br_pix: 'Pix', mx_clabe: 'CLABE' };
export const railLabel = (rail: string | null | undefined): string => (rail ? RAILS[rail] ?? rail : '');

/** The viewer holds exactly one Confío dollar; this is its name. Never "Dollar+". */
export const dollarName = (key: string | null | undefined): string =>
  key === 'cusd_plus' ? 'Confío Dollar+' : 'Confío Dollar';

/** How an asset is named on screen (the dollar by its product name). */
export function assetTitle(asset: { key: string; kind?: string; name: string; symbol: string }): string {
  if (asset.key === 'cusd_plus' || asset.key === 'cusd') {
    return dollarName(asset.key);
  }
  return asset.name || asset.symbol;
}

export const isDollarAsset = (asset: { key: string; kind?: string }): boolean =>
  asset.kind === 'dollar' || asset.key === 'cusd' || asset.key === 'cusd_plus';

/** A row with no balance at all (units "0"). Unparseable units are not zero. */
export const isZeroUnits = (units: string | null | undefined): boolean => {
  try {
    return units != null && BigInt(units) === 0n;
  } catch {
    return false;
  }
};

/**
 * Which Confío dollar is the viewer's: the server's answer when there is one,
 * else the only dollar holding a balance, else null (treat any dollar as it).
 */
export function viewerDollarKey(
  known: string | null | undefined,
  assets: ReadonlyArray<{ key: string; kind?: string; units?: string | null }>,
): string | null {
  if (known) {
    return known;
  }
  const held = assets.filter((a) => isDollarAsset(a) && !isZeroUnits(a.units ?? null));
  return held.length === 1 ? held[0].key : null;
}

/** "0x1234…abcd" */
export function shortAddress(address: string | null | undefined): string {
  if (!address || address.length < 12) {
    return address || '';
  }
  return `${address.slice(0, 6)}…${address.slice(-4)}`;
}

/** Where a rule's money goes, in one line. */
export function ruleDestination(rule: {
  kind: string; payeeName: string | null; payeeHandle: string | null;
  payoutLabel: string | null; payoutRail: string | null;
  assetName: string | null; assetSymbol: string | null;
}): string {
  if (rule.kind === 'send') {
    return rule.payeeName || (rule.payeeHandle ? `@${rule.payeeHandle.replace(/^@/, '')}` : 'Alguien de Confío');
  }
  if (rule.kind === 'payout') {
    return rule.payoutLabel || railLabel(rule.payoutRail) || 'Cuenta bancaria';
  }
  return rule.assetName || rule.assetSymbol || 'Inversión';
}

export function ruleVerb(kind: string): string {
  return kind === 'send' ? 'Enviar' : kind === 'payout' ? 'Pagar' : 'Invertir';
}

/** "Enviar US$50.00 a Ana" */
export function ruleTitle(rule: Parameters<typeof ruleDestination>[0] & { amountUsd: string }): string {
  const to = ruleDestination(rule);
  const amount = usd(rule.amountUsd);
  return rule.kind === 'buy' ? `Invertir ${amount} en ${to}` : `${ruleVerb(rule.kind)} ${amount} a ${to}`;
}

/** What the user typed in a US$ field, as integer cents (null if not an amount). */
export function typedCents(text: string): bigint | null {
  const canonical = normalizeAmountInput(text);
  if (canonical === null || canonical.startsWith('-')) {
    return null;
  }
  return toCents(canonical);
}

/** Cents as an editable amount string in the user's number format. */
export function centsToInput(cents: bigint): string {
  return centsToDecimal(cents).replace('.', getSeparators().decimal);
}
