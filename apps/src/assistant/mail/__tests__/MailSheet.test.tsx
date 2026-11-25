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
jest.mock('../../../components/svg/GmailLogo', () => 'GmailLogo');
jest.mock('react-native-svg', () => {
  const View = require('react-native').View;
  return { __esModule: true, default: View, Circle: View, Defs: View, LinearGradient: View, Rect: View, Stop: View };
});

import { MAIL_CONSENT_VERSION } from '../api';
import MailSheet from '../MailSheet';

const MAIL = {
  available: true, connected: true, needsReconnect: false, canSend: true, canCalendar: true, consentOutdated: false,
  email: 'owner@gmail.example', needs: [], consentVersion: 3,
};

let tree: renderer.ReactTestRenderer;
const flush = () => new Promise<void>((resolve) => { setImmediate(() => resolve()); });
const shown = () => JSON.stringify(tree.toJSON());

async function open(mail: object | null) {
  mockQuery.mockResolvedValue({ data: { assistantMail: mail } });
  mockMutate.mockResolvedValue({ data: {} });
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
afterEach(() => act(() => tree?.unmount()));

it('asks consent version 3: mail is told and answered in the conversation', () => {
  expect(MAIL_CONSENT_VERSION).toBe(3);
});

it('before connecting: what it does, the data, the risk and one button', async () => {
  await open({ ...MAIL, connected: false, email: null });
  expect(shown()).toContain('Tu Gmail, en Confío');
  expect(shown()).toContain('Me pides escribir o responder en nuestra conversación');
  expect(shown()).toContain('aún no está verificado');
  expect(shown()).toContain('Conectar Gmail');
});

it('connected: manages the connection only, with no inbox, ask or writing here', async () => {
  await open(MAIL);
  expect(shown()).toContain('Gmail conectado');
  expect(shown()).toContain('Activo · owner@gmail.example');
  expect(shown()).toContain('Ir a mi conversación');
  expect(shown()).not.toContain('Crear borrador');
  expect(shown()).not.toContain('Pregúntale a tu correo');
  expect(mockMutate).not.toHaveBeenCalled();  // no agenda or anything read from Google on opening
});

it('an older consent shows what changed before reading again', async () => {
  await open({ ...MAIL, consentOutdated: true, needsReconnect: true });
  expect(shown()).toContain('Revisa lo que cambió');
  expect(shown()).toContain('Aceptar y reconectar');
});

it('a connection accepted under the older text is asked again, to tell mail in the conversation', async () => {
  await open({ ...MAIL, consentVersion: 2 });
  expect(shown()).toContain('Revisa lo que cambió');
});

it('missing permissions offer to reconnect', async () => {
  await open({ ...MAIL, canSend: false, canCalendar: false });
  expect(shown()).toContain('Sin permiso para enviar correos');
  expect(shown()).toContain('Reconectar para dar los permisos');
});

it('a failed read keeps the way out', async () => {
  await open(null);
  expect(shown()).toContain('Reintentar');
  expect(shown()).toContain('Desconectar Gmail y borrar');
});
