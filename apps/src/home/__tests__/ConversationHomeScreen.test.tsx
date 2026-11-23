// Inicio in the conversation home: header (menu, money line, Cobrar, bell),
// the conversation, and the old Home's background work kept running unseen.
import React from 'react';
import { Text as RNText } from 'react-native';
import renderer, { act } from 'react-test-renderer';

const mockNavigate = jest.fn();
const mockOpenMonth = jest.fn();
const mockSetHomeActive = jest.fn();
const mockOpenDrawer = jest.fn();
let mockFocused = true;
let mockBoxOpen = false;
let mockHomeSeq = 0;
let mockAccount: any = { id: 'personal_0', type: 'personal' };
let mockDrawer: any;
let mockUnreadNotifications = 0;

const mockLogHomeNav = jest.fn();
jest.mock('../../services/homeNavAnalytics', () => ({ logHomeNav: (...args: unknown[]) => mockLogHomeNav(...args) }));
jest.mock('react-native-vector-icons/Feather', () => 'Icon');
jest.mock('react-native-safe-area-context', () => ({ SafeAreaView: require('react-native').View }));
jest.mock('@react-navigation/native', () => ({
  useNavigation: () => ({ navigate: mockNavigate }),
  useIsFocused: () => mockFocused,
}));
jest.mock('../../components/common/AppText', () => ({ Text: require('react-native').Text }));
jest.mock('../../components/QrPayIcon', () => ({ QrShowIcon: 'QrShowIcon' }));
jest.mock('../../assistant/AssistantSheet', () => 'AssistantSheet');
jest.mock('../../assistant/AssistantContext', () => ({
  useAssistant: () => ({ isOpen: mockBoxOpen, setHomeActive: mockSetHomeActive, homeSeq: mockHomeSeq }),
}));
jest.mock('../../contexts/AccountContext', () => ({ useAccount: () => ({ activeAccount: mockAccount }) }));
jest.mock('../../contexts/AuthContext', () => ({ useAuth: () => ({ userProfile: { firstName: ' Ana ' } }) }));
jest.mock('../../contexts/HeaderContext', () => ({ useHeader: () => ({ unreadNotifications: mockUnreadNotifications }) }));
jest.mock('../../navigation/Header', () => ({ Header: 'Header', HEADER_HEIGHT: 64 }));
jest.mock('../../screens/HomeScreen', () => ({ HomeScreen: 'HomeScreen' }));
jest.mock('../AppDrawer', () => ({ useAppDrawer: () => mockDrawer }));
jest.mock('../usePrimaryAction', () => ({ usePrimaryAction: () => ({ kind: 'pay', onPress: jest.fn() }) }));

import { ConversationHomeScreen } from '../ConversationHomeScreen';
import { sharedHomeMoneyStore, type HomeMoney } from '../homeMoneyStore';

// No drawer provider in these tests: the screen reads the shared store.
const publishHomeMoney = (next: HomeMoney) => sharedHomeMoneyStore.publish(next);
const resetHomeMoney = () => sharedHomeMoneyStore.reset();

const money = (over: Partial<HomeMoney> = {}): HomeMoney => ({
  ready: true, total: 'US$254,30', masked: false, canToggle: true, toggleBalance: jest.fn(),
  currencyCode: 'USD', currencyHint: 'Mostrar en bolivianos', toggleCurrency: jest.fn(), refresh: jest.fn(),
  accounts: [], switchAccount: jest.fn(), createBusiness: jest.fn(),
  month: { kind: 'month', summary: { year: 2026, month: 11, current: { incomeUsd: '340', spendingUsd: '185' } } as any },
  openMonth: mockOpenMonth, tiles: [], actions: [], notice: null, ...over,
});
const texts = (tree: renderer.ReactTestRenderer) =>
  tree.root.findAllByType(RNText).map((n) => [n.props.children].flat(Infinity).join(''));
const labels = (tree: renderer.ReactTestRenderer) => tree.root
  .findAll((n) => typeof n.props.accessibilityLabel === 'string' && typeof n.props.onPress === 'function')
  .map((n) => n.props.accessibilityLabel as string);
const press = async (tree: renderer.ReactTestRenderer, label: string) => {
  const node = tree.root.findAll((n) => n.props.accessibilityLabel === label && typeof n.props.onPress === 'function')[0];
  if (!node) throw new Error(`no button ${label}; have ${labels(tree).join(' | ')}`);
  await act(async () => { node.props.onPress(); });
};
async function mount() {
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<ConversationHomeScreen />); });
  await act(async () => { await Promise.resolve(); });
  return tree;
}
const conversation = (tree: renderer.ReactTestRenderer) => tree.root.findByType('AssistantSheet' as any).props.home;

beforeEach(() => {
  jest.clearAllMocks();
  mockFocused = true;
  mockBoxOpen = false;
  mockHomeSeq = 0;
  mockAccount = { id: 'personal_0', type: 'personal' };
  mockUnreadNotifications = 0;
  mockDrawer = { isOpen: false, open: mockOpenDrawer, close: jest.fn(), hasNews: false, openGesture: { onGesture: 'open' } };
  resetHomeMoney();
});

it('the header says the total and what came in and went out; the total opens the menu and the month "Tu mes"', async () => {
  publishHomeMoney(money());
  const tree = await mount();
  // The month figures carry the currency, like the total.
  expect(texts(tree)).toEqual(expect.arrayContaining(['US$254,30', 'US$340', 'US$185']));
  await press(tree, 'Menú');
  await press(tree, 'Mi dinero: US$254,30. Abrir menú');
  expect(mockOpenDrawer).toHaveBeenCalledTimes(2);
  // One tap, as the month line on the old Inicio.
  await press(tree, 'Tu mes: entraron 340 dólares y salieron 185. Abrir tu mes');
  expect(mockOpenMonth).toHaveBeenCalledTimes(1);
  expect(mockOpenDrawer).toHaveBeenCalledTimes(2);
  await press(tree, 'Cobrar');
  expect(mockNavigate).toHaveBeenLastCalledWith('Charge');
  await press(tree, 'Notificaciones');
  expect(mockNavigate).toHaveBeenLastCalledWith('Notification');
  expect(mockLogHomeNav.mock.calls).toEqual(
    [['header', 'menu'], ['header', 'money'], ['header', 'month'], ['header', 'charge'], ['header', 'notifications']]);
  await act(async () => tree.unmount());
});

it('a hidden balance shows neither the total nor the month figures', async () => {
  publishHomeMoney(money({ masked: true, total: '••••••' }));
  const tree = await mount();
  const all = texts(tree);
  expect(all).toContain('••••••');
  expect(all.join(' ')).not.toMatch(/340|185/);
  expect(labels(tree)).toContain('Mi dinero, saldo oculto. Abrir menú');
  expect(labels(tree).some((l) => l.startsWith('Tu mes'))).toBe(false);
  await act(async () => tree.unmount());
});

it('before the first balances answer nothing is drawn as an amount, the month included', async () => {
  // The month can be known before the balances are: it never sits under a blank total.
  publishHomeMoney(money({ ready: false }));
  const tree = await mount();
  expect(texts(tree).join('')).not.toMatch(/US\$|\d/);
  expect(labels(tree).some((l) => l.startsWith('Tu mes'))).toBe(false);
  expect(labels(tree)).toContain('Mi dinero. Abrir menú');
  await act(async () => tree.unmount());
});

it('badges: news behind the menu and unread notifications', async () => {
  mockDrawer.hasNews = true;
  mockUnreadNotifications = 3;
  publishHomeMoney(money());
  const tree = await mount();
  expect(labels(tree)).toEqual(expect.arrayContaining(['Menú, hay novedades', 'Notificaciones, 3 sin leer']));
  expect(texts(tree)).toContain('3');
  await act(async () => tree.unmount());
});

it('a business: the header names the account and has no Cobrar icon (it is the main button)', async () => {
  mockAccount = { id: 'business_1_0', type: 'business', business: { name: 'Panadería' } };
  publishHomeMoney(money());
  let tree = await mount();
  expect(texts(tree)).toContain('Negocio · Panadería');
  expect(labels(tree)).not.toContain('Cobrar');
  // Its name takes the second line: the month is in the menu.
  expect(labels(tree).some((l) => l.startsWith('Tu mes'))).toBe(false);
  expect(texts(tree).join(' ')).not.toContain('340');
  expect(labels(tree).some((l) => l.startsWith('Negocio · Panadería. Mi dinero'))).toBe(true);
  await act(async () => tree.unmount());

  mockAccount = { ...mockAccount, isEmployee: true };
  tree = await mount();
  expect(texts(tree)).toContain('Empleado · Panadería');
  await act(async () => tree.unmount());
});

it('the conversation gets the name, the main button and the notice, and is live only while it is what is on screen', async () => {
  const notice = { key: 'pendingIncoming', icon: 'download', text: 'Tienes dinero por recibir', onPress: jest.fn() };
  publishHomeMoney(money({ notice }));
  let tree = await mount();
  expect(conversation(tree)).toMatchObject({ active: true, name: 'Ana', notice });
  expect(conversation(tree).primary.kind).toBe('pay');
  conversation(tree).primary.onPress();
  expect(mockLogHomeNav).toHaveBeenLastCalledWith('composer', 'pay');
  expect(mockSetHomeActive).toHaveBeenLastCalledWith(true);
  await act(async () => tree.unmount());
  // Unmounting hands requests back to the floating box.
  expect(mockSetHomeActive).toHaveBeenLastCalledWith(false);

  // The box is open over Inicio (Julian's channel): the conversation pauses but still owns requests.
  mockBoxOpen = true;
  tree = await mount();
  expect(conversation(tree).active).toBe(false);
  expect(mockSetHomeActive).toHaveBeenLastCalledWith(true);
  await act(async () => tree.unmount());

  // Another screen is in front.
  mockBoxOpen = false;
  mockFocused = false;
  tree = await mount();
  expect(conversation(tree).active).toBe(false);
  expect(mockSetHomeActive).toHaveBeenCalledWith(false);
  await act(async () => tree.unmount());
});

it('the old Home runs behind it for its background work and dialogs only: there is no second money screen', async () => {
  publishHomeMoney(money());
  const tree = await mount();
  // Embedded: it draws its dialogs and nothing else (see HomeScreen).
  expect(tree.root.findAllByType('HomeScreen' as any)).toHaveLength(1);
  expect(tree.root.findByType('HomeScreen' as any).props.embedded).toBe(true);
  // No header of another screen is ever drawn over the conversation.
  expect(tree.root.findAllByType('Header' as any)).toHaveLength(0);
  await act(async () => tree.unmount());
});

it('a sideways drag on the conversation pulls the menu open', async () => {
  publishHomeMoney(money());
  const tree = await mount();
  expect(tree.root.findAll((n) => n.props.onGesture === 'open').length).toBeGreaterThan(0);
  await act(async () => tree.unmount());
});
