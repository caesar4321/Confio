import React from 'react';
import renderer, { act } from 'react-test-renderer';

const mockQuery = jest.fn();
const mockMutate = jest.fn();
const mockClient = { query: (options: any) => mockQuery(options), mutate: (options: any) => mockMutate(options) };
jest.mock('@apollo/client', () => ({
  gql: (parts: TemplateStringsArray, ...values: string[]) => parts.reduce((all, part, i) => all + part + (values[i] ?? ''), ''),
  // One client, as in the app: a new one each render would restart every effect that depends on it.
  useApolloClient: () => mockClient,
}));
jest.mock('../../../components/common/AppText', () => ({
  Text: require('react-native').Text,
  TextInput: require('react-native').TextInput,
}));
jest.mock('react-native-safe-area-context', () => ({
  SafeAreaProvider: ({ children }: any) => children,
  SafeAreaView: require('react-native').View,
}));
jest.mock('react-native-vector-icons/Feather', () => 'Icon');
jest.mock('../connectFlow', () => ({ finishMailConnect: () => null }));
jest.mock('../connectLink', () => ({ onMailConnectResult: () => () => undefined }));
jest.mock('../verifier', () => ({ saveVerifier: jest.fn() }));

import { MAIL_CONSENT_VERSION } from '../api';
import MailSheet from '../MailSheet';

const MAIL = {
  available: true, connected: true, needsReconnect: false, canSend: true, canCalendar: true, consentOutdated: false,
  email: 'owner@gmail.example',
  needs: [{ id: '1', kind: 'reply', dueDate: null, amount: null, currency: null, summary: 'Ana pregunta por el contrato' }],
};

let tree: renderer.ReactTestRenderer;
const flush = () => new Promise<void>((resolve) => { setImmediate(() => resolve()); });
const shown = () => JSON.stringify(tree.toJSON());
const agendaCalls = () => mockMutate.mock.calls.filter(([options]) => String(options.mutation).includes('ShowAssistantMailAgenda'));

async function open(mail: object, agenda: object | Error = { success: true, events: [] }) {
  mockQuery.mockResolvedValue({ data: { assistantMail: mail } });
  mockMutate.mockImplementation(async () => {
    if (agenda instanceof Error) {
      throw agenda;
    }
    return { data: { showAssistantMailAgenda: agenda } };
  });
  await act(async () => {
    tree = renderer.create(React.createElement(MailSheet, { userId: 'u1', onClose: jest.fn() }));
    await flush();
    await flush();
  });
}

beforeEach(() => {
  mockQuery.mockReset();
  mockMutate.mockReset();
});
afterEach(() => act(() => tree.unmount()));

it('shows the new kind in our words and the summary as a claim of the mail', async () => {
  await open(MAIL);
  expect(shown()).toContain('Parece que esperan tu respuesta');
  expect(shown()).toContain('Según el correo: ');
  expect(shown()).toContain('Ana pregunta por el contrato');
});

it('shows today and tomorrow from the calendar', async () => {
  await open(MAIL, { success: true, events: [
    { title: 'Dentista', day: '2026-11-23', startsAt: '2026-11-23T21:00:00+00:00', allDay: false },
    { title: 'Feriado', day: '2026-11-24', startsAt: null, allDay: true },
  ] });
  expect(agendaCalls()).toHaveLength(1);
  expect(shown()).toContain('Dentista');
  // Day and hour of a timed event both come from its instant, on this phone's clock.
  const at = new Date('2026-11-23T21:00:00+00:00');
  expect(shown()).toContain(
    `${at.toLocaleDateString('es', { day: 'numeric', month: 'short' })} · ${at.toLocaleTimeString('es', { hour: '2-digit', minute: '2-digit' })}`);
  expect(shown()).toContain('24 nov · Todo el día');
});

it('an ended grant found by the calendar shows the reconnect button', async () => {
  await open(MAIL, { success: false, errorCode: 'reconnect', events: null });
  expect(shown()).toContain('Volver a conectar Gmail');
  expect(shown()).not.toContain('Hoy y mañana en tu calendario');
});

it('connected under the older text: the new text comes first and nothing is read', async () => {
  await open({ ...MAIL, needsReconnect: true, consentOutdated: true, needs: [] });
  expect(shown()).toContain('Esto cambió desde que conectaste tu Gmail');
  expect(shown()).toContain('Aceptar y conectar Gmail');
  expect(shown()).not.toContain('Volver a conectar Gmail');
  expect(agendaCalls()).toHaveLength(0);
});

it('a calendar that fails does not cover the mail', async () => {
  await open(MAIL, new Error('offline'));
  expect(shown()).toContain('No pude leer tu calendario ahora.');
  expect(shown()).toContain('Parece que esperan tu respuesta');
  expect(shown()).not.toContain('No pude completar eso con tu correo');
});

it('without the calendar permission it never asks Google and offers to reconnect', async () => {
  await open({ ...MAIL, canCalendar: false });
  expect(agendaCalls()).toHaveLength(0);
  expect(shown()).toContain('Reconectar para incluir tu calendario');
});

it('the consent says what is read now, and carries its own version', async () => {
  await open({ ...MAIL, connected: false, canCalendar: false, email: null, needs: [] });
  expect(MAIL_CONSENT_VERSION).toBe(2);
  expect(shown()).toContain('correos que esperan tu respuesta');
  expect(shown()).toContain('Tu calendario no se guarda ni se envía a OpenAI');
  expect(shown()).toContain('busca en todo tu Gmail');
  expect(shown()).toContain('cuántas');
  expect(shown()).toContain('un resumen de una línea');
  expect(agendaCalls()).toHaveLength(0);
});
