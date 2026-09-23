import React from 'react';
import renderer, {act} from 'react-test-renderer';
import {Share, Text, TouchableOpacity} from 'react-native';
import Clipboard from '@react-native-clipboard/clipboard';

let mockAccount: any;
let mockMethodId = 'br_pix_receive';
let mockPassOk = true;
const mockRefetch = jest.fn().mockResolvedValue({});
const mockApollo = {query: jest.fn().mockResolvedValue({data: {localIncomingDeposits: []}})};
jest.mock('react-native-vector-icons/Feather', () => 'Icon');
jest.mock('react-native-qrcode-svg', () => 'QRCode');
jest.mock('@react-native-clipboard/clipboard', () => ({setString: jest.fn()}));
jest.mock('@react-navigation/native', () => ({
  useNavigation: () => ({navigate: jest.fn(), goBack: jest.fn()}),
  useRoute: () => ({params: {methodId: mockMethodId}}), useFocusEffect: () => {},
}));
jest.mock('@apollo/client', () => ({useApolloClient: () => mockApollo, useQuery: (query: string) => ({
  data: query === 'account' ? {localReceiveAccount: mockAccount} : {}, refetch: mockRefetch,
})}));
jest.mock('../LocalAccountApplicationScreen', () => 'Application');
jest.mock('../../components/breb/BrebLocationGate', () => ({useBrebLocationPass: () => mockPassOk}));
jest.mock('../../components/ramps/RampActionBar', () => ({RampActionBar: 'ActionBar'}));
jest.mock('../../components/ramps/RampHero', () => ({RampHero: 'Hero'}));
jest.mock('../../components/ramps/RampReveal', () => ({RampReveal: ({children}: any) => children}));
jest.mock('../../components/ramps/RampStepHeader', () => ({RampStepHeader: 'Step'}));
jest.mock('../../utils/rampFlow', () => ({requestRampCriticalAuth: jest.fn()}));
jest.mock('../../services/infiniaJourney', () => ({createInfiniaJourney: jest.fn()}));
jest.mock('../../services/paymentBridge', () => ({bridgeRequestId: jest.fn()}));
jest.mock('../../services/localMoney', () => ({LOCAL_RECEIVE_ACCOUNT: 'account', LOCAL_MONEY_METHODS: 'methods',
  LOCAL_MONEY_LIMITS: 'limits', LOCAL_DEPOSITS: 'deposits', currencyName: () => 'reales', heldReasonCopy: jest.fn()}));
import Screen from '../LocalReceiveScreen';

beforeEach(() => {
  jest.clearAllMocks();
  mockApollo.query.mockResolvedValue({data: {localIncomingDeposits: []}});
  mockMethodId = 'br_pix_receive';
  mockPassOk = true;
  mockAccount = {status: 'active', country: 'BR', asset: 'BRL', localAccountId: 'brl',
    instructionKind: 'qr', value: 'pix-copy-paste', holderName: 'Ana', institution: 'Bank', receiveThirdParty: 'enabled'};
});

it('shows a provider Bre-B QR alongside the llave without replacing copy-key controls', async () => {
  mockMethodId = 'co_breb_receive';
  mockAccount = {...mockAccount, country: 'CO', asset: 'COP', instructionKind: 'breb_key',
    value: '@ana', qrValue: 'provider-breb-payload'};
  let tree!: renderer.ReactTestRenderer;
  await act(async () => {tree = renderer.create(<Screen />);});
  expect(tree.root.findByType('QRCode' as any).props.value).toBe('provider-breb-payload');
  const copy = tree.root.findAllByType(TouchableOpacity)
    .find(node => node.findAllByType(Text).some(t => t.props.children === 'Copiar'))!;
  await act(async () => {copy.props.onPress();});
  expect(Clipboard.setString).toHaveBeenCalledWith('@ana');
  await act(async () => tree.unmount());
});

it('shows own-name-only guidance when third-party permission is disabled', async () => {
  mockAccount = {...mockAccount, receiveThirdParty: 'disabled', receiveSameName: 'enabled'};
  let tree!: renderer.ReactTestRenderer;
  await act(async () => {tree = renderer.create(<Screen />);});
  const text = tree.root.findAllByType(Text).map(node => node.props.children);
  expect(text).toContain('Por ahora recibe solo desde cuentas a tu nombre.');
  expect(text).not.toContain('Puedes recibir de cualquier persona o empresa.');
  await act(async () => tree.unmount());
});

it('does not invite deposits when neither receiving permission is enabled', async () => {
  mockAccount = {...mockAccount, receiveThirdParty: 'disabled', receiveSameName: 'disabled'};
  let tree!: renderer.ReactTestRenderer;
  await act(async () => {tree = renderer.create(<Screen />);});
  const text = tree.root.findAllByType(Text).map(node => node.props.children);
  expect(text).toContain('Los depósitos aún no están disponibles en esta cuenta. Contacta a soporte antes de recibir un pago.');
  expect(text).not.toContain('Puedes recibir de cualquier persona o empresa.');
  await act(async () => tree.unmount());
});

it('renders and copies the exact Pix QR payload and labels shared data correctly', async () => {
  const share = jest.spyOn(Share, 'share').mockResolvedValue({action: Share.sharedAction});
  let tree!: renderer.ReactTestRenderer;
  try {
    await act(async () => {tree = renderer.create(<Screen />);});
    expect(tree.root.findByType('QRCode' as any).props.value).toBe('pix-copy-paste');
    expect(tree.root.findByType('Hero' as any).props.title).toBe('Tu código Pix');
    const button = (label: string) => tree.root.findAllByType(TouchableOpacity)
      .find(node => node.findAllByType(Text).some(t => t.props.children === label))!;
    await act(async () => {button('Copiar').props.onPress(); await button('Compartir').props.onPress();});
    expect(Clipboard.setString).toHaveBeenCalledWith('pix-copy-paste');
    expect(share).toHaveBeenCalledWith({message: expect.stringContaining('Tu código Pix Copia e Cola: pix-copy-paste')});
  } finally {
    if (tree) await act(async () => tree.unmount());
    share.mockRestore();
  }
});

it('keeps Pix key presentation for a key response', async () => {
  mockAccount = {...mockAccount, instructionKind: 'pix_key', value: 'ana@example.com'};
  let tree!: renderer.ReactTestRenderer;
  await act(async () => {tree = renderer.create(<Screen />);});
  expect(tree.root.findAllByType('QRCode' as any)).toHaveLength(0);
  expect(tree.root.findByType('Hero' as any).props.title).toBe('Tu propia chave Pix');
  await act(async () => tree.unmount());
});

it('shows incoming receipts without steps, selection, summary or manual conversion actions', async () => {
  mockApollo.query.mockResolvedValue({data: {localIncomingDeposits: [{
    internalId: 'auto-credit', asset: 'BRL', amount: '32.51', occurredAt: '2026-09-16T04:08:43Z',
    held: false, heldReason: '', automaticStatus: 'pending',
    sender: {name: 'Ana Pérez', bankName: 'Banco', accountMasked: '•••• 7890', reference: 'REF-1'},
  }]}});
  let tree!: renderer.ReactTestRenderer;
  await act(async () => {tree = renderer.create(<Screen />);});
  const node = tree.root.findAllByType(Text).find(t => t.props.children === 'Ingreso recibido')!;
  expect(node).toBeTruthy();
  expect(tree.root.findAllByType(TouchableOpacity).some(t => t.findAllByType(Text).includes(node))).toBe(false);
  expect(tree.root.findAllByType('Step' as any)).toHaveLength(0);
  const text = JSON.stringify(tree.toJSON());
  for (const value of ['Ana Pérez', 'Banco', '•••• 7890', 'REF-1']) expect(text).toContain(value);
  for (const oldCopy of ['Resumen', 'Convertir a dólares', 'Listo para convertir', 'Escríbenos a soporte', 'confirma la conversión']) {
    expect(text).not.toContain(oldCopy);
  }
  await act(async () => tree.unmount());
});

it('withholds receiving controls for an unpaid opening', async () => {
  mockAccount = {...mockAccount, status: 'awaiting_payment', value: ''};
  let tree!: renderer.ReactTestRenderer;
  await act(async () => {tree = renderer.create(<Screen />);});
  expect(tree.root.findAllByType('QRCode' as any)).toHaveLength(0);
  expect(tree.root.findAllByType(Text).some(t => t.props.children === 'Copiar')).toBe(false);
  await act(async () => tree.unmount());
});

it('clears the previous account receipts even when loading the new account fails', async () => {
  mockApollo.query.mockResolvedValue({data: {localIncomingDeposits: [{
    internalId: 'old-credit', asset: 'BRL', amount: '32.51', occurredAt: '2026-09-16T04:08:43Z', held: false,
  }]}});
  let tree!: renderer.ReactTestRenderer;
  await act(async () => {tree = renderer.create(<Screen />);});
  expect(JSON.stringify(tree.toJSON())).toContain('Ingreso recibido');
  mockAccount = {...mockAccount, localAccountId: 'another-account'};
  mockApollo.query.mockRejectedValue(new Error('offline'));
  await act(async () => {tree.update(<Screen />);});
  expect(JSON.stringify(tree.toJSON())).not.toContain('Ingreso recibido');
  await act(async () => tree.unmount());
});

it('reloads the withheld Bre-B key when verification completes without another focus event', async () => {
  mockMethodId = 'co_breb_receive';
  mockPassOk = false;
  mockAccount = {...mockAccount, country: 'CO', asset: 'COP', value: ''};
  let tree!: renderer.ReactTestRenderer;
  try {
    await act(async () => {tree = renderer.create(<Screen />);});
    mockRefetch.mockClear();
    mockPassOk = true;
    await act(async () => {tree.update(<Screen />);});
    expect(mockRefetch).toHaveBeenCalledTimes(1);
  } finally {
    if (tree) await act(async () => tree.unmount());
  }
});
