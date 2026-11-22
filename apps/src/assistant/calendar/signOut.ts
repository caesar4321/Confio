import { ASSISTANT_CALENDAR_ENABLED } from './flag';

/** Every path that ends a session calls this. Never throws. */
export async function forgetCalendarOnSignOut(): Promise<void> {
  if (!ASSISTANT_CALENDAR_ENABLED) {
    return;
  }
  try {
    const { forgetCalendar } = await import('./forgetCalendar');
    await forgetCalendar();
  } catch {
    console.error('Error clearing the assistant calendar');
  }
}
