/**
 * "¿Qué te frena para recargar?" — one tap after a verified person closes the
 * guide's "Ya puedes recargar" step, before they ever saw a price (leaving a
 * price is asked by services/topUpExit). The guide rests that step for days,
 * so this can't nag. The keys are the server's (assistant/guide.py
 * TOP_UP_DECLINE_REASONS).
 */

export const GUIDE_TOP_UP_STEP = 'top_up';

export const TOP_UP_DECLINE_REASONS = [
  ['no_money', 'No tengo el dinero ahora'],
  ['trust', 'Todavía no confío en la app'],
  ['no_use', 'No sé para qué me sirve'],
  ['fees', 'Me preocupan las comisiones'],
  ['pay_method', 'Mi banco o billetera no aparece'],
  ['looking', 'Solo estoy mirando'],
  ['loan', 'Buscaba un préstamo'],
  ['other', 'Otra cosa'],
] as const;

/** Asked, and closed without answering. */
export const TOP_UP_DECLINE_SKIPPED = 'skipped';

export type TopUpDeclineReason = (typeof TOP_UP_DECLINE_REASONS)[number];

/** Every answer in a fresh random order, so no answer wins by its place; 'other' stays last. */
export function shuffledDeclineReasons(random: () => number = Math.random): TopUpDeclineReason[] {
  const rest = TOP_UP_DECLINE_REASONS.filter(([id]) => id !== 'other');
  const other = TOP_UP_DECLINE_REASONS.filter(([id]) => id === 'other');
  for (let i = rest.length - 1; i > 0; i -= 1) {
    const j = Math.floor(random() * (i + 1));
    [rest[i], rest[j]] = [rest[j], rest[i]];
  }
  return [...rest, ...other];
}

let listener: (() => void) | null = null;

/** The host registers itself; returns the unsubscribe. */
export function subscribeTopUpDecline(next: () => void): () => void {
  listener = next;
  return () => {
    if (listener === next) listener = null;
  };
}

/** Ask, if a host is mounted. True when the sheet was shown. */
export function requestTopUpDecline(): boolean {
  if (!listener) return false;
  listener();
  return true;
}

export function resetTopUpDeclineForTests(): void {
  listener = null;
}
