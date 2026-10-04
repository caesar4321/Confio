import React from 'react';
import renderer, {act} from 'react-test-renderer';
import {TextInput, TouchableOpacity} from 'react-native';
const mockClient = {query: jest.fn(), mutate: jest.fn()};
jest.mock('@apollo/client', () => ({useApolloClient: () => mockClient}));
jest.mock('@react-navigation/native', () => ({useIsFocused: () => true}));
jest.mock('../../components/PaymentQrScannerModal', () => ({PaymentQrScannerModal: 'Scanner'}));
jest.mock('../../utils/rampFlow', () => ({requestRampCriticalAuth: jest.fn()}));
let mockSequence = 0;
jest.mock('../../services/stereumQr', () => ({
  STEREUM_QR_AVAILABILITY: 'availability', DECODE_STEREUM_QR: 'decode', PAY_STEREUM_QR: 'pay', STEREUM_QR_PAYMENT: 'status',
  qrRequestId: () => `request-${++mockSequence}`, readPendingQr: jest.fn(), savePendingQr: jest.fn(), clearPendingQr: jest.fn(),
  validBobAmount: (value: string) => /^\d+([.,]\d{1,2})?$/.test(value) && Number(value.replace(',', '.')) >= 1 && Number(value.replace(',', '.')) <= 69000,
}));
import {readPendingQr, savePendingQr, clearPendingQr} from '../../services/stereumQr';
import {requestRampCriticalAuth} from '../../utils/rampFlow';
import Screen from '../BoliviaQrSendScreen';
const preview = {requestId:'decoded', recipientName:'ANA PEREZ', bankName:'Banco de prueba', accountLast4:'1234', amount:'10.00', fixedAmount:true, currency:'BOB', expiresOn:'2099-01-01'};
const button = (tree: renderer.ReactTestRenderer, title: string) => tree.root.findAllByType(TouchableOpacity).find(node => node.props.children?.props?.children === title)!;
const texts = (tree: renderer.ReactTestRenderer) => JSON.stringify(tree.toJSON());
let tree: renderer.ReactTestRenderer;
beforeEach(() => {
  jest.clearAllMocks(); mockSequence = 0;
  (readPendingQr as jest.Mock).mockResolvedValue(null);
  (savePendingQr as jest.Mock).mockResolvedValue(undefined);
  (clearPendingQr as jest.Mock).mockResolvedValue(undefined);
  (requestRampCriticalAuth as jest.Mock).mockResolvedValue(true);
  mockClient.query.mockResolvedValue({data:{stereumQrAvailability:{enabled:true, canPay:true}}});
  mockClient.mutate.mockImplementation(async ({mutation}) => mutation === 'decode' ? {data:{decodeStereumQr:preview}} : {data:{payStereumQr:{requestId:'request-2', status:'pending'}}});
});
afterEach(async () => {if (tree) await act(async () => tree.unmount());});
const mount = async () => {await act(async () => {tree = renderer.create(<Screen onBack={() => {}} accountId="personal-1" initialQr="encrypted|qr" />);});};
it('decodes the handoff once and does not pay on scan or review', async () => {
  await mount(); expect(mockClient.mutate).toHaveBeenCalledTimes(1);
  expect(texts(tree)).toContain('ANA PEREZ'); expect(tree.root.findAllByType(TextInput)).toHaveLength(0);
  await act(async () => button(tree, 'Revisar pago').props.onPress());
  expect(mockClient.mutate).toHaveBeenCalledTimes(1); expect(requestRampCriticalAuth).not.toHaveBeenCalled();
});
it('saves the request before submitting and suppresses double taps', async () => {
  await mount(); await act(async () => button(tree, 'Revisar pago').props.onPress());
  await act(async () => {const b=button(tree, 'Confirmar pago de prueba'); b.props.onPress(); b.props.onPress();});
  const calls = mockClient.mutate.mock.calls.filter(([a]) => a.mutation === 'pay');
  expect(calls).toHaveLength(1); expect(calls[0][0].variables).toEqual({requestId:'request-2', decodeRequestId:'decoded', amount:'10.00'});
  expect((savePendingQr as jest.Mock).mock.invocationCallOrder[0]).toBeLessThan(mockClient.mutate.mock.invocationCallOrder[1]);
  expect(texts(tree)).toContain('Pago de prueba en revisión'); expect(button(tree, 'Confirmar pago de prueba')).toBeUndefined();
});
it('keeps a lost response locked for status recovery', async () => {
  await mount(); mockClient.mutate.mockRejectedValue(new Error('timeout'));
  await act(async () => button(tree, 'Revisar pago').props.onPress()); await act(async () => button(tree, 'Confirmar pago de prueba').props.onPress());
  expect(texts(tree)).toContain('No repitas el pago'); expect(button(tree, 'Confirmar pago de prueba')).toBeUndefined(); expect(clearPendingQr).not.toHaveBeenCalled();
});
it('recovers a saved request before decoding another QR', async () => {
  (readPendingQr as jest.Mock).mockResolvedValue('old-request'); await mount(); expect(mockClient.mutate).not.toHaveBeenCalled();
  mockClient.query.mockResolvedValue({data:{stereumQrPayment:{requestId:'old-request',status:'succeeded'}}});
  await act(async () => button(tree, 'Consultar estado').props.onPress());
  expect(clearPendingQr).toHaveBeenCalledWith('personal-1'); expect(texts(tree)).toContain('Pago de prueba completado');
});
it('never sends when secure storage fails', async () => {
  (savePendingQr as jest.Mock).mockRejectedValue(new Error('locked')); await mount();
  await act(async () => button(tree, 'Revisar pago').props.onPress()); await act(async () => button(tree, 'Confirmar pago de prueba').props.onPress());
  expect(mockClient.mutate).toHaveBeenCalledTimes(1); expect(texts(tree)).toContain('No se envió el pago');
});
it('fails closed when recovery storage is unreadable', async () => {
  (readPendingQr as jest.Mock).mockRejectedValue(new Error('locked')); await mount();
  expect(mockClient.mutate).not.toHaveBeenCalled(); expect(button(tree, 'Escanear o importar QR')).toBeUndefined();
});
it('validates open amounts', async () => {
  mockClient.mutate.mockResolvedValue({data:{decodeStereumQr:{...preview, fixedAmount:false,amount:'0.00'}}}); await mount();
  const field = tree.root.findByType(TextInput);
  for (const value of ['0','1.001','70000']) {await act(async () => field.props.onChangeText(value)); expect(button(tree, 'Revisar pago').props.disabled).toBe(true);}
  await act(async () => field.props.onChangeText('12,50')); expect(button(tree, 'Revisar pago').props.disabled).toBe(false);
});
it('does not send after unmount during authentication', async () => {
  let auth!: (v: boolean) => void; (requestRampCriticalAuth as jest.Mock).mockReturnValue(new Promise(resolve => {auth=resolve;}));
  await mount(); await act(async () => button(tree, 'Revisar pago').props.onPress());
  await act(async () => button(tree, 'Confirmar pago de prueba').props.onPress()); await act(async () => tree.unmount()); await act(async () => auth(true));
  expect(mockClient.mutate).toHaveBeenCalledTimes(1); expect(savePendingQr).not.toHaveBeenCalled();
});
