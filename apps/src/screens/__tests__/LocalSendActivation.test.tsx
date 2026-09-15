import React from 'react';
import renderer, {act} from 'react-test-renderer';
import {Text, TouchableOpacity} from 'react-native';

const mockNavigate = jest.fn();
const mockRefetch = jest.fn().mockResolvedValue({});
const mockRecheck = jest.fn();
let mockAccountStatus = 'none';
jest.mock('react-native-vector-icons/Feather', () => 'Icon');
jest.mock('@apollo/client', () => ({useQuery: (query: string) => ({
  data: query === 'methods' ? {localMoneyMethods: [{id: 'co_breb', country: 'CO', asset: 'COP', status: 'live', accountStatus: mockAccountStatus}]}
    : query === 'saved' ? {localSavedDestinations: [{id: 'recipient', holderName: 'Ana', label: 'Llave', verification: 'verified'}]}
    : query === 'address' ? {myRampAddress: {isComplete: true}} : {},
  refetch: mockRefetch,
})}));
// useFocusEffect is a no-op here: the refresh-on-return is not what this test checks.
jest.mock('@react-navigation/native', () => ({useNavigation: () => ({navigate: mockNavigate}),
  useRoute: () => ({params: {methodId: 'co_breb'}}), useFocusEffect: () => {}}));
// The location gate has its own screen; here the person is already confirmed in Colombia.
jest.mock('../../components/breb/BrebLocationGate', () => ({BrebLocationGate: ({children}: any) => children}));
jest.mock('../../apollo/queries', () => ({GET_MY_RAMP_ADDRESS: 'address'}));
jest.mock('../../contexts/AccountContext', () => ({useAccount: () => ({activeAccount: {type: 'personal'}})}));
jest.mock('../../hooks/useSavingsPortfolio', () => ({useSavingsPortfolio: () => ({savings: {balanceUsd: 20}, usdtBalanceUsd: 0})}));
jest.mock('../../components/PaymentQrScannerModal', () => ({PaymentQrScannerModal: 'Scanner'}));
jest.mock('../../components/ramps/RampActionBar', () => ({RampActionBar: 'ActionBar'}));
jest.mock('../../components/ramps/RampHero', () => ({RampHero: 'Hero'}));
jest.mock('../../components/ramps/RampReveal', () => ({RampReveal: 'Reveal'}));
jest.mock('../../components/ramps/RampStepHeader', () => ({RampStepHeader: 'Step'}));
jest.mock('../../utils/rampFlow', () => ({requestRampCriticalAuth: jest.fn()}));
jest.mock('../../services/infiniaJourney', () => ({createInfiniaJourney: jest.fn()}));
jest.mock('../../services/paymentBridge', () => ({}));
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
  mockRecheck.mockImplementation(async (id: string) => ({id, holderName: 'Ana', label: 'Llave', verification: 'verified'}));
});

it('a failed saved-recipient request cannot become an unverified-holder override', async () => {
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
