/**
 * The presale's backup gate must verify the wallet of the chain that actually
 * settles the purchase.
 *
 * Incident (2026-10-20): the presale moved to BSC, but all three gates passed
 * the legacy 'presale' action, which demands the account's registered Algorand
 * address. Every account migrated to BSC has none, so tapping into the presale
 * alerted "Depósito no disponible" and went straight back: Julian's own
 * account, and 1941 of 12727 personal/0 accounts.
 *
 * Testing the hook alone could not catch this. The bug was the action the
 * SCREEN passed, so these mount the screen and read the gate's argument.
 */
import React from 'react';
import renderer, { act } from 'react-test-renderer';
import { Alert, TextInput, TouchableOpacity } from 'react-native';

const mockEnforcement = jest.fn();
const mockBuyPresaleBsc = jest.fn();
const mockFace = jest.fn();
const mockWsOpen = jest.fn();
const mockGoBack = jest.fn();
let mockQueryData: any;

jest.mock('@react-navigation/native', () => {
  // Stable, like the real navigation object: a new one per render re-fires
  // the screen's init effect and hides the true gate count.
  // Read the spy lazily: the factory runs before the consts initialize.
  const navigation = { goBack: (...args: any[]) => mockGoBack(...args), navigate: jest.fn() };
  return { useNavigation: () => navigation };
});
jest.mock('@apollo/client', () => ({
  useQuery: (query: any, options?: any) => (options?.skip ? {} : mockQueryData(query)),
}));
jest.mock('../../apollo/queries', () => ({
  GET_PRESALE_PARTICIPATE_DATA: 'participate',
  GET_BSC_CONFIO_DOLLAR_BALANCE: 'bscBalance',
  GET_MY_BALANCES: 'legacyBalance',
}));
jest.mock('../../hooks/useBackupEnforcement', () => {
  // One stable object, like the real hook's memoized callback: a new identity
  // per render would re-fire the screen's init effect and inflate every count.
  const api = {
    checkBackupEnforcement: (...args: any[]) => mockEnforcement(...args),
    BackupEnforcementModal: () => null,
  };
  return { useBackupEnforcement: () => api };
});
// hooks/enforcementActions is deliberately NOT mocked: a wrong mapping there
// is the bug these tests exist to catch.
jest.mock('../../services/presaleBsc', () => ({ buyPresaleBsc: (...a: any[]) => mockBuyPresaleBsc(...a) }));
jest.mock('../../services/faceAuthentication', () => ({ authenticateWithFace: (...a: any[]) => mockFace(...a) }));
jest.mock('../../services/presaleWs', () => ({
  PresaleWsSession: class { open = (...a: any[]) => mockWsOpen(...a); },
}));
jest.mock('../../services/algorandService', () => ({ __esModule: true, default: {} }));
jest.mock('react-native-vector-icons/Feather', () => 'Icon');
jest.mock('../../navigation/Header', () => ({ Header: 'Header' }));
jest.mock('../../components/LoadingOverlay', () => ({ LoadingOverlay: () => null }));
jest.mock('../../components/TelegramGroupModal', () => ({ TelegramGroupModal: () => null }));
jest.mock('../../components/common/BrandFieldBackground', () => ({ BrandFieldBackground: ({ children }: any) => children }));
jest.mock('../../contexts/CountryContext', () => ({ useCountry: () => ({ selectedCountry: ['Honduras', '+504', 'HN'] }) }));
jest.mock('../../contexts/NumberLocaleProvider', () => ({ useNumberLocale: () => undefined }));
jest.mock('../../utils/numberLocale', () => ({
  ...jest.requireActual('../../utils/numberLocale'),
  getNumberLocaleCountry: () => 'HN',
}));
jest.mock('../../assets/png/CONFIO.png', () => 1);

import { ConfioPresaleParticipateScreen } from '../ConfioPresaleParticipateScreen';

const PHASE = { minPurchase: '10', maxPurchase: '1000', pricePerToken: '0.25', totalRaised: '0', totalParticipants: 0 };
const participateData = (presaleChain: string) => ({
  presaleChain,
  activePresalePhase: PHASE,
  presaleCurveStats: { currentPrice: '0.25', totalRaisedUsd: '0', nextMilestoneUsd: '1000', participants: 0 },
  presaleTelegramGroup: { enabled: false, url: null },
});

let tree: renderer.ReactTestRenderer;
const mountScreen = async (presaleChain: string, participate?: any) => {
  mockQueryData = (query: any) => {
    if (query === 'participate') return participate
      ?? { data: participateData(presaleChain), loading: false, error: undefined, refetch: jest.fn() };
    if (query === 'bscBalance') return { data: { cusdPlusSummary: { cusdBalanceUsd: 500, balanceUsd: 0 } }, loading: false, error: undefined };
    return { data: { myBalances: { cusd: '500' } }, loading: false, error: undefined };
  };
  await act(async () => { tree = renderer.create(<ConfioPresaleParticipateScreen />); });
  return tree;
};

beforeEach(() => {
  jest.clearAllMocks();
  jest.spyOn(Alert, 'alert').mockImplementation(() => {});
  mockEnforcement.mockResolvedValue(true);
  mockFace.mockResolvedValue(true);
  mockBuyPresaleBsc.mockResolvedValue(undefined);
  mockWsOpen.mockRejectedValue(new Error('the legacy rail must not be opened here'));
});
afterEach(() => {
  act(() => { tree?.unmount(); });
  jest.restoreAllMocks();
});

// Drive the form to the confirmation dialog, then confirm, which is the only
// way to reach executeSwap's gate.
const buyThroughTheForm = async () => {
  const input = tree.root.findAllByType(TextInput)[0];
  await act(async () => { input.props.onChangeText('100'); });
  // The two required confirmations, in the order the screen renders them.
  const toggles = tree.root.findAllByType(TouchableOpacity).filter(node => typeof node.props.onPress === 'function');
  await act(async () => { toggles[toggles.length - 3].props.onPress(); });
  await act(async () => { toggles[toggles.length - 2].props.onPress(); });
  await act(async () => { toggles[toggles.length - 1].props.onPress(); });
  const confirm = (Alert.alert as jest.Mock).mock.calls
    .flatMap(call => call[2] || [])
    .find((button: any) => button?.text === 'Confirmar');
  expect(confirm).toBeDefined();
  await act(async () => { await confirm.onPress(); });
};

it('verifies the BSC wallet at every gate when the presale settles on BSC', async () => {
  await mountScreen('bsc');

  // Gate 1: screen entry. This is the one that alerted and went back.
  expect(mockEnforcement).toHaveBeenCalledWith('presale_bsc');

  await buyThroughTheForm();

  // Gates 2 and 3: the swap button and the confirmed purchase. Exactly three,
  // so a gate that stopped running would fail here rather than pass quietly.
  expect(mockEnforcement.mock.calls).toEqual([['presale_bsc'], ['presale_bsc'], ['presale_bsc']]);
  expect(mockBuyPresaleBsc).toHaveBeenCalledWith('100');
  // An allowed entry stays on the screen.
  expect(mockGoBack).not.toHaveBeenCalled();
});

it('keeps asking for the Algorand wallet at every gate while the legacy rail settles', async () => {
  // The legacy session opens past the gate; this rail's own behaviour is not
  // under test, only which wallet each of its three gates asks for.
  mockWsOpen.mockRejectedValue(new Error('legacy session unavailable in tests'));
  await mountScreen('algorand');

  await buyThroughTheForm();

  expect(mockEnforcement.mock.calls).toEqual([['presale'], ['presale'], ['presale']]);
  // The BSC purchase must never run on the legacy rail.
  expect(mockBuyPresaleBsc).not.toHaveBeenCalled();
});

it('never buys when the purchase gate itself refuses', async () => {
  // Entry and the swap button pass; the gate in executeSwap is the one that
  // refuses, so only its own check can stop the purchase here.
  mockEnforcement.mockResolvedValueOnce(true).mockResolvedValueOnce(true).mockResolvedValue(false);
  await mountScreen('bsc');

  await buyThroughTheForm();

  expect(mockEnforcement).toHaveBeenCalledTimes(3);
  expect(mockFace).not.toHaveBeenCalled();
  expect(mockBuyPresaleBsc).not.toHaveBeenCalled();
});

// A failed chain query used to read as "Algorand": the gate then demanded an
// Algorand address a migrated account does not have, and the legacy opt-in
// ceremony ran behind the retry screen.
it('prepares nothing when the server never said which chain settles', async () => {
  await mountScreen('bsc', { data: undefined, loading: false, error: new Error('presale query failed'), refetch: jest.fn() });

  expect(mockEnforcement).not.toHaveBeenCalled();
  expect(mockWsOpen).not.toHaveBeenCalled();
  expect(mockGoBack).not.toHaveBeenCalled();
});

it('prepares nothing when no presale phase is active', async () => {
  await mountScreen('bsc', {
    data: { ...participateData('bsc'), activePresalePhase: null },
    loading: false, error: undefined, refetch: jest.fn(),
  });

  expect(mockEnforcement).not.toHaveBeenCalled();
  expect(mockWsOpen).not.toHaveBeenCalled();
});

it('leaves the screen when entry is refused, instead of showing the form', async () => {
  mockEnforcement.mockResolvedValue(false);
  await mountScreen('bsc');

  // The refusal has to ACT: without this the form stays up on a wallet we
  // could not verify.
  expect(mockGoBack).toHaveBeenCalled();
  expect(mockBuyPresaleBsc).not.toHaveBeenCalled();
  expect(mockFace).not.toHaveBeenCalled();
});
