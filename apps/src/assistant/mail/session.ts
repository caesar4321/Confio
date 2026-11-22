// The app lock unmounts every Modal's children, and connecting always takes
// longer than the lock's 10 seconds away. What must survive that lives here, in
// memory only, per person, until they close the sheet.
import type { MailDraft, MailSource } from './api';

export type MailSession = {
  open: boolean;
  notice: string | null;
  finishing: Promise<void> | null;
  drafting: Promise<void> | null;
  to: string;
  instructions: string;
  replyTo: MailSource | null;
  draft: MailDraft | null;
};

const sessions = new Map<string, MailSession>();

export function mailSession(userId: string): MailSession {
  let session = sessions.get(userId);
  if (!session) {
    session = { open: false, notice: null, finishing: null, drafting: null, to: '', instructions: '', replyTo: null, draft: null };
    sessions.set(userId, session);
  }
  return session;
}

export const isMailSheetOpen = () => Array.from(sessions.values()).some((session) => session.open);

export function closeMailSession(userId: string) {
  sessions.delete(userId);
}
