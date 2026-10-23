import React from 'react';
import renderer, { act } from 'react-test-renderer';

let mockAccount: any = { id: 'personal', type: 'personal' };
const mockRefetch = jest.fn();
jest.mock('@react-navigation/native', () => ({ useNavigation: () => ({ navigate: jest.fn() }) }));
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
}));
jest.mock('../../contexts/HeaderContext', () => ({ useHeader: () => ({ profileMenu: { openProfileMenu: jest.fn() } }) }));
jest.mock('../../contexts/AccountContext', () => ({ useAccount: () => ({ activeAccount: mockAccount }) }));
jest.mock('../../contexts/AuthContext', () => ({ useAuth: () => ({ isAuthenticated: true }) }));
jest.mock('../../apollo/queries', () => ({ GET_MESSAGE_INBOX_UNREAD_COUNT: 'unread' }));
jest.mock('@apollo/client', () => ({ useQuery: () => ({ refetch: mockRefetch }) }));

import { BottomTabNavigator } from '../BottomTabNavigator';
import { exitToDiscover } from '../exitToDiscover';
import { DiscoverEntryScreen } from '../../screens/DiscoverEntryScreen';

it('switches the center tab when switching between personal and business accounts', async () => {
  mockAccount = { id: 'personal', type: 'personal' };
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<BottomTabNavigator />); });
  const routes = () => tree.root.findAllByType('Screen' as any).map(s => s.props.name);
  expect(routes()).toEqual(['Home', 'Invest', 'Scan', 'Comprar', 'Profile']);
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
