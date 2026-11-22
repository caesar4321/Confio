import React from 'react';
import renderer, { act } from 'react-test-renderer';

const mockAnalyze = jest.fn();
jest.mock('@apollo/client', () => ({ gql: () => ({}), useMutation: () => [mockAnalyze] }));
jest.mock('react-native-safe-area-context', () => ({
  SafeAreaProvider: ({ children }: any) => children,
  SafeAreaView: ({ children }: any) => children,
}));
jest.mock('react-native-vector-icons/Feather', () => () => null);
jest.mock('../../../components/common/AppText', () => ({ Text: require('react-native').Text }));
jest.mock('../consent', () => ({
  CALENDAR_CONSENT_VERSION: 1,
  readCalendarConsent: jest.fn(),
  saveCalendarConsent: jest.fn(async () => undefined),
  clearCalendarConsent: jest.fn(async () => undefined),
}));
jest.mock('../deviceCalendar', () => ({
  hasCalendarAccess: jest.fn(async () => true),
  requestCalendarAccess: jest.fn(async () => true),
  listDeviceCalendars: jest.fn(async () => [{ id: 'c', title: 'Personal', account: 'iCloud' }]),
  listDeviceEvents: jest.fn(),
}));
jest.mock('../reminders', () => ({
  cancelAllReminders: jest.fn(async () => undefined),
  cancelReminder: jest.fn(async () => undefined),
  pruneReminders: jest.fn(async () => []),
  scheduleReminder: jest.fn(async () => true),
}));

jest.mock('../forgetCalendar', () => ({
  forgetCalendar: jest.fn(async () => {
    await require('../consent').clearCalendarConsent();
    await require('../reminders').cancelAllReminders();
  }),
}));

import * as consent from '../consent';
import * as device from '../deviceCalendar';
import * as reminders from '../reminders';
import CalendarConnectSheet from '../CalendarConnectSheet';

const soon = Date.now() + 5 * 86400000;
let tree: renderer.ReactTestRenderer;
const text = () => tree.root
  .findAll((node) => [node.props.children].flat().some((child) => typeof child === 'string'))
  .map((node) => [node.props.children].flat().filter((child) => typeof child === 'string').join(''))
  .join('|');
const flush = () => new Promise<void>((resolve) => { setImmediate(() => resolve()); });

async function open(saved: string[] | null) {
  (consent.readCalendarConsent as jest.Mock).mockResolvedValue(saved);
  await act(async () => {
    tree = renderer.create(React.createElement(CalendarConnectSheet, { userId: '7', onClose: jest.fn() }));
    await flush();
  });
}

async function press(label: string) {
  const target = tree.root.findAll((node) => {
    if (typeof node.props.onPress !== 'function') {
      return false;
    }
    return node.findAll((child) => [child.props.children].flat().join('') === label).length > 0
      || node.props.accessibilityLabel === label;
  }).pop()!;
  await act(async () => {
    target.props.onPress();
    await flush();
  });
}

beforeEach(() => {
  jest.clearAllMocks();
  (device.hasCalendarAccess as jest.Mock).mockResolvedValue(true);
  (device.listDeviceEvents as jest.Mock).mockResolvedValue([
    { id: 'e1', title: 'Pagar luz 142', startsAt: soon, allDay: false },
    { id: 'e2', title: 'Médico', startsAt: soon + 1, allDay: false },
  ]);
});
afterEach(() => act(() => tree.unmount()));

it('reads nothing and sends nothing before consent', async () => {
  await open(null);
  expect(text()).toContain('Elegir calendarios');
  expect(device.listDeviceEvents).not.toHaveBeenCalled();
  expect(mockAnalyze).not.toHaveBeenCalled();
});

it('sends only the ticked titles, cleaned, after the tap', async () => {
  mockAnalyze.mockResolvedValue({ data: { analyzeAssistantCalendar: { success: true, kinds: ['payment'] } } });
  await open(['c']);
  expect(mockAnalyze).not.toHaveBeenCalled();
  await press('Pagar luz #');
  await press('Enviar y revisar (1/12)');
  expect(mockAnalyze).toHaveBeenCalledWith({ variables: { titles: ['Pagar luz #'], consentVersion: 1 } });
  expect(text()).toContain('Parece un pago');
});

it('disconnect clears the choice and the nudges', async () => {
  await open(['c']);
  await press('Desconectar y borrar');
  expect(consent.clearCalendarConsent).toHaveBeenCalled();
  expect(reminders.cancelAllReminders).toHaveBeenCalled();
  expect(text()).not.toContain('Médico');
});

it('treats a permission removed in settings as a revoke', async () => {
  (device.hasCalendarAccess as jest.Mock).mockResolvedValue(false);
  await open(['c']);
  expect(consent.clearCalendarConsent).toHaveBeenCalled();
  expect(device.listDeviceEvents).not.toHaveBeenCalled();
});

it('can still disconnect when the calendar cannot be read', async () => {
  (device.listDeviceEvents as jest.Mock).mockRejectedValue(new Error('read'));
  await open(['c']);
  await press('Desconectar y borrar');
  expect(consent.clearCalendarConsent).toHaveBeenCalled();
});

it('keeps revoke on screen when startup fails', async () => {
  (consent.readCalendarConsent as jest.Mock).mockRejectedValue(new Error('keystore'));
  await act(async () => {
    tree = renderer.create(React.createElement(CalendarConnectSheet, { userId: '7', onClose: jest.fn() }));
    await flush();
  });
  await press('Desconectar y borrar');
  expect(consent.clearCalendarConsent).toHaveBeenCalled();
});

it('does not read the calendar when closed while saving', async () => {
  await open(null);
  await press('Elegir calendarios');
  await press('Personal');
  let finish!: () => void;
  (consent.saveCalendarConsent as jest.Mock).mockReturnValueOnce(new Promise<void>((done) => { finish = done; }));
  await press('Guardar');
  act(() => tree.unmount());
  await act(async () => {
    finish();
    await flush();
  });
  expect(device.listDeviceEvents).not.toHaveBeenCalled();
});

it('says what failed when the choice saved but reading did not', async () => {
  (device.listDeviceEvents as jest.Mock).mockRejectedValue(new Error('read'));
  await open(null);
  await press('Elegir calendarios');
  await press('Personal');
  await press('Guardar');
  expect(text()).toContain('Guardé tu elección');
});
