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

/**
 * The units a first deposit of `amountCents` moves. Confío Dollar+ is a share
 * whose `valueUsd` the server rounds to the cent (half-even, so it can round
 * up): shares for exactly the minimum can be worth a fraction of a cent less
 * than the plan price, and the server refuses that (`first_fee_short`). At
 * the minimum it therefore asks for one cent more, capped at the whole
 * position ('max').
 */
export function depositUnitsForUsd(
  amountCents: bigint,
  minCents: bigint,
  asset: { key: string; units: string; valueUsd: string | null },
): string | null {
  const target = asset.key === 'cusd_plus' && amountCents === minCents ? minCents + 1n : amountCents;
  return unitsForUsd(target, asset);
}

/** Confío Dollar+ whose whole balance only rounds to the minimum: it may fall
 * a fraction of a cent short of the first period. */
export function mayFallShort(minCents: bigint, asset: { key: string; valueUsd: string | null } | null): boolean {
  const value = toCents(asset?.valueUsd);
  return !!asset && asset.key === 'cusd_plus' && value !== null && minCents > 0n && value === minCents;
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

// Payout rail names. The server's names come first (offer.payoutRailOptions,
// read on its own by useRailLabels), so a rail switched on by the server is
// named with no app release; this table is the fallback for an older server,
// and a rail neither knows is a generic bank account, never its raw key.
const RAILS: Record<string, string> = { co_breb: 'Bre-B', br_pix: 'Pix', mx_clabe: 'CLABE' };
const serverRailLabels: Record<string, string> = {};
export const GENERIC_RAIL = 'Cuenta bancaria';

/** Store the server's rail names (useRailLabels). */
export function registerRailLabels(options: { key: string; label: string }[] | null | undefined): void {
  (options ?? []).forEach((o) => {
    if (o && typeof o.key === 'string' && typeof o.label === 'string' && o.label.trim()) {
      serverRailLabels[o.key] = o.label.trim();
    }
  });
}

/** Test helper: forget the server's names. */
export function clearRailLabels(): void {
  Object.keys(serverRailLabels).forEach((k) => { delete serverRailLabels[k]; });
}

const knownRailLabel = (rail: string): string | null => serverRailLabels[rail] ?? RAILS[rail] ?? null;

export const railLabel = (rail: string | null | undefined): string =>
  (rail ? knownRailLabel(rail) ?? GENERIC_RAIL : '');

/**
 * The rails as one phrase after "una cuenta …": "Pix o CLABE". Unknown rails
 * read "bancaria" (so "una cuenta bancaria"), once.
 */
export function railsPhrase(rails: string[], word: 'o' | 'y' | ',' = 'o'): string {
  const names: string[] = [];
  rails.forEach((r) => {
    const name = knownRailLabel(r) ?? 'bancaria';
    if (!names.includes(name)) {
      names.push(name);
    }
  });
  if (word === ',') {
    return names.join(', ');
  }
  return names.length <= 1 ? names.join('') : `${names.slice(0, -1).join(', ')} ${word} ${names[names.length - 1]}`;
}

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
    return rule.payoutLabel || railLabel(rule.payoutRail) || GENERIC_RAIL;
  }
  if (rule.kind === 'card') {
    // The server puts the card's name in payeeName (decision 35).
    return rule.payeeName || 'Tu tarjeta';
  }
  if (rule.kind === 'buy') {
    return rule.assetName || rule.assetSymbol || 'Inversión';
  }
  return 'Regla automática';
}

export function ruleVerb(kind: string): string {
  return kind === 'send' ? 'Enviar' : kind === 'payout' ? 'Pagar' : kind === 'buy' ? 'Invertir' : kind === 'card' ? 'Tarjeta' : 'Regla';
}

/** "Enviar US$50.00 a Ana"; a card: "Tarjeta Confío: hasta US$100.00". */
export function ruleTitle(rule: Parameters<typeof ruleDestination>[0] & { amountUsd: string }): string {
  const to = ruleDestination(rule);
  const amount = usd(rule.amountUsd);
  if (rule.kind === 'buy') {
    return `Invertir ${amount} en ${to}`;
  }
  if (rule.kind === 'card') {
    return `${to}: hasta ${amount}`;
  }
  if (rule.kind !== 'send' && rule.kind !== 'payout') {
    return `Regla automática de ${amount}`;
  }
  return `${ruleVerb(rule.kind)} ${amount} a ${to}`;
}

/**
 * A card rule's period: "cada 28 días", "cada día". An unknown period (no
 * frequency, or one this build does not know) is never guessed as a day:
 * "por período", so a limit reads "hasta US$X por período".
 */
export function cardPeriodLabel(days: number | null | undefined): string {
  if (typeof days !== 'number' || !Number.isFinite(days) || days < 1) {
    return 'por período';
  }
  if (days === 1) {
    return 'cada día';
  }
  return `cada ${Math.round(days)} días`;
}

const CARD_PERIOD_DAYS: Record<string, number> = { daily: 1, weekly: 7, biweekly: 14, monthly: 28 };
export const cardPeriodDays = (frequency: string | null | undefined): number | null =>
  (frequency && Object.prototype.hasOwnProperty.call(CARD_PERIOD_DAYS, frequency) ? CARD_PERIOD_DAYS[frequency] : null);

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
