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
