// How calendars and events read on screen: names the phone left untranslated, accounts, and days.
import type { DeviceCalendar, DeviceEvent } from './deviceCalendar';

// Samsung (and other Android builds) hand back their resource keys instead of the translated names.
const CALENDAR_KEYS: Record<string, string> = {
  calendar_displayname_local: 'Calendario del teléfono',
  calendar_displayname_birthday: 'Cumpleaños',
};
const ACCOUNT_KEYS: Record<string, string> = {
  account_name_local: 'En este teléfono',
};
const RAW_KEY = /^[a-z]+(_[a-z]+)+$/;

export function calendarName(raw: string): string {
  const name = (raw || '').trim();
  if (CALENDAR_KEYS[name]) {
    return CALENDAR_KEYS[name];
  }
  return !name || RAW_KEY.test(name) ? 'Calendario' : name;
}

export function accountName(raw: string): string {
  const name = (raw || '').trim();
  if (ACCOUNT_KEYS[name]) {
    return ACCOUNT_KEYS[name];
  }
  // An email is the account, shown as is.
  return !name || RAW_KEY.test(name) ? 'Otros calendarios' : name;
}

/** A dot color only when the phone gave a real one. */
export function calendarColor(calendar?: DeviceCalendar): string | null {
  const color = calendar?.color;
  return typeof color === 'string' && /^#(?:[0-9a-f]{3}|[0-9a-f]{6}|[0-9a-f]{8})$/i.test(color) ? color : null;
}

export type AccountGroup = { account: string; calendars: DeviceCalendar[] };

/** Calendars by account, in the order the phone lists them. */
export function groupByAccount(calendars: DeviceCalendar[]): AccountGroup[] {
  const groups = new Map<string, DeviceCalendar[]>();
  calendars.forEach((calendar) => {
    const account = accountName(calendar.account);
    groups.set(account, [...(groups.get(account) ?? []), calendar]);
  });
  return [...groups.entries()].map(([account, list]) => ({ account, calendars: list }));
}

const WEEKDAYS = ['dom', 'lun', 'mar', 'mié', 'jue', 'vie', 'sáb'];
const MONTHS = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic'];
const pad = (value: number) => String(value).padStart(2, '0');
const dayKey = (date: Date) => `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`;

/** "Hoy", "Mañana", then "lun 2 dic". */
export function dayLabel(at: number, now = Date.now()): string {
  const date = new Date(at);
  const today = new Date(now);
  const tomorrow = new Date(now);
  tomorrow.setDate(tomorrow.getDate() + 1);
  if (dayKey(date) === dayKey(today)) {
    return 'Hoy';
  }
  if (dayKey(date) === dayKey(tomorrow)) {
    return 'Mañana';
  }
  return `${WEEKDAYS[date.getDay()]} ${date.getDate()} ${MONTHS[date.getMonth()]}`;
}

export function timeLabel(event: DeviceEvent): string {
  if (event.allDay) {
    return 'Todo el día';
  }
  const date = new Date(event.startsAt);
  return `${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

export type DayGroup = { key: string; label: string; events: DeviceEvent[] };

/** Events (already sorted) by local day. */
export function groupByDay(events: DeviceEvent[], now = Date.now()): DayGroup[] {
  const groups: DayGroup[] = [];
  events.forEach((event) => {
    const key = dayKey(new Date(event.startsAt));
    const last = groups[groups.length - 1];
    if (last?.key === key) {
      last.events.push(event);
    } else {
      groups.push({ key, label: dayLabel(event.startsAt, now), events: [event] });
    }
  });
  return groups;
}
