// Dependency-free, so the notification handlers can import it.
export const CALENDAR_NUDGE_PREFIX = 'assistant-calendar:';

/** A calendar nudge is not a push: its id comes from the agenda, so never log, store or route on it. */
export const isCalendarNudge = (id?: string | null) => !!id?.startsWith(CALENDAR_NUDGE_PREFIX);
