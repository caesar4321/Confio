/* eslint-disable @typescript-eslint/no-require-imports */
import React from 'react';
import { Text as RNText } from 'react-native';
import renderer, { act } from 'react-test-renderer';

const mockQuery = jest.fn();
const mockMutate = jest.fn();
const mockStart = jest.fn();
let mockOnExecuted: (() => void) | undefined;
let mockDex = true;

jest.mock('react-native-vector-icons/Feather', () => 'Icon');
jest.mock('../../components/common/AppText', () => ({
  Text: require('react-native').Text, TextInput: require('react-native').TextInput,
}));
jest.mock('../../components/common/Button', () => ({
  Button: ({ title, onPress, disabled }: any) => {
    const { Pressable, Text } = require('react-native');
    return <Pressable testID={`btn-${title}`} onPress={onPress} disabled={disabled}><Text>{title}</Text></Pressable>;
  },
}));
jest.mock('../../config/features', () => ({ get DEX_TRADING_UI_ENABLED() { return mockDex; } }));
jest.mock('../../components/smartAccount/SignFlowSheet', () => ({ SignFlowSheet: () => null }));
jest.mock('../../components/smartAccount/useSignFlow', () => ({
  useSignFlow: (options: any = {}) => {
    mockOnExecuted = options.onExecuted;
    return { state: { phase: 'idle' }, start: (...a: unknown[]) => mockStart(...a) };
  },
}));
jest.mock('../../utils/graphqlSchemaMismatch', () => ({ isSchemaMismatch: () => false }));
const mockClient = { query: (...a: unknown[]) => mockQuery(...a), mutate: (...a: unknown[]) => mockMutate(...a) };
jest.mock('@apollo/client', () => ({
  gql: (s: TemplateStringsArray) => s.join(''),
  useApolloClient: () => mockClient,
}));

import { HandsOffCards } from '../HandsOffCards';
import { handsOffActions } from '../handsOff';
import { purchaseCapAmount } from '../comprarHandsOff';

const PURCHASE = '2c1d3b5f-1111-4222-8333-944455556666';
const ORDER = '9a8b7c6d-1111-4222-8333-944455556666';

function texts(tree: renderer.ReactTestRenderer) {
  return tree.root.findAllByType(RNText).map((t) => [].concat(t.props.children).join('')).join(' | ');
}

async function mount(actions: any[], onOpen = jest.fn()) {
  let tree!: renderer.ReactTestRenderer;
  await act(async () => {
    tree = renderer.create(<HandsOffCards messageId="9" actions={actions} onOpen={onOpen} />);
  });
  return tree;
}

beforeEach(() => {
  jest.useRealTimers();
  mockQuery.mockReset();
  mockMutate.mockReset();
  mockStart.mockReset();
  mockDex = true;
});

describe('Comprar hands-off helpers', () => {
  it('keeps purchase cards with the hands-off ones', () => {
    expect(handsOffActions([{ type: 'trade' }, { type: 'relay_purchase', target: PURCHASE }] as any))
      .toEqual([{ type: 'relay_purchase', target: PURCHASE }]);
  });
  it('keeps purchase caps small', () => {
    expect(purchaseCapAmount('120')).toBe('120.00');
    expect(purchaseCapAmount('1500')).toBeNull();
    expect(purchaseCapAmount('0')).toBeNull();
  });
});

describe('Comprar hands-off cards', () => {
  it('shows the purchase being paid, then done with the order', async () => {
    const onOpen = jest.fn();
    mockQuery.mockResolvedValueOnce({ data: { assistantRelayPurchase: {
      status: 'done', label: 'Comprar Chompa por US$35', order: ORDER } } });
    const tree = await mount([{ type: 'relay_purchase', target: PURCHASE, label: 'Comprar Chompa por US$35' }], onOpen);
    expect(mockQuery.mock.calls[0][0].variables).toEqual({ purchase: PURCHASE });
    expect(texts(tree)).toContain('Pagado');
    tree.root.findByProps({ testID: 'relay-purchase-order' }).props.onPress();
    expect(onOpen).toHaveBeenCalledWith('MarketOrder', { orderId: ORDER });
  });

  it('cap card: small choices, the server preselection, Face, then the purchase resumes', async () => {
    mockQuery.mockResolvedValue({ data: { assistantRelayPurchase: {
      status: 'waiting_rule', label: 'x', mode: 'new', choices: ['50', '150', '300'], preselected: '50' } } });
    const tree = await mount([{ type: 'purchase_cap', target: PURCHASE }]);
    expect(texts(tree)).toContain('US$50');
    expect(texts(tree)).toContain('hasta US$50 por semana, en promedio');
    await act(async () => { tree.root.findByProps({ testID: 'btn-Firmar con Confío Face' }).props.onPress(); });
    expect(mockStart).toHaveBeenCalledWith(expect.objectContaining({ faceStepUp: true }));
    mockMutate.mockResolvedValue({ data: { prepareAssistantPurchaseCap: { success: true } } });
    await mockStart.mock.calls[0][0].prepare();
    expect(mockMutate.mock.calls[0][0].variables).toEqual({ purchase: PURCHASE, amount: '50.00' });
    mockMutate.mockResolvedValue({ data: { resumeAssistantRelayPurchase: { status: 'pending' } } });
    await act(async () => { await mockOnExecuted!(); });
    expect(mockMutate.mock.calls[1][0].variables).toEqual({ purchase: PURCHASE });
  });

  it('cap card raises, and another amount above the small maximum is refused', async () => {
    mockQuery.mockResolvedValue({ data: { assistantRelayPurchase: { status: 'waiting_rule', label: 'x',
      mode: 'raise', currentCap: '150.00', preselected: '300' } } });
    const tree = await mount([{ type: 'purchase_cap', target: PURCHASE }]);
    expect(texts(tree)).toContain('Sube tu límite de compras');
    await act(async () => { tree.root.findByProps({ testID: 'purchase-cap-other' }).props.onPress(); });
    await act(async () => { tree.root.findByProps({ testID: 'purchase-cap-input' }).props.onChangeText('5000'); });
    expect(tree.root.findByProps({ testID: 'btn-Firmar con Confío Face' }).props.disabled).toBe(true);
    await act(async () => { tree.root.findByProps({ testID: 'purchase-cap-input' }).props.onChangeText('200'); });
    await act(async () => { tree.root.findByProps({ testID: 'btn-Firmar con Confío Face' }).props.onPress(); });
    mockMutate.mockResolvedValue({ data: { prepareAssistantPurchaseCap: { success: true } } });
    await mockStart.mock.calls[0][0].prepare();
    expect(mockMutate.mock.calls[0][0].variables.amount).toBe('200.00');
  });

  it('move card: the server amount, Face, then the purchase resumes', async () => {
    mockQuery.mockResolvedValue({ data: { assistantRelayPurchase: { status: 'waiting_move', label: 'x',
      moveAmount: '40' } } });
    const tree = await mount([{ type: 'purchase_move', target: PURCHASE, label: 'Mover' }]);
    expect(texts(tree)).toContain('Mover US$40.00 a tu Cuenta inteligente');
    await act(async () => { tree.root.findByProps({ testID: 'btn-Mover con Confío Face' }).props.onPress(); });
    mockMutate.mockResolvedValue({ data: { prepareAssistantPurchaseMove: { success: true } } });
    await mockStart.mock.calls[0][0].prepare();
    expect(mockMutate.mock.calls[0][0].variables).toEqual({ purchase: PURCHASE });
  });

  it('paywall opens the offer; Hazlo tú opens the product to buy from the wallet', async () => {
    const onOpen = jest.fn();
    const tree = await mount([{ type: 'purchase_offer', target: 'chat_purchase', destination: 'MarketProduct',
      ticker: '42' }], onOpen);
    tree.root.findByProps({ testID: 'btn-Activa Cuenta inteligente' }).props.onPress();
    expect(onOpen).toHaveBeenCalledWith('SmartAccountOffer', { door: 'chip', trigger: 'chat_purchase' });
    tree.root.findByProps({ testID: 'purchase-offer-diy' }).props.onPress();
    expect(onOpen).toHaveBeenCalledWith('MarketProduct', { productId: '42' });
  });

  it('Hazlo tú alone when the account cannot pay it', async () => {
    const tree = await mount([{ type: 'purchase_offer', target: '', destination: 'MarketProduct', ticker: '42' }]);
    expect(tree.root.findAllByProps({ testID: 'btn-Activa Cuenta inteligente' })).toHaveLength(0);
    expect(tree.root.findAllByProps({ testID: 'purchase-offer-diy' }).length).toBeGreaterThan(0);
  });
});
