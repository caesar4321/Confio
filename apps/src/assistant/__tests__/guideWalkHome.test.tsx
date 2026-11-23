// A first-step walk in the conversation home: no tab or Inicio verb to
// circle, so the first stop opens its screen and the pencil takes over from
// the first button inside it (docs/designs/ai-assistant-first-redesign.md 7.5).
import React from 'react';
import renderer, { act } from 'react-test-renderer';

const mockNavigate = jest.fn();
let mockWalkAnswer: Promise<unknown> = Promise.resolve({ data: { assistantWalk: null } });
const mockRecord = jest.fn(async (_options: { variables: { step: string; event: string; detail?: string } }) => ({}));
let mockRoute = 'Home';
let mockGuide: any = null;
let mockConversationHome = true;

jest.mock('../../config/features', () => ({
  get CONVERSATION_HOME_ENABLED() { return mockConversationHome; },
}));
jest.mock('react-native-vector-icons/Feather', () => 'Icon');
jest.mock('react-native-safe-area-context', () => ({
  useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }),
  initialWindowMetrics: { insets: { top: 0, bottom: 0, left: 0, right: 0 } },
}));
jest.mock('../../components/common/AppText', () => ({ Text: require('react-native').Text }));
jest.mock('../../contexts/AccountContext', () => ({ useAccount: () => ({ activeAccount: { id: 'personal_0', type: 'personal' } }) }));
jest.mock('../../contexts/AuthContext', () => ({ useAuth: () => ({ isAuthenticated: true, isLoading: false }) }));
jest.mock('../../navigation/RootNavigation', () => ({
  navigationRef: { navigate: (...args: unknown[]) => mockNavigate(...args) },
}));
jest.mock('../AssistantContext', () => ({
  useAssistant: () => ({
    route: mockRoute, isOpen: false, open: jest.fn(), inCall: false, available: true, aiEnabled: true,
    setGuideShown: jest.fn(), showNavNote: jest.fn(),
  }),
}));
jest.mock('../AssistantMascot', () => 'AssistantMascot');
jest.mock('../GuideOpening', () => 'GuideOpening');
jest.mock('../destinations', () => ({ openDestination: jest.fn(), resolveNavigate: () => null }));
jest.mock('../../services/topUpExit', () => ({ forgetTopUpPriceSeen: jest.fn(), sawTopUpPriceThisRun: () => false }));
jest.mock('../api', () => ({
  ASK_ASSISTANT_IN_GUIDE: 'askInGuide', GET_ASSISTANT_GUIDE: 'guide', GET_ASSISTANT_THREAD: 'thread',
  GET_ASSISTANT_WALK: 'walk', RECORD_ASSISTANT_GUIDE_EVENT: 'record',
}));
jest.mock('@apollo/client', () => ({
  useApolloClient: () => ({ query: () => mockWalkAnswer }),
  useMutation: (mutation: string) => [mutation === 'record' ? mockRecord : jest.fn(async () => ({}))],
  useQuery: (query: string, options: { skip?: boolean }) => ({
    data: options.skip ? undefined : query === 'guide' ? { assistantGuide: mockGuide } : undefined,
    refetch: jest.fn(async () => ({})),
  }),
}));

import AssistantGuideCard from '../AssistantGuideCard';
import { requestGuideTrail, requestGuideWalk, setGuidePointer, useGuidePointer, type GuidePointer } from '../guidePointer';

let pointer: GuidePointer | null = null;
const Probe = () => {
  pointer = useGuidePointer();
  return null;
};
const TO_TOP_UP = [
  { route: 'Home', text: 'Toca Recibir.', pointer: 'home_receive' },
  { route: 'Receive', text: 'Toca aquí para crear tu recarga.', pointer: 'recharge_now' },
  { route: '*tab', text: 'Toca Inicio para seguir.', pointer: 'tab_home' },
  { route: '*back', text: 'Toca la flecha para volver.', pointer: 'nav_back' },
];
const events = () => mockRecord.mock.calls.map(([options]) => {
  const { step, event, detail } = options.variables;
  return [step, event, detail].filter(Boolean).join(':');
});
async function mount() {
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<><AssistantGuideCard /><Probe /></>); });
  return tree;
}
const goTo = async (tree: renderer.ReactTestRenderer, route: string) => {
  mockRoute = route;
  await act(async () => { tree.update(<><AssistantGuideCard /><Probe /></>); });
};

beforeEach(() => {
  jest.clearAllMocks();
  jest.useFakeTimers();
  mockRoute = 'Home';
  mockGuide = null;
  mockConversationHome = true;
  setGuidePointer(null);
});
afterEach(() => {
  jest.clearAllTimers();
  jest.useRealTimers();
});

it('opens the first stop instead of pointing at a button Inicio no longer has', async () => {
  const tree = await mount();
  await act(async () => { requestGuideTrail({ step: 'top_up', detail: '', stops: TO_TOP_UP }); });
  expect(mockNavigate).toHaveBeenCalledWith('Main', { screen: 'Receive', params: undefined });
  expect(pointer).toBeNull();
  expect(events()).toEqual(['top_up:opened:home_receive']);

  // On the screen it opened, the pencil circles the real button.
  await goTo(tree, 'Receive');
  expect(pointer).toMatchObject({ id: 'recharge_now', text: 'Toca aquí para crear tu recarga.', step: 'top_up' });
  await act(async () => tree.unmount());
});

it('each Inicio stop has its screen: tabs become drawer routes, Pagar the stack scanner', async () => {
  const tree = await mount();
  const first = (pointerId: string) => [{ route: 'Home', text: '', pointer: pointerId }, { route: 'X', text: 'x', pointer: '' }];
  const opened = async (pointerId: string) => {
    mockNavigate.mockClear();
    await act(async () => { requestGuideTrail({ step: 'send', detail: '', stops: first(pointerId) }); });
    return mockNavigate.mock.calls[0];
  };
  expect(await opened('home_send')).toEqual(['Main', { screen: 'Send', params: undefined }]);
  expect(await opened('tab_pay')).toEqual(['Main', { screen: 'Scan', params: { mode: 'pagar' } }]);
  expect(await opened('tab_profile')).toEqual(['Main', { screen: 'BottomTabs', params: { screen: 'Profile', params: undefined } }]);
  expect(await opened('tab_comprar')).toEqual(['Main', { screen: 'BottomTabs', params: { screen: 'Comprar', params: undefined } }]);
  const invest = await opened('tab_invest');
  expect(invest[1].params.screen).toBe('Invest');
  expect(invest[1].params.params.segment).toBe('invest');
  await act(async () => tree.unmount());
});

it('asked from a screen that is already on the way: points there, never carries the person back', async () => {
  const TO_BUY = [
    { route: 'Home', text: 'Toca Invertir.', pointer: 'tab_invest' },
    { route: 'Invest', text: 'Toca aquí para ver las acciones.', pointer: 'invest_stocks' },
    { route: 'StocksList', text: 'Elige la que tú quieras.', pointer: '' },
    { route: 'StockDetail', text: 'Si quieres comprarla, toca aquí.', pointer: 'asset_buy' },
  ];
  mockRoute = 'StockDetail';
  const tree = await mount();
  await act(async () => { requestGuideTrail({ step: 'invest', detail: 'stocks', stops: TO_BUY }); });
  expect(mockNavigate).not.toHaveBeenCalled();
  expect(pointer).toMatchObject({ id: 'asset_buy', text: 'Si quieres comprarla, toca aquí.' });
  expect(events()).toEqual([]);
  await act(async () => tree.unmount());
});

it('"Verificar mi identidad" opens the verification screen itself, not Perfil', async () => {
  const TO_VERIFY = [
    { route: 'Home', text: 'Toca Perfil.', pointer: 'tab_profile' },
    { route: 'Profile', text: 'Toca Verificación.', pointer: 'profile_verification' },
    { route: 'Verification', text: 'Toca aquí para verificar tu identidad.', pointer: 'verify_start' },
  ];
  const tree = await mount();
  await act(async () => { requestGuideTrail({ step: 'verify', detail: '', stops: TO_VERIFY }); });
  expect(mockNavigate).toHaveBeenCalledWith('Main', { screen: 'Verification', params: undefined });
  expect(mockNavigate).toHaveBeenCalledTimes(1);
  // The event says what was opened for them.
  expect(events()).toEqual(['verify:opened:verification']);
  await goTo(tree, 'Verification');
  expect(pointer).toMatchObject({ id: 'verify_start' });
  await act(async () => tree.unmount());
});

it('a "Muéstrame" answered after the person moved on does not take them anywhere', async () => {
  let answer!: (value: unknown) => void;
  mockWalkAnswer = new Promise((resolve) => { answer = resolve; });
  const tree = await mount();
  await act(async () => { requestGuideWalk('top_up'); });
  await goTo(tree, 'Invest');
  await act(async () => { answer({ data: { assistantWalk: { key: 'top_up', trail: TO_TOP_UP } } }); });
  expect(mockNavigate).not.toHaveBeenCalled();
  expect(pointer).toBeNull();

  // Still on the screen where it was asked: it runs.
  mockWalkAnswer = Promise.resolve({ data: { assistantWalk: { key: 'top_up', trail: TO_TOP_UP } } });
  await act(async () => { requestGuideWalk('top_up'); });
  expect(mockNavigate).toHaveBeenCalledWith('Main', { screen: 'Receive', params: undefined });
  await act(async () => tree.unmount());
});

it('already on that screen: no navigation, the pencil points right away', async () => {
  mockRoute = 'Receive';
  const tree = await mount();
  await act(async () => { requestGuideTrail({ step: 'top_up', detail: '', stops: TO_TOP_UP }); });
  expect(mockNavigate).not.toHaveBeenCalled();
  expect(pointer).toMatchObject({ id: 'recharge_now' });
  // Nothing was opened for them: nothing to count as opened.
  expect(events()).toEqual([]);
  await act(async () => tree.unmount());
});

it('back on Inicio mid-walk the walk ends instead of circling nothing', async () => {
  const tree = await mount();
  await act(async () => { requestGuideTrail({ step: 'top_up', detail: '', stops: TO_TOP_UP }); });
  await goTo(tree, 'Receive');
  expect(pointer).not.toBeNull();
  await goTo(tree, 'Home');
  expect(pointer).toBeNull();
  // And it does not start again from another screen.
  await goTo(tree, 'Receive');
  expect(pointer).toBeNull();
  await act(async () => tree.unmount());
});

it('the card itself never opens in the conversation home: the conversation says the step', async () => {
  mockGuide = { step: 'top_up', stage: 'top_up', text: 'Ya puedes recargar.', presentation: 'bubble', chips: [] };
  const tree = await mount();
  await act(async () => { jest.advanceTimersByTime(5000); });
  expect(events()).toEqual([]);
  expect(tree.toJSON()).toBeNull();
  await act(async () => tree.unmount());
});

it('five tabs: unchanged, the pencil circles Recibir on Inicio and the card opens', async () => {
  mockConversationHome = false;
  mockGuide = { step: 'top_up', stage: 'top_up', text: 'Ya puedes recargar.', presentation: 'bubble', chips: [] };
  const tree = await mount();
  await act(async () => { jest.advanceTimersByTime(1500); });
  expect(events()).toEqual(['top_up:shown']);
  await act(async () => { requestGuideTrail({ step: 'top_up', detail: '', stops: TO_TOP_UP }); });
  expect(mockNavigate).not.toHaveBeenCalled();
  expect(pointer).toMatchObject({ id: 'home_receive', text: 'Toca Recibir.' });
  await act(async () => tree.unmount());
});
