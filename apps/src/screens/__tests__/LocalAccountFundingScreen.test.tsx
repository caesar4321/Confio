import React from 'react';
import renderer, { act } from 'react-test-renderer';
import { Text, TouchableOpacity } from 'react-native';
const mockAuthorize = jest.fn();
const mockRefetch = jest.fn().mockResolvedValue({});
let mockRows: any[] = [];
jest.mock('@apollo/client', () => ({ useQuery: (q: string) => q === 'availability' ? {
  data: { paymentBridgeAvailability: { toProvider: true, toWallet: true }, paymentBridgeInstructions: [] },
} : { data: { myPaymentBridges: mockRows }, refetch: mockRefetch } }));
jest.mock('@react-navigation/native', () => ({ useNavigation: () => ({ goBack: jest.fn() }) }));
jest.mock('react-native-safe-area-context', () => ({ SafeAreaView: 'SafeAreaView' }));
jest.mock('../../services/paymentBridge', () => ({ BRIDGE_AVAILABILITY: 'availability', BRIDGE_HISTORY: 'history',
  authorizePaymentBridge: (...args: any[]) => mockAuthorize(...args), bridgeRequestId: jest.fn(), preparePaymentBridge: jest.fn() }));
import Screen, { bridgeAmount, bridgeStatus } from '../LocalAccountFundingScreen';

beforeEach(() => { jest.clearAllMocks(); mockRows = []; });
it('formats token units without floating point rounding', () => {
  expect(bridgeAmount('999999999999999999', 18)).toBe('0.999999');
});
it('never describes bridge delivery as bank payout completion', () => {
  expect(bridgeStatus({ status: 'delivered', sourceTokenId: 'BSC:USDT' } as any)).toContain('Pendiente de acreditación');
});
it('restores pending history after reopening without signing again', async () => {
  mockRows = [{ internalId: 'existing', status: 'submitted', sourceTokenId: 'BSC:USDT', amountUnits: '10000000000000000000' }];
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<Screen />); });
  expect(tree.root.findAllByType(Text).some(n => n.props.children === 'Envío en proceso')).toBe(true);
  expect(mockAuthorize).not.toHaveBeenCalled();
  await act(async () => { tree.unmount(); });
});
it('shows an uncertain submission error without automatically retrying', async () => {
  mockRows = [{ internalId: 'existing', status: 'prepared', sourceTokenId: 'POL:USDC', amountUnits: '10000000',
    amountOutMin: '9800000000000000000', feeUnits: '0', deadline: '2000000000' }];
  mockAuthorize.mockRejectedValue(new Error('network lost'));
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<Screen />); });
  const history = tree.root.findAllByType(TouchableOpacity).find(n => n.findAllByType(Text).some(t => t.props.children === 'existing'))!;
  await act(async () => { history.props.onPress(); });
  const confirm = tree.root.findAllByType(TouchableOpacity).find(n => n.findAllByType(Text).some(t => t.props.children === 'Confirmar envío'))!;
  await act(async () => { await confirm.props.onPress(); });
  expect(mockAuthorize).toHaveBeenCalledTimes(1);
  expect(mockRefetch).toHaveBeenCalled();
  expect(tree.root.findAllByType(Text).some(n => String(n.props.children).includes('No pudimos confirmar'))).toBe(true);
  await act(async () => { tree.unmount(); });
});
