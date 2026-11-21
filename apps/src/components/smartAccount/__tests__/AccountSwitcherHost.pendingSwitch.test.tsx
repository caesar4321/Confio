// A notification tapped while the Cuenta inteligente (or an inherited account)
// is the active context stores a pending switch and opens the Home tab. That
// tab is the smart home, whose AccountSwitcherHost must consume the switch and
// then run the deferred navigation, exactly as HomeScreen does.
import React from 'react';
import renderer, { act } from 'react-test-renderer';

let mockPendingSwitch: string | null = null;
let mockPendingNavigation: (() => void) | null = null;
jest.mock('../../../services/pushNotificationService', () => ({
  PushNotificationService: {
    getPendingAccountSwitch: () => mockPendingSwitch,
    getPendingNavigation: () => mockPendingNavigation,
    clearPendingAccountSwitch: () => { mockPendingSwitch = null; },
    clearPendingNavigation: () => { mockPendingNavigation = null; },
  },
}));
jest.mock('@react-navigation/native', () => {
  const ReactLocal = require('react');
  return {
    useNavigation: () => ({ navigate: jest.fn() }),
    // Focus = mount, for this test.
    useFocusEffect: (cb: () => (() => void) | void) => { ReactLocal.useEffect(cb, [cb]); },
  };
});
jest.mock('../../ProfileMenu', () => ({ ProfileMenu: () => null }));
jest.mock('../../AccountSwitchOverlay', () => ({ AccountSwitchOverlay: () => null }));
jest.mock('../../../contexts/HeaderContext', () => ({
  useHeader: () => ({ profileMenu: { showProfileMenu: false, closeProfileMenu: jest.fn() } }),
}));
jest.mock('../../../contexts/AccountContext', () => ({
  useAccount: () => ({ accounts: [], activeAccount: { id: 'smart_0', type: 'smart' } }),
}));
const mockSwitchAccount = jest.fn();
jest.mock('../../../hooks/useAtomicAccountSwitch', () => ({
  useAtomicAccountSwitch: () => ({ switchAccount: mockSwitchAccount, state: { isLoading: false, progress: '' } }),
}));

import { AccountSwitcherHost } from '../AccountSwitcherHost';
import { PENDING_NAVIGATION_DELAY_MS, PENDING_SWITCH_READ_DELAY_MS } from '../../../hooks/usePendingNotificationSwitch';

let tree: renderer.ReactTestRenderer | undefined;
beforeEach(() => {
  jest.useFakeTimers();
  mockSwitchAccount.mockReset();
  mockPendingSwitch = null;
  mockPendingNavigation = null;
});
afterEach(() => {
  if (tree) { act(() => tree!.unmount()); tree = undefined; }
  jest.useRealTimers();
});

const settle = async (ms: number) => {
  await act(async () => { jest.advanceTimersByTime(ms); });
  await act(async () => { await Promise.resolve(); await Promise.resolve(); });
};

it('switches to the pending account, then runs the deferred navigation once', async () => {
  const navigate = jest.fn();
  mockPendingSwitch = 'personal_0';
  mockPendingNavigation = navigate;
  mockSwitchAccount.mockResolvedValue(true);

  act(() => { tree = renderer.create(<AccountSwitcherHost />); });
  await settle(PENDING_SWITCH_READ_DELAY_MS);
  expect(mockSwitchAccount).toHaveBeenCalledWith('personal_0');
  // Consumed: nobody else (HomeScreen mounting after the switch) runs it again.
  expect(mockPendingSwitch).toBeNull();
  expect(mockPendingNavigation).toBeNull();
  expect(navigate).not.toHaveBeenCalled();

  // The switch swaps the Home tab to HomeScreen: the navigation still runs.
  act(() => tree!.unmount());
  tree = undefined;
  await settle(PENDING_NAVIGATION_DELAY_MS);
  expect(navigate).toHaveBeenCalledTimes(1);
});

it('does not navigate when the switch fails', async () => {
  const navigate = jest.fn();
  mockPendingSwitch = 'business_7_0';
  mockPendingNavigation = navigate;
  mockSwitchAccount.mockResolvedValue(false);

  act(() => { tree = renderer.create(<AccountSwitcherHost />); });
  await settle(PENDING_SWITCH_READ_DELAY_MS);
  await settle(PENDING_NAVIGATION_DELAY_MS);
  expect(mockSwitchAccount).toHaveBeenCalledWith('business_7_0');
  expect(navigate).not.toHaveBeenCalled();
});

it('does nothing without both a pending switch and a navigation', async () => {
  mockPendingSwitch = 'personal_0';
  act(() => { tree = renderer.create(<AccountSwitcherHost />); });
  await settle(PENDING_SWITCH_READ_DELAY_MS);
  expect(mockSwitchAccount).not.toHaveBeenCalled();
  expect(mockPendingSwitch).toBe('personal_0');
});
