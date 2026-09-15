import React from 'react';
import renderer, {act} from 'react-test-renderer';
import {Share, Text, TouchableOpacity} from 'react-native';
import Clipboard from '@react-native-clipboard/clipboard';

let mockAccount: any;
let mockMethodId = 'br_pix_receive';
let mockPassOk = true;
const mockRefetch = jest.fn().mockResolvedValue({});
const mockApollo = {query: jest.fn().mockResolvedValue({data: {infiniaJourneyDeposits: []}})};
jest.mock('react-native-vector-icons/Feather', () => 'Icon');
jest.mock('react-native-qrcode-svg', () => 'QRCode');
jest.mock('@react-native-clipboard/clipboard', () => ({setString: jest.fn()}));
jest.mock('@react-navigation/native', () => ({
  useNavigation: () => ({navigate: jest.fn(), goBack: jest.fn()}),
  useRoute: () => ({params: {methodId: mockMethodId}}), useFocusEffect: () => {},
}));
jest.mock('@apollo/client', () => ({useApolloClient: () => mockApollo, useQuery: (query: string) => ({
  data: query === 'account' ? {localReceiveAccount: mockAccount} : {}, refetch: mockRefetch,
})}));
jest.mock('../LocalAccountApplicationScreen', () => 'Application');
jest.mock('../../components/breb/BrebLocationGate', () => ({useBrebLocationPass: () => mockPassOk}));
jest.mock('../../components/ramps/RampActionBar', () => ({RampActionBar: 'ActionBar'}));
jest.mock('../../components/ramps/RampHero', () => ({RampHero: 'Hero'}));
jest.mock('../../components/ramps/RampReveal', () => ({RampReveal: ({children}: any) => children}));
jest.mock('../../components/ramps/RampStepHeader', () => ({RampStepHeader: 'Step'}));
jest.mock('../../utils/rampFlow', () => ({requestRampCriticalAuth: jest.fn()}));
jest.mock('../../services/infiniaJourney', () => ({createInfiniaJourney: jest.fn()}));
jest.mock('../../services/paymentBridge', () => ({bridgeRequestId: jest.fn()}));
jest.mock('../../services/localMoney', () => ({LOCAL_RECEIVE_ACCOUNT: 'account', LOCAL_MONEY_METHODS: 'methods',
  LOCAL_MONEY_LIMITS: 'limits', LOCAL_DEPOSITS: 'deposits', currencyName: () => 'reales', heldReasonCopy: jest.fn()}));
import Screen from '../LocalReceiveScreen';

beforeEach(() => {
  jest.clearAllMocks();
  mockMethodId = 'br_pix_receive';
  mockPassOk = true;
  mockAccount = {status: 'active', country: 'BR', asset: 'BRL', localAccountId: 'brl',
    instructionKind: 'qr', value: 'pix-copy-paste', holderName: 'Ana', institution: 'Bank', receiveThirdParty: 'enabled'};
});

it('renders and copies the exact Pix QR payload and labels shared data correctly', async () => {
  const share = jest.spyOn(Share, 'share').mockResolvedValue({action: Share.sharedAction});
  let tree!: renderer.ReactTestRenderer;
  try {
    await act(async () => {tree = renderer.create(<Screen />);});
    expect(tree.root.findByType('QRCode' as any).props.value).toBe('pix-copy-paste');
    expect(tree.root.findByType('Hero' as any).props.title).toBe('Tu código Pix');
    const button = (label: string) => tree.root.findAllByType(TouchableOpacity)
      .find(node => node.findAllByType(Text).some(t => t.props.children === label))!;
    await act(async () => {button('Copiar').props.onPress(); await button('Compartir').props.onPress();});
    expect(Clipboard.setString).toHaveBeenCalledWith('pix-copy-paste');
    expect(share).toHaveBeenCalledWith({message: expect.stringContaining('Tu código Pix Copia e Cola: pix-copy-paste')});
  } finally {
    if (tree) await act(async () => tree.unmount());
    share.mockRestore();
  }
});

it('keeps Pix key presentation for a key response', async () => {
  mockAccount = {...mockAccount, instructionKind: 'pix_key', value: 'ana@example.com'};
  let tree!: renderer.ReactTestRenderer;
  await act(async () => {tree = renderer.create(<Screen />);});
  expect(tree.root.findAllByType('QRCode' as any)).toHaveLength(0);
  expect(tree.root.findByType('Hero' as any).props.title).toBe('Tu propia chave Pix');
  await act(async () => tree.unmount());
});

it('withholds receiving controls for an unpaid opening', async () => {
  mockAccount = {...mockAccount, status: 'awaiting_payment', value: ''};
  let tree!: renderer.ReactTestRenderer;
  await act(async () => {tree = renderer.create(<Screen />);});
  expect(tree.root.findAllByType('QRCode' as any)).toHaveLength(0);
  expect(tree.root.findAllByType(Text).some(t => t.props.children === 'Copiar')).toBe(false);
  await act(async () => tree.unmount());
});

it('reloads the withheld Bre-B key when verification completes without another focus event', async () => {
  mockMethodId = 'co_breb_receive';
  mockPassOk = false;
  mockAccount = {...mockAccount, country: 'CO', asset: 'COP', value: ''};
  let tree!: renderer.ReactTestRenderer;
  try {
    await act(async () => {tree = renderer.create(<Screen />);});
    mockRefetch.mockClear();
    mockPassOk = true;
    await act(async () => {tree.update(<Screen />);});
    expect(mockRefetch).toHaveBeenCalledTimes(1);
  } finally {
    if (tree) await act(async () => tree.unmount());
  }
});
