// Plain helpers of the assistant's purchases: no Apollo, so the push service
// and the chat can use them without the GraphQL documents.

export const ACTIVE: ReadonlySet<string> = new Set(['queued', 'working', 'needs_person', 'awaiting_code']);
export const FINISHED: ReadonlySet<string> = new Set(['payment_ready', 'stopped', 'cancelled']);
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function taskIdOf(value: unknown): string | null {
  return typeof value === 'string' && UUID.test(value.trim()) ? value.trim().toLowerCase() : null;
}

/** The task a notification opens: its data as the in-app list sees it, or a
 * push's flattened `data_` keys (notifications/fcm_service.py). */
export function agentTaskNotificationRoute(raw: unknown): string | null {
  let data: unknown = raw;
  if (typeof data === 'string') {
    try {
      data = JSON.parse(data);
    } catch {
      return null;
    }
  }
  if (!data || typeof data !== 'object') {
    return null;
  }
  const d = data as Record<string, unknown>;
  const kind = d.type ?? d.data_type ?? d.extra_type;
  if (kind !== 'agent_task') {
    return null;
  }
  return taskIdOf(d.task_id ?? d.data_task_id ?? d.extra_task_id);
}

// How the server works out a top total (agent_tasks/operate.py cart_top), sent with the products to choose.
export type CapRule = { margin: string; minExtra: string; commaDecimals: boolean; maxQuantity?: number | null };
export type CartPick = { price: string; unit?: string | null; quantity: number };

const PRICE_NUMBER = /\d[\d.,]*\d|\d/;

// A plain decimal ("112.50", "0.6", "30") as an exact fraction, or null.
function fraction(text: string | null | undefined): [number, number] | null {
  const found = /^(\d{1,12})(?:\.(\d{1,6}))?$/.exec(String(text ?? '').trim());
  if (!found) {
    return null;
  }
  const decimals = found[2] ?? '';
  return [Number(found[1] + decimals), 10 ** decimals.length];
}

/** The most the chosen products may cost with shipping and taxes, written as the store writes prices (spec
 * decision 42): the sum of each unit price times its quantity, plus the larger of sum × margin and the floor,
 * rounded up to a whole unit, in the first pick's price text. Exactly the server's operate.cart_top: the
 * server approves up to it only when the two agree to the character. Null when any price was not read. */
export function cartTop(picks: CartPick[], rule: CapRule | null | undefined): string | null {
  if (!rule || !picks.length) {
    return null;
  }
  const margin = fraction(rule.margin);
  const floor = fraction(rule.minExtra);
  if (!margin || !floor) {
    return null;
  }
  const most = rule.maxQuantity || 9;
  let cents = 0;
  for (const pick of picks) {
    const unit = fraction(pick.unit);
    if (!unit || unit[1] > 100 || !Number.isInteger(pick.quantity) || pick.quantity < 1 || pick.quantity > most) {
      return null;
    }
    cents += ((unit[0] * 100) / unit[1]) * pick.quantity;
  }
  if (cents <= 0) {
    return null;
  }
  // Everything in 1 / (100 × margin's denominator × floor's denominator) of a unit: whole numbers only.
  const scale = 100 * margin[1] * floor[1];
  const sum = cents * margin[1] * floor[1];
  const extra = Math.max(cents * margin[0] * floor[1], floor[0] * 100 * margin[1]);
  const scaled = sum + extra;
  if (!Number.isSafeInteger(scaled)) {
    return null;
  }
  const whole = (scaled - (scaled % scale)) / scale + (scaled % scale ? 1 : 0);
  const [group, point] = rule.commaDecimals ? ['.', ','] : [',', '.'];
  const written = `${String(whole).replace(/\B(?=(\d{3})+(?!\d))/g, group)}${point}00`;
  const template = picks[0].price;
  const found = PRICE_NUMBER.exec(template);
  if (!found) {
    return null;
  }
  return (template.slice(0, found.index) + written + template.slice(found.index + found[0].length)).trim();
}

type Action = { type: string; target?: string | null };

/** The purchases a message's actions carry ({type: 'task', target: <id>}), once each. */
export function taskActions(actions: Action[]): string[] {
  const found: string[] = [];
  for (const a of actions) {
    const taskId = a.type === 'task' ? taskIdOf(a.target) : null;
    if (taskId && !found.includes(taskId)) {
      found.push(taskId);
    }
  }
  return found;
}

// A purchase posts several notes; its card is drawn once, under the newest of
// them, and updates in place. Each mounted note says "I carry this purchase".
const carriers = new Map<string, Map<string, number>>();
const listeners = new Set<() => void>();

/** The message that draws this purchase's card: the newest note carrying it. */
export function latestCardFor(taskId: string): string | null {
  let best: string | null = null;
  let bestAt = -Infinity;
  for (const [messageId, at] of carriers.get(taskId) ?? []) {
    if (at > bestAt || (at === bestAt && best !== null && messageId > best)) {
      best = messageId;
      bestAt = at;
    }
  }
  return best;
}

/** Register a note as carrying a purchase; returns how to take it back. */
export function showCard(taskId: string, messageId: string, at: number): () => void {
  if (!carriers.has(taskId)) {
    carriers.set(taskId, new Map());
  }
  carriers.get(taskId)!.set(messageId, at);
  listeners.forEach((tell) => tell());
  // Kept after the note scrolls out of the list: the card stays where the newest note is,
  // and never jumps to an older one (losing what was being typed in it).
  return () => undefined;
}

/** Tests only: a conversation with no purchase notes yet. */
export function forgetCards(): void {
  carriers.clear();
}

export function onCards(tell: () => void): () => void {
  listeners.add(tell);
  return () => { listeners.delete(tell); };
}
