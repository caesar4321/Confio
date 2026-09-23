import React from 'react';
import renderer, {act} from 'react-test-renderer';
import {Alert, AppState} from 'react-native';
import {launchImageLibrary} from 'react-native-image-picker';
import RNQRGenerator from 'rn-qr-generator';

const mockNavigate = jest.fn();
const mockQuery = jest.fn();
const mockInvoice = jest.fn();
let mockScanner: any;
let mockMode: string | undefined;
jest.mock('react-native-vector-icons/Feather', () => 'Icon');
jest.mock('react-native-safe-area-context', () => ({useSafeAreaInsets: () => ({top: 0, bottom: 0, left: 0, right: 0})}));
jest.mock('react-native-image-picker', () => ({launchImageLibrary: jest.fn()}));
jest.mock('rn-qr-generator', () => ({detect: jest.fn()}));
jest.mock('react-native-vision-camera', () => ({
  Camera: Object.assign((props: any) => require('react').createElement('Camera', props), {getCameraPermissionStatus: async () => 'granted', requestCameraPermission: async () => 'granted'}),
  useCameraDevice: () => ({id: 'back'}),
  useCodeScanner: (options: any) => {mockScanner = options; return options;},
}));
jest.mock('@react-navigation/native', () => ({
  useNavigation: () => ({navigate: mockNavigate, goBack: jest.fn()}),
  useRoute: () => ({params: {mode: mockMode}}), useIsFocused: () => true,
  useFocusEffect: (fn: any) => {require('react').useEffect(fn, [fn]);},
}));
jest.mock('@apollo/client', () => ({useApolloClient: () => ({query: mockQuery}), useMutation: () => [mockInvoice]}));
jest.mock('../../apollo/queries', () => ({GET_INVOICE: 'invoice'}));
jest.mock('../../services/localMoney', () => ({LOCAL_MONEY_METHODS: 'methods'}));
jest.mock('../../contexts/AccountContext', () => ({useAccount: () => ({activeAccount: {id: 'user-1', type: 'personal'}})}));
jest.mock('../../components/common/Button', () => ({Button: 'Button'}));
import {ScanScreen} from '../ScanScreen';

beforeEach(() => {
  jest.clearAllMocks(); mockMode = 'pagar';
  AppState.currentState = 'active';
  jest.spyOn(Alert, 'alert').mockImplementation(() => {});
});
afterEach(() => jest.restoreAllMocks());
const scan = (value: string) => mockScanner.onCodeScanned([{value}]);

it.each([['BR','br_qr'],['AR','ar_qr']])('routes %s QR through server availability, without paying', async (country, methodId) => {
  mockQuery.mockResolvedValue({data: {localMoneyMethods: [{id: methodId, status: 'live'}]}});
  let tree!: renderer.ReactTestRenderer;
  await act(async () => {tree = renderer.create(<ScanScreen />);});
  const raw = `0002015802${country}63040000`;
  await act(async () => {scan(raw); scan(raw);});
  expect(mockQuery).toHaveBeenCalledTimes(1);
  expect(mockNavigate).toHaveBeenCalledWith('LocalSend', {methodId, scannedQr: raw});
  expect(mockInvoice).not.toHaveBeenCalled();
  await act(async () => tree.unmount());
});

it('does not route an unavailable Peru QR', async () => {
  mockQuery.mockResolvedValue({data: {localMoneyMethods: []}});
  let tree!: renderer.ReactTestRenderer;
  await act(async () => {tree = renderer.create(<ScanScreen />);});
  await act(async () => {scan('0002015802PE63040000');});
  expect(mockNavigate).not.toHaveBeenCalled();
  expect(Alert.alert).toHaveBeenCalledWith('Medio no disponible', expect.any(String), expect.any(Array), {cancelable: false});
  await act(async () => {scan('0002015802PE63040000');});
  expect(Alert.alert).toHaveBeenCalledTimes(1);
  await act(async () => {(Alert.alert as jest.Mock).mock.calls[0][2][0].onPress();});
  await act(async () => {scan('0002015802PE63040000');});
  expect(Alert.alert).toHaveBeenCalledTimes(2);
  await act(async () => tree.unmount());
});

it('routes a gallery QR through the same review flow', async () => {
  const raw = '0002015802BR63040000';
  (launchImageLibrary as jest.Mock).mockResolvedValue({assets: [{uri: 'file:///qr.png'}]});
  (RNQRGenerator.detect as jest.Mock).mockResolvedValue({values: [raw]});
  mockQuery.mockResolvedValue({data: {localMoneyMethods: [{id: 'br_qr', status: 'live'}]}});
  let tree!: renderer.ReactTestRenderer;
  await act(async () => {tree = renderer.create(<ScanScreen />);});
  await act(async () => {
    await tree.root.findAllByProps({accessibilityLabel: 'Elegir un código QR desde la galería'})[0].props.onPress();
  });
  expect(mockNavigate).toHaveBeenCalledWith('LocalSend', {methodId: 'br_qr', scannedQr: raw});
  await act(async () => tree.unmount());
});

it('does not start a local payment from collect mode', async () => {
  mockMode = 'cobrar';
  let tree!: renderer.ReactTestRenderer;
  await act(async () => {tree = renderer.create(<ScanScreen />);});
  await act(async () => {scan('0002015802BR63040000');});
  expect(mockQuery).not.toHaveBeenCalled();
  expect(mockNavigate).not.toHaveBeenCalled();
  expect(Alert.alert).toHaveBeenCalledWith('QR para pagar', expect.any(String), expect.any(Array), {cancelable: false});
  await act(async () => tree.unmount());
});

it('ignores a late availability response after leaving Scan', async () => {
  let finish!: (value: any) => void;
  mockQuery.mockImplementationOnce(() => new Promise(resolve => {finish = resolve;}));
  let tree!: renderer.ReactTestRenderer;
  await act(async () => {tree = renderer.create(<ScanScreen />);});
  await act(async () => {scan('0002015802BR63040000');});
  await act(async () => tree.unmount());
  await act(async () => {finish({data: {localMoneyMethods: [{id: 'br_qr', status: 'live'}]}});});
  expect(mockNavigate).not.toHaveBeenCalled();
});

it.each(['needs_verification', 'needs_document'])('keeps the QR when routing to %s requirements', async status => {
  mockQuery.mockResolvedValue({data: {localMoneyMethods: [{id: 'br_qr', status}]}});
  let tree!: renderer.ReactTestRenderer;
  await act(async () => {tree = renderer.create(<ScanScreen />);});
  await act(async () => {scan('0002015802BR63040000');});
  expect(mockNavigate).toHaveBeenCalledWith('LocalSend', {methodId: 'br_qr', scannedQr: '0002015802BR63040000'});
  await act(async () => tree.unmount());
});

it('fails closed on a capability query error and lets the user retry after dismissal', async () => {
  mockQuery.mockRejectedValueOnce(new Error('offline'));
  let tree!: renderer.ReactTestRenderer;
  await act(async () => {tree = renderer.create(<ScanScreen />);});
  await act(async () => {scan('0002015802BR63040000');});
  expect(mockNavigate).not.toHaveBeenCalled();
  await act(async () => {(Alert.alert as jest.Mock).mock.calls[0][2][0].onPress();});
  mockQuery.mockResolvedValue({data: {localMoneyMethods: [{id: 'br_qr', status: 'live'}]}});
  await act(async () => {scan('0002015802BR63040000');});
  expect(mockNavigate).toHaveBeenCalledTimes(1);
  await act(async () => tree.unmount());
});

it('preserves the Confío invoice lookup', async () => {
  mockInvoice.mockResolvedValue({data: {getInvoice: {success: true, invoice: {id: 'invoice-1', createdByUser: {id: 'other'}}}}});
  let tree!: renderer.ReactTestRenderer;
  await act(async () => {tree = renderer.create(<ScanScreen />);});
  await act(async () => {scan('confio://pay/invoice-1');});
  expect(mockInvoice).toHaveBeenCalledWith({variables: {invoiceId: 'invoice-1'}});
  expect(mockNavigate).toHaveBeenCalledWith('PaymentConfirmation', expect.any(Object));
  expect(mockQuery).not.toHaveBeenCalled();
  await act(async () => tree.unmount());
});

it('does not treat an embedded verification link in a malformed EMV code as a Confío QR', async () => {
  let tree!: renderer.ReactTestRenderer;
  await act(async () => {tree = renderer.create(<ScanScreen />);});
  await act(async () => {scan('000201verify/attacker');});
  expect(Alert.alert).toHaveBeenCalledWith('Código QR no compatible', expect.any(String), expect.any(Array), {cancelable: false});
  expect(mockNavigate).not.toHaveBeenCalled();
  expect(mockInvoice).not.toHaveBeenCalled();
  expect(mockQuery).not.toHaveBeenCalled();
  await act(async () => tree.unmount());
});
