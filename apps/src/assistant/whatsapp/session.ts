// The app lock unmounts every Modal's children, and linking always takes longer than its 10 seconds
// away (the code is typed in WhatsApp). What must survive that lives here, in memory only, per person,
// until they close the sheet. The last known draft is kept whole: the server forgets a message's text once it
// has gone, and coming back must show what went and where, never an empty box to send it again.
import type { WhatsAppDraft } from './api';

export type WhatsAppSession = {
  open: boolean;
  replyingId: string | null;
  body: string;
  draft: WhatsAppDraft | null;
  /** The tap on Enviar. While its request is unsettled, and for SENT_GRACE_MS after it settled without an
   * answer, no read may call it a draft again (a read answered before the send reached the server would). */
  tapped: { id: string; at: number; settled: boolean } | null;
  /** Reads of the draft, counted here so a sheet remounted after the lock drops answers asked before. */
  reads: number;
  /** Empty answers in a row while it is on its way: one server hiccup is not "no sé si salió". */
  missing: number;
};

export const SENT_GRACE_MS = 90_000;  // after the send request settled (or timed out, SEND_TIMEOUT_MS)
export const SEND_TIMEOUT_MS = 30_000;  // the send request is given up on the phone after this

const sessions = new Map<string, WhatsAppSession>();

export function whatsAppSession(userId: string): WhatsAppSession {
  let session = sessions.get(userId);
  if (!session) {
    session = { open: false, replyingId: null, body: '', draft: null, tapped: null, missing: 0, reads: 0 };
    sessions.set(userId, session);
  }
  return session;
}

/** Closing the sheet forgets it all, except a message still on its way: reopening shows it, not a box to send it again. */
export function closeWhatsAppSession(userId: string) {
  const session = sessions.get(userId);
  if (session?.draft?.status === 'sending') {
    session.open = false;
    return;
  }
  sessions.delete(userId);
}

/** Everything about messages, one on its way included (unlinking). Whether the sheet is open stays:
 * linking again right after must survive the lock like the first time. */
export function forgetWhatsAppSession(userId: string) {
  const open = sessions.get(userId)?.open ?? false;
  sessions.delete(userId);
  whatsAppSession(userId).open = open;
}
