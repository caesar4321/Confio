// A top-up order in the conversation: how to pay it and how it is going.
import React from 'react';
import { Linking, Text as RNText } from 'react-native';
import renderer, { act } from 'react-test-renderer';

const mockCopy = jest.fn();
let mockServed: any;
let mockView: any;

jest.mock('react-native-vector-icons/Feather', () => 'Icon');
jest.mock('react-native-qrcode-svg', () => 'QRCode');
jest.mock('@react-native-clipboard/clipboard', () => ({ setString: (...a: unknown[]) => mockCopy(...a) }));
jest.mock('../../components/common/AppText', () => ({ Text: require('react-native').Text }));
jest.mock('../../apollo/queries', () => ({ GET_RAMP_ORDER_STATUS: 'orderStatus' }));
let mockPoll: number | undefined;
jest.mock('@apollo/client', () => ({
  useQuery: (_q: string, options: any) => {
    mockPoll = options.pollInterval;
    return { data: mockServed ? { rampOrderStatus: mockServed } : undefined };
  },
}));
jest.mock('../../utils/rampFormat', () => ({ USD_UNIT: 'USD', formatRampMoney: (value: string) => `US$${value}` }));
const mockBuild = jest.fn((_input: unknown) => mockView);
jest.mock('../../utils/rampInstructions', () => ({ buildRampInstructionView: (input: unknown) => mockBuild(input) }));

import { TopUpOrderCard, topUpOrderStatus } from '../TopUpOrderCard';

const ORDER = { orderId: 'ord-1', countryCode: 'BO', paymentMethodCode: 'QRI-BO', paymentMethodDisplay: 'QR Simple',
  amountIn: '500', amountOut: '71.20', fiatCurrency: 'BOB', paymentDetails: '{"qr":"000201","amount":"500"}' };
const texts = (tree: renderer.ReactTestRenderer) =>
  tree.root.findAllByType(RNText).map((n) => [n.props.children].flat(Infinity).join(''));
const press = async (tree: renderer.ReactTestRenderer, label: string) => {
  const node = tree.root.findAll((n) => n.props.accessibilityLabel === label && typeof n.props.onPress === 'function')[0];
  if (!node) throw new Error(`no button ${label}`);
  await act(async () => { node.props.onPress(); });
};
async function mount(onOpen = jest.fn()) {
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<TopUpOrderCard order={ORDER} onOpen={onOpen} />); });
  return tree;
}

beforeEach(() => {
  jest.clearAllMocks();
  mockServed = { success: true, status: 'WAITING', paymentDetails: '{"reference":"A1"}', nextActionUrl: null };
  mockView = { variant: 'qr', title: 'Paga con QR', subtitle: 'Escanéalo desde tu banco', qrValue: '000201', rows: [
    { label: 'Referencia', value: 'A1' }] };
  jest.spyOn(Linking, 'openURL').mockResolvedValue(true as any);
});

it('says how it is going in plain words, and when the instructions to pay still apply', () => {
  expect(topUpOrderStatus('')).toEqual({ label: 'Esperando tu pago', tone: 'wait', pay: true });
  expect(topUpOrderStatus('WAITING').pay).toBe(true);
  // Paid and on its way: nothing more to pay.
  expect(topUpOrderStatus('PAYMENT_RECEIVED')).toEqual({ label: 'Procesando tu recarga', tone: 'wait', pay: false });
  for (const code of ['DELIVERED', 'CRYPTO_DELIVERED', 'FIAT_DELIVERED']) {
    expect(topUpOrderStatus(code)).toEqual({ label: 'Recarga completada', tone: 'good', pay: false });
  }
  // Never paid, cancelled or returned: said as it is, with nothing to pay into.
  for (const code of ['REJECTED', 'FAILED', 'CANCELLED', 'REFUNDED', 'REFUND_IN_PROGRESS', 'INVALID_WITHDRAWALS_DETAILS']) {
    expect(topUpOrderStatus(code)).toEqual({ label: 'Esta recarga no se completó', tone: 'bad', pay: false });
  }
});

it('shows the QR and the details to copy, built from what the order said and what the server says now', async () => {
  const onOpen = jest.fn();
  const tree = await mount(onOpen);
  expect(mockBuild).toHaveBeenLastCalledWith(expect.objectContaining({
    direction: 'ON_RAMP', paymentMethodCode: 'QRI-BO',
    paymentDetails: { qr: '000201', amount: '500', reference: 'A1' },
  }));
  // What they pay and get is on the card itself (the form that showed it is gone).
  expect(texts(tree)).toEqual(expect.arrayContaining(
    ['Esperando tu pago', 'Pagas 500 BOB · Recibes aprox. US$71.20', 'Paga con QR', 'Referencia', 'A1']));
  expect(texts(tree).join(' ')).toContain('a tu mismo nombre');
  expect(tree.root.findAllByType('QRCode' as any)).toHaveLength(1);
  expect(mockPoll).toBe(10000);
  await press(tree, 'Referencia: A1. Toca para copiar');
  expect(mockCopy).toHaveBeenCalledWith('A1');
  await press(tree, 'Ver en pantalla completa');
  expect(onOpen).toHaveBeenCalledTimes(1);
  await act(async () => tree.unmount());
});

it('a bank page is one button; a payload too long for a QR is left to the full screen', async () => {
  mockView = { variant: 'redirect', title: 'Paga en tu banco', subtitle: '', actionUrl: 'https://banco.example/pagar',
    allowExternalAction: true, actionLabel: 'Ir a PSE', qrValue: 'x'.repeat(3000), rows: [] };
  let tree = await mount();
  expect(tree.root.findAllByType('QRCode' as any)).toHaveLength(0);
  await press(tree, 'Ir a PSE');
  expect(Linking.openURL).toHaveBeenCalledWith('https://banco.example/pagar');
  await act(async () => tree.unmount());
  // As the full screen: a link the method does not mean to be opened is not a button.
  mockView = { ...mockView, allowExternalAction: false };
  tree = await mount();
  expect(tree.root.findAll((n) => n.props.accessibilityLabel === 'Ir a PSE')).toHaveLength(0);
  await act(async () => tree.unmount());
});

it('once it is paid or refused, the instructions go and the outcome stays', async () => {
  mockServed = { success: true, status: 'DELIVERED' };
  let tree = await mount();
  expect(texts(tree)).toEqual(['Recarga completada', 'Pagas 500 BOB · Recibes aprox. US$71.20', 'Ver la recarga']);
  // An order that ended is not asked about again.
  await act(async () => { tree.update(<TopUpOrderCard order={ORDER} onOpen={jest.fn()} />); });
  expect(mockPoll).toBe(0);
  await act(async () => tree.unmount());
  mockServed = { success: true, status: 'CANCELLED' };
  tree = await mount();
  expect(texts(tree)).toContain('Esta recarga no se completó');
  expect(tree.root.findAllByType('QRCode' as any)).toHaveLength(0);
  await act(async () => tree.unmount());
});

it('a status read that fails changes nothing: a paid order never goes back to "waiting for your payment"', async () => {
  mockServed = { success: true, status: 'PAYMENT_RECEIVED' };
  const tree = await mount();
  expect(texts(tree)).toContain('Procesando tu recarga');
  expect(tree.root.findAllByType('QRCode' as any)).toHaveLength(0);
  // The provider hiccups on the next read.
  mockServed = { success: false, error: 'timeout' };
  await act(async () => { tree.update(<TopUpOrderCard order={ORDER} onOpen={jest.fn()} />); });
  expect(texts(tree)).toContain('Procesando tu recarga');
  expect(texts(tree)).not.toContain('Esperando tu pago');
  expect(tree.root.findAllByType('QRCode' as any)).toHaveLength(0);
  await act(async () => tree.unmount());
});
