import { clearCalendarConsent } from './consent';
import { cancelAllReminders } from './reminders';

/** Revoke and sign-out: no choice and no nudge stays on the phone. */
export async function forgetCalendar(): Promise<void> {
  await clearCalendarConsent();
  await cancelAllReminders();
}
