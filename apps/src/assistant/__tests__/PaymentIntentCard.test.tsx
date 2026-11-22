// The payment card in the conversation and the sheet where it is approved.
import React from 'react';
import { Text as RNText } from 'react-native';
import renderer, { act } from 'react-test-renderer';

const mockNavigate = jest.fn();
const mockRefetch = jest.fn(async () => ({}));
const mockApprove = jest.fn();
const mockRequote = jest.fn(async () => ({}));
const mockCancel = jest.fn(async () => null);
const mockTrack = jest.fn();
let mockIntent: any = null;
let mockLoading = false;
let mockPoll: number | undefined;

jest.mock('react-native-vector-icons/Feather', () => 'Icon');
jest.mock('react-native-safe-area-context', () => ({ useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }) }));
jest.mock('../../components/common/AppText', () => ({ Text: require('react-native').Text }));
jest.mock('../../navigation/RootNavigation', () => ({ navigationRef: { navigate: (...a: unknown[]) => mockNavigate(...a) } }));
jest.mock('../../utils/numberLocale', () => ({
  formatDecimal: (value: string, options: { decimals: number }) => Number(value).toFixed(options.decimals),
}));
jest.mock('@apollo/client', () => ({
  gql: jest.requireActual('graphql-tag').gql,
  useQuery: (_q: unknown, options: { pollInterval?: number }) => {
    mockPoll = options.pollInterval;
    return { data: mockIntent ? { assistantPaymentIntent: mockIntent } : undefined, loading: mockLoading, refetch: mockRefetch };
  },
}));
jest.mock('../../services/paymentIntent', () => {
  const actual = jest.requireActual('../../services/paymentIntent');
  return {
    GET_MESSAGE_PAYMENT_INTENT: 'intentByMessage',
    PaymentIntentError: actual.PaymentIntentError,
    intentState: actual.intentState,
    payeeLevelLine: actual.payeeLevelLine,
    timeLeft: actual.timeLeft,
    approvePaymentIntent: (...a: unknown[]) => mockApprove(...a),
    requotePaymentIntent: (...a: unknown[]) => mockRequote(...(a as [])),
    cancelPaymentIntent: (...a: unknown[]) => mockCancel(...(a as [])),
    trackPaymentIntent: (...a: unknown[]) => mockTrack(...a),
  };
});
jest.mock('../../services/paymentBridge', () => ({
  FIELDS: jest.requireActual('graphql-tag').gql`fragment PaymentBridgeFields on PaymentBridgeTransferType { internalId }`,
}));
jest.mock('../../apollo/client', () => ({ apolloClient: {} }));

import { PaymentIntentCard } from '../PaymentIntentCard';
import { PaymentIntentError } from '../../services/paymentIntent';

const intent = (over: object = {}) => ({
  id: 'intent-1', status: 'quoted', statusReason: '', methodId: 'br_qr', family: 'local_charge', destinationId: 'dest-1',
  payeeName: 'Padaria Pão Quente', payeeLevel: 'institution_charge', payeeAccount: '', payeeDocument: '', institution: 'Itaú',
  amountExact: true, amountLocal: '42.50', currency: 'BRL', totalUsd: '8.12', feeUsd: '0.10', rate: '5.30',
  expiresAt: new Date(Date.now() + 240_000).toISOString(), displayHash: 'hash-1', ...over,
});
const texts = (tree: renderer.ReactTestRenderer) =>
  tree.root.findAllByType(RNText).map((n) => [n.props.children].flat(Infinity).join(''));
const labels = (tree: renderer.ReactTestRenderer) => tree.root
  .findAll((n) => typeof n.props.accessibilityLabel === 'string' && typeof n.props.onPress === 'function')
  .map((n) => n.props.accessibilityLabel as string);
const press = async (tree: renderer.ReactTestRenderer, label: string | RegExp) => {
  const node = tree.root.findAll((n) => typeof n.props.onPress === 'function' && typeof n.props.accessibilityLabel === 'string'
    && (typeof label === 'string' ? n.props.accessibilityLabel === label : label.test(n.props.accessibilityLabel)))[0];
  if (!node) throw new Error(`no button ${label}; have ${labels(tree).join(' | ')}`);
  await act(async () => { await node.props.onPress(); });
};
async function mount() {
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<PaymentIntentCard messageId="77" />); });
  return tree;
}

beforeEach(() => {
  jest.clearAllMocks();
  jest.useFakeTimers();
  mockIntent = intent();
  mockLoading = false;
});
afterEach(() => {
  jest.clearAllTimers();
  jest.useRealTimers();
});

it('says who is paid, how far that is vouched for, what they get and what it costs', async () => {
  const tree = await mount();
  expect(texts(tree)).toEqual(expect.arrayContaining([
    'Pago preparado', 'Padaria Pão Quente', 'Cobro emitido por Itaú. El nombre no está verificado', 'Recibe', '42.50 BRL', 'Tú pagas', 'US$8.12', 'Revisar y pagar',
  ]));
  expect(texts(tree).some((t) => /^Vale \d:\d\d$/.test(t))).toBe(true);
  expect(mockTrack).toHaveBeenCalledWith('intent-1', 'card_shown');
  // At rest it asks the server for nothing more.
  expect(mockPoll).toBe(0);
  await act(async () => tree.unmount());
});

it('nothing to draw it from: no card made of anything else', async () => {
  mockIntent = null;
  const tree = await mount();
  expect(texts(tree)).toEqual([]);
  await act(async () => tree.unmount());
});

// The sheet slides away before anything else may open (iOS: one modal at a time).
const afterSheetCloses = async () => { await act(async () => { jest.advanceTimersByTime(450); }); };
const sheetIsUp = (tree: renderer.ReactTestRenderer) => texts(tree).includes('Revisa antes de pagar');

it('the sheet repeats everything; approving closes it first, then the card checks, asks the face and signs', async () => {
  let finish!: (value: object) => void;
  mockApprove.mockImplementation((_intent: unknown, onStage: (s: string) => void) => {
    onStage('face');
    return new Promise((resolve) => { finish = resolve; });
  });
  const tree = await mount();
  await press(tree, 'Revisar y pagar US$8.12 a Padaria Pão Quente');
  expect(mockTrack).toHaveBeenCalledWith('intent-1', 'sheet_opened');
  expect(texts(tree)).toEqual(expect.arrayContaining([
    'Revisa antes de pagar', 'Le pagas a', 'Recibe exactamente', 'Comisión incluida', 'US$0.10', 'Sale de tu cuenta personal',
    'Aprobar y pagar US$8.12', 'Ahora no',
  ]));
  // Opening the sheet approves nothing.
  expect(mockApprove).not.toHaveBeenCalled();
  await press(tree, 'Aprobar y pagar US$8.12');
  // The sheet is gone BEFORE the approval starts: Confío Face could not open over it.
  expect(sheetIsUp(tree)).toBe(false);
  expect(mockApprove).not.toHaveBeenCalled();
  expect(texts(tree)).toContain('Revisando que nada cambió…');
  await afterSheetCloses();
  expect(mockApprove).toHaveBeenCalledTimes(1);
  expect(mockApprove.mock.calls[0][0]).toMatchObject({ id: 'intent-1', displayHash: 'hash-1' });
  // The card says where it is, and offers nothing to tap meanwhile.
  expect(texts(tree)).toContain('Confirma con tu rostro');
  expect(labels(tree).some((l) => l.startsWith('Revisar y pagar'))).toBe(false);
  await act(async () => { finish({ journeyId: 'journey-1' }); });
  expect(mockRefetch).toHaveBeenCalled();
  expect(mockPoll).toBe(5000);
  await act(async () => tree.unmount());
});

it('two taps start one approval', async () => {
  mockApprove.mockReturnValue(new Promise(() => {}));
  const tree = await mount();
  await press(tree, 'Revisar y pagar US$8.12 a Padaria Pão Quente');
  const approve = tree.root.findAll((n) => n.props.accessibilityLabel === 'Aprobar y pagar US$8.12'
    && typeof n.props.onPress === 'function')[0];
  await act(async () => { approve.props.onPress(); approve.props.onPress(); });
  await afterSheetCloses();
  expect(mockApprove).toHaveBeenCalledTimes(1);
  await act(async () => tree.unmount());
});

it('"Ahora no" closes it and pays nothing; a refusal is said on the card, which can be tried again', async () => {
  const tree = await mount();
  await press(tree, 'Revisar y pagar US$8.12 a Padaria Pão Quente');
  await press(tree, 'Ahora no');
  expect(mockApprove).not.toHaveBeenCalled();
  expect(sheetIsUp(tree)).toBe(false);

  await press(tree, 'Revisar y pagar US$8.12 a Padaria Pão Quente');
  mockApprove.mockRejectedValueOnce(new PaymentIntentError('Necesitas confirmar con tu rostro para pagar.', 'face'));
  await press(tree, 'Aprobar y pagar US$8.12');
  await afterSheetCloses();
  expect(texts(tree)).toContain('Necesitas confirmar con tu rostro para pagar.');
  // Nothing is stuck: the card is a card again.
  expect(labels(tree)).toContain('Revisar y pagar US$8.12 a Padaria Pão Quente');
  await act(async () => tree.unmount());
});

it('an unknown outcome says to check the status, never to pay again, and the card keeps watching', async () => {
  const tree = await mount();
  await press(tree, 'Revisar y pagar US$8.12 a Padaria Pão Quente');
  mockApprove.mockRejectedValueOnce(new PaymentIntentError('No pudimos confirmar si tu pago salió. Revisa su estado antes de pagar otra vez.', 'unsettled', null, true));
  await press(tree, 'Aprobar y pagar US$8.12');
  await afterSheetCloses();
  expect(texts(tree)).toContain('No pudimos confirmar si tu pago salió. Revisa su estado antes de pagar otra vez.');
  expect(mockPoll).toBe(5000);
  // It stops asking after a while even if nothing changes.
  await act(async () => { jest.advanceTimersByTime(3 * 60 * 1000 + 100); });
  expect(mockPoll).toBe(0);
  await act(async () => tree.unmount());
});

it('confirmed and not signed is not a dead end: sign now, or drop it', async () => {
  mockIntent = intent({ status: 'awaiting_signature' });
  mockApprove.mockResolvedValue({ journeyId: 'journey-1' });
  const tree = await mount();
  expect(texts(tree)).toContain('Falta tu firma: todavía no se pagó nada');
  await press(tree, 'Firmar ahora el pago de US$8.12 a Padaria Pão Quente');
  await afterSheetCloses();
  expect(mockApprove).toHaveBeenCalledTimes(1);
  await press(tree, 'No pagar esto');
  expect(mockCancel).toHaveBeenCalledWith('intent-1');
  await act(async () => tree.unmount());
});

it('the rail wants the person verified first: said, with the way there', async () => {
  const tree = await mount();
  await press(tree, 'Revisar y pagar US$8.12 a Padaria Pão Quente');
  mockApprove.mockRejectedValueOnce(new PaymentIntentError('Primero verifica tu identidad para hacer este pago.', 'verification'));
  await press(tree, 'Aprobar y pagar US$8.12');
  await afterSheetCloses();
  await press(tree, 'Verificar mi identidad');
  await act(async () => { jest.advanceTimersByTime(10); });
  expect(mockNavigate).toHaveBeenLastCalledWith('Main', { screen: 'Verification', params: undefined });
  await act(async () => tree.unmount());
});

it('inside the floating box (a modal) nothing is approved: it takes the person to Inicio', async () => {
  const leave = jest.fn();
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<PaymentIntentCard messageId="77" onLeaveBox={leave} />); });
  await press(tree, 'Revisar y pagar US$8.12 a Padaria Pão Quente');
  expect(leave).toHaveBeenCalledTimes(1);
  expect(sheetIsUp(tree)).toBe(false);
  await act(async () => { jest.advanceTimersByTime(300); });
  expect(mockNavigate).toHaveBeenLastCalledWith('Main', { screen: 'BottomTabs', params: { screen: 'Home' } });
  expect(mockApprove).not.toHaveBeenCalled();
  await act(async () => tree.unmount());
});

it('a rail that finishes on its own screen is not approved here', async () => {
  mockIntent = intent({ family: 'ramp_order', methodId: 'bo_qr' });
  const tree = await mount();
  expect(labels(tree).some((l) => l.startsWith('Revisar y pagar'))).toBe(false);
  expect(texts(tree)).toContain('Este pago se revisa y se termina en Pagar.');
  await press(tree, 'Abrir Pagar');
  await act(async () => { jest.advanceTimersByTime(10); });
  expect(mockNavigate).toHaveBeenLastCalledWith('Main', { screen: 'Scan', params: { mode: 'pagar' } });
  // Pago Móvil is funded from the sheet, so it is approved here.
  mockIntent = intent({ family: 'ramp_order', methodId: 've_pagomovil_send' });
  const pagoMovil = await mount();
  expect(labels(pagoMovil).some((l) => l.startsWith('Revisar y pagar'))).toBe(true);
  await act(async () => { tree.unmount(); pagoMovil.unmount(); });
});

it('a quote that ran out offers new figures, not a payment', async () => {
  mockIntent = intent({ expiresAt: new Date(Date.now() - 1000).toISOString() });
  const tree = await mount();
  expect(labels(tree)).not.toContain('Revisar y pagar US$8.12 a Padaria Pão Quente');
  await press(tree, 'La cotización venció. Cotizar de nuevo');
  expect(mockRequote).toHaveBeenCalledWith('intent-1');
  expect(mockRefetch).toHaveBeenCalled();
  await act(async () => tree.unmount());
});

it('follows the payment: paying, then paid with its receipt; never "paid" before the server says so', async () => {
  mockIntent = intent({ status: 'paying', journeyId: 'journey-1' });
  let tree = await mount();
  expect(texts(tree)).toContain('Pagando…');
  expect(texts(tree)).not.toContain('Pagado');
  expect(mockPoll).toBe(5000);
  await press(tree, 'Ver el estado del pago');
  await act(async () => { jest.advanceTimersByTime(10); });
  expect(mockNavigate).toHaveBeenLastCalledWith('Main', { screen: 'LocalTransferStatus', params: { journeyId: 'journey-1' } });
  await act(async () => tree.unmount());

  mockIntent = intent({ status: 'paid', journeyId: 'journey-1' });
  tree = await mount();
  expect(texts(tree)).toEqual(expect.arrayContaining(['Pagado', 'Ver comprobante']));
  expect(labels(tree).some((l) => l.startsWith('Revisar y pagar'))).toBe(false);
  await act(async () => tree.unmount());

  // A send has no screen that shows this very payment: its status is said, with no link to somewhere else.
  mockIntent = intent({ status: 'paid', family: 'confio_send', orderId: 'send-9', journeyId: null });
  tree = await mount();
  expect(texts(tree)).toContain('Pagado');
  expect(labels(tree)).not.toContain('Ver el estado del pago');
  await act(async () => tree.unmount());
});

it('every cent is shown: an exact amount never loses its last digit', async () => {
  mockIntent = intent({ amountLocal: '150.5', totalUsd: '100' });
  const tree = await mount();
  expect(texts(tree)).toEqual(expect.arrayContaining(['150.50 BRL', 'US$100.00']));
  await act(async () => tree.unmount());
});

it('a name nobody vouches for is shown as a warning', async () => {
  mockIntent = intent({ payeeLevel: 'self_reported', institution: '' });
  const tree = await mount();
  expect(texts(tree)).toContain('Sin verificar: el nombre lo escribió quien cobra');
  await act(async () => tree.unmount());
});

it.each(['institution_charge', 'institution_amount', 'saved_payee'])('%s never gets a tick beside the name', async (payeeLevel) => {
  mockIntent = intent({ payeeLevel });
  const tree = await mount();
  expect(tree.root.findAll((n) => n.props.name === 'alert-triangle').length).toBeGreaterThan(0);
  expect(tree.root.findAll((n) => n.props.name === 'check-circle')).toHaveLength(0);
  await act(async () => tree.unmount());
});

it('"No pagar" cancels it on the server', async () => {
  const tree = await mount();
  await press(tree, 'No pagar esto');
  expect(mockCancel).toHaveBeenCalledWith('intent-1');
  await act(async () => tree.unmount());
});
