export type DirectMessageStatus = 'sending' | 'pending' | 'approved' | 'rejected' | 'failed' | 'unsent';

export type DirectMessage = {
  id: string;
  body: string;
  kind: 'text' | 'tip' | string;
  tipAmount?: string | null;
  fromMe: boolean;
  status: DirectMessageStatus | string;
  reason?: string | null;
  clientKey?: string | null;
  createdAt: string;
};

export type DirectParticipant = { userId: string; username: string; avatarUrl?: string | null };

export type DirectConversation = {
  id: string;
  status: 'active' | 'request' | string;
  isIncomingRequest: boolean;
  unreadCount: number;
  clearedAt?: string | null;
  sendBlock?: string | null;
  sendBlockMessage?: string | null;
  other: DirectParticipant;
  lastMessage?: DirectMessage | null;
};

/** A new idempotency key for one send (retries reuse it). */
export const newClientKey = () =>
  `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}-${Math.random().toString(36).slice(2, 10)}`;

const FINAL = new Set(['approved', 'rejected', 'failed']);

const order = (m: DirectMessage) => {
  const n = Number(m.id);
  // Local (not yet stored) messages sort after every stored one.
  return Number.isFinite(n) ? n : Number.MAX_SAFE_INTEGER;
};

/**
 * Merge a server page into what the chat shows, newest first: the server
 * copy wins by id, and replaces the local "sending" copy with the same
 * client key. Nothing is ever shown twice.
 */
export const mergeMessages = (current: DirectMessage[], incoming: DirectMessage[]): DirectMessage[] => {
  const byId = new Map<string, DirectMessage>();
  const keys = new Set(incoming.map((m) => m.clientKey).filter(Boolean) as string[]);
  for (const m of current) {
    if (m.status === 'sending' || m.status === 'unsent') {
      if (m.clientKey && keys.has(m.clientKey)) continue;
    }
    byId.set(m.id, m);
  }
  for (const m of incoming) {
    const known = byId.get(m.id);
    // A review only moves forward: a late "pending" copy (a slow send
    // response) never replaces the verdict a poll already brought.
    if (known && FINAL.has(known.status) && !FINAL.has(m.status)) continue;
    byId.set(m.id, m);
  }
  return [...byId.values()].sort((a, b) => order(b) - order(a));
};

/** "Tú: hola" / "hola" / "Revisando…" for the inbox row. */
export const previewOf = (m: DirectMessage | null | undefined): string => {
  if (!m) return '';
  if (m.kind === 'tip') return m.fromMe ? 'Enviaste una propina' : 'Te envió una propina';
  if (m.fromMe && m.status === 'pending') return 'Tú: revisando…';
  if (m.fromMe && (m.status === 'rejected' || m.status === 'failed')) return 'Tú: no enviado';
  return m.fromMe ? `Tú: ${m.body}` : m.body;
};

/** "14:05" today, "ayer", "12 oct" before. */
export const chatTime = (iso: string, now: Date = new Date()): string => {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '';
  const sameDay = date.toDateString() === now.toDateString();
  if (sameDay) return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`;
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (date.toDateString() === yesterday.toDateString()) return 'ayer';
  const months = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic'];
  return `${date.getDate()} ${months[date.getMonth()]}`;
};
