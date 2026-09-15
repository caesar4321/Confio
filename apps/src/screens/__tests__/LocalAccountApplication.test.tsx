import React from 'react';
import renderer, {act} from 'react-test-renderer';
import {Text} from 'react-native';

const mockPay = jest.fn();
const mockApply = jest.fn();
let mockPassDeadline: number | null = null;
let mockScope = 'user:account:1';
let mockMethod: any;
let mockAccounts: any[] = [];
let mockPassValid = true;
jest.mock('react-native-vector-icons/Feather', () => 'Icon');
jest.mock('@react-native-clipboard/clipboard', () => ({setString: jest.fn()}));
jest.mock('@apollo/client', () => ({useQuery: (query: string) => ({
  data: query === 'methods' ? {localMoneyMethods: [mockMethod]}
    : query === 'address' ? {myRampAddress: {isComplete: true}} : {},
  loading: false,
  refetch: jest.fn().mockResolvedValue({}),
})}));
jest.mock('@react-navigation/native', () => ({
  useNavigation: () => ({navigate: jest.fn(), goBack: jest.fn(), canGoBack: () => true, replace: jest.fn()}),
  useRoute: () => ({params: {methodId: mockMethod.id}}),
  useFocusEffect: () => {},
}));
jest.mock('../../apollo/queries', () => ({GET_MY_RAMP_ADDRESS: 'address'}));
jest.mock('../../contexts/AccountContext', () => ({useAccount: () => ({activeAccount: {type: 'personal'}})}));
jest.mock('../../components/breb/BrebLocationGate', () => ({useBrebLocationScope: () => mockScope}));
jest.mock('../../hooks/useLocalPaymentAccounts', () => ({
  useLocalPaymentAccounts: () => ({accounts: mockAccounts, refetch: jest.fn().mockResolvedValue({})}),
}));
jest.mock('../../components/ramps/RampActionBar', () => ({RampActionBar: 'ActionBar'}));
jest.mock('../../components/ramps/RampHero', () => ({RampHero: 'Hero'}));
jest.mock('../../components/ramps/RampReveal', () => ({RampReveal: ({children}: any) => children}));
jest.mock('../../components/ramps/RampStepHeader', () => ({RampStepHeader: 'Step'}));
jest.mock('../../services/brebLocation', () => ({
  applyCobreBreb: (...args: any[]) => mockApply(...args),
  brebLocationPassValid: () => mockPassValid && (mockPassDeadline === null || Date.now() < mockPassDeadline),
  brebLocationPassRemainingMs: () => mockPassDeadline === null ? 60000 : Math.max(0, mockPassDeadline - Date.now()),
}));
jest.mock('../../services/localMoney', () => ({
  LOCAL_MONEY_METHODS: 'methods',
  currencyName: () => 'pesos',
  activateLocalMoney: jest.fn(),
  quoteLocalActivation: jest.fn().mockResolvedValue('10'),
  payLocalActivation: (...args: any[]) => mockPay(...args),
}));
import Screen from '../LocalAccountApplicationScreen';

const texts = (tree: renderer.ReactTestRenderer) =>
  tree.root.findAllByType(Text).map(node => ([] as any[]).concat(node.props.children).join(''));
const bar = (tree: renderer.ReactTestRenderer) => tree.root.findByType('ActionBar' as any);

beforeEach(() => {
  jest.clearAllMocks();
  mockAccounts = [];
  mockPassValid = true;
  mockPassDeadline = null;
  mockScope = 'user:account:1';
  mockMethod = {id: 'co_breb', country: 'CO', asset: 'COP', status: 'live', accountStatus: 'none'};
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
