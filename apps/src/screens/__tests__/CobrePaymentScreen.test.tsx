import React from 'react';
import renderer, {act} from 'react-test-renderer';
import {Text, TextInput, TouchableOpacity} from 'react-native';
const mockPrepare = jest.fn(),
  mockCreate = jest.fn(),
  mockAuthorize = jest.fn();
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
  preparePaymentBridge: (...a: any[]) => mockPrepare(...a),
  authorizePaymentBridge: (...a: any[]) => mockAuthorize(...a),
}));
jest.mock('../../services/cobreJourney', () => ({
  COBRE_OPTIONS: 'options',
  COBRE_HISTORY: 'history',
  COBRE_DEPOSITS: 'deposits',
  createCobreJourney: (...a: any[]) => mockCreate(...a),
  cobreStage: (s: string) => s,
}));
jest.mock('../../services/infiniaJourney', () => ({}));
jest.mock('@apollo/client', () => ({
  useQuery: (q: string) => ({
    refetch: mockRefetch,
    data:
      q === 'options'
        ? {
            cobreJourneysEnabled: true,
            myPaymentAccounts: [
              {
                internalId: 'copco',
                provider: 'cobre',
                country: 'XXX',
                asset: 'COPCO',
                status: 'ACTIVE',
              },
              {
                internalId: 'local',
                provider: 'cobre',
                country: 'COL',
                asset: 'COP',
                status: 'ACTIVE',
              },
              {
                internalId: 'crypto',
                provider: 'cobre',
                country: 'XXX',
                asset: 'USD_STABLE',
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
                provider: 'COBRE',
                country: 'COL',
                asset: 'COP',
                label: 'Bank',
                holderName: 'Holder',
              },
            ],
          }
        : q === 'history'
          ? {myCobreJourneys: []}
          : {cobreJourneyDeposits: []},
  }),
}));
import Screen from '../CobrePaymentScreen';

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
  await press('COL · COP');
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
      copcoAccountId: 'copco',
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
