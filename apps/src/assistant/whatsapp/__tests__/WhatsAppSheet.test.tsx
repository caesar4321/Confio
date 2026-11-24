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
  lastSyncAt: null, ownPhoneHint: '4567', suggestedPhone: '+59171234567', consentVersion: 4, consentOutdated: false,
  notices: [], ...over,
});
const notice = { id: '7', kind: 'order', chat: 'Farmacia Central', preview: 'Su pedido está listo', summary: 'Pedido listo', time: '10:01', createdAt: '' };

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
  expect(words()).toContain('Guardamos cifradas las últimas 48 horas de cada chat');
  expect(words()).not.toContain('«Chrome»');  // the long text waits behind "Cómo funciona"
  await press('Cómo funciona');
  expect(words()).toContain('«Chrome»');
  await press('Vincular WhatsApp');
  expect(mockMutate).toHaveBeenCalledWith(expect.objectContaining({ variables: { phone: '+59171234567', consentVersion: 4, country: 'BO' } }));
});

it('pairing: the code, copied as WhatsApp takes it, and the steps', async () => {
  mockLink = link({ state: 'pairing', code: 'ABCD-EFGH' });
  const { words, press } = open();
  expect(words()).toContain('Código A B C D E F G H');  // one cell per character, read out one by one
  expect(words()).toContain('Vincular con el número de teléfono');
  await press('Copiar código');
  expect(mockSetString).toHaveBeenCalledWith('ABCDEFGH');
});

it('unlinking asks first', async () => {
  mockLink = link({ state: 'linked' });
  const alert = jest.spyOn(Alert, 'alert').mockImplementation(() => undefined);
  const { press } = open();
  await press('Desvincular WhatsApp');
  expect(alert).toHaveBeenCalled();
  expect(mockMutate).not.toHaveBeenCalledWith(expect.objectContaining({ variables: undefined, mutation: expect.anything() }));
});

it('a newer consent than this build knows: update, never the old text', () => {
  mockLink = link({ consentVersion: 5 });
  expect(open().words()).toContain('Actualiza la app');
});

it('the number is typed with its country: the account number only fills it in, a pasted +code picks the country', async () => {
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
  expect(button().props.disabled).toBe(true);  // no country picked: no number to link
  expect(JSON.stringify(tree.toJSON())).toContain('Elige el país');
  act(() => field().props.onChangeText('+58 414 765 4321'));
  expect(button().props.disabled).toBe(false);
  await act(async () => {
    await button().props.onPress();
  });
  expect(mockMutate).toHaveBeenCalledWith(expect.objectContaining({ variables: { phone: '+584147654321', consentVersion: 4, country: 'VE' } }));
});
it('linked: the screen only manages the link; messages are told in the conversation', async () => {
  mockLink = link({ state: 'linked', notices: [notice], lastSyncAt: new Date().toISOString() });
  const onClose = jest.fn();
  let tree: any;
  act(() => {
    tree = create(<WhatsAppSheet userId="1" onClose={onClose} />);
  });
  mounted.push(tree);
  const words = JSON.stringify(tree.toJSON());
  expect(words).toContain('Te aviso de lo importante en nuestra conversación.');
  expect(words).not.toContain('Farmacia Central');  // no inbox here any more
  expect(words).not.toContain('Responder');
  const go = tree.root.findAll((n: any) => typeof n.props.onPress === 'function'
    && n.findAll((c: any) => c.props.children === 'Ir a mi conversación').length > 0);
  act(() => go[go.length - 1].props.onPress());
  expect(onClose).toHaveBeenCalled();
});

