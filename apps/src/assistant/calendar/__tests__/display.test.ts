import { accountName, calendarColor, calendarName, dayLabel, groupByAccount, groupByDay, timeLabel } from '../display';

it('cleans raw Android names', () => {
  expect(calendarName('calendar_displayname_local')).toBe('Calendario del teléfono');
  expect(calendarName('calendar_displayname_birthday')).toBe('Cumpleaños');
  expect(calendarName('calendar_displayname_holidays')).toBe('Calendario');
  expect(calendarName('')).toBe('Calendario');
  expect(calendarName('Trabajo')).toBe('Trabajo');
  expect(calendarName('mi_calendario Casa')).toBe('mi_calendario Casa');
  expect(accountName('account_name_local')).toBe('En este teléfono');
  expect(accountName('ana@example.com')).toBe('ana@example.com');
  expect(accountName('iCloud')).toBe('iCloud');
});

it('groups calendars by account in phone order', () => {
  const groups = groupByAccount([
    { id: 'a', title: 'A', account: 'x@example.com' },
    { id: 'b', title: 'B', account: 'account_name_local' },
    { id: 'c', title: 'C', account: 'x@example.com' },
  ]);
  expect(groups.map((group) => [group.account, group.calendars.map((c) => c.id)])).toEqual([
    ['x@example.com', ['a', 'c']],
    ['En este teléfono', ['b']],
  ]);
});

it('only trusts real colors', () => {
  expect(calendarColor({ id: 'a', title: 'A', account: '', color: '#1a2B3c' })).toBe('#1a2B3c');
  expect(calendarColor({ id: 'a', title: 'A', account: '', color: 'url(x)' })).toBeNull();
  expect(calendarColor({ id: 'a', title: 'A', account: '' })).toBeNull();
  expect(calendarColor(undefined)).toBeNull();
});

it('labels days and times', () => {
  const now = new Date(2026, 10, 29, 10, 0).getTime();
  expect(dayLabel(new Date(2026, 10, 29, 23, 0).getTime(), now)).toBe('Hoy');
  expect(dayLabel(new Date(2026, 10, 30, 8, 0).getTime(), now)).toBe('Mañana');
  expect(dayLabel(new Date(2026, 11, 2, 8, 0).getTime(), now)).toBe('mié 2 dic');
  expect(timeLabel({ id: 'e', title: '', startsAt: new Date(2026, 11, 2, 8, 5).getTime(), allDay: false })).toBe('08:05');
  expect(timeLabel({ id: 'e', title: '', startsAt: now, allDay: true })).toBe('Todo el día');
});

it('groups sorted events by day', () => {
  const now = new Date(2026, 10, 29, 10, 0).getTime();
  const at = (day: number, hour: number) => new Date(2026, 10, day, hour).getTime();
  const groups = groupByDay([
    { id: '1', title: '', startsAt: at(29, 11), allDay: false },
    { id: '2', title: '', startsAt: at(29, 18), allDay: false },
    { id: '3', title: '', startsAt: at(30, 0), allDay: true },
  ], now);
  expect(groups.map((group) => [group.label, group.events.map((event) => event.id)])).toEqual([
    ['Hoy', ['1', '2']],
    ['Mañana', ['3']],
  ]);
});
