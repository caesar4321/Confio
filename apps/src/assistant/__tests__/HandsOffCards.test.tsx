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

import { capAmount, capText, diyScreenAllowed, handsOffActions } from '../handsOff';
import { HandsOffCards } from '../HandsOffCards';

const TRADE = '1b0c2a4e-1111-4222-8333-944455556666';

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

describe('helpers', () => {
  it('says the cap as a weekly average', () => {
    expect(capText('1000.00')).toBe('hasta US$1,000 por semana, en promedio');
    expect(capText('')).toBe('');
  });
  it('reads a typed cap', () => {
    expect(capAmount('1500')).toBe('1500.00');
    expect(capAmount('0')).toBeNull();
    expect(capAmount('20000')).toBeNull();
  });
  it('never opens bitcoin or gold where the app ships without them', () => {
    expect(diyScreenAllowed('BuyCrypto', false)).toBe(false);
    expect(diyScreenAllowed('BuyCrypto', true)).toBe(true);
    expect(diyScreenAllowed('BuyStock', false)).toBe(true);
    expect(diyScreenAllowed('Elsewhere', true)).toBe(false);
  });
  it('keeps only hands-off actions', () => {
    expect(handsOffActions([{ type: 'trade' }, { type: 'relay_trade', target: TRADE }] as any))
      .toEqual([{ type: 'relay_trade', target: TRADE }]);
  });
});

describe('cards', () => {
  it('shows a hands-off trade in progress, then done', async () => {
    mockQuery.mockResolvedValueOnce({ data: { assistantRelayTrade: { status: 'done', label: 'Comprar US$20 de TSLA' } } });
    const tree = await mount([{ type: 'relay_trade', target: TRADE, label: 'Comprar US$20 de TSLA' }]);
    expect(mockQuery.mock.calls[0][0].variables).toEqual({ trade: TRADE });
    expect(texts(tree)).toContain('Hecho');
  });

  it('cap card: preselects the server choice, signs with Face, then resumes the trade', async () => {
    mockQuery.mockResolvedValue({ data: { assistantRelayTrade: {
      status: 'waiting_rule', label: 'x', mode: 'new', choices: ['250', '1000', '2500'], preselected: '1000' } } });
    const tree = await mount([{ type: 'trade_cap', target: TRADE }]);
    expect(texts(tree)).toContain('hasta US$1,000 por semana, en promedio');
    await act(async () => { tree.root.findByProps({ testID: 'btn-Firmar con Confío Face' }).props.onPress(); });
    expect(mockStart).toHaveBeenCalledWith(expect.objectContaining({ faceStepUp: true }));
    mockMutate.mockResolvedValue({ data: { prepareAssistantTradeCap: { success: true } } });
    await mockStart.mock.calls[0][0].prepare();
    expect(mockMutate.mock.calls[0][0].variables).toEqual({ trade: TRADE, amount: '1000.00' });
    mockMutate.mockResolvedValue({ data: { resumeAssistantRelayTrade: { status: 'pending' } } });
    await act(async () => { await mockOnExecuted!(); });
    expect(mockMutate.mock.calls[1][0].variables).toEqual({ trade: TRADE });
  });

  it('cap card: another amount', async () => {
    mockQuery.mockResolvedValue({ data: { assistantRelayTrade: { status: 'waiting_rule', label: 'x', mode: 'raise',
      currentCap: '250.00', preselected: '1000' } } });
    const tree = await mount([{ type: 'trade_cap', target: TRADE }]);
    expect(texts(tree)).toContain('Sube tu límite semanal');
    await act(async () => { tree.root.findByProps({ testID: 'cap-other' }).props.onPress(); });
    await act(async () => { tree.root.findByProps({ testID: 'cap-input' }).props.onChangeText('3000'); });
    await act(async () => { tree.root.findByProps({ testID: 'btn-Firmar con Confío Face' }).props.onPress(); });
    mockMutate.mockResolvedValue({ data: { prepareAssistantTradeCap: { success: true } } });
    await mockStart.mock.calls[0][0].prepare();
    expect(mockMutate.mock.calls[0][0].variables.amount).toBe('3000.00');
  });

  it('paywall opens the offer by the chip door; Hazlo tú opens the prefilled screen', async () => {
    const onOpen = jest.fn();
    const tree = await mount([{ type: 'trade_offer', target: 'chat_trade', destination: 'BuyCrypto', ticker: 'BTCB' }],
      onOpen);
    tree.root.findByProps({ testID: 'btn-Activa Cuenta inteligente' }).props.onPress();
    expect(onOpen).toHaveBeenCalledWith('SmartAccountOffer', { door: 'chip', trigger: 'chat_trade' });
    tree.root.findByProps({ testID: 'trade-offer-diy' }).props.onPress();
    expect(onOpen).toHaveBeenCalledWith('BuyCrypto', { symbol: 'BTCB' });
  });

  it('no bitcoin or gold screen on a build without them', async () => {
    mockDex = false;
    const tree = await mount([{ type: 'trade_offer', target: 'chat_trade', destination: 'BuyCrypto', ticker: 'BTCB' }]);
    expect(tree.root.findAllByProps({ testID: 'trade-offer-diy' })).toHaveLength(0);
  });

  it('move card: the server amount, Face, then the trade resumes', async () => {
    mockQuery.mockResolvedValue({ data: { assistantRelayTrade: { status: 'waiting_move', label: 'x',
      moveAmount: '40' } } });
    const tree = await mount([{ type: 'trade_move', target: TRADE, label: 'Mover' }]);
    expect(texts(tree)).toContain('Mover US$40.00 a tu Cuenta inteligente');
    await act(async () => { tree.root.findByProps({ testID: 'btn-Mover con Confío Face' }).props.onPress(); });
    mockMutate.mockResolvedValue({ data: { prepareAssistantTradeMove: { success: true } } });
    await mockStart.mock.calls[0][0].prepare();
    expect(mockMutate.mock.calls[0][0].variables).toEqual({ trade: TRADE });
    mockMutate.mockResolvedValue({ data: { resumeAssistantRelayTrade: { status: 'pending' } } });
    await act(async () => { await mockOnExecuted!(); });
    expect(mockMutate.mock.calls[1][0].variables).toEqual({ trade: TRADE });
  });

  it('migration card signs with Face', async () => {
    const tree = await mount([{ type: 'account_migration', label: 'Actualizar mi Cuenta inteligente' }]);
    tree.root.findByProps({ testID: 'btn-Actualizar con Confío Face' }).props.onPress();
    expect(mockStart).toHaveBeenCalledWith(expect.objectContaining({ faceStepUp: true }));
  });
});
