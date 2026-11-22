jest.mock('react-native', () => ({
  NativeModules: { ConfioCalendar: { listEvents: jest.fn(async () => []), permissionStatus: jest.fn(async () => 'denied') } },
  Platform: { OS: 'ios' },
  PermissionsAndroid: {},
}));
const mockStore = new Map<string, string>();
jest.mock('react-native-keychain', () => ({
  ACCESSIBLE: { WHEN_UNLOCKED_THIS_DEVICE_ONLY: 'device' },
  getGenericPassword: jest.fn(async ({ service }: any) =>
    (mockStore.has(service) ? { password: mockStore.get(service) } : false)),
  setGenericPassword: jest.fn(async (_u: string, value: string, { service }: any) => {
    mockStore.set(service, value);
    return { service };
  }),
  resetGenericPassword: jest.fn(async ({ service }: any) => mockStore.delete(service)),
}));

import { NativeModules } from 'react-native';
import * as Keychain from 'react-native-keychain';
import { clearCalendarConsent, readCalendarConsent, saveCalendarConsent } from '../consent';
import { hasCalendarAccess, listDeviceEvents } from '../deviceCalendar';
import { cleanTitle, reminderTime, upcoming } from '../events';
import { ASSISTANT_CALENDAR_ENABLED } from '../flag';

beforeEach(() => mockStore.clear());

it('ships off', () => {
  expect(ASSISTANT_CALENDAR_ENABLED).toBe(false);
});

it('never asks the phone for events without a chosen calendar', async () => {
  expect(await listDeviceEvents([], 1, 2)).toEqual([]);
  expect(NativeModules.ConfioCalendar.listEvents).not.toHaveBeenCalled();
  expect(await hasCalendarAccess()).toBe(false);
});

it('keeps consent per user, on this device, and forgets it on revoke', async () => {
  await saveCalendarConsent('7', ['a']);
  expect(await readCalendarConsent('7')).toEqual(['a']);
  expect(await readCalendarConsent('8')).toBeNull();
  expect((Keychain.setGenericPassword as jest.Mock).mock.calls[0][2].accessible).toBe('device');
  await clearCalendarConsent();
  expect(await readCalendarConsent('7')).toBeNull();
});

it.each(['not json', '{"version":0,"calendarIds":["a"]}', '{"version":1,"calendarIds":[]}', '{"version":1}'])(
  'reads %s as not allowed',
  async (value) => {
    mockStore.set('com.confio.assistant.calendar', value);
    expect(await readCalendarConsent('7')).toBeNull();
  },
);

it('strips numbers, links, emails, long codes and control characters', () => {
  expect(cleanTitle('Pagar luz R$ 142,50 cuenta 0012-3456')).toBe('Pagar luz R$ # cuenta #');
  const hidden = String.fromCharCode(0x202e);
  const out = cleanTitle(`Ver https://evil.example/x a@b.co 00020126580014BRGOVBCBPIX0136abc${hidden}\nya`);
  ['evil', '@', 'BCBPIX', hidden, '\n'].forEach((gone) => expect(out).not.toContain(gone));
  expect(cleanTitle('tel ١٢٣٤ y ５５５')).toBe('tel # y #');
  expect(cleanTitle('Reunión con mamá')).toBe('Reunión con mamá');
  expect(cleanTitle('x '.repeat(100)).length).toBeLessThanOrEqual(80);
  expect(cleanTitle('')).toBe('Sin título');
});

it('strips text that renders as nothing', () => {
  const tags = Array.from('pay').map((c) => String.fromCodePoint(0xe0000 + c.charCodeAt(0))).join('');
  const other = [0xad, 0x2060, 0x61c, 0xfeff, 0x3164, 0xfe0f].map((c) => String.fromCodePoint(c)).join('');
  expect(cleanTitle(`Cena${tags}${other} hoy`)).toBe('Cena hoy');
});

it('hides bare domains and every script\'s digits', () => {
  expect(cleanTitle('Pagar bit.ly/pago o pagos-cfe.com/x')).toBe('Pagar [enlace] o [enlace]');
  const digits = [0x9e7, 0x968, 0x1d7cf].map((c) => String.fromCodePoint(c)).join('');
  expect(cleanTitle(`Cuota ${digits}`)).toBe('Cuota #');
});

it('keeps emoji and never cuts one in half', () => {
  const cake = String.fromCodePoint(0x1f382);
  expect(cleanTitle(`Cumple ${cake} hoy`)).toBe(`Cumple ${cake} hoy`);
  expect(cleanTitle(`${'a '.repeat(39)}${cake} y más`)).toBe(`${'a '.repeat(39)}${cake}…`);
  expect(cleanTitle(`Cita ${String.fromCharCode(0xd800)}ok`)).toBe('Cita ok');
});

it('orders and de-duplicates events', () => {
  const event = (id: string, startsAt: number) => ({ id, startsAt, title: id, allDay: false });
  expect(upcoming([event('b', 2), event('a', 1), event('b', 2)]).map((e) => e.id)).toEqual(['a', 'b']);
});

it('nudges at 9:00 the day before, else an hour before a timed event', () => {
  const start = new Date(2026, 10, 25, 18, 0).getTime();
  const event = { id: 'a', title: '', startsAt: start, allDay: false };
  expect(reminderTime(event, new Date(2026, 10, 20).getTime())).toBe(new Date(2026, 10, 24, 9).getTime());
  const sameDay = new Date(2026, 10, 25, 8).getTime();
  expect(reminderTime(event, sameDay)).toBe(start - 3600000);
  expect(reminderTime({ ...event, allDay: true }, sameDay)).toBeNull();
  expect(reminderTime(event, start - 60000)).toBeNull();
});
