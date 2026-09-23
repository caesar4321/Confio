import React from 'react';
import renderer, {act} from 'react-test-renderer';
import {Text, TextInput, TouchableOpacity} from 'react-native';
import Clipboard from '@react-native-clipboard/clipboard';

const mockNavigate = jest.fn();
const mockRefetch = jest.fn().mockResolvedValue({});
const mockRecheck = jest.fn();
const mockPrepareBridge = jest.fn();
const mockPayoutQuote = jest.fn();
const mockResolve = jest.fn();
let mockBridgeSequence = 0;
let mockAccountStatus = 'none';
let mockMethodId = 'co_breb';
let mockAccounts: any[] = [];
let mockLimits: any = undefined;
let mockExtraMethods: any[] = [];
let mockInitialQr: string | undefined;
jest.mock('react-native-vector-icons/Feather', () => 'Icon');
jest.mock('@apollo/client', () => ({useQuery: (query: string) => ({
  data: query === 'methods' ? {localMoneyMethods: [{id: mockMethodId, country: 'CO', asset: 'COP', status: 'live', accountStatus: mockAccountStatus}, ...mockExtraMethods]}
    : query === 'saved' ? {localSavedDestinations: [{id: 'recipient', holderName: 'Ana', label: 'Llave', verification: 'verified'}]}
    : query === 'address' ? {myRampAddress: {isComplete: true}}
    : query === 'accounts' ? {myPaymentAccounts: mockAccounts}
    : query === 'limits' ? {localMoneyLimits: mockLimits} : {},
  refetch: mockRefetch,
})}));
// useFocusEffect is a no-op here: the refresh-on-return is not what this test checks.
jest.mock('@react-navigation/native', () => ({useNavigation: () => ({navigate: mockNavigate}),
  useRoute: () => ({params: {methodId: mockMethodId, scannedQr: mockInitialQr}}), useFocusEffect: () => {}}));
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
  fetchPayoutQuote: (...args: any[]) => mockPayoutQuote(...args),
  resolveLocalDestination: (...args: any[]) => mockResolve(...args),
}));
import Screen from '../LocalSendScreen';

beforeEach(() => {
  jest.clearAllMocks(); mockAccountStatus = 'none'; mockMethodId = 'co_breb';
  mockPrepareBridge.mockReset(); mockBridgeSequence = 0;
  mockPayoutQuote.mockReset();
  mockResolve.mockReset();
  mockAccounts = []; mockLimits = undefined;
  mockExtraMethods = [];
  mockInitialQr = undefined;
  mockRecheck.mockImplementation(async (id: string) => ({id, holderName: 'Ana', label: 'Llave', verification: 'verified'}));
});

it('retains the main scanner QR through account opening and resolves it only once', async () => {
  mockMethodId = 'br_qr'; mockInitialQr = 'gateway-qr';
  mockResolve.mockResolvedValue({id: 'qr', methodId: 'br_qr', verification: 'not_checked', label: 'QR'});
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<Screen />); });
  expect(mockResolve).not.toHaveBeenCalled();
  mockAccountStatus = 'active';
  await act(async () => { tree.update(<Screen />); });
  expect(mockResolve).toHaveBeenCalledWith('br_qr', 'gateway-qr', 20000);
  await act(async () => { tree.update(<Screen />); });
  expect(mockResolve).toHaveBeenCalledTimes(1);
  expect(mockPrepareBridge).not.toHaveBeenCalled();
  await act(async () => tree.unmount());
});

it.each([['br_pix', 'br_qr'], ['ar_cvu', 'ar_qr']])('offers a labelled QR entry on %s and resolves through %s', async (methodId, qrId) => {
  mockMethodId = methodId;
  mockAccountStatus = 'active';
  mockExtraMethods = [{id: qrId, country: 'CO', asset: 'COP', status: 'live'}];
  mockResolve.mockResolvedValue({id: 'qr-recipient', methodId: qrId, verification: 'not_checked', label: 'QR · Loja'});
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<Screen />); });
  const button = tree.root.findAllByType(TouchableOpacity).find(n => n.props.accessibilityLabel === 'Escanear QR');
  expect(button).toBeDefined();
  expect(button!.findAllByType(Text).some(n => n.props.children === 'QR')).toBe(true);
  await act(async () => { button!.props.onPress(); });
  expect(tree.root.findByType('Scanner' as any).props.visible).toBe(true);
  await act(async () => { tree.root.findByType('Scanner' as any).props.onScanned('raw-emv'); });
  expect(mockResolve).toHaveBeenCalledWith(qrId, 'raw-emv', 20000);
  await act(async () => tree.unmount());
});

it('does not expose a QR rail that the server marks unavailable', async () => {
  mockMethodId = 'br_pix'; mockAccountStatus = 'active';
  mockExtraMethods = [{id: 'br_qr', country: 'CO', status: 'unavailable'}];
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<Screen />); });
  expect(tree.root.findAllByType(TouchableOpacity).some(n => n.props.accessibilityLabel === 'Escanear QR')).toBe(false);
  await act(async () => tree.unmount());
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

it.each(['not_checked', 'unverified'])('handles %s recipients without conflating skipped and failed checks', async verification => {
  mockAccountStatus = 'active';
  mockAccounts = [
    {provider: 'infinia', asset: 'COP', status: 'active'},
    {provider: 'infinia', asset: 'USDC_POL', status: 'active', fundingInstructions: [{kind: 'crypto_address', status: 'active'}]},
  ];
  mockRecheck.mockResolvedValueOnce({id: 'recipient', holderName: '', label: 'Bre-B · @maria.rod', verification});
  let tree!: renderer.ReactTestRenderer;
  await act(async () => {tree = renderer.create(<Screen />);});
  try {
    const saved = tree.root.findAllByType(TouchableOpacity).find(node =>
      node.findAllByType(Text).some(text => text.props.children === 'Ana'))!;
    await act(async () => {saved.props.onPress();});
    await act(async () => {tree.root.findAllByType(TextInput).find(node => node.props.placeholder === '0')!.props.onChangeText('5');});
    const texts = tree.root.findAllByType(Text).map(node => node.props.children);
    expect(texts).not.toContain('Titular sin verificar');
    expect(texts).not.toContain('Titular verificado');
    expect(tree.root.findByType('ActionBar' as any).props.primaryDisabled).toBe(verification === 'unverified');
    if (verification === 'not_checked') {
      expect(texts).toContain('Bre-B · @maria.rod');
      expect(texts).not.toContain('No pudimos verificar el titular');
      expect(texts).not.toContain('Revisé los datos y son correctos');
    } else {
      expect(texts).toContain('No pudimos verificar el titular');
      expect(texts).toContain('Revisé los datos y son correctos');
    }
  } finally {
    await act(async () => tree.unmount());
  }
});

it.each(['Llave Bre-B · @maria.rod', 'QR · Kiosco · ABC1234567'])(
  'reviews the exact destination %s and invalidates review when it is edited', async label => {
    mockAccountStatus = 'active';
    mockAccounts = [
      {internalId: 'local', provider: 'infinia', asset: 'COP', status: 'active'},
      {internalId: 'crypto', provider: 'infinia', asset: 'USDC_POL', status: 'active',
        fundingInstructions: [{internalId: 'instruction', kind: 'crypto_address', status: 'active'}]},
    ];
    mockRecheck.mockResolvedValueOnce({id: 'recipient', holderName: '', label, verification: 'not_checked'});
    mockPrepareBridge.mockResolvedValueOnce({internalId: 'bridge', feeUnits: '0', deadline: '9999999999'});
    mockPayoutQuote.mockResolvedValue({minimumTarget: '19000', asset: 'COP', rate: '3800'});
    let tree!: renderer.ReactTestRenderer;
    await act(async () => {tree = renderer.create(<Screen />);});
    try {
      const saved = tree.root.findAllByType(TouchableOpacity).find(node =>
        node.findAllByType(Text).some(text => text.props.children === 'Ana'))!;
      await act(async () => {saved.props.onPress();});
      await act(async () => {tree.root.findAllByType(TextInput).find(node => node.props.placeholder === '0')!.props.onChangeText('5');});
      await act(async () => {await tree.root.findByType('ActionBar' as any).props.onPrimaryPress();});
      const texts = () => tree.root.findAllByType(Text).map(node => node.props.children);
      expect(texts()).toContain('Revisión final');
      expect(texts()).toContain(label);
      expect(texts()).not.toContain('Titular sin verificar');
      expect(texts()).not.toContain('Titular verificado');
      expect(tree.root.findByType('ActionBar' as any).props.primaryLabel).toBe('Confirmar envío');
      expect(mockPayoutQuote).toHaveBeenCalledWith('recipient', {bridgeId: 'bridge'});
      await act(async () => {tree.root.findAllByType(TextInput).find(node => node.props.placeholder !== '0')!.props.onChangeText('@otra.persona');});
      expect(texts()).not.toContain('Revisión final');
      expect(tree.root.findByType('ActionBar' as any).props.primaryLabel).toBe('Continuar');
      expect(mockResolve).not.toHaveBeenCalled();
    } finally {
      await act(async () => tree.unmount());
    }
  },
);

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

it.each(['typed', 'pasted', 'scanned'])('can continue directly with a %s recipient', async source => {
  mockAccountStatus = 'active';
  mockAccounts = [
    {provider: 'infinia', asset: 'COP', status: 'active'},
    {provider: 'infinia', asset: 'USDC_POL', status: 'active',
      fundingInstructions: [{internalId: 'instruction', kind: 'crypto_address', status: 'active'}]},
  ];
  mockResolve.mockResolvedValue({id: 'new-recipient', holderName: '', label: 'Llave Bre-B · @maria', verification: 'not_checked'});
  mockPrepareBridge.mockResolvedValue({internalId: 'bridge', feeUnits: '0', deadline: '9999999999'});
  mockPayoutQuote.mockResolvedValue({minimumTarget: '19000', asset: 'COP', rate: '3800'});
  let tree!: renderer.ReactTestRenderer;
  await act(async () => {tree = renderer.create(<Screen />);});
  try {
    await act(async () => {
      if (source === 'typed') {
        tree.root.findAllByType(TextInput).find(node => node.props.placeholder !== '0')!.props.onChangeText('@maria');
      } else if (source === 'pasted') {
        (Clipboard.getString as jest.Mock).mockResolvedValueOnce('@maria');
        await tree.root.findAllByType(TouchableOpacity).find(node =>
          node.props.accessibilityLabel === 'Pegar desde el portapapeles')!.props.onPress();
      } else {
        tree.root.findByType('Scanner' as any).props.onScanned('qr-payload');
      }
      tree.root.findAllByType(TextInput).find(node => node.props.placeholder === '0')!.props.onChangeText('5');
    });
    const texts = () => tree.root.findAllByType(Text).map(node => node.props.children);
    expect(texts()).not.toContain('Revisar');
    expect(texts()).not.toContain('Revisando los datos…');
    // Paste and scan are finished entries and prepare the recipient at once;
    // typing (still in the field) waits for leaving it or Continue.
    expect(mockResolve).toHaveBeenCalledTimes(source === 'typed' ? 0 : 1);
    expect(tree.root.findByType('ActionBar' as any).props.primaryLoading).toBe(false);
    expect(tree.root.findByType('ActionBar' as any).props.primaryDisabled).toBe(false);
    await act(async () => {await tree.root.findByType('ActionBar' as any).props.onPrimaryPress();});
    expect(mockResolve).toHaveBeenCalledTimes(1);
    expect(mockResolve).toHaveBeenCalledWith('co_breb', source === 'scanned' ? 'qr-payload' : '@maria', 20000);
    expect(texts()).toContain('Revisión final');
  } finally {
    await act(async () => tree.unmount());
  }
});

const activePair = () => {
  mockAccountStatus = 'active';
  mockAccounts = [
    {provider: 'infinia', asset: 'COP', status: 'active'},
    {provider: 'infinia', asset: 'USDC_POL', status: 'active',
      fundingInstructions: [{internalId: 'instruction', kind: 'crypto_address', status: 'active'}]},
  ];
};

it.each(['leaving the field', 'keyboard Done', 'paste'])('typing a recipient then %s shows it and its estimate', async source => {
  jest.useFakeTimers({doNotFake: ['nextTick', 'queueMicrotask', 'setImmediate']});
  activePair();
  mockResolve.mockResolvedValue({id: 'new-recipient', holderName: '', label: 'Llave Bre-B · @maria', verification: 'not_checked'});
  mockPayoutQuote.mockResolvedValue({targetAmount: '19000', minimumTarget: '19000', asset: 'COP', rate: '3800'});
  let tree!: renderer.ReactTestRenderer;
  await act(async () => {tree = renderer.create(<Screen />);});
  try {
    const input = () => tree.root.findAllByType(TextInput).find(node => node.props.placeholder !== '0')!;
    const texts = () => tree.root.findAllByType(Text).map(node => node.props.children);
    await act(async () => {
      if (source === 'paste') {
        (Clipboard.getString as jest.Mock).mockResolvedValueOnce('@maria');
        await tree.root.findAllByType(TouchableOpacity).find(node =>
          node.props.accessibilityLabel === 'Pegar desde el portapapeles')!.props.onPress();
      } else input().props.onChangeText('@maria');
    });
    if (source !== 'paste') {
      // Never per keystroke: each preparation saves a recipient on the server.
      expect(mockResolve).not.toHaveBeenCalled();
      await act(async () => {
        if (source === 'keyboard Done') input().props.onSubmitEditing();
        else input().props.onBlur();
      });
    }
    expect(mockResolve).toHaveBeenCalledTimes(1);
    expect(mockResolve).toHaveBeenCalledWith('co_breb', '@maria', 20000);
    expect(texts()).not.toContain('Usar estos datos');
    expect(texts()).toContain('Llave Bre-B · @maria');
    expect(texts()).toContain('Confirma que estos son los datos que te compartió quien recibe.');
    expect(mockPrepareBridge).not.toHaveBeenCalled();
    await act(async () => {
      tree.root.findAllByType(TextInput).find(node => node.props.placeholder === '0')!.props.onChangeText('5');
    });
    await act(async () => {jest.advanceTimersByTime(600);});
    expect(mockPayoutQuote).toHaveBeenCalledWith('new-recipient', {amount: '5'});
    await act(async () => {await Promise.resolve();});
    expect(texts()).toContain('Estimado que recibe');
    expect(tree.root.findByType('ActionBar' as any).props.primaryDisabled).toBe(false);
    await act(async () => {input().props.onChangeText('@otra');});
    expect(texts()).not.toContain('Llave Bre-B · @maria');
    // Leaving the field unchanged after it was prepared asks nothing again.
    await act(async () => {input().props.onChangeText('@maria'); input().props.onBlur();});
    await act(async () => {input().props.onBlur();});
    expect(mockResolve).toHaveBeenCalledTimes(2);
  } finally {
    await act(async () => tree.unmount());
    jest.useRealTimers();
  }
});

it('Continue tapped while leaving the field shares the recipient request', async () => {
  activePair();
  let finish!: (row: any) => void;
  mockResolve.mockReturnValue(new Promise(resolve => {finish = resolve;}));
  mockPrepareBridge.mockResolvedValue({internalId: 'bridge', feeUnits: '0', deadline: '9999999999'});
  mockPayoutQuote.mockResolvedValue({minimumTarget: '19000', asset: 'COP', rate: '3800'});
  let tree!: renderer.ReactTestRenderer;
  await act(async () => {tree = renderer.create(<Screen />);});
  try {
    const input = () => tree.root.findAllByType(TextInput).find(node => node.props.placeholder !== '0')!;
    await act(async () => {
      input().props.onChangeText('@maria');
      tree.root.findAllByType(TextInput).find(node => node.props.placeholder === '0')!.props.onChangeText('5');
    });
    // Same render: the blur and the Continue press land together.
    const onContinue = tree.root.findByType('ActionBar' as any).props.onPrimaryPress;
    let continuing!: Promise<void>;
    await act(async () => {input().props.onBlur(); continuing = onContinue();});
    await act(async () => {finish({id: 'new-recipient', holderName: '', label: 'Llave', verification: 'not_checked'}); await continuing;});
    expect(mockResolve).toHaveBeenCalledTimes(1);
    expect(tree.root.findAllByType(Text).map(node => node.props.children)).toContain('Revisión final');
  } finally {
    await act(async () => tree.unmount());
  }
});

it('a failed recipient preparation is asked again on Continue', async () => {
  activePair();
  mockResolve.mockRejectedValueOnce(new Error('Sin conexión'))
    .mockResolvedValue({id: 'new-recipient', holderName: '', label: 'Llave', verification: 'not_checked'});
  mockPrepareBridge.mockResolvedValue({internalId: 'bridge', feeUnits: '0', deadline: '9999999999'});
  mockPayoutQuote.mockResolvedValue({minimumTarget: '19000', asset: 'COP', rate: '3800'});
  let tree!: renderer.ReactTestRenderer;
  await act(async () => {tree = renderer.create(<Screen />);});
  try {
    const input = () => tree.root.findAllByType(TextInput).find(node => node.props.placeholder !== '0')!;
    await act(async () => {
      input().props.onChangeText('@maria');
      tree.root.findAllByType(TextInput).find(node => node.props.placeholder === '0')!.props.onChangeText('5');
    });
    await act(async () => {input().props.onBlur();});
    expect(tree.root.findAllByType(Text).map(node => node.props.children)).toContain('Sin conexión');
    await act(async () => {await tree.root.findByType('ActionBar' as any).props.onPrimaryPress();});
    expect(mockResolve).toHaveBeenCalledTimes(2);
    expect(tree.root.findAllByType(Text).map(node => node.props.children)).toContain('Revisión final');
  } finally {
    await act(async () => tree.unmount());
  }
});

it.each(['timeout', 'edit'])('ignores late recipient responses after %s', async reason => {
  jest.useFakeTimers({doNotFake: ['nextTick', 'queueMicrotask', 'setImmediate']});
  mockAccountStatus = 'active';
  mockAccounts = [
    {provider: 'infinia', asset: 'COP', status: 'active'},
    {provider: 'infinia', asset: 'USDC_POL', status: 'active',
      fundingInstructions: [{internalId: 'instruction', kind: 'crypto_address', status: 'active'}]},
  ];
  let finish!: (row: any) => void;
  mockResolve.mockReturnValue(new Promise(resolve => {finish = resolve;}));
  let tree!: renderer.ReactTestRenderer;
  await act(async () => {tree = renderer.create(<Screen />);});
  try {
    await act(async () => {
      tree.root.findAllByType(TextInput).find(node => node.props.placeholder !== '0')!.props.onChangeText('@maria');
      tree.root.findAllByType(TextInput).find(node => node.props.placeholder === '0')!.props.onChangeText('5');
    });
    let continuing!: Promise<void>;
    await act(async () => {continuing = tree.root.findByType('ActionBar' as any).props.onPrimaryPress();});
    expect(tree.root.findByType('ActionBar' as any).props.primaryLoading).toBe(true);
    if (reason === 'edit') {
      await act(async () => {
        tree.root.findAllByType(TextInput).find(node => node.props.placeholder !== '0')!.props.onChangeText('@otra');
      });
    } else {
      await act(async () => {jest.advanceTimersByTime(20000); await continuing;});
    }
    expect(tree.root.findByType('ActionBar' as any).props.primaryLoading).toBe(false);
    if (reason === 'timeout') {
      expect(tree.root.findAllByType(Text).map(node => node.props.children))
        .toContain('No pudimos preparar el destinatario. Intenta de nuevo.');
    }
    await act(async () => {finish({id: 'late', verification: 'not_checked', label: 'Late recipient'}); await continuing;});
    expect(mockPrepareBridge).not.toHaveBeenCalled();
    expect(tree.root.findAllByType(Text).map(node => node.props.children)).not.toContain('Late recipient');
  } finally {
    await act(async () => tree.unmount());
    jest.useRealTimers();
  }
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


it('allows continuing above the monthly allowance while offering EDD', async () => {
  mockAccountStatus = 'active';
  mockLimits = {known: true, available: '0', limit: '10000', used: '10000', nearLimit: true};
  mockAccounts = [
    {provider: 'infinia', asset: 'COP', status: 'active'},
    {provider: 'infinia', asset: 'USDC_POL', status: 'active',
      fundingInstructions: [{kind: 'crypto_address', status: 'active'}]},
  ];
  let tree!: renderer.ReactTestRenderer;
  await act(async () => {tree = renderer.create(<Screen />);});
  const saved = tree.root.findAllByType(TouchableOpacity).find(node =>
    node.findAllByType(Text).some(text => text.props.children === 'Ana'))!;
  await act(async () => {await saved.props.onPress();});
  await act(async () => {tree.root.findAllByType(TextInput).find(node => node.props.placeholder === '0')!.props.onChangeText('5');});
  expect(tree.root.findByType('ActionBar' as any).props.primaryDisabled).toBe(false);
  const edd = tree.root.findAllByType(TouchableOpacity).find(node =>
    node.findAllByType(Text).some(text => text.props.children === 'Aumentar mi límite mensual'))!;
  await act(async () => {edd.props.onPress();});
  expect(mockNavigate).toHaveBeenCalledWith('LocalLimitIncrease');
  await act(async () => tree.unmount());
});


it.each([
  ['032180000118359719', true],
  ['032-180-000118359719', true],
  ['abc032180000118359719', false],
  ['032180000118359718', false],
])('automatically prepares only valid numeric recipient entries: %s', async (entry, accepted) => {
  mockMethodId = 'mx_clabe';
  mockResolve.mockResolvedValue({id: 'mx-recipient', holderName: 'Ana', label: 'CLABE', verification: 'verified'});
  let tree!: renderer.ReactTestRenderer;
  await act(async () => {tree = renderer.create(<Screen />);});
  try {
    const input = tree.root.findAllByType(TextInput).find(node => node.props.placeholder !== '0')!;
    await act(async () => {input.props.onChangeText(entry);});
    expect(mockResolve).toHaveBeenCalledTimes(accepted ? 1 : 0);
    if (accepted) expect(mockResolve).toHaveBeenCalledWith('mx_clabe', '032180000118359719', 20000);
  } finally {
    await act(async () => tree.unmount());
  }
});


it('does not silently turn pasted text containing letters into a bank account', async () => {
  mockMethodId = 'mx_clabe';
  (Clipboard.getString as jest.Mock).mockResolvedValueOnce('abc032180000118359719');
  let tree!: renderer.ReactTestRenderer;
  await act(async () => {tree = renderer.create(<Screen />);});
  try {
    await act(async () => {
      await tree.root.findAllByType(TouchableOpacity).find(node =>
        node.props.accessibilityLabel === 'Pegar desde el portapapeles')!.props.onPress();
    });
    expect(mockResolve).not.toHaveBeenCalled();
    expect(tree.root.findAllByType(Text).map(node => node.props.children)).toContain(
      'Esa CLABE no es válida. Revisa los 18 dígitos.');
  } finally {
    await act(async () => tree.unmount());
  }
});
