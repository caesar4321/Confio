import React from 'react';
import renderer, {act} from 'react-test-renderer';
import {Text, TextInput, TouchableOpacity} from 'react-native';
const mockPrepare = jest.fn(),
  mockCreate = jest.fn(),
  mockAuthorize = jest.fn(),
  mockAttach = jest.fn(),
  mockFetch = jest.fn();
let mockHistoryRows: any[] = [];
const mockRefetch = jest.fn().mockResolvedValue({});
jest.mock('@react-navigation/native', () => ({
  useNavigation: () => ({goBack: jest.fn()}),
}));
jest.mock('react-native-safe-area-context', () => ({
  SafeAreaView: 'SafeAreaView',
}));
jest.mock('../LocalAccountFundingScreen', () => ({
  bridgeAmount: (s: string) => s,
}));
jest.mock('../../services/paymentBridge', () => ({
  bridgeRequestId: () => 'request-1',
  journeyReturnBridgeRequestId: (provider: string, id: string) => `return-${provider}-${id}`,
  preparePaymentBridge: (...a: any[]) => mockPrepare(...a),
  authorizePaymentBridge: (...a: any[]) => mockAuthorize(...a),
  fetchPaymentBridge: (...a: any[]) => mockFetch(...a),
}));
jest.mock('../../services/infiniaJourney', () => ({
  INFINIA_OPTIONS: 'options',
  INFINIA_HISTORY: 'history',
  INFINIA_DEPOSITS: 'deposits',
  createInfiniaJourney: (...a: any[]) => mockCreate(...a),
  attachInfiniaBridge: (...a: any[]) => mockAttach(...a),
  infiniaStage: (s: string) => s,
}));
jest.mock('../../services/cobreJourney', () => ({}));
jest.mock('@apollo/client', () => ({
  useQuery: (q: string) => ({
    refetch: mockRefetch,
    data:
      q === 'options'
        ? {
            infiniaJourneysEnabled: true,
            myPaymentAccounts: [
              {
                internalId: 'local',
                provider: 'infinia',
                country: 'PER',
                asset: 'PEN',
                status: 'ACTIVE',
              },
              {
                internalId: 'crypto',
                provider: 'infinia',
                country: 'XXX',
                asset: 'USDC_POL',
                status: 'ACTIVE',
                fundingInstructions: [
                  {
                    internalId: 'instruction',
                    kind: 'CRYPTO_ADDRESS',
                    status: 'ACTIVE',
                  },
                ],
              },
            ],
            myPayoutDestinations: [
              {
                internalId: 'bank',
                provider: 'INFINIA',
                country: 'PER',
                asset: 'PEN',
                label: 'Bank',
                holderName: 'Holder',
              },
            ],
          }
        : q === 'history'
          ? {myInfiniaJourneys: mockHistoryRows}
          : {infiniaJourneyDeposits: []},
  }),
}));
import Screen from '../InfiniaPaymentScreen';

beforeEach(() => {
  jest.clearAllMocks();
  mockHistoryRows = [];
});

it('reviews first, persists the bank instruction, then signs once on confirmation', async () => {
  mockPrepare.mockResolvedValue({
    internalId: 'bridge',
    amountUnits: '10',
    feeUnits: '0',
    amountOutMin: '9.9',
  });
  mockCreate.mockResolvedValue({internalId: 'journey'});
  mockAuthorize.mockResolvedValue({});
  let tree!: renderer.ReactTestRenderer;
  await act(async () => {
    tree = renderer.create(<Screen />);
  });
  const press = async (text: string) => {
    const button = tree.root
      .findAllByType(TouchableOpacity)
      .find(b =>
        b
          .findAllByType(Text)
          .some(t => String(t.props.children).includes(text)),
      )!;
    await act(async () => {
      await button.props.onPress();
    });
  };
  await press('PER · PEN');
  await press('Bank · Holder');
  const inputs = tree.root.findAllByType(TextInput);
  await act(async () => {
    inputs[0].props.onChangeText('10');
    inputs[1].props.onChangeText('30');
  });
  await press('Revisar pago');
  expect(mockPrepare).toHaveBeenCalledTimes(1);
  expect(mockCreate).not.toHaveBeenCalled();
  expect(mockAuthorize).not.toHaveBeenCalled();
  await press('Confirmar conversión y pago');
  expect(mockCreate).toHaveBeenCalledWith(
    expect.objectContaining({
      destinationId: 'bank',
      minimumFxOutput: '30',
      bridgeId: 'bridge',
    }),
  );
  expect(mockAuthorize).toHaveBeenCalledTimes(1);
  expect(mockCreate.mock.invocationCallOrder[0]).toBeLessThan(
    mockAuthorize.mock.invocationCallOrder[0],
  );
  await act(async () => tree.unmount());
});

it.each(['prepare', 'attach'])('recovers a lost %s response using the same journey return request', async failure => {
  mockHistoryRows = [{internalId: 'journey', stage: 'awaiting_wallet_authorization', cryptoAccountId: 'crypto', walletArrivalUnits: '2500000'}];
  mockPrepare.mockResolvedValue({internalId: 'bridge', amountOutMin: '2400000', sourceTokenId: 'POL:USDC'});
  mockAttach.mockResolvedValue({internalId: 'journey'});
  if (failure === 'prepare') mockPrepare.mockRejectedValueOnce(new Error('response lost'));
  else mockAttach.mockRejectedValueOnce(new Error('response lost'));
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<Screen />); });
  const resume = async () => {
    const button = tree.root.findAllByType(TouchableOpacity).find(b => b.findAllByType(Text).some(t => t.props.children === 'Revisar envío pendiente'))!;
    await act(async () => { await button.props.onPress(); });
  };
  await resume();
  // Simulate restarting the screen: the request must not depend on a local ref.
  await act(async () => { tree.unmount(); tree = renderer.create(<Screen />); });
  await resume();
  expect(mockPrepare).toHaveBeenCalledTimes(2);
  expect(mockPrepare.mock.calls[0]).toEqual(mockPrepare.mock.calls[1]);
  expect(mockPrepare.mock.calls[1][3]).toBe('return-infinia-journey');
  expect(mockAttach).toHaveBeenLastCalledWith('journey', 'bridge');
  expect(mockAuthorize).not.toHaveBeenCalled();
  await act(async () => tree.unmount());
});

it.each(['to_bank', 'to_wallet'])('shows immutable approval details when resuming %s', async direction => {
  mockHistoryRows = [{internalId: 'journey', stage: 'bridging', direction, bridgeId: 'bridge', destinationSummary: 'Saved bank · Alice · 1234', minimumFxOutput: '35.50', localAsset: 'PEN'}];
  mockFetch.mockResolvedValue({internalId: 'bridge', status: 'prepared', sourceTokenId: direction === 'to_bank' ? 'BSC:USDT' : 'POL:USDC', amountUnits: '10000000', feeUnits: '1000', amountOutMin: '9800000'});
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<Screen />); });
  const resume = tree.root.findAllByType(TouchableOpacity).find(b => b.findAllByType(Text).some(t => t.props.children === 'Revisar envío pendiente'))!;
  await act(async () => { await resume.props.onPress(); });
  const texts = tree.root.findAllByType(Text).map(t => React.Children.toArray(t.props.children).join(''));
  expect(texts.some(t => t.includes('10000000'))).toBe(true);
  expect(texts.some(t => t.includes('Costo de conversión adicional: 1000 dólares.'))).toBe(true);
  if (direction === 'to_bank') {
    expect(texts).toContain('Destino del pago: Saved bank · Alice · 1234');
    expect(texts.some(t => t.includes('35.50 PEN'))).toBe(true);
  } else {
    expect(texts).toContain('Dólares a traer a Confío: 10000000');
  }
  expect(mockAuthorize).not.toHaveBeenCalled();
  await act(async () => tree.unmount());
});
