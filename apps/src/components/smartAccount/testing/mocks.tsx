// Shared jest mocks for the Cuenta inteligente screen tests. Import this file
// FIRST in a test: it registers the mocks before the screen under test loads.
// Not imported by app code.
/* eslint-env jest */
import React from 'react';

export const nav = {
  navigate: jest.fn(),
  goBack: jest.fn(),
  replace: jest.fn(),
  popTo: jest.fn(),
  push: jest.fn(),
  reset: jest.fn(),
  addListener: jest.fn(() => () => {}),
};
let routeParams: any;
export const setRouteParams = (params: any) => {
  routeParams = params;
};

jest.mock('@react-navigation/native', () => {
  const m = require('./mocks');
  return {
    useNavigation: () => m.nav,
    useRoute: () => ({ params: m.currentRouteParams() }),
  };
});
export const currentRouteParams = () => routeParams;

jest.mock('react-native-safe-area-context', () => ({
  useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }),
}));
jest.mock('react-native-vector-icons/Feather', () => 'Icon');
jest.mock('../../svg/CuentaInteligenteMark', () => 'CuentaInteligenteMark');
jest.mock('../../SkeletonLoader', () => ({ SkeletonLoader: 'SkeletonLoader' }));
jest.mock('../AssetMark', () => ({ AssetMark: 'AssetMark' }));
jest.mock('../../../services/paidOffers', () => ({ logOfferStep: jest.fn(), logSmartAccountFunnel: jest.fn() }));
// The device record for the direct claim path: recorded, never stored.
export const rememberedDirect: any[] = [];
jest.mock('../useRememberDirectClaim', () => {
  const m = require('./mocks');
  return {
    useRememberDirectClaim: (list: any[] | null | undefined, toEntry: (x: any) => any) => {
      (list ?? []).map(toEntry).filter(Boolean).forEach((e: any) => m.rememberedDirect.push(e));
    },
    rememberDirectClaim: jest.fn(),
  };
});
// The direct (serverless) claim glue: every call is a jest.fn.
jest.mock('../../../services/smartAccountDirect', () => ({
  loadDirectEntry: jest.fn(),
  loadInheritedDirectEntry: jest.fn(),
  loadOfflineDesignations: jest.fn(async () => []),
  ownWalletAddress: jest.fn(),
  readDirectSituation: jest.fn(),
  runDirectStep: jest.fn(),
}));

// The shared Header: its title and whatever sits on its right.
jest.mock('../../../navigation/Header', () => {
  const ReactLocal = require('react');
  const { View, Text } = require('react-native');
  return {
    Header: ({ title, rightAccessory }: any) => ReactLocal.createElement(
      View, { testID: 'header' }, ReactLocal.createElement(Text, null, title), rightAccessory,
    ),
  };
});

// The person picker: a button that picks Ana.
jest.mock('../ConfioContactPicker', () => {
  const ReactLocal = require('react');
  const { Pressable } = require('react-native');
  return {
    ConfioContactPicker: ({ visible, onPick }: any) => (visible
      ? ReactLocal.createElement(Pressable, { testID: 'pick-ana', onPress: () => onPick({ handle: 'ana', name: 'Ana P.' }) })
      : null),
  };
});

jest.mock('../AccountSwitcherHost', () => {
  const m = require('./mocks');
  return {
    AccountSwitcherHost: () => null,
    useReturnToPersonal: () => ({ returnToPersonal: m.returnToPersonal, switching: false, progress: '' }),
  };
});
export const returnToPersonal = jest.fn();

export const profileMenu = { showProfileMenu: false, openProfileMenu: jest.fn(), closeProfileMenu: jest.fn() };
jest.mock('../../../contexts/HeaderContext', () => {
  const m = require('./mocks');
  return { useHeader: () => ({ profileMenu: m.profileMenu }) };
});
let activeAccount: any = { id: 'personal_0', type: 'personal', index: 0, avatar: 'J' };
export const setActiveAccount = (account: any) => {
  activeAccount = account;
};
export const currentActiveAccount = () => activeAccount;
jest.mock('../../../contexts/AccountContext', () => {
  const m = require('./mocks');
  return { useAccount: () => ({ activeAccount: m.currentActiveAccount(), accounts: [] }) };
});

// Every read and prepare is a jest.fn; the pure helpers stay real.
jest.mock('../../../services/smartAccount', () => {
  const actual = jest.requireActual('../../../services/smartAccount');
  const mocked: Record<string, unknown> = { ...actual };
  Object.keys(actual).forEach((key) => {
    if (/^(fetch|prepare|decline|delete|signAndSubmit)/.test(key)) {
      mocked[key] = jest.fn();
    }
  });
  return mocked;
});

// The Home eye toggle ("ocultar saldo").
let balanceHidden = false;
export const setBalanceHidden = (v: boolean) => {
  balanceHidden = v;
};
export const currentBalanceHidden = () => balanceHidden;
jest.mock('../../../utils/balanceVisibility', () => {
  const m = require('./mocks');
  return { isBalanceHidden: async () => m.currentBalanceHidden() };
});

export function resetMocks() {
  balanceHidden = false;
  jest.clearAllMocks();
  rememberedDirect.length = 0;
  nav.addListener.mockImplementation(() => () => {});
  routeParams = undefined;
  activeAccount = { id: 'personal_0', type: 'personal', index: 0, avatar: 'J' };
}

export { React };
