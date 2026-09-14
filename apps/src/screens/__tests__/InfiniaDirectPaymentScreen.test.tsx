import React from 'react';
import renderer, {act} from 'react-test-renderer';
import {Text, TextInput, TouchableOpacity} from 'react-native';

const mockRefetch = jest.fn().mockResolvedValue({});
const mockCreateJourney = jest.fn().mockResolvedValue({internalId: 'journey'});
const mockAuthorizeBridge = jest.fn().mockResolvedValue({});
const mockPrepareBridge = jest.fn();
const mockFetchBridge = jest.fn();
let mockRows: any[] = [];

jest.mock('@apollo/client', () => ({
  gql: (parts: TemplateStringsArray) => parts.join(''),
  useQuery: (query: string) => {
    if (query.includes('query InfiniaJourneyOptions')) {
      return {data: {
        infiniaJourneysEnabled: true,
        myPaymentAccounts: [
          {internalId: 'local', provider: 'infinia', asset: 'PEN', country: 'PER', status: 'active'},
          {internalId: 'crypto', provider: 'infinia', asset: 'USDC_POL', country: 'XXX', status: 'active',
            fundingInstructions: [{internalId: 'instruction', kind: 'crypto_address', status: 'active'}]},
        ],
        myPayoutDestinations: [],
      }, refetch: mockRefetch};
    }
    if (query.includes('query InfiniaJourneyDeposits')) {
      return {data: {infiniaJourneyDeposits: [
        {internalId: 'credit', amount: '10', asset: 'PEN', occurredAt: '2026-09-14T12:00:00Z'},
      ]}, refetch: mockRefetch};
    }
    return {data: {myInfiniaJourneys: mockRows}, refetch: mockRefetch};
  },
}));
jest.mock('@react-navigation/native', () => ({useNavigation: () => ({goBack: jest.fn()})}));
jest.mock('react-native-safe-area-context', () => ({SafeAreaView: 'SafeAreaView'}));
jest.mock('../../services/infiniaJourney', () => ({
  ...jest.requireActual('../../services/infiniaJourney'),
  createInfiniaJourney: (...args: unknown[]) => mockCreateJourney(...args),
}));
jest.mock('../../services/paymentBridge', () => ({
  authorizePaymentBridge: (...args: unknown[]) => mockAuthorizeBridge(...args),
  preparePaymentBridge: (...args: unknown[]) => mockPrepareBridge(...args),
  fetchPaymentBridge: (...args: unknown[]) => mockFetchBridge(...args),
  bridgeRequestId: () => 'request-id',
  journeyReturnBridgeRequestId: () => 'return-request-id',
}));
jest.mock('../LocalAccountFundingScreen', () => ({
  bridgeAmount: (units: string, decimals: number) => String(Number(units) / 10 ** decimals),
}));

import InfiniaPaymentScreen from '../InfiniaPaymentScreen';

describe('Infinia direct inbound payments', () => {
  let tree: renderer.ReactTestRenderer;
  const buttons = (label: string) => tree.root.findAllByType(TouchableOpacity).filter(node =>
    node.findAllByType(Text).some(text => String(text.props.children).startsWith(label)));
  const press = async (label: string) => {
    const matches = buttons(label);
    expect(matches).toHaveLength(1);
    expect(matches[0].props.disabled).toBe(false);
    await act(async () => { await matches[0].props.onPress(); });
  };
  const enter = async (placeholder: string, value: string) => {
    const input = tree.root.findAllByType(TextInput).find(node => node.props.placeholder === placeholder);
    expect(input).toBeDefined();
    await act(async () => { input!.props.onChangeText(value); });
  };

  beforeEach(() => {
    jest.clearAllMocks();
    mockRows = [];
  });
  afterEach(async () => {
    if (tree) await act(async () => { tree.unmount(); });
  });

  it('requires a separate wallet minimum and submits both minima without requesting a signature', async () => {
    await act(async () => { tree = renderer.create(<InfiniaPaymentScreen />); });
    await press('Hacia un banco');
    await press('PER · PEN');
    await press('10 PEN');
    await enter('Mínimo aceptado en la conversión (dólares)', '2,5');
    expect(buttons('Confirmar conversión y pago')[0].props.disabled).toBe(true);
    expect(mockCreateJourney).not.toHaveBeenCalled();

    await enter('Mínimo de USDT a recibir en tu billetera', '2,4');
    await press('Confirmar conversión y pago');
    expect(mockCreateJourney).toHaveBeenCalledTimes(1);
    expect(mockCreateJourney).toHaveBeenCalledWith(expect.objectContaining({
      direction: 'to_wallet', requestId: 'request-id', localAccountId: 'local',
      cryptoAccountId: 'crypto', creditId: 'credit', minimumFxOutput: '2.5', minimumWalletOutput: '2.4',
    }));
    expect(mockPrepareBridge).not.toHaveBeenCalled();
    expect(mockAuthorizeBridge).not.toHaveBeenCalled();
  });

  it('never offers signing for a provider-funded pending bridge', async () => {
    mockRows = [{internalId: 'direct', direction: 'to_wallet', stage: 'bridging',
      bridgeId: 'direct-bridge', bridgeFundingMode: 'infinia'}];
    await act(async () => { tree = renderer.create(<InfiniaPaymentScreen />); });
    expect(buttons('Revisar envío pendiente')).toHaveLength(0);
    expect(buttons('Confirmar envío pendiente')).toHaveLength(0);
    expect(mockFetchBridge).not.toHaveBeenCalled();
    expect(mockAuthorizeBridge).not.toHaveBeenCalled();
  });

  it('retains explicit review and signing for a legacy wallet-funded bridge', async () => {
    mockRows = [{internalId: 'legacy', direction: 'to_wallet', stage: 'bridging',
      bridgeId: 'wallet-bridge', bridgeFundingMode: 'wallet'}];
    const bridge = {internalId: 'wallet-bridge', status: 'prepared', sourceTokenId: 'POL:USDC',
      amountUnits: '2500000', amountOutMin: '2400000000000000000', feeUnits: '0'};
    mockFetchBridge.mockResolvedValue(bridge);
    await act(async () => { tree = renderer.create(<InfiniaPaymentScreen />); });
    await press('Revisar envío pendiente');
    expect(mockFetchBridge).toHaveBeenCalledWith('wallet-bridge');
    expect(mockAuthorizeBridge).not.toHaveBeenCalled();
    await press('Confirmar envío pendiente');
    expect(mockAuthorizeBridge).toHaveBeenCalledWith(bridge);
    expect(mockCreateJourney).not.toHaveBeenCalled();
    expect(mockPrepareBridge).not.toHaveBeenCalled();
  });
});
