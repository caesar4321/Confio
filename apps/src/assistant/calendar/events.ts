import type { DeviceEvent } from './deviceCalendar';

export const WINDOW_DAYS = 14;
export const MAX_SENT = 12;

const MAX_RAW = 300;
const MAX_TITLE = 80;
const CONTROL = /\p{Cc}/gu;
// Text that renders as nothing (tag characters, joiners, fillers).
const HIDDEN = /[\p{Cf}\u00ad\u034f\u061c\u115f-\u1160\u17b4-\u17b5\u180b-\u180f\u200b-\u200f\u202a-\u202e\u2060-\u206f\u2800\u3164\ufe00-\ufe0f\ufeff\uffa0\ufff0-\ufff8\u{e0000}-\u{e0fff}]/gu;
// Not in HIDDEN: Babel drops the u flag, and then the class eats both halves of every emoji.
const LONE_SURROGATE = /^[\uD800-\uDFFF]$/;
const LINK = /\w+:\/\/\S+|\S+@\S+|(?:[\p{L}\p{N}_-]+\.)+\p{L}{2,}\S*/giu;
const LONG_TOKEN = /\S{25,}/gu;
const NUMBER = /\p{Nd}+(?:[\s.,:/()+-]*\p{Nd}+)*/gu;

// What leaves the phone, and exactly what the person sees before it does.
// The server repeats this (assistant/calendar_context.py clean_title).
export function cleanTitle(raw: string): string {
  const text = Array.from(raw || '')
    .filter((point) => !LONE_SURROGATE.test(point))
    .slice(0, MAX_RAW)
    .join('')
    .replace(CONTROL, ' ')
    .replace(HIDDEN, '')
    .replace(LINK, '[enlace]')
    .replace(LONG_TOKEN, '[código]')
    .replace(NUMBER, '#')
    .replace(/\s+/g, ' ')
    .trim();
  if (!text) {
    return 'Sin título';
  }
  // By code point, so an emoji is never cut in half.
  const points = Array.from(text);
  return points.length <= MAX_TITLE ? text : `${points.slice(0, MAX_TITLE - 1).join('').trimEnd()}…`;
}

export function upcoming(events: DeviceEvent[]): DeviceEvent[] {
  const byId = new Map(events.map((event) => [event.id, event]));
  return [...byId.values()].sort((a, b) => a.startsAt - b.startsAt);
}

/** 9:00 the day before; if that passed, an hour before a timed event; else none. */
export function reminderTime(event: DeviceEvent, now = Date.now()): number | null {
  const dayBefore = new Date(event.startsAt);
  dayBefore.setDate(dayBefore.getDate() - 1);
  dayBefore.setHours(9, 0, 0, 0);
  if (dayBefore.getTime() > now) {
    return dayBefore.getTime();
  }
  const hourBefore = event.startsAt - 60 * 60 * 1000;
  return !event.allDay && hourBefore > now ? hourBefore : null;
}
