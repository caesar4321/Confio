import React from 'react';
import { Alert } from 'react-native';
import { act, create } from 'react-test-renderer';

import WhatsAppSheet from '../WhatsAppSheet';

let mockLink: any = null;
const mockMutate = jest.fn();
const mockSetString = jest.fn();
const mockQuery = jest.fn();
const mockClient = { mutate: (...args: unknown[]) => mockMutate(...args), query: (...args: unknown[]) => mockQuery(...args) };
jest.mock('@apollo/client', () => ({ gql: () => ({}), useApolloClient: () => mockClient }));
jest.mock('@react-native-clipboard/clipboard', () => ({ setString: (value: string) => mockSetString(value) }));
jest.mock('react-native-safe-area-context', () => ({ SafeAreaProvider: 'SafeAreaProvider', SafeAreaView: 'SafeAreaView' }));
jest.mock('react-native-vector-icons/Feather', () => 'Icon');
jest.mock('../../../components/common/AppText', () => {
  const RN = require('react-native');
  return { Text: RN.Text, TextInput: RN.TextInput };
});
jest.mock('../useWhatsApp', () => ({ useWhatsApp: () => ({ link: mockLink, refetch: jest.fn(async () => ({})) }) }));

const link = (over: Record<string, unknown> = {}) => ({
  state: 'none', code: null, codeAt: null, phoneHint: '4567', reason: null, reasonMessage: null, linkedAt: null,
  lastSyncAt: null, ownPhoneHint: '4567', suggestedPhone: '+59171234567', consentVersion: 2, consentOutdated: false,
  notices: [], ...over,
});
const notice = { id: '7', kind: 'order', chat: 'Farmacia Central', preview: 'Su pedido está listo', summary: 'Pedido listo', time: '10:01', createdAt: '' };
const draft = { id: 'd1', chat: 'Farmacia Central', phone: null, body: '¿A qué hora cierran?', status: 'draft', reason: null, displayHash: 'hash-1' };

const mounted: any[] = [];
// Unmounted after each test: a sheet left open keeps polling a message on its way.
afterEach(() => {
  act(() => mounted.splice(0).forEach((tree) => tree.unmount()));
});

function open() {
  let tree: any;
  act(() => {
    tree = create(<WhatsAppSheet userId="1" onClose={jest.fn()} />);
  });
  mounted.push(tree);
  const words = () => JSON.stringify(tree.toJSON());
  const press = async (label: string) => {
    const target = tree.root.findAll((node: any) => typeof node.props.onPress === 'function'
      && node.findAll((child: any) => child.props.children === label).length > 0);
    await act(async () => {
      await target[target.length - 1].props.onPress();
    });
  };
  const type = (text: string) => act(() => {
    tree.root.findByProps({ placeholder: 'Escribe tu respuesta' }).props.onChangeText(text);
  });
  return { words, press, type };
}

beforeEach(() => {
  jest.clearAllMocks();
  mockMutate.mockResolvedValue({ data: {} });
  mockQuery.mockResolvedValue({ data: { whatsAppDraft: null } });
  require('../session').forgetWhatsAppSession('1');
});

it('consent first, then the pairing asks for the code of the accepted text', async () => {
  mockLink = link();
  mockMutate.mockResolvedValue({ data: { startWhatsAppLink: { success: true } } });
  const { words, press } = open();
  expect(words()).toContain('restringir');  // the risk is always in sight, not behind "Cómo funciona"
  // What is read, by an AI, for how long: in sight before the button, not behind a toggle.
  expect(words()).toContain('Una IA marca lo importante y lo guardamos cifrado mientras siga vinculado');
  expect(words()).not.toContain('«Chrome»');  // the long text waits behind "Cómo funciona"
  await press('Cómo funciona');
  expect(words()).toContain('«Chrome»');
  await press('Vincular WhatsApp');
  expect(mockMutate).toHaveBeenCalledWith(expect.objectContaining({ variables: { phone: '+59171234567', consentVersion: 2 } }));
});

it('pairing: the code, copied as WhatsApp takes it, and the steps', async () => {
  mockLink = link({ state: 'pairing', code: 'ABCD-EFGH' });
  const { words, press } = open();
  expect(words()).toContain('Código A B C D E F G H');  // one cell per character, read out one by one
  expect(words()).toContain('Vincular con el número de teléfono');
  await press('Copiar código');
  expect(mockSetString).toHaveBeenCalledWith('ABCDEFGH');
});

it('a reply leaves only from the card that shows its exact text, with that text\'s hash', async () => {
  mockLink = link({ state: 'linked', notices: [notice] });
  const { words, press, type } = open();
  expect(words()).toContain('Parece un pedido');
  await press('Responder');
  type('¿A qué hora cierran?');
  mockMutate.mockResolvedValueOnce({ data: { createWhatsAppDraft: { success: true, draft } } });
  await press('Revisar antes de enviar');
  expect(mockMutate).toHaveBeenLastCalledWith(expect.objectContaining({ variables: { noticeId: '7', body: '¿A qué hora cierran?' } }));
  expect(words()).toContain('Se enviará desde tu WhatsApp a Farmacia Central:');
  const sends = mockMutate.mock.calls.length;
  mockMutate.mockResolvedValueOnce({ data: { sendWhatsAppDraft: { success: true, draft: { ...draft, status: 'sending' } } } });
  await press('Enviar');
  expect(mockMutate.mock.calls.length).toBe(sends + 1);
  expect(mockMutate).toHaveBeenLastCalledWith(expect.objectContaining({ variables: { id: 'd1', displayHash: 'hash-1' } }));
  expect(words()).toContain('Enviando desde tu WhatsApp');
  expect(words()).not.toContain('"Enviar"');
});

it('unlinking asks first', async () => {
  mockLink = link({ state: 'linked' });
  const alert = jest.spyOn(Alert, 'alert').mockImplementation(() => undefined);
  const { press } = open();
  await press('Desvincular WhatsApp');
  expect(alert).toHaveBeenCalled();
  expect(mockMutate).not.toHaveBeenCalledWith(expect.objectContaining({ variables: undefined, mutation: expect.anything() }));
});

it('back from the app lock: the reply and its send are read back, so it is never sent twice', async () => {
  mockLink = link({ state: 'linked', notices: [notice] });
  const first = open();
  await first.press('Responder');
  first.type('¿A qué hora cierran?');
  mockMutate.mockResolvedValueOnce({ data: { createWhatsAppDraft: { success: true, draft } } });
  await first.press('Revisar antes de enviar');
  act(() => mounted.splice(0).forEach((tree) => tree.unmount()));  // the lock unmounts the Modal
  // As the server answers once a message went: its text is gone.
  mockQuery.mockResolvedValue({ data: { whatsAppDraft: { ...draft, chat: null, body: '', status: 'sent' } } });
  let again: ReturnType<typeof open>;
  await act(async () => {
    again = open();
  });
  expect(mockQuery).toHaveBeenCalledWith(expect.objectContaining({ variables: { id: 'd1' } }));
  expect(again!.words()).toContain('Enviado a Farmacia Central:');
  expect(again!.words()).toContain('¿A qué hora cierran?');  // what went, kept from before
  expect(again!.words()).not.toContain('"Enviar"');
  expect(again!.words()).not.toContain('Revisar antes de enviar');
});

it('a send whose answer was lost shows what the server has, not a retry', async () => {
  mockLink = link({ state: 'linked', notices: [notice] });
  const { words, press, type } = open();
  await press('Responder');
  type('¿A qué hora cierran?');
  mockMutate.mockResolvedValueOnce({ data: { createWhatsAppDraft: { success: true, draft } } });
  await press('Revisar antes de enviar');
  mockMutate.mockRejectedValueOnce(new Error('network'));
  mockQuery.mockResolvedValue({ data: { whatsAppDraft: { ...draft, status: 'sending' } } });
  await press('Enviar');
  expect(words()).toContain('Enviando desde tu WhatsApp');
});

it('a newer consent than this build knows: update, never the old text', () => {
  mockLink = link({ consentVersion: 3 });
  expect(open().words()).toContain('Actualiza la app');
});

it('a reply whose record expired after it went out is never offered again', async () => {
  mockLink = link({ state: 'linked', notices: [notice] });
  const first = open();
  await first.press('Responder');
  first.type('¿A qué hora cierran?');
  mockMutate.mockResolvedValueOnce({ data: { createWhatsAppDraft: { success: true, draft } } });
  await first.press('Revisar antes de enviar');
  mockMutate.mockResolvedValueOnce({ data: { sendWhatsAppDraft: { success: true, draft: { ...draft, status: 'sending' } } } });
  await first.press('Enviar');
  act(() => mounted.splice(0).forEach((tree) => tree.unmount()));
  mockQuery.mockResolvedValue({ data: { whatsAppDraft: null } });  // expired, or the read failed as null
  let again: ReturnType<typeof open>;
  await act(async () => {
    again = open();
  });
  // One empty answer is a hiccup: still on its way, and never a box to send it again.
  expect(again!.words()).toContain('Enviando desde tu WhatsApp a Farmacia Central:');
  expect(again!.words()).not.toContain('Revisar antes de enviar');
  for (let read = 0; read < 2; read += 1) {
    act(() => mounted.splice(0).forEach((tree) => tree.unmount()));
    await act(async () => {
      again = open();
    });
  }
  // Three in a row: gone, and no one can say whether it went.
  expect(again!.words()).toContain('No sé si salió a Farmacia Central:');
  expect(again!.words()).not.toContain('Revisar antes de enviar');
});

it('a slow answer never overwrites a newer one', async () => {
  const { mergeDraft } = require('../rules');
  expect(mergeDraft({ ...draft, status: 'sent' }, { ...draft, chat: null, body: '', status: 'sent' }).body).toBe('¿A qué hora cierran?');
  expect(mergeDraft({ ...draft }, null)).toBeNull();  // never sent: gone
});

it('a send whose answer the lock hid comes back as on its way, never as a draft to change', async () => {
  mockLink = link({ state: 'linked', notices: [notice] });
  const first = open();
  await first.press('Responder');
  first.type('¿A qué hora cierran?');
  mockMutate.mockResolvedValueOnce({ data: { createWhatsAppDraft: { success: true, draft } } });
  await first.press('Revisar antes de enviar');
  let answer: (value: unknown) => void = () => undefined;
  mockMutate.mockImplementationOnce(() => new Promise((resolve) => { answer = resolve; }));
  const tapping = first.press('Enviar');
  act(() => mounted.splice(0).forEach((tree) => tree.unmount()));  // locked before the answer
  answer({ data: { sendWhatsAppDraft: { success: true, draft: { ...draft, status: 'sending' } } } });
  await tapping;
  mockQuery.mockRejectedValue(new Error('network'));  // and the read back fails too
  let again: ReturnType<typeof open>;
  await act(async () => {
    again = open();
  });
  expect(again!.words()).toContain('Enviando desde tu WhatsApp a Farmacia Central:');
  expect(again!.words()).not.toContain('Cambiar el texto');
  expect(again!.words()).not.toContain('Revisar antes de enviar');
});

it('a read answered before the send reached the server never brings Enviar back', async () => {
  mockLink = link({ state: 'linked', notices: [notice] });
  const { words, press, type } = open();
  await press('Responder');
  type('¿A qué hora cierran?');
  mockMutate.mockResolvedValueOnce({ data: { createWhatsAppDraft: { success: true, draft } } });
  await press('Revisar antes de enviar');
  mockMutate.mockRejectedValueOnce(new Error('network'));  // the answer is lost
  mockQuery.mockResolvedValue({ data: { whatsAppDraft: draft } });  // and the read says "draft" (too early)
  await press('Enviar');
  expect(words()).toContain('Enviando desde tu WhatsApp a Farmacia Central:');
  expect(words()).not.toContain('Cambiar el texto');
});

it('a refusal is believed: the draft comes back to change or send', async () => {
  mockLink = link({ state: 'linked', notices: [notice] });
  const { words, press, type } = open();
  await press('Responder');
  type('¿A qué hora cierran?');
  mockMutate.mockResolvedValueOnce({ data: { createWhatsAppDraft: { success: true, draft } } });
  await press('Revisar antes de enviar');
  mockMutate.mockResolvedValueOnce({ data: { sendWhatsAppDraft: { success: false, error: 'Llegaste al límite', errorCode: 'rate_limited' } } });
  mockQuery.mockResolvedValue({ data: { whatsAppDraft: draft } });
  await press('Enviar');
  expect(words()).toContain('Llegaste al límite');
  expect(words()).toContain('Cambiar el texto');
});

it('closing the sheet while a message is on its way keeps it', () => {
  const { whatsAppSession, closeWhatsAppSession } = require('../session');
  whatsAppSession('1').draft = { ...draft, status: 'sending' };
  closeWhatsAppSession('1');
  expect(whatsAppSession('1').draft.status).toBe('sending');
  whatsAppSession('1').draft = { ...draft, status: 'sent' };
  closeWhatsAppSession('1');
  expect(whatsAppSession('1').draft).toBeNull();
});

it('a draft replaced by a newer version is never sent: back to the box with its text', async () => {
  mockLink = link({ state: 'linked', notices: [notice] });
  const { words, press, type } = open();
  await press('Responder');
  type('¿A qué hora cierran?');
  mockMutate.mockResolvedValueOnce({ data: { createWhatsAppDraft: { success: true, draft } } });
  await press('Revisar antes de enviar');
  mockMutate.mockResolvedValueOnce({ data: { sendWhatsAppDraft: { success: false, error: 'Ese mensaje ya no existe.', errorCode: 'not_found' } } });
  await press('Enviar');
  expect(words()).not.toContain('No sé si salió');
  expect(words()).toContain('Revisar antes de enviar');
  expect(words()).toContain('¿A qué hora cierran?');
});

it('the send request carries its own timeout', async () => {
  mockLink = link({ state: 'linked', notices: [notice] });
  const { press, type } = open();
  await press('Responder');
  type('Hola');
  mockMutate.mockResolvedValueOnce({ data: { createWhatsAppDraft: { success: true, draft } } });
  await press('Revisar antes de enviar');
  mockMutate.mockResolvedValueOnce({ data: { sendWhatsAppDraft: { success: true, draft: { ...draft, status: 'sending' } } } });
  await press('Enviar');
  const call = mockMutate.mock.calls.find((args: any[]) => args[0]?.variables?.displayHash);
  expect(call[0].context.fetchOptions.signal).toBeDefined();
});

it('unlinking forgets what was kept, a message on its way included', async () => {
  const { whatsAppSession } = require('../session');
  whatsAppSession('1').draft = { ...draft, status: 'sending' };
  mockLink = link({ state: 'linked' });
  const alert = jest.spyOn(Alert, 'alert').mockImplementation(() => undefined);
  const { press } = open();
  await press('Desvincular WhatsApp');
  mockMutate.mockResolvedValueOnce({ data: { unlinkWhatsApp: { success: true } } });
  await act(async () => {
    await (alert.mock.calls[0][2] as any)[1].onPress();
  });
  expect(whatsAppSession('1').draft).toBeNull();
});

it('the number is typed: the account number only fills it in, and no country code means no link', async () => {
  mockLink = link({ suggestedPhone: null });
  mockMutate.mockResolvedValue({ data: { startWhatsAppLink: { success: true } } });
  let tree: any;
  act(() => {
    tree = create(<WhatsAppSheet userId="1" onClose={jest.fn()} />);
  });
  mounted.push(tree);
  const field = () => tree.root.findByProps({ accessibilityLabel: 'Tu número de WhatsApp, con el código de país' });
  const button = () => tree.root.findAll((node: any) => node.props.accessibilityRole === 'button'
    && node.findAll((child: any) => child.props.children === 'Vincular WhatsApp').length > 0)[0];
  expect(button().props.disabled).toBe(true);
  act(() => field().props.onChangeText('71234567'));
  expect(field().props.value).toBe('+71234567');  // the + stays: the country code is asked for
  act(() => field().props.onChangeText('+58 414 765 4321'));
  expect(button().props.disabled).toBe(false);
  await act(async () => {
    await button().props.onPress();
  });
  expect(mockMutate).toHaveBeenCalledWith(expect.objectContaining({ variables: { phone: '+584147654321', consentVersion: 2 } }));
});
