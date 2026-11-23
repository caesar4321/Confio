// The shopping task screen: when the store's live view shows, what it may
// load, and what the person can do on each turn.
import React from 'react';
import { Alert, Text as RNText } from 'react-native';
import renderer, { act } from 'react-test-renderer';

const ID = '3f2b8c1e-9a4d-4e6f-8b2a-1c3d5e7f9a0b';
const LIVE = 'https://www.browserbase.com/devtools-fullscreen/inspector.html?wss=connect.browserbase.com/x';
let mockTask: any;
let mockQueryOptions: any;
let mockStuck = false;
// What a refresh returns: the task as it is now, or a refresh held by the test.
const mockQuery = jest.fn(async () => ({ data: { agentTask: mockTask } }));
const mockClient = { query: (options: any) => { mockQueryOptions = options; return mockQuery(); } };
const mockRefetch = jest.fn(async () => ({}));
const mockOpen = jest.fn();
const mockResume = jest.fn();
const mockCancel = jest.fn();
const mockChat = jest.fn();
const mockNavigate = jest.fn();

jest.mock('react-native-vector-icons/Feather', () => 'Icon');
// Counts real mounts: a remount is what reloads the page.
let mockWebMounts = 0;
jest.mock('react-native-webview', () => {
  const React = require('react');
  return function WebView() {
    React.useEffect(() => { mockWebMounts += 1; }, []);
    return null;
  };
});
jest.mock('../../components/common/AppText', () => ({ Text: require('react-native').Text }));
jest.mock('../../navigation/Header', () => ({ Header: () => null }));
jest.mock('../../assistant/AssistantContext', () => ({ useOptionalAssistant: () => ({ open: mockChat }) }));
const mockSecure = jest.fn();
jest.mock('../secureScreen', () => ({ setSecureScreen: (on: boolean) => mockSecure(on) }));
jest.mock('@react-navigation/native', () => ({
  useNavigation: () => ({ navigate: mockNavigate, goBack: jest.fn() }),
  useRoute: () => ({ params: { taskId: ID } }),
  useFocusEffect: (cb: () => (() => void) | void) => require('react').useEffect(cb, [cb]),
}));
jest.mock('@apollo/client', () => ({
  gql: (s: TemplateStringsArray) => s.join(''),
  // One client for the app's life, as Apollo's provider gives.
  useApolloClient: () => mockClient,
  useMutation: (doc: string) => {
    if (doc.includes('openAgentLiveView')) return [mockOpen];
    // A hung request keeps Apollo's own loading flag on forever: the screen must not follow it.
    if (doc.includes('resumeAgentTask')) return [mockResume, { loading: mockStuck }];
    return [mockCancel, { loading: mockStuck }];
  },
}));

import { AgentTaskScreen, forgetShownTurns, showsLiveView } from '../AgentTaskScreen';

const task = (over: any = {}) => ({
  id: ID, goal: 'un chocolate', site: 'mercadolibre.com.mx', status: 'needs_person', reason: 'login',
  message: 'Necesito que inicies sesión en mercadolibre.com.mx.', waitUntil: null, checkoutHanded: false,
  paymentIntentId: null, createdAt: '2026-11-23T12:00:00Z', ...over,
});
const texts = (tree: renderer.ReactTestRenderer) =>
  tree.root.findAllByType(RNText).map((n) => [n.props.children].flat(Infinity).join(''));
const webViews = (tree: renderer.ReactTestRenderer) =>
  tree.root.findAll((n) => typeof n.type === 'function' && (n.type as any).name === 'WebView');
// The app's Button itself (its loading/disabled props), not the touchable inside it.
const appButton = (tree: renderer.ReactTestRenderer, title: string) =>
  tree.root.findAll((n) => n.props.title === title && typeof n.props.onPress === 'function')[0];
const button = (tree: renderer.ReactTestRenderer, label: string) =>
  tree.root.findAll((n) => n.props.accessibilityLabel === label && typeof n.props.onPress === 'function')[0];

let mounted: renderer.ReactTestRenderer[] = [];
async function mount() {
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<AgentTaskScreen />); });
  mounted.push(tree);
  return tree;
}
afterEach(() => {
  mounted.forEach((t) => act(() => { t.unmount(); }));
  mounted = [];
  jest.useRealTimers();
});
// The next refresh (every 2.5 s while the task moves) brings the task as it is now.
async function rerender(_tree: renderer.ReactTestRenderer) {
  await act(async () => { jest.advanceTimersByTime(2500); });
  await act(async () => { await Promise.resolve(); });
}

beforeEach(() => {
  jest.useFakeTimers();
  jest.clearAllMocks();
  mockQuery.mockReset();
  // A new object each time, as every network answer is.
  mockQuery.mockImplementation(async () => ({ data: { agentTask: mockTask && { ...mockTask } } }));
  mockOpen.mockReset();
  mockResume.mockReset();
  mockCancel.mockReset();
  mockWebMounts = 0;
  mockStuck = false;
  forgetShownTurns();
  mockTask = task();
  mockOpen.mockResolvedValue({ data: { openAgentLiveView: {
    success: true, errors: [], url: LIVE, expiresIn: 900, site: 'mercadolibre.com.mx', host: 'www.browserbase.com',
    pageHost: 'www.mercadolibre.com.mx', view: 'view-1' } } });
  mockResume.mockResolvedValue({ data: { resumeAgentTask: { success: true, errors: [] } } });
  mockCancel.mockResolvedValue({ data: { cancelAgentTask: { success: true, errors: [] } } });
});

it('shows the store only on the person\'s turn before the hand-over, and keeps it after', () => {
  expect(showsLiveView(task())).toBe(true);
  expect(showsLiveView(task({ status: 'working' }))).toBe(false);
  expect(showsLiveView(task({ status: 'awaiting_code', reason: 'checkout', checkoutHanded: true }))).toBe(true);
  expect(showsLiveView(task({ status: 'working', reason: 'checkout', checkoutHanded: true }))).toBe(true);
  for (const status of ['payment_ready', 'stopped', 'cancelled']) {
    expect(showsLiveView(task({ status, checkoutHanded: true }))).toBe(false);
  }
});

it('keeps the screen out of screenshots while it is open (Android FLAG_SECURE)', async () => {
  const tree = await mount();
  expect(mockSecure).toHaveBeenLastCalledWith(true);
  act(() => { tree.unmount(); });
  mounted = [];
  expect(mockSecure).toHaveBeenLastCalledWith(false);
});

it('asks for a fresh screen on the person\'s turn and shows where they are typing', async () => {
  const tree = await mount();
  expect(mockOpen).toHaveBeenCalledWith({ variables: { id: ID } });
  const [view] = webViews(tree);
  expect(view.props.source).toEqual({ uri: LIVE });
  expect(view.props.incognito).toBe(true);
  expect(view.props.cacheEnabled).toBe(false);
  expect(view.props.injectedJavaScript).toBeUndefined();
  // Every address reaches the check: one refused by the whitelist would be handed to the phone's apps.
  expect(view.props.originWhitelist).toEqual(['*']);
  expect(texts(tree)).toContain('Al abrir: www.mercadolibre.com.mx');
  expect(texts(tree)).toContain('Necesito que inicies sesión en mercadolibre.com.mx.');
});

it('never lets the page move to another host', async () => {
  const tree = await mount();
  const allow = webViews(tree)[0].props.onShouldStartLoadWithRequest;
  expect(allow({ url: `${LIVE}&x=1`, isTopFrame: true })).toBe(true);
  expect(allow({ url: 'https://phish.test/login', isTopFrame: true })).toBe(false);
  expect(allow({ url: 'http://www.browserbase.com/x', isTopFrame: true })).toBe(false);
  expect(allow({ url: 'intent://scan#Intent;end', isTopFrame: true })).toBe(false);
  // A frame inside the page: https only, never another app or plain http.
  expect(allow({ url: 'https://cdn.example.test/frame', isTopFrame: false })).toBe(true);
  for (const url of ['http://evil.test/', 'tel:123', 'intent://x#Intent;end', 'whatsapp://send']) {
    expect(allow({ url, isTopFrame: false })).toBe(false);
  }
});

it('the agent left the store: no screen, no way to reopen it, only Cancelar', async () => {
  mockOpen.mockResolvedValueOnce({ data: { openAgentLiveView: {
    success: false, errors: ['Por seguridad no te muestro esa página.'], errorCode: 'left_store' } } });
  const tree = await mount();
  expect(webViews(tree)).toHaveLength(0);
  expect(texts(tree)).toContain('Por seguridad no te muestro esa página.');
  expect(button(tree, 'Abrir de nuevo')).toBeUndefined();
  expect(button(tree, 'Ya terminé')).toBeUndefined();
  expect(button(tree, 'Cancelar')).toBeDefined();
});

it('before the hand-over a screen that cannot be reopened is taken down', async () => {
  const tree = await mount();
  expect(webViews(tree)).toHaveLength(1);
  mockOpen.mockResolvedValueOnce({ data: { openAgentLiveView: {
    success: false, errors: ['Por seguridad no te muestro esa página.'], errorCode: 'left_store' } } });
  await act(async () => { webViews(tree)[0].props.onHttpError(); });
  await act(async () => { button(tree, 'Abrir de nuevo').props.onPress(); });
  expect(webViews(tree)).toHaveLength(0);
});

it('an answer for a turn that already ended is dropped', async () => {
  let stale!: (v: unknown) => void;
  let fresh!: (v: unknown) => void;
  mockOpen.mockReturnValueOnce(new Promise((resolve) => { stale = resolve; }));
  const tree = await mount();
  // The agent took the browser back, then handed it over again: that turn's open is still pending.
  mockTask = task({ status: 'working', reason: '' });
  await rerender(tree);
  mockOpen.mockReturnValueOnce(new Promise((resolve) => { fresh = resolve; }));
  mockTask = task({ reason: 'captcha' });
  await rerender(tree);
  await act(async () => { stale({ data: { openAgentLiveView: { success: true, errors: [], url: LIVE,
    host: 'www.browserbase.com' } } }); });
  // The first turn's screen is not shown in the second.
  expect(webViews(tree)).toHaveLength(0);
  await act(async () => { fresh({ data: { openAgentLiveView: { success: true, errors: [], url: `${LIVE}&2`,
    host: 'www.browserbase.com' } } }); });
  expect(webViews(tree)[0].props.source).toEqual({ uri: `${LIVE}&2` });
});

it('"Abrir de nuevo" reloads a page that failed to load, even at the same address', async () => {
  const tree = await mount();
  const before = webViews(tree)[0].props;
  await act(async () => { before.onError(); });
  await act(async () => { button(tree, 'Abrir de nuevo').props.onPress(); });
  expect(webViews(tree)[0].props.source).toEqual({ uri: LIVE });
  expect(mockWebMounts).toBe(2);
  expect(texts(tree)).not.toContain('La pantalla de la tienda se cerró.');
});

it('a page whose process was killed, or that stopped answering, can be reloaded', async () => {
  const tree = await mount();
  await act(async () => { webViews(tree)[0].props.onContentProcessDidTerminate(); });
  await act(async () => { button(tree, 'Abrir de nuevo').props.onPress(); });
  expect(mockWebMounts).toBe(2);
  await act(async () => { webViews(tree)[0].props.onRenderProcessGone(); });
  await act(async () => { button(tree, 'Abrir de nuevo').props.onPress(); });
  expect(mockWebMounts).toBe(3);
  // No error at all, just a dead screen: the person can still reload it.
  await act(async () => { button(tree, 'La pantalla no responde').props.onPress(); });
  expect(mockWebMounts).toBe(4);
});

it('the same screen at the same address is not reloaded when a new turn opens it again', async () => {
  mockTask = task({ reason: 'checkout', checkoutHanded: true, waitUntil: '2099-01-01T00:00:00Z' });
  const tree = await mount();
  mockTask = task({ status: 'awaiting_code', reason: 'checkout', checkoutHanded: true });
  await rerender(tree);
  mockTask = task({ reason: 'screen', checkoutHanded: true, waitUntil: '2099-01-01T00:10:00Z' });
  await rerender(tree);
  expect(mockOpen).toHaveBeenCalledTimes(2);
  expect(mockWebMounts).toBe(1);
});

it('never loads an address the server gave that is not the live view\'s https host', async () => {
  mockOpen.mockResolvedValueOnce({ data: { openAgentLiveView: { success: true, errors: [],
    url: 'http://www.browserbase.com/x', host: 'www.browserbase.com' } } });
  const tree = await mount();
  expect(webViews(tree)).toHaveLength(0);
});

it('after the hand-over, a new turn\'s "Ya terminé" waits for that turn\'s own screen', async () => {
  mockTask = task({ reason: 'checkout', checkoutHanded: true, waitUntil: '2099-01-01T00:00:00Z' });
  const tree = await mount();
  expect(button(tree, 'Ya terminé').props.disabled).toBe(false);
  // The code was not read: a new turn, its open still pending, the old page still up.
  let opened!: (v: unknown) => void;
  mockOpen.mockReturnValueOnce(new Promise((resolve) => { opened = resolve; }));
  mockTask = task({ reason: 'screen', checkoutHanded: true, waitUntil: '2099-01-01T00:10:00Z' });
  await rerender(tree);
  expect(webViews(tree)).toHaveLength(1);
  expect(button(tree, 'Ya terminé').props.disabled).toBe(true);
  await act(async () => { opened({ data: { openAgentLiveView: { success: true, errors: [], url: LIVE,
    host: 'www.browserbase.com' } } }); });
  expect(button(tree, 'Ya terminé').props.disabled).toBe(false);
});

it('coming back late in a turn whose screen was shown still lets the person say done', async () => {
  mockTask = task({ reason: 'checkout', checkoutHanded: true, waitUntil: '2099-01-02T00:00:00Z' });
  const first = await mount();
  act(() => { first.unmount(); });
  mounted = [];
  // Under a minute left: the server will not open the screen again.
  mockOpen.mockResolvedValueOnce({ data: { openAgentLiveView: {
    success: false, errors: ['Esto ya no está esperando tu respuesta.'], errorCode: 'not_open' } } });
  const tree = await mount();
  expect(button(tree, 'Ya terminé').props.disabled).toBe(false);
});

it('a refresh that left before "Ya terminé" was answered is dropped, not written over it', async () => {
  const tree = await mount();
  let late!: (v: { data: { agentTask: unknown } }) => void;
  mockQuery.mockImplementationOnce(() => new Promise<any>((resolve) => { late = resolve; }));
  await act(async () => { jest.advanceTimersByTime(2500); });  // a refresh leaves...
  mockResume.mockResolvedValueOnce({ data: { resumeAgentTask: { success: true, errors: [],
    task: task({ status: 'working', reason: '' }) } } });
  // The refresh after the answer is held too, so only the epoch can keep the old one out.
  let after!: (v: { data: { agentTask: unknown } }) => void;
  mockQuery.mockImplementationOnce(() => new Promise<any>((resolve) => { after = resolve; }));
  await act(async () => { button(tree, 'Ya terminé').props.onPress(); });
  // ...and comes back after the answer, still saying it is the person's turn.
  await act(async () => { late({ data: { agentTask: task() } }); });
  expect(button(tree, 'Ya terminé')).toBeUndefined();
  expect(mockOpen).toHaveBeenCalledTimes(1);
  await act(async () => { after({ data: { agentTask: task({ status: 'working', reason: '' }) } }); });
  expect(button(tree, 'Ya terminé')).toBeUndefined();
});

it('the same turn key again after "Ya terminé" is a new turn: the screen is asked for again', async () => {
  mockTask = task({ reason: 'code', checkoutHanded: true, waitUntil: '2099-01-01T00:00:00Z' });
  const tree = await mount();
  mockResume.mockResolvedValueOnce({ data: { resumeAgentTask: { success: true, errors: [],
    task: task({ status: 'awaiting_code', reason: '', checkoutHanded: true, waitUntil: null }) } } });
  await act(async () => { button(tree, 'Ya terminé').props.onPress(); });
  // The session's end caps every turn at the same deadline: same reason, same waitUntil.
  await rerender(tree);
  expect(mockOpen).toHaveBeenCalledTimes(2);
  expect(button(tree, 'Ya terminé').props.disabled).toBe(false);
});

it('a reopen whose answer was lost: "Ya terminé" reads the tab still on screen, by its token', async () => {
  mockTask = task({ reason: 'checkout', checkoutHanded: true, waitUntil: '2099-01-01T00:00:00Z' });
  const tree = await mount();
  mockOpen.mockRejectedValueOnce(new Error('network'));  // it may have recorded another tab on the server
  await act(async () => { button(tree, 'La pantalla no responde').props.onPress(); });
  expect(webViews(tree)).toHaveLength(1);  // the page stays
  expect(button(tree, 'Ya terminé').props.disabled).toBe(false);
  await act(async () => { button(tree, 'Ya terminé').props.onPress(); });
  expect(mockResume).toHaveBeenCalledWith({ variables: { id: ID, view: 'view-1' } });
});

it('with no token (an older server), a lost reopen still waits for an open known to have worked', async () => {
  mockOpen.mockResolvedValue({ data: { openAgentLiveView: { success: true, errors: [], url: LIVE,
    host: 'www.browserbase.com' } } });
  mockTask = task({ reason: 'checkout', checkoutHanded: true, waitUntil: '2099-01-01T00:00:00Z' });
  const tree = await mount();
  mockOpen.mockRejectedValueOnce(new Error('network'));
  await act(async () => { button(tree, 'La pantalla no responde').props.onPress(); });
  expect(button(tree, 'Ya terminé').props.disabled).toBe(true);
  await act(async () => { button(tree, 'Abrir de nuevo').props.onPress(); });
  expect(button(tree, 'Ya terminé').props.disabled).toBe(false);
});

it('under a minute left: no reopen buttons, and a refused open keeps the sign-in screen', async () => {
  const soon = new Date(Date.now() + 45_000).toISOString();
  mockTask = task({ waitUntil: soon });
  const tree = await mount();
  expect(button(tree, 'La pantalla no responde')).toBeUndefined();
  mockTask = task({ reason: 'captcha', waitUntil: soon });
  mockOpen.mockResolvedValueOnce({ data: { openAgentLiveView: {
    success: false, errors: ['Esto ya no está esperando tu respuesta.'], errorCode: 'not_open' } } });
  await rerender(tree);
  expect(button(tree, 'Abrir de nuevo')).toBeUndefined();
  expect(webViews(tree)).toHaveLength(1);
});

it('a refresh from before a tap, arriving after a newer one, is not applied', async () => {
  const tree = await mount();
  let older!: (v: any) => void;
  mockQuery.mockImplementationOnce(() => new Promise<any>((resolve) => { older = resolve; }));
  await act(async () => { jest.advanceTimersByTime(2500); });
  mockTask = task({ status: 'payment_ready', reason: '', checkoutHanded: true });
  mockResume.mockResolvedValueOnce({ data: { resumeAgentTask: { success: false, errors: ['x'] } } });
  await act(async () => { button(tree, 'Ya terminé').props.onPress(); });  // its refresh brings payment_ready
  await act(async () => { older({ data: { agentTask: task() } }); });
  expect(button(tree, 'Ver el pago')).toBeDefined();
});

it('a "Ya terminé" that never gets an answer stops holding the screen after a while', async () => {
  mockStuck = true;
  const tree = await mount();
  mockResume.mockReturnValueOnce(new Promise(() => undefined));  // a hung connection
  await act(async () => { button(tree, 'Ya terminé').props.onPress(); });
  mockTask = task({ status: 'payment_ready', reason: '', checkoutHanded: true });
  await rerender(tree);
  expect(button(tree, 'Ver el pago')).toBeUndefined();  // still held: a refresh is not applied mid-tap
  await act(async () => { jest.advanceTimersByTime(30_000); });
  await act(async () => { await Promise.resolve(); });
  expect(button(tree, 'Ver el pago')).toBeDefined();
  expect(texts(tree).some((t) => t.startsWith('No pude seguir'))).toBe(false);
});

it('after a hung "Ya terminé" is released the buttons work again, and the turn is asked for anew', async () => {
  mockStuck = true;
  const tree = await mount();
  mockResume.mockReturnValueOnce(new Promise(() => undefined));
  await act(async () => { button(tree, 'Ya terminé').props.onPress(); });
  expect(appButton(tree, 'Ya terminé').props.loading).toBe(true);
  await act(async () => { jest.advanceTimersByTime(30_000); });
  await act(async () => { await Promise.resolve(); });
  // Same turn, same key: the server may have passed through another state; the screen is asked for again.
  expect(mockOpen).toHaveBeenCalledTimes(2);
  expect(appButton(tree, 'Ya terminé').props.loading).toBe(false);
  expect(button(tree, 'Ya terminé').props.disabled).toBe(false);
  expect(appButton(tree, 'Cancelar').props.loading).toBe(false);
});

it('a refusal that arrives after the release is still told', async () => {
  const tree = await mount();
  let answer!: (v: any) => void;
  mockResume.mockReturnValueOnce(new Promise<any>((resolve) => { answer = resolve; }));
  await act(async () => { button(tree, 'Ya terminé').props.onPress(); });
  await act(async () => { jest.advanceTimersByTime(30_000); });
  await act(async () => { answer({ data: { resumeAgentTask: { success: false, errors: ['Se acabó el tiempo.'] } } }); });
  expect(texts(tree)).toContain('Se acabó el tiempo.');
});

it('a reopen that never answers is given up on: the buttons come back', async () => {
  mockTask = task({ reason: 'checkout', checkoutHanded: true, waitUntil: '2099-01-01T00:00:00Z' });
  const tree = await mount();
  mockOpen.mockReturnValueOnce(new Promise(() => undefined));
  await act(async () => { button(tree, 'La pantalla no responde').props.onPress(); });
  expect(button(tree, 'Ya terminé').props.disabled).toBe(true);
  await act(async () => { jest.advanceTimersByTime(25_000); });
  expect(texts(tree)).toContain('No pude abrir la pantalla de la tienda. Revisa tu conexión.');
  expect(appButton(tree, 'Abrir de nuevo').props.loading).toBe(false);
  await act(async () => { button(tree, 'Abrir de nuevo').props.onPress(); });
  expect(button(tree, 'Ya terminé').props.disabled).toBe(false);
});

it('refreshes wait for one still on its way instead of piling up', async () => {
  await mount();
  mockQuery.mockImplementationOnce(() => new Promise(() => undefined));
  const before = mockQuery.mock.calls.length;
  await act(async () => { jest.advanceTimersByTime(2500); });
  await act(async () => { jest.advanceTimersByTime(2500); });
  await act(async () => { jest.advanceTimersByTime(2500); });
  expect(mockQuery.mock.calls.length).toBe(before + 1);
});

it('a reload is offered only while a failed try still leaves time to open again', async () => {
  mockTask = task({ reason: 'checkout', checkoutHanded: true, waitUntil: new Date(Date.now() + 80_000).toISOString() });
  const tree = await mount();
  expect(button(tree, 'La pantalla no responde')).toBeUndefined();
});

it('a reopen that fails with no time left to retry keeps "Ya terminé": the page on screen is the recorded one', async () => {
  mockTask = task({ reason: 'checkout', checkoutHanded: true, waitUntil: new Date(Date.now() + 75_000).toISOString() });
  const tree = await mount();
  await act(async () => { webViews(tree)[0].props.onError(); });
  mockOpen.mockReturnValueOnce(new Promise(() => undefined));
  await act(async () => { button(tree, 'Abrir de nuevo').props.onPress(); });
  await act(async () => { jest.advanceTimersByTime(25_000); });  // 50 s left: no reopen possible
  expect(button(tree, 'Ya terminé').props.disabled).toBe(false);
});

it('an open given up on, answering after a newer one, does not replace it', async () => {
  mockTask = task({ reason: 'checkout', checkoutHanded: true, waitUntil: '2099-01-01T00:00:00Z' });
  const tree = await mount();
  let stale!: (v: any) => void;
  mockOpen.mockReturnValueOnce(new Promise<any>((resolve) => { stale = resolve; }));
  await act(async () => { button(tree, 'La pantalla no responde').props.onPress(); });
  await act(async () => { jest.advanceTimersByTime(25_000); });
  mockOpen.mockResolvedValueOnce({ data: { openAgentLiveView: { success: true, errors: [], url: `${LIVE}&new`,
    host: 'www.browserbase.com' } } });
  await act(async () => { button(tree, 'Abrir de nuevo').props.onPress(); });
  await act(async () => { stale({ data: { openAgentLiveView: { success: true, errors: [], url: `${LIVE}&old`,
    host: 'www.browserbase.com' } } }); });
  expect(webViews(tree)[0].props.source).toEqual({ uri: `${LIVE}&new` });
});

it('an open given up on, answering before anything newer, is not taken', async () => {
  mockTask = task({ reason: 'checkout', checkoutHanded: true, waitUntil: '2099-01-01T00:00:00Z' });
  const tree = await mount();
  let stale!: (v: any) => void;
  mockOpen.mockReturnValueOnce(new Promise<any>((resolve) => { stale = resolve; }));
  await act(async () => { button(tree, 'La pantalla no responde').props.onPress(); });
  await act(async () => { jest.advanceTimersByTime(25_000); });
  await act(async () => { stale({ data: { openAgentLiveView: { success: true, errors: [], url: `${LIVE}&old`,
    host: 'www.browserbase.com', view: 'view-old' } } }); });
  // Given up on: neither its page nor its tab is taken; "Ya terminé" names the screen still shown.
  expect(webViews(tree)[0].props.source).toEqual({ uri: LIVE });
  await act(async () => { button(tree, 'Ya terminé').props.onPress(); });
  expect(mockResume).toHaveBeenCalledWith({ variables: { id: ID, view: 'view-1' } });
});

it('a new turn does not send the last turn\'s token: its own screen must open first', async () => {
  mockTask = task({ reason: 'checkout', checkoutHanded: true, waitUntil: '2099-01-01T00:00:00Z' });
  const tree = await mount();
  mockOpen.mockRejectedValueOnce(new Error('network'));
  mockTask = task({ reason: 'screen', checkoutHanded: true, waitUntil: '2099-01-01T00:10:00Z' });
  await rerender(tree);
  expect(webViews(tree)).toHaveLength(1);  // the page stays...
  expect(button(tree, 'Ya terminé').props.disabled).toBe(true);  // ...but its tab was the last turn's
  mockOpen.mockResolvedValueOnce({ data: { openAgentLiveView: { success: true, errors: [], url: LIVE,
    host: 'www.browserbase.com', view: 'view-2' } } });
  await act(async () => { button(tree, 'Abrir de nuevo').props.onPress(); });
  await act(async () => { button(tree, 'Ya terminé').props.onPress(); });
  expect(mockResume).toHaveBeenLastCalledWith({ variables: { id: ID, view: 'view-2' } });
});

it('a token the server does not recognise is not sent again', async () => {
  const tree = await mount();
  mockResume.mockResolvedValueOnce({ data: { resumeAgentTask: { success: false, errorCode: 'view',
    errors: ['No reconozco esa pantalla. Ábrela de nuevo.'] } } });
  await act(async () => { button(tree, 'Ya terminé').props.onPress(); });
  expect(texts(tree)).toContain('No reconozco esa pantalla. Ábrela de nuevo.');
  mockResume.mockResolvedValueOnce({ data: { resumeAgentTask: { success: true, errors: [] } } });
  await act(async () => { button(tree, 'Ya terminé').props.onPress(); });
  expect(mockResume).toHaveBeenLastCalledWith({ variables: { id: ID, view: null } });
});

it('nothing runs for a screen that was left', async () => {
  const tree = await mount();
  mockResume.mockReturnValueOnce(new Promise(() => undefined));
  await act(async () => { button(tree, 'Ya terminé').props.onPress(); });
  act(() => { tree.unmount(); });
  mounted = [];
  const before = mockQuery.mock.calls.length;
  await act(async () => { jest.advanceTimersByTime(60_000); });
  expect(mockQuery.mock.calls.length).toBe(before);
});

it('the "wait" note goes away once the first tap is answered', async () => {
  const alert = jest.spyOn(Alert, 'alert').mockImplementation(() => undefined);
  const tree = await mount();
  let answer!: (v: any) => void;
  mockResume.mockReturnValueOnce(new Promise<any>((resolve) => { answer = resolve; }));
  await act(async () => { button(tree, 'Ya terminé').props.onPress(); });
  await act(async () => { button(tree, 'Cancelar').props.onPress(); });
  const confirm = (alert.mock.calls[0][2] as any[]).find((b) => b.style === 'destructive');
  await act(async () => { await confirm.onPress(); });
  await act(async () => { answer({ data: { resumeAgentTask: { success: true, errors: [] } } }); });
  expect(texts(tree)).not.toContain('Espera un momento: tu respuesta anterior todavía se está enviando.');
});

it('a second tap while the first is answered says so', async () => {
  const alert = jest.spyOn(Alert, 'alert').mockImplementation(() => undefined);
  const tree = await mount();
  mockResume.mockReturnValueOnce(new Promise(() => undefined));
  await act(async () => { button(tree, 'Ya terminé').props.onPress(); });
  await act(async () => { button(tree, 'Cancelar').props.onPress(); });
  const confirm = (alert.mock.calls[0][2] as any[]).find((b) => b.style === 'destructive');
  await act(async () => { await confirm.onPress(); });
  expect(mockCancel).not.toHaveBeenCalled();
  expect(texts(tree)).toContain('Espera un momento: tu respuesta anterior todavía se está enviando.');
});

it('a first read that failed keeps trying, and can be retried by hand', async () => {
  mockQuery.mockRejectedValueOnce(new Error('offline'));
  const tree = await mount();
  expect(texts(tree)).toContain('No pude leer la tarea. Revisa tu conexión.');
  expect(button(tree, 'Reintentar')).toBeDefined();
  await rerender(tree);
  expect(texts(tree)).toContain('Necesito que inicies sesión en mercadolibre.com.mx.');
});

it('"Ya terminé" waits while the screen is being opened again (another tab may be recorded)', async () => {
  mockTask = task({ reason: 'checkout', checkoutHanded: true, waitUntil: '2099-01-01T00:00:00Z' });
  const tree = await mount();
  let opened!: (v: any) => void;
  mockOpen.mockReturnValueOnce(new Promise<any>((resolve) => { opened = resolve; }));
  await act(async () => { button(tree, 'La pantalla no responde').props.onPress(); });
  expect(button(tree, 'Ya terminé').props.disabled).toBe(true);
  await act(async () => { opened({ data: { openAgentLiveView: { success: true, errors: [], url: LIVE,
    host: 'www.browserbase.com' } } }); });
  expect(button(tree, 'Ya terminé').props.disabled).toBe(false);
});

it('"Ya terminé" waits for this turn\'s screen, and polls never share a request', async () => {
  let opened!: (v: unknown) => void;
  mockOpen.mockReturnValueOnce(new Promise((resolve) => { opened = resolve; }));
  const tree = await mount();
  // Refreshes never come from (or go to) the cache, and never join a request already on its way.
  expect(mockQueryOptions.fetchPolicy).toBe('no-cache');
  expect(mockQueryOptions.context).toEqual({ queryDeduplication: false });
  expect(button(tree, 'Ya terminé').props.disabled).toBe(true);
  await act(async () => { opened({ data: { openAgentLiveView: { success: true, errors: [], url: LIVE,
    host: 'www.browserbase.com' } } }); });
  expect(button(tree, 'Ya terminé').props.disabled).toBe(false);
});

it('"Ya terminé" takes the focus off the store page, which closes its keyboard', async () => {
  const { TextInput } = require('react-native');
  const tree = await mount();
  const sink = tree.root.findByType(TextInput);
  expect(sink.props.showSoftInputOnFocus).toBe(false);
  const focus = jest.spyOn(sink.instance, 'focus');
  const blur = jest.spyOn(sink.instance, 'blur');
  await act(async () => { button(tree, 'Ya terminé').props.onPress(); });
  expect(focus).toHaveBeenCalled();
  expect(blur).toHaveBeenCalled();
});

it('two quick taps send one "Ya terminé"', async () => {
  let done!: (v: unknown) => void;
  mockResume.mockReturnValueOnce(new Promise((resolve) => { done = resolve; }));
  const tree = await mount();
  const press = button(tree, 'Ya terminé').props.onPress;
  await act(async () => { press(); press(); });
  await act(async () => { done({ data: { resumeAgentTask: { success: true, errors: [] } } }); });
  expect(mockResume).toHaveBeenCalledTimes(1);
});

it('"Ya terminé" hands the turn back, and the screen closes when the agent takes the browser again', async () => {
  const tree = await mount();
  await act(async () => { button(tree, 'Ya terminé').props.onPress(); });
  // The screen on display names its tab: that one is read.
  expect(mockResume).toHaveBeenCalledWith({ variables: { id: ID, view: 'view-1' } });
  mockTask = task({ status: 'working', reason: '' });
  await rerender(tree);
  expect(webViews(tree)).toHaveLength(0);
  expect(button(tree, 'Ya terminé')).toBeUndefined();
});

it('after the hand-over the page stays as the person left it while the code is read', async () => {
  mockTask = task({ reason: 'checkout', checkoutHanded: true, waitUntil: '2099-01-01T00:00:00Z' });
  const tree = await mount();
  expect(texts(tree).some((t) => t.startsWith('Tiempo restante'))).toBe(true);
  mockTask = task({ status: 'awaiting_code', reason: 'checkout', checkoutHanded: true });
  await rerender(tree);
  expect(webViews(tree)).toHaveLength(1);
  expect(mockOpen).toHaveBeenCalledTimes(1);
  // Back to the person (the code was not read): asked again, the same URL keeps the page.
  mockTask = task({ reason: 'screen', checkoutHanded: true });
  await rerender(tree);
  expect(mockOpen).toHaveBeenCalledTimes(2);
  expect(webViews(tree)[0].props.source).toEqual({ uri: LIVE });
  // A Mexican store's fallback is the bank (the message says so): no chat button.
  expect(button(tree, 'Abrir el chat')).toBeUndefined();
  // Paid card ready: the screen closes and the chat holds the payment.
  mockTask = task({ status: 'payment_ready', reason: '', checkoutHanded: true });
  await rerender(tree);
  expect(webViews(tree)).toHaveLength(0);
  expect(button(tree, 'Ver el pago')).toBeDefined();
});

it('a Brazilian store\'s unread Pix code is pasted in the chat', async () => {
  mockTask = task({ site: 'mercadolivre.com.br', reason: 'unsigned', checkoutHanded: true });
  const tree = await mount();
  await act(async () => { button(tree, 'Abrir el chat').props.onPress(); });
  expect(mockChat).toHaveBeenCalledWith({ channel: 'ia' });
});

it('says why the screen did not open, and lets the person ask again', async () => {
  mockOpen.mockResolvedValueOnce({ data: { openAgentLiveView: {
    success: false, errors: ['Ya no hay tiempo para abrir la pantalla.'], errorCode: 'expired' } } });
  const tree = await mount();
  expect(webViews(tree)).toHaveLength(0);
  expect(texts(tree)).toContain('Ya no hay tiempo para abrir la pantalla.');
  expect(button(tree, 'Ya terminé').props.disabled).toBe(true);
  await act(async () => { button(tree, 'Abrir de nuevo').props.onPress(); });
  expect(webViews(tree)).toHaveLength(1);
});

it('asks before cancelling', async () => {
  const alert = jest.spyOn(Alert, 'alert').mockImplementation(() => undefined);
  const tree = await mount();
  await act(async () => { button(tree, 'Cancelar').props.onPress(); });
  expect(mockCancel).not.toHaveBeenCalled();
  const confirm = (alert.mock.calls[0][2] as any[]).find((b) => b.style === 'destructive');
  await act(async () => { await confirm.onPress(); });
  expect(mockCancel).toHaveBeenCalledWith({ variables: { id: ID } });
});

it('says so when the task is not this person\'s or does not exist', async () => {
  mockTask = null;
  const tree = await mount();
  expect(texts(tree).some((t) => t.startsWith('No encontré esta tarea.'))).toBe(true);
  expect(texts(tree).some((t) => t.includes('cuenta personal'))).toBe(true);
  expect(mockOpen).not.toHaveBeenCalled();
});
