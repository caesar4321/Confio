import React from 'react';
import renderer, {act} from 'react-test-renderer';
import {Text, TextInput, TouchableOpacity} from 'react-native';

const mockNavigate = jest.fn();
const mockRefetch = jest.fn().mockResolvedValue({});
const mockRecheck = jest.fn();
const mockPrepareBridge = jest.fn();
let mockBridgeSequence = 0;
let mockAccountStatus = 'none';
let mockAccounts: any[] = [];
jest.mock('react-native-vector-icons/Feather', () => 'Icon');
jest.mock('@apollo/client', () => ({useQuery: (query: string) => ({
  data: query === 'methods' ? {localMoneyMethods: [{id: 'co_breb', country: 'CO', asset: 'COP', status: 'live', accountStatus: mockAccountStatus}]}
    : query === 'saved' ? {localSavedDestinations: [{id: 'recipient', holderName: 'Ana', label: 'Llave', verification: 'verified'}]}
    : query === 'address' ? {myRampAddress: {isComplete: true}}
    : query === 'accounts' ? {myPaymentAccounts: mockAccounts} : {},
  refetch: mockRefetch,
})}));
// useFocusEffect is a no-op here: the refresh-on-return is not what this test checks.
jest.mock('@react-navigation/native', () => ({useNavigation: () => ({navigate: mockNavigate}),
  useRoute: () => ({params: {methodId: 'co_breb'}}), useFocusEffect: () => {}}));
// The location gate has its own screen; here the person is already confirmed in Colombia.
jest.mock('../../components/breb/BrebLocationGate', () => ({BrebLocationGate: ({children}: any) => children}));
jest.mock('../../services/brebLocation', () => ({isBrebLocationFailure: (error: any) => Boolean(error?.brebLocation)}));
jest.mock('../../apollo/queries', () => ({GET_MY_RAMP_ADDRESS: 'address'}));
jest.mock('../../contexts/AccountContext', () => ({useAccount: () => ({activeAccount: {type: 'personal'}})}));
jest.mock('../../hooks/useSavingsPortfolio', () => ({useSavingsPortfolio: () => ({savings: {balanceUsd: 20}, cusdBalanceUsd: 30, usdtBalanceUsd: 100})}));
jest.mock('../../components/PaymentQrScannerModal', () => ({PaymentQrScannerModal: 'Scanner'}));
jest.mock('../../components/ramps/RampActionBar', () => ({RampActionBar: 'ActionBar'}));
jest.mock('../../components/ramps/RampHero', () => ({RampHero: 'Hero'}));
jest.mock('../../components/ramps/RampReveal', () => ({RampReveal: 'Reveal'}));
jest.mock('../../components/ramps/RampStepHeader', () => ({RampStepHeader: 'Step'}));
jest.mock('../../utils/rampFlow', () => ({requestRampCriticalAuth: jest.fn()}));
jest.mock('../../services/infiniaJourney', () => ({createInfiniaJourney: jest.fn()}));
jest.mock('../../services/paymentBridge', () => ({
  preparePaymentBridge: (...args: any[]) => mockPrepareBridge(...args),
  bridgeRequestId: () => `request-${++mockBridgeSequence}`,
}));
jest.mock('../LocalAccountFundingScreen', () => ({bridgeAmount: jest.fn()}));
jest.mock('../../services/localMoney', () => ({
  LOCAL_MONEY_METHODS: 'methods', LOCAL_MONEY_ACCOUNTS: 'accounts', LOCAL_MONEY_LIMITS: 'limits', LOCAL_SAVED_DESTINATIONS: 'saved',
  currencyName: () => 'pesos',
  // Picking a saved recipient re-checks it on the server; here it is still current.
  recheckLocalDestination: (id: string) => mockRecheck(id),
}));
import Screen from '../LocalSendScreen';

beforeEach(() => {
  jest.clearAllMocks(); mockAccountStatus = 'none';
  mockPrepareBridge.mockReset(); mockBridgeSequence = 0;
  mockAccounts = [];
  mockRecheck.mockImplementation(async (id: string) => ({id, holderName: 'Ana', label: 'Llave', verification: 'verified'}));
});

it('replaces a rejected fee quote but retains the request after network uncertainty', async () => {
  mockAccountStatus = 'active';
  mockAccounts = [
    {provider: 'infinia', asset: 'COP', status: 'active'},
    {provider: 'infinia', asset: 'USDC_POL', status: 'active', fundingInstructions: [
      {internalId: 'instruction', kind: 'crypto_address', status: 'active'}]},
  ];
  mockPrepareBridge.mockRejectedValueOnce(Object.assign(new Error('Fee changed'), {quoteRefreshRequired: true}))
    .mockRejectedValue(new Error('Network timeout'));
  let tree!: renderer.ReactTestRenderer;
  await act(async () => {tree = renderer.create(<Screen />);});
  const saved = tree.root.findAllByType(TouchableOpacity).find(node =>
    node.findAllByType(Text).some(text => text.props.children === 'Ana'))!;
  await act(async () => {await saved.props.onPress();});
  await act(async () => {tree.root.findAllByType(TextInput).find(node => node.props.placeholder === '0')!.props.onChangeText('50');});
  for (let attempt = 0; attempt < 3; attempt++) {
    await act(async () => {await tree.root.findByType('ActionBar' as any).props.onPrimaryPress();});
  }
  expect(mockPrepareBridge.mock.calls.map(call => call[3])).toEqual(['request-1', 'request-2', 'request-2']);
  expect(mockPrepareBridge.mock.calls.every(call => call[1] === '50')).toBe(true);
  await act(async () => tree.unmount());
});

it('shows cUSD plus savings as spendable, excluding raw USDT', async () => {
  mockAccountStatus = 'active';
  let tree!: renderer.ReactTestRenderer;
  await act(async () => {tree = renderer.create(<Screen />);});
  const saved = tree.root.findAllByType(TouchableOpacity).find(node =>
    node.findAllByType(Text).some(text => text.props.children === 'Ana'))!;
  await act(async () => {saved.props.onPress();});
  const labels = tree.root.findAllByType(Text).map(node => ([] as any[]).concat(node.props.children).join(''));
  expect(labels.filter(label => label.startsWith('Saldo disponible:'))).toEqual(['Saldo disponible: US$50,00']);
  await act(async () => tree.unmount());
});

it('offers a retry, not a disabled send or another fee, when paid account data is missing', async () => {
  mockAccountStatus = 'active';
  let tree!: renderer.ReactTestRenderer;
  await act(async () => {tree = renderer.create(<Screen />);});
  const action = tree.root.findByType('ActionBar' as any);
  expect(action.props.primaryLabel).toBe('Actualizar cuenta');
  expect(action.props.primaryDisabled).toBe(false);
  expect(tree.root.findAllByType(Text).map(node => node.props.children)).not.toContain(
    'Elige a quién envías e ingresa el monto para ver el estimado.');
  await act(async () => {await action.props.onPrimaryPress();});
  expect(mockRefetch).toHaveBeenCalled();
  expect(mockNavigate).not.toHaveBeenCalled();
  mockAccounts = [
    {provider: 'infinia', asset: 'COP', status: 'active'},
    {provider: 'infinia', asset: 'USDC_POL', status: 'active',
      fundingInstructions: [{kind: 'crypto_address', status: 'active'}]},
  ];
  await act(async () => {tree.update(<Screen />);});
  expect(tree.root.findByType('ActionBar' as any).props.primaryLabel).toBe('Continuar');
  const saved = tree.root.findAllByType(TouchableOpacity).find(node =>
    node.findAllByType(Text).some(text => text.props.children === 'Ana'))!;
  await act(async () => {await saved.props.onPress();});
  await act(async () => {tree.root.findAllByType(TextInput).find(node => node.props.placeholder === '0')!.props.onChangeText('5');});
  expect(tree.root.findByType('ActionBar' as any).props.primaryDisabled).toBe(false);
  await act(async () => tree.unmount());
});

it('a failed saved-recipient request cannot become an unverified-holder override', async () => {
  mockAccountStatus = 'active';
  mockAccounts = [
    {provider: 'infinia', asset: 'COP', status: 'active'},
    {provider: 'infinia', asset: 'USDC_POL', status: 'active', fundingInstructions: [{kind: 'crypto_address', status: 'active'}]},
  ];
  mockRecheck.mockRejectedValueOnce(new Error('Network request failed'));
  let tree!: renderer.ReactTestRenderer;
  await act(async () => {tree = renderer.create(<Screen />);});
  const saved = tree.root.findAllByType(TouchableOpacity).find(node =>
    node.findAllByType(Text).some(text => text.props.children === 'Ana'))!;
  await act(async () => {saved.props.onPress();});
  const texts = () => tree.root.findAllByType(Text).map(node => node.props.children);
  expect(texts()).not.toContain('Revisé los datos y son correctos');
  expect(tree.root.findByType('ActionBar' as any).props.primaryDisabled).toBe(true);
  const retry = tree.root.findAllByType(TouchableOpacity).find(node =>
    node.findAllByType(Text).some(text => text.props.children === 'Intentar de nuevo'))!;
  await act(async () => {retry.props.onPress();});
  expect(texts()).toContain('Titular verificado');
  expect(texts()).not.toContain('Revisé los datos y son correctos');
  expect(mockRecheck).toHaveBeenCalledTimes(2);
  await act(async () => {tree.unmount();});
});

it('a failed location check on a saved recipient says why and offers the location screen', async () => {
  mockAccountStatus = 'active';
  mockAccounts = [
    {provider: 'infinia', asset: 'COP', status: 'active'},
    {provider: 'infinia', asset: 'USDC_POL', status: 'active', fundingInstructions: [{kind: 'crypto_address', status: 'active'}]},
  ];
  mockRecheck.mockRejectedValueOnce(Object.assign(new Error('Permite la ubicación precisa para usar Bre-B.'), {brebLocation: true}));
  let tree!: renderer.ReactTestRenderer;
  await act(async () => {tree = renderer.create(<Screen />);});
  const saved = tree.root.findAllByType(TouchableOpacity).find(node =>
    node.findAllByType(Text).some(text => text.props.children === 'Ana'))!;
  await act(async () => {saved.props.onPress();});
  const texts = () => tree.root.findAllByType(Text).map(node => node.props.children);
  expect(texts()).toContain('Permite la ubicación precisa para usar Bre-B.');
  expect(tree.root.findByType('ActionBar' as any).props.primaryDisabled).toBe(true);
  const confirm = tree.root.findAllByType(TouchableOpacity).find(node =>
    node.findAllByType(Text).some(text => text.props.children === 'Confirmar ubicación'))!;
  await act(async () => {confirm.props.onPress();});
  expect(mockNavigate).toHaveBeenCalledWith('BrebLocationCheck');
  await act(async () => {tree.unmount();});
});

it.each([['none', 'Solicitar cuenta'], ['awaiting_payment', 'Completar apertura']])(
  'an account that is %s opens on its own application screen', async (status, label) => {
    mockAccountStatus = status;
    let tree!: renderer.ReactTestRenderer;
    await act(async () => {tree = renderer.create(<Screen />);});
    const saved = tree.root.findAllByType(TouchableOpacity).find(node =>
      node.findAllByType(Text).some(text => text.props.children === 'Ana'))!;
    await act(async () => {saved.props.onPress();});
    // Choosing a recipient never starts an opening (or a fee prompt) by itself.
    expect(mockNavigate).not.toHaveBeenCalled();
    const action = tree.root.findByType('ActionBar' as any);
    expect(action.props.primaryLabel).toBe(label);
    expect(action.props.primaryDisabled).toBe(false);
    await act(async () => {await action.props.onPrimaryPress();});
    expect(mockNavigate).toHaveBeenCalledWith('LocalAccountApplication', {methodId: 'co_breb'});
    await act(async () => {tree.unmount();});
  },
);

it.each(['none', 'awaiting_payment', 'provisioning'])('can manage a %s opening without a recipient', async status => {
  mockAccountStatus = status;
  let tree!: renderer.ReactTestRenderer;
  await act(async () => {tree = renderer.create(<Screen />);});
  try {
    const action = tree.root.findByType('ActionBar' as any);
    expect(action.props.primaryDisabled).toBe(false);
    await act(async () => {await action.props.onPrimaryPress();});
    expect(mockNavigate).toHaveBeenCalledWith('LocalAccountApplication', {methodId: 'co_breb'});
  } finally {
    await act(async () => tree.unmount());
  }
});
