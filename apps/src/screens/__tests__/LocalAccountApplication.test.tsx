import React from 'react';
import renderer, {act} from 'react-test-renderer';
import {Modal, Text, TouchableOpacity} from 'react-native';

const mockPay = jest.fn();
const mockApply = jest.fn();
const mockActivate = jest.fn();
const mockQuote = jest.fn();
const mockGoBack = jest.fn();
const mockAccountRefetch = jest.fn().mockResolvedValue({});
let mockRemovalPrevented = false;
let mockPassDeadline: number | null = null;
const mockPassListeners = new Set<() => void>();
let mockScope = 'user:account:1';
let mockMethod: any;
let mockAccounts: any[] = [];
let mockPassValid = true;
let mockMethodsError: any = null;
const mockMethodsRefetch = jest.fn().mockResolvedValue({});
jest.mock('react-native-vector-icons/Feather', () => 'Icon');
jest.mock('@react-native-clipboard/clipboard', () => ({setString: jest.fn()}));
jest.mock('@apollo/client', () => ({useQuery: (query: string) => ({
  data: query === 'methods' ? (mockMethodsError ? undefined : {localMoneyMethods: [mockMethod]})
    : query === 'address' ? {myRampAddress: {isComplete: true}} : {},
  error: query === 'methods' ? mockMethodsError : undefined,
  loading: false,
  refetch: query === 'methods' ? mockMethodsRefetch : jest.fn().mockResolvedValue({}),
})}));
jest.mock('@react-navigation/native', () => ({
  useNavigation: () => ({navigate: jest.fn(), goBack: mockGoBack, canGoBack: () => true, replace: jest.fn()}),
  usePreventRemove: (prevent: boolean) => {mockRemovalPrevented = prevent;},
  useRoute: () => ({params: {methodId: mockMethod.id}}),
  useFocusEffect: () => {},
}));
jest.mock('../../apollo/queries', () => ({GET_MY_RAMP_ADDRESS: 'address'}));
jest.mock('../../contexts/AccountContext', () => ({useAccount: () => ({activeAccount: {type: 'personal'}})}));
jest.mock('../../components/breb/BrebLocationGate', () => ({useBrebLocationScope: () => mockScope}));
jest.mock('../../hooks/useLocalPaymentAccounts', () => ({
  useLocalPaymentAccounts: () => ({accounts: mockAccounts, refetch: mockAccountRefetch}),
}));
jest.mock('../../components/ramps/RampActionBar', () => ({RampActionBar: 'ActionBar'}));
jest.mock('../../components/ramps/RampHero', () => ({RampHero: 'Hero'}));
jest.mock('../../components/ramps/RampReveal', () => ({RampReveal: ({children}: any) => children}));
jest.mock('../../components/ramps/RampStepHeader', () => ({RampStepHeader: 'Step'}));
jest.mock('../../services/brebLocation', () => ({
  applyCobreBreb: (...args: any[]) => mockApply(...args),
  brebLocationPassValid: () => mockPassValid && (mockPassDeadline === null || Date.now() < mockPassDeadline),
  brebLocationPassRemainingMs: () => mockPassDeadline === null ? 60000 : Math.max(0, mockPassDeadline - Date.now()),
  onBrebLocationPassChange: (listener: () => void) => {
    mockPassListeners.add(listener);
    return () => { mockPassListeners.delete(listener); };
  },
}));
jest.mock('../../services/localMoney', () => ({
  LOCAL_MONEY_METHODS: 'methods',
  currencyName: () => 'pesos',
  activateLocalMoney: (...args: any[]) => mockActivate(...args),
  quoteLocalActivation: (...args: any[]) => mockQuote(...args),
  payLocalActivation: (...args: any[]) => mockPay(...args),
}));
import Screen from '../LocalAccountApplicationScreen';

const texts = (tree: renderer.ReactTestRenderer) =>
  tree.root.findAllByType(Text).map(node => ([] as any[]).concat(node.props.children).join(''));
const bar = (tree: renderer.ReactTestRenderer) => tree.root.findByType('ActionBar' as any);

beforeEach(() => {
  jest.clearAllMocks();
  mockAccounts = [];
  mockMethodsError = null;
  mockQuote.mockResolvedValue('10');
  mockPassValid = true;
  mockPassDeadline = null;
  mockScope = 'user:account:1';
  mockMethod = {id: 'co_breb', country: 'CO', asset: 'COP', status: 'live', accountStatus: 'none'};
});

it('explains an opening that is still pending after polling and allows another status check', async () => {
  jest.useFakeTimers({doNotFake: ['nextTick', 'setImmediate', 'queueMicrotask']});
  mockMethod = {id: 'br_pix', country: 'BR', asset: 'BRL', status: 'live', accountStatus: 'provisioning'};
  mockPay.mockResolvedValue(true);
  mockActivate.mockResolvedValue('provisioning');
  let tree!: renderer.ReactTestRenderer;
  let opening!: Promise<void>;
  try {
    await act(async () => {tree = renderer.create(<Screen />);});
    await act(async () => {opening = bar(tree).props.onPrimaryPress();});
    for (let i = 0; i < 10; i += 1) {
      await act(async () => {jest.advanceTimersByTime(5000);});
    }
    await act(async () => {await opening;});
    expect(mockActivate).toHaveBeenCalledTimes(10);
    expect(texts(tree)).toContain('La apertura está tardando más de lo habitual. Puedes salir y tocar Revisar la apertura para continuar.');
    expect(tree.root.findByType(Modal).props.visible).toBe(false);
    expect(bar(tree).props.primaryDisabled).toBe(false);
    expect(mockRemovalPrevented).toBe(false);
  } finally {
    if (tree) await act(async () => tree.unmount());
    jest.useRealTimers();
  }
});

it('blocks the screen with the shared progress modal while opening and clears it on failure', async () => {
  mockMethod = {id: 'mx_clabe', country: 'MX', asset: 'MXN', status: 'live', accountStatus: 'none'};
  let fail!: (error: Error) => void;
  mockPay.mockImplementationOnce(() => new Promise((_resolve, reject) => { fail = reject; }));
  let tree!: renderer.ReactTestRenderer;
  let opening!: Promise<void>;
  await act(async () => {tree = renderer.create(<Screen />);});
  await act(async () => {opening = bar(tree).props.onPrimaryPress();});
  expect(tree.root.findByType(Modal).props.visible).toBe(true);
  expect(texts(tree)).toContain('Por favor no cierres la aplicación');
  await act(async () => {fail(new Error('Intenta de nuevo')); await opening;});
  expect(tree.root.findByType(Modal).props.visible).toBe(false);
  expect(texts(tree)).toContain('Intenta de nuevo');
  expect(bar(tree).props.primaryDisabled).toBe(false);
  await act(async () => tree.unmount());
});

it('shows paid activation as complete instead of spinning in the cost section', async () => {
  mockMethod = {id: 'mx_clabe', country: 'MX', asset: 'MXN', status: 'live', accountStatus: 'active'};
  let tree!: renderer.ReactTestRenderer;
  await act(async () => {tree = renderer.create(<Screen />);});
  expect(texts(tree)).toContain('Tu cuenta está activa. La apertura ya está pagada.');
  expect(bar(tree).props.primaryLabel).toBe('Ir a mi cuenta');
  expect(mockPay).not.toHaveBeenCalled();
  await act(async () => tree.unmount());
});

it('does not trap a completed opening behind a stalled account refresh', async () => {
  mockMethod = {id: 'mx_clabe', country: 'MX', asset: 'MXN', status: 'live', accountStatus: 'awaiting_payment'};
  mockPay.mockResolvedValueOnce(true);
  mockActivate.mockResolvedValueOnce('active');
  let release!: () => void;
  mockAccountRefetch.mockImplementationOnce(() => new Promise<void>(resolve => {release = resolve;}));
  let tree!: renderer.ReactTestRenderer;
  let opening!: Promise<void>;
  await act(async () => {tree = renderer.create(<Screen />);});
  await act(async () => {opening = bar(tree).props.onPrimaryPress();});
  try {
    expect(mockGoBack).toHaveBeenCalledTimes(1);
    expect(tree.root.findByType(Modal).props.visible).toBe(false);
  } finally {
    await act(async () => {release(); await opening; tree.unmount();});
  }
});

it('prevents duplicate opening and back navigation while busy, then refreshes accounts before returning', async () => {
  mockMethod = {id: 'mx_clabe', country: 'MX', asset: 'MXN', status: 'live', accountStatus: 'awaiting_payment'};
  let finish!: (paid: boolean) => void;
  mockPay.mockImplementationOnce(() => new Promise<boolean>(resolve => {finish = resolve;}));
  mockActivate.mockResolvedValueOnce('active');
  let tree!: renderer.ReactTestRenderer;
  let opening!: Promise<void>;
  await act(async () => {tree = renderer.create(<Screen />);});
  const press = bar(tree).props.onPrimaryPress;
  await act(async () => {opening = press(); await press();});
  expect(mockPay).toHaveBeenCalledTimes(1);
  expect(mockRemovalPrevented).toBe(true);
  expect(mockGoBack).not.toHaveBeenCalled();
  await act(async () => {finish(true); await opening;});
  expect(mockAccountRefetch).toHaveBeenCalledTimes(1);
  expect(mockGoBack).toHaveBeenCalledTimes(1);
  expect(tree.root.findByType(Modal).props.visible).toBe(false);
  expect(mockRemovalPrevented).toBe(false);
  await act(async () => tree.unmount());
});

it('does not carry an issued key into another account context', async () => {
  mockMethod = {id: 'cobre_co_breb_receive', country: 'CO', asset: 'COP', status: 'live', accountStatus: 'none'};
  mockApply.mockResolvedValueOnce('@first-account');
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<Screen />); });
  await act(async () => { await bar(tree).props.onPrimaryPress(); });
  expect(texts(tree)).toContain('@first-account');
  mockScope = 'user:another-account:2';
  mockPassValid = false;
  await act(async () => { tree.update(<Screen />); });
  expect(texts(tree)).not.toContain('@first-account');
  await act(async () => { tree.unmount(); });
});

it('rearms key hiding when application renews an already-valid pass', async () => {
  jest.useFakeTimers({doNotFake: ['nextTick', 'setImmediate', 'queueMicrotask']});
  mockMethod = {id: 'cobre_co_breb_receive', country: 'CO', asset: 'COP', status: 'live', accountStatus: 'none'};
  mockPassDeadline = Date.now() + 60000;
  mockApply.mockImplementationOnce(async () => {
    mockPassDeadline = Date.now() + 120000;
    return '@ana';
  });
  let tree!: renderer.ReactTestRenderer;
  try {
    await act(async () => { tree = renderer.create(<Screen />); });
    await act(async () => { await bar(tree).props.onPrimaryPress(); });
    expect(texts(tree)).toContain('@ana');
    await act(async () => { jest.advanceTimersByTime(61000); });
    expect(texts(tree)).toContain('@ana');
    await act(async () => { jest.advanceTimersByTime(61000); });
    expect(texts(tree)).not.toContain('@ana');
    expect(texts(tree)).toContain('Confirma tu ubicación');
  } finally {
    if (tree) await act(async () => { tree.unmount(); });
    jest.useRealTimers();
  }
});

it('approving the opening fee covers only the amount shown', async () => {
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<Screen />); });
  expect(bar(tree).props.primaryLabel).toBe('Aceptar y solicitar · US$10');
  const answers: boolean[] = [];
  mockPay.mockImplementationOnce(async (_id: string, prompts: any) => {
    answers.push(await prompts.confirmFee('10.00'), await prompts.confirmFee('12'));
    return false;
  });
  await act(async () => { await bar(tree).props.onPrimaryPress(); });
  expect(answers).toEqual([true, false]);
  // The changed amount is shown and needs its own approval.
  expect(bar(tree).props.primaryLabel).toBe('Aceptar y solicitar · US$12');
  expect(texts(tree).join('\n')).toContain('ahora es US$12');
  await act(async () => { tree.unmount(); });
});

it('a departed application cannot approve a late fee request', async () => {
  let captured: any;
  let finish!: (value: boolean) => void;
  mockPay.mockImplementationOnce(async (_id: string, prompts: any) => {
    captured = prompts;
    return new Promise<boolean>(resolve => { finish = resolve; });
  });
  let tree!: renderer.ReactTestRenderer;
  let opening!: Promise<void>;
  await act(async () => { tree = renderer.create(<Screen />); });
  await act(async () => { opening = bar(tree).props.onPrimaryPress(); });
  mockScope = 'user:another-account:2';
  await act(async () => { tree.update(<Screen />); });
  expect(await captured.confirmFee('10')).toBe(false);
  await act(async () => { finish(false); await opening; });
  await act(async () => { tree.unmount(); });
});

it('a departed application stops after its second payment', async () => {
  mockMethod = {...mockMethod, accountStatus: 'awaiting_payment'};
  let finish!: (value: boolean) => void;
  mockPay.mockResolvedValueOnce(true)
    .mockImplementationOnce(() => new Promise<boolean>(resolve => { finish = resolve; }));
  mockActivate.mockResolvedValue('awaiting_payment');
  let tree!: renderer.ReactTestRenderer;
  let opening!: Promise<void>;
  await act(async () => { tree = renderer.create(<Screen />); });
  await act(async () => { opening = bar(tree).props.onPrimaryPress(); });
  expect(mockActivate).toHaveBeenCalledTimes(1);
  mockScope = 'user:another-account:2';
  await act(async () => { tree.update(<Screen />); });
  await act(async () => { finish(true); await opening; });
  // The second payment finished after the user left: no further opening step.
  expect(mockActivate).toHaveBeenCalledTimes(1);
  await act(async () => { tree.unmount(); });
});

it('an opening already started elsewhere offers a retry instead of hanging', async () => {
  mockQuote.mockResolvedValueOnce(null);
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<Screen />); });
  expect(texts(tree).join('\n')).toContain('Intentar de nuevo');
  expect(bar(tree).props.primaryDisabled).toBe(true);
  const retry = tree.root.findAllByType(TouchableOpacity).find(node =>
    node.findAllByType(Text).some(text => ([] as any[]).concat(text.props.children).join('').includes('Intentar de nuevo')))!;
  await act(async () => { retry.props.onPress(); });
  expect(bar(tree).props.primaryLabel).toBe('Aceptar y solicitar · US$10');
  await act(async () => { tree.unmount(); });
});

it('a ready account shows what it costs before paying, then pays only that', async () => {
  mockMethod = {...mockMethod, accountStatus: 'awaiting_payment'};
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<Screen />); });
  expect(bar(tree).props.primaryLabel).toBe('Ver el monto a pagar');
  const answers: boolean[] = [];
  mockPay.mockImplementation(async (_id: string, prompts: any) => {
    answers.push(await prompts.confirmPayment('10'));
    return false;
  });
  await act(async () => { await bar(tree).props.onPrimaryPress(); });
  expect(answers).toEqual([false]);
  expect(bar(tree).props.primaryLabel).toBe('Pagar US$10 y activar');
  await act(async () => { await bar(tree).props.onPrimaryPress(); });
  expect(answers).toEqual([false, true]);
  await act(async () => { tree.unmount(); });
});

it('a pass forgotten elsewhere hides the key at once', async () => {
  mockMethod = {id: 'cobre_co_breb_receive', country: 'CO', asset: 'COP', status: 'live', accountStatus: 'none'};
  mockAccounts = [{provider: 'cobre', fundingInstructions: [{kind: 'breb_key', status: 'active', displayValue: '@ana'}]}];
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<Screen />); });
  expect(texts(tree)).toContain('@ana');
  mockPassValid = false; // e.g. a conversion got the explicit refusal
  await act(async () => { mockPassListeners.forEach(listener => listener()); });
  expect(texts(tree)).not.toContain('@ana');
  await act(async () => { tree.unmount(); });
});

it('a Bre-B key shows only while the location pass lasts', async () => {
  mockMethod = {id: 'cobre_co_breb_receive', country: 'CO', asset: 'COP', status: 'live', accountStatus: 'none'};
  mockAccounts = [{provider: 'cobre', fundingInstructions: [{kind: 'breb_key', status: 'active', displayValue: '@ana'}]}];
  mockPassValid = false;
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<Screen />); });
  expect(texts(tree)).not.toContain('@ana');
  expect(texts(tree)).toContain('Confirma tu ubicación');
  await act(async () => { tree.unmount(); });
  mockPassValid = true;
  await act(async () => { tree = renderer.create(<Screen />); });
  expect(texts(tree)).toContain('@ana');
  await act(async () => { tree.unmount(); });
});

it('a failed load offers a retry instead of a dead end', async () => {
  mockMethodsError = new Error('Network request failed');
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<Screen />); });
  expect(texts(tree)).toContain('No pudimos cargar esta cuenta');
  expect(texts(tree)).not.toContain('No disponible por ahora');
  const action = bar(tree);
  expect(action.props.primaryLabel).toBe('Intentar de nuevo');
  expect(action.props.primaryDisabled).toBeFalsy();
  await act(async () => { action.props.onPrimaryPress(); });
  expect(mockMethodsRefetch).toHaveBeenCalled();
  await act(async () => { tree.unmount(); });
});
