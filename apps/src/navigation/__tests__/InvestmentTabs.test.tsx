import React from 'react';
import renderer, { act } from 'react-test-renderer';

let mockAccount: any = { id: 'personal', type: 'personal' };
const mockRefetch = jest.fn();
let mockFocusedTab: string | undefined;
jest.mock('@react-navigation/native', () => ({
  useNavigation: () => ({ navigate: jest.fn() }),
  useRoute: () => ({ key: 'BottomTabs-1', name: 'BottomTabs' }),
  // The parent stack's raw state: this shell under a pushed screen.
  useNavigationState: (select: (state: unknown) => unknown) => select({
    index: 1,
    routes: [{ key: 'BottomTabs-1', name: 'BottomTabs', focused: mockFocusedTab }, { key: 'StockDetail-2', name: 'StockDetail' }],
  }),
  getFocusedRouteNameFromRoute: (route: { focused?: string }) => route.focused,
}));
jest.mock('@react-navigation/bottom-tabs', () => ({ createBottomTabNavigator: () => ({ Navigator: 'Navigator', Screen: 'Screen' }) }));
jest.mock('react-native-vector-icons/Feather', () => 'Icon');
jest.mock('../../screens/HomeScreen', () => ({ HomeScreen: 'HomeScreen' }));
jest.mock('../../screens/InvestTabScreen', () => ({ InvestTabScreen: 'InvestTabScreen' }));
jest.mock('../../screens/ComprarScreen', () => ({ ComprarScreen: 'ComprarScreen' }));
jest.mock('../../screens/ScanTab', () => 'ScanTab');
jest.mock('../../screens/ChargeScreen', () => ({ ChargeScreen: 'ChargeScreen' }));
jest.mock('../../screens/ProfileScreen', () => ({ ProfileScreen: 'ProfileScreen' }));
jest.mock('../Header', () => ({ Header: 'Header' }));
jest.mock('../../components/QrPayIcon', () => ({ QrPayIcon: 'QrPayIcon' }));
jest.mock('../../services/communityPeek', () => ({
  useCommunityPeek: () => ({ items: [], lastSeenAt: null, lastSeenId: 0, loaded: false, unread: 0, neverOpened: false }),
  peekBadge: () => null,
  refreshCommunityPeek: jest.fn(),
  watchCommunityPeek: () => () => {},
}));
jest.mock('../../contexts/HeaderContext', () => ({ useHeader: () => ({ profileMenu: { openProfileMenu: jest.fn() } }) }));
jest.mock('../../contexts/AccountContext', () => ({ useAccount: () => ({ activeAccount: mockAccount }) }));
jest.mock('../../contexts/AuthContext', () => ({ useAuth: () => ({ isAuthenticated: true }) }));
jest.mock('../../apollo/queries', () => ({ GET_MESSAGE_INBOX_UNREAD_COUNT: 'unread' }));
jest.mock('@apollo/client', () => ({ useQuery: () => ({ refetch: mockRefetch }) }));
// The flag is a build constant: each test picks the navigator it is about.
let mockConversationHome = false;
jest.mock('../../config/features', () => {
  const mock = {};
  Object.defineProperties(mock, Object.getOwnPropertyDescriptors(jest.requireActual('../../config/features')));
  Object.defineProperty(mock, 'CONVERSATION_HOME_ENABLED', { get: () => mockConversationHome });
  return mock;
});
const mockLogHomeNav = jest.fn();
jest.mock('../../services/homeNavAnalytics', () => ({ logHomeNav: (...args: unknown[]) => mockLogHomeNav(...args) }));
jest.mock('../../home/AppDrawer', () => ({ AppDrawerProvider: 'AppDrawerProvider' }));
jest.mock('../../home/ConversationHomeScreen', () => ({ ConversationHomeScreen: 'ConversationHomeScreen' }));
jest.mock('../../home/DrawerHeader', () => ({ DrawerHeader: 'DrawerHeader' }));
jest.mock('../../home/FloatingPrimaryButton', () => ({ FloatingPrimaryButton: 'FloatingPrimaryButton' }));

import { BottomTabNavigator } from '../BottomTabNavigator';
import { exitToDiscover } from '../exitToDiscover';
import { DiscoverEntryScreen } from '../../screens/DiscoverEntryScreen';

afterEach(() => {
  mockConversationHome = false;
  mockFocusedTab = undefined;
  mockLogHomeNav.mockClear();
});

it('conversation home: opened straight on a drawer screen, the floating Pagar knows it from the first render', async () => {
  mockConversationHome = true;
  mockFocusedTab = 'Comprar';
  mockAccount = { id: 'personal', type: 'personal' };
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<BottomTabNavigator />); });
  expect(tree.root.findByType('FloatingPrimaryButton' as any).props.tab).toBe('Comprar');
  await act(async () => tree.unmount());
});

it('conversation home: no tab bar, the same routes minus the Pagar tab, and Inicio is the conversation', async () => {
  mockConversationHome = true;
  mockAccount = { id: 'personal', type: 'personal' };
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<BottomTabNavigator />); });
  const screens = () => tree.root.findAllByType('Screen' as any);
  const routes = () => screens().map(s => s.props.name);
  const navigator = () => tree.root.findByType('Navigator' as any);
  // Pagar opens the stack's scanner, which has the back arrow a screen without tabs needs.
  expect(routes()).toEqual(['Home', 'Invest', 'Comprar', 'Profile']);
  expect(screens()[0].props.component).toBe('ConversationHomeScreen');
  expect(screens()[0].props.options.headerShown).toBe(false);
  // Inicio keeps publishing balances for the drawer while another screen is in front.
  expect(screens()[0].props.options.freezeOnBlur).toBe(false);
  expect(navigator().props.tabBar()).toBeNull();
  expect(tree.root.findAllByType('AppDrawerProvider' as any)).toHaveLength(1);
  // The floating Pagar button is told which screen is in front and places itself.
  expect(tree.root.findByType('FloatingPrimaryButton' as any).props.tab).toBe('Home');
  for (const tab of ['Invest', 'Comprar', 'Profile', 'Home']) {
    mockFocusedTab = tab;
    await act(async () => { tree.update(<BottomTabNavigator />); });
    expect(tree.root.findByType('FloatingPrimaryButton' as any).props.tab).toBe(tab);
  }

  // A business keeps Cobrar as a route (Recibir and the payment receipt return to it).
  mockAccount = { id: 'business', type: 'business' };
  await act(async () => { tree.update(<BottomTabNavigator />); });
  expect(routes()).toEqual(['Home', 'Invest', 'Charge', 'Comprar', 'Profile']);

  // A Cuenta inteligente context keeps its own home and its tab bar; the wrapper stays (no remount).
  mockAccount = { id: 'smart', type: 'smart', index: 0 };
  await act(async () => { tree.update(<BottomTabNavigator />); });
  expect(routes()).toEqual(['Home', 'Profile']);
  expect(navigator().props.tabBar).toBeUndefined();
  expect(tree.root.findAllByType('AppDrawerProvider' as any)).toHaveLength(1);
  expect(tree.root.findAllByType('FloatingPrimaryButton' as any)).toHaveLength(0);
  await act(async () => tree.unmount());
});

it('switches the center tab when switching between personal and business accounts', async () => {
  mockAccount = { id: 'personal', type: 'personal' };
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<BottomTabNavigator />); });
  const routes = () => tree.root.findAllByType('Screen' as any).map(s => s.props.name);
  expect(routes()).toEqual(['Home', 'Invest', 'Scan', 'Comprar', 'Profile']);
  // Tab taps are counted under the same names the conversation home's doors use.
  const listeners = tree.root.findByType('Navigator' as any).props.screenListeners;
  listeners({ route: { name: 'Scan' } }).tabPress();
  listeners({ route: { name: 'Invest' } }).tabPress();
  expect(mockLogHomeNav.mock.calls).toEqual([['tabs', 'pay'], ['tabs', 'invest']]);
  mockAccount = { id: 'business', type: 'business' };
  await act(async () => { tree.update(<BottomTabNavigator />); });
  expect(routes()).toEqual(['Home', 'Invest', 'Charge', 'Comprar', 'Profile']);
  mockAccount = { id: 'employee', type: 'business', isEmployee: true, employeePermissions: { sendFunds: false } };
  await act(async () => { tree.update(<BottomTabNavigator />); });
  expect(routes()).toEqual(['Home', 'Invest', 'Charge', 'Comprar', 'Profile']);
  await act(async () => tree.unmount());
});

it('clears the abandoned trade stack back to Inicio', () => {
  const reset = jest.fn();
  exitToDiscover({ reset });
  expect(reset).toHaveBeenCalledWith({ index: 0, routes: [{ name: 'BottomTabs', params: { screen: 'Home' } }] });
});

it('routes old feed links to Invertir › Comunidad without adding another feed screen', async () => {
  const popTo = jest.fn();
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<DiscoverEntryScreen navigation={{ popTo } as any} route={{ key: 'discover', name: 'Discover' }} />); });
  expect(popTo).toHaveBeenCalledWith('BottomTabs', { screen: 'Invest', params: { segment: 'community' } });
  await act(async () => tree.unmount());
});
