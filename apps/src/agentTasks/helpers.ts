// Plain helpers of the shopping task screens: no Apollo, so the push service
// and the chat's chips can use them without the GraphQL documents.

export const ACTIVE: ReadonlySet<string> = new Set(['queued', 'working', 'needs_person', 'awaiting_code']);
export const FINISHED: ReadonlySet<string> = new Set(['payment_ready', 'stopped', 'cancelled']);
// The agent comes back after these: the screen closes when it does.
export const BACK_TO_AGENT: ReadonlySet<string> = new Set(['login', 'captcha']);
// The code could not be read off the screen (or was not prepared): what else
// the person can do is in the server's message. Only a Brazilian store's Pix
// code is pasted in the chat; Bolivia pays from Pagar, Mexico from the bank.
export const PASTE_REASONS: ReadonlySet<string> = new Set(['code', 'code_refused', 'screen', 'retry', 'offsite',
  'unsigned']);

export function pastesInChat(site: string, reason: string): boolean {
  return PASTE_REASONS.has(reason) && /(^|\.)[a-z0-9-]+\.br$/i.test(site.trim());
}

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

/** What a frame inside the live view may load: https or a blank frame, never
 * another app's scheme or plain http. */
export function allowedSubframe(url: string): boolean {
  return url === 'about:blank' || url.startsWith('about:srcdoc') || /^https:\/\/[^/?#]/i.test(url);
}

/** Only the live view's own host (and blank frames) may load in the WebView. */
export function allowedInLiveView(url: string, host: string | null | undefined): boolean {
  if (!host) {
    return false;
  }
  if (url === 'about:blank' || url.startsWith('about:srcdoc')) {
    return true;
  }
  const match = /^https:\/\/([^/?#:]+)(?::443)?(?:[/?#]|$)/i.exec(url);
  return !!match && match[1].toLowerCase() === host.toLowerCase();
}

/** "12:05" left until `until`, or null once it passed. */
export function timeLeft(until: string | null | undefined, now: number): string | null {
  if (!until) {
    return null;
  }
  const end = Date.parse(until);
  if (Number.isNaN(end)) {
    return null;
  }
  const seconds = Math.floor((end - now) / 1000);
  if (seconds <= 0) {
    return null;
  }
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
}
