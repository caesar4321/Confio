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
  listDeviceCalendars: jest.fn(),
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
  (device.listDeviceCalendars as jest.Mock).mockResolvedValue([{ id: 'c', title: 'Personal', account: 'iCloud' }]);
  (device.listDeviceEvents as jest.Mock).mockResolvedValue([
    { id: 'e1', title: 'Pagar luz 142', startsAt: soon, allDay: false },
    { id: 'e2', title: 'Médico', startsAt: soon + 1, allDay: false },
  ]);
});
afterEach(() => act(() => tree.unmount()));

it('reads nothing and sends nothing before consent', async () => {
  await open(null);
  expect(text()).toContain('Permitir acceso al calendario');
  expect(text()).toContain('Paso 1 de 2');
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
  // The answer is at the top, the ticks clear, and the footer goes back to the conversation.
  expect(text()).toContain('Confío IA revisó 1 y encontró 1 por atender');
  expect(text()).toContain('Parece un pago: Pagar luz #');
  expect(text()).toContain('Ir a mi conversación');
});

it('says so, by the button, when nothing was found or it failed', async () => {
  mockAnalyze.mockResolvedValueOnce({ data: { analyzeAssistantCalendar: { success: true, kinds: ['none'] } } });
  await open(['c']);
  await press('Médico');
  await press('Enviar y revisar (1/12)');
  expect(text()).toContain('Confío IA revisó 1: nada por atender');
  mockAnalyze.mockResolvedValueOnce({ data: { analyzeAssistantCalendar: { success: false, error: 'Llegaste al límite de hoy.' } } });
  await press('Médico');
  await press('Enviar y revisar (1/12)');
  expect(text()).toContain('Llegaste al límite de hoy.');
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
  await press('Permitir acceso al calendario');
  let finish!: () => void;
  (consent.saveCalendarConsent as jest.Mock).mockReturnValueOnce(new Promise<void>((done) => { finish = done; }));
  await press('Listo');
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
  await press('Permitir acceso al calendario');
  await press('Listo');
  expect(text()).toContain('Guardé tu elección');
});

const checkbox = (label: string) => tree.root.findAll((node) => node.props.accessibilityRole === 'checkbox'
  && node.props.accessibilityLabel === label && typeof node.props.onPress === 'function').pop()!;
const SAMSUNG = [
  { id: 'local', title: 'calendar_displayname_local', account: 'account_name_local' },
  { id: 'bday', title: 'calendar_displayname_birthday', account: 'account_name_local' },
  { id: 'work', title: 'Trabajo', account: 'ana@example.com' },
  { id: 'odd', title: 'some_raw_key', account: 'ana@example.com', color: '#FF0000' },
];

it('starts a first choice with every calendar, and select-all clears and fills them', async () => {
  (device.listDeviceCalendars as jest.Mock).mockResolvedValue(SAMSUNG);
  await open(null);
  await press('Permitir acceso al calendario');
  expect(text()).toContain('Paso 2 de 2');
  expect(text()).toContain('4 de 4 elegidos');
  expect(checkbox('Todos los calendarios').props.accessibilityState).toEqual({ checked: true });
  await press('Todos los calendarios');
  expect(text()).toContain('0 de 4 elegidos');
  expect(checkbox('Trabajo').props.accessibilityState).toEqual({ checked: false });
  await press('Trabajo');
  expect(text()).toContain('1 de 4 elegidos');
  expect(checkbox('Todos los calendarios').props.accessibilityState).toEqual({ checked: 'mixed' });
  await press('Todos los calendarios');
  expect(text()).toContain('4 de 4 elegidos');
  await press('Listo');
  expect(consent.saveCalendarConsent).toHaveBeenCalledWith('7', ['local', 'bday', 'work', 'odd']);
});

it('cleans raw Android names and groups calendars by account', async () => {
  (device.listDeviceCalendars as jest.Mock).mockResolvedValue(SAMSUNG);
  await open(null);
  await press('Permitir acceso al calendario');
  const shown = text();
  expect(shown).not.toMatch(/calendar_displayname|account_name_local|some_raw_key/);
  expect(shown.indexOf('En este teléfono')).toBeLessThan(shown.indexOf('Calendario del teléfono'));
  expect(shown.indexOf('Calendario del teléfono')).toBeLessThan(shown.indexOf('Cumpleaños'));
  expect(shown.indexOf('Cumpleaños')).toBeLessThan(shown.indexOf('ana@example.com'));
  expect(shown.indexOf('ana@example.com')).toBeLessThan(shown.indexOf('Trabajo'));
  expect(checkbox('Calendario')).toBeTruthy();
});

it('keeps an earlier choice when changing calendars', async () => {
  (device.listDeviceCalendars as jest.Mock).mockResolvedValue(SAMSUNG);
  await open(['work']);
  expect(text()).toContain('Activo · 1 calendario');
  await press('Cambiar calendarios');
  expect(text()).toContain('1 de 4 elegidos');
});

it('cannot save an empty choice', async () => {
  await open(null);
  await press('Permitir acceso al calendario');
  await press('Todos los calendarios');
  const listo = tree.root.findAll((node) => node.props.accessibilityRole === 'button'
    && node.findAll((child) => child.props.children === 'Listo').length > 0).pop()!;
  expect(listo.props.accessibilityState.disabled).toBe(true);
});

it('shows the events by day and closes to the conversation when nothing is ticked', async () => {
  await open(['c']);
  expect(text()).toContain('Calendario conectado');
  expect(text()).toContain('Ir a mi conversación');
  expect(text()).not.toContain('Al tocar el botón');
  await press('Médico');
  expect(text()).toContain('Al tocar el botón, aceptas enviar a Confío y a OpenAI (Estados Unidos)');
  expect(text()).not.toContain('Ir a mi conversación');
});
