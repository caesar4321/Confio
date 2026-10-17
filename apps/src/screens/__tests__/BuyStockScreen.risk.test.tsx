import React from 'react';
import renderer, {act} from 'react-test-renderer';
import {TouchableOpacity} from 'react-native';

let mockSheetProps: any = null;
// Stable like the real memoized market rows (the quote effect depends on it).
const mockStock = {ticker: 'TQQQ', symbol: 'TQQQon', name: 'ProShares UltraPro QQQ', priceUsd: 90, color: '#000', logoUrl: ''};
const mockBuy = jest.fn();
const mockRefetchComplex = jest.fn(() => Promise.resolve());

jest.mock('@react-navigation/native', () => ({
  useNavigation: () => ({goBack: jest.fn(), navigate: jest.fn()}),
  useRoute: () => ({params: {ticker: 'TQQQ'}}),
}));
jest.mock('react-native-safe-area-context', () => ({SafeAreaView: 'SafeAreaView'}));
jest.mock('react-native-vector-icons/Feather', () => 'Icon');
jest.mock('../../navigation/Header', () => ({Header: 'Header'}));
jest.mock('../../components/TickerLogo', () => ({TickerLogo: 'TickerLogo'}));
jest.mock('../../components/common/StockTradeLoadingOverlay', () => ({StockTradeLoadingOverlay: () => null}));
jest.mock('../../components/common/SuccessHero', () => ({SuccessHero: () => null}));
jest.mock('../../components/common/ReceiptCard', () => ({ReceiptCard: () => null}));
jest.mock('../../components/common/StockTradeSuccessContent', () => ({StockTradeSuccessContent: ({children}: any) => children}));
jest.mock('../../services/communityShare', () => ({requestActivityShare: jest.fn()}));
jest.mock('../../utils/numberFormatting', () => ({useNumberFormat: () => ({formatNumber: (v: number) => String(v)})}));
jest.mock('../../hooks/useSavingsPortfolio', () => ({
  useSavingsPortfolio: () => ({
    savings: {balanceUsd: 500},
    stocks: {enabled: true, buyEnabled: true},
    refetch: () => Promise.resolve(),
  }),
}));
jest.mock('../../contexts/AccountContext', () => ({useAccount: () => ({activeAccount: {isEmployee: false}})}));
jest.mock('../../hooks/useStockMonthNow', () => ({openTuMesNow: jest.fn()}));
jest.mock('../../config/features', () => ({CUSD_CONVERSION_UI_ENABLED: true, STOCKS_TRADING_UI_ENABLED: true}));
jest.mock('../../assets/png/cUSDPlus.png', () => 1);
jest.mock('../../hooks/useGmMarket', () => ({
  useGmMarket: () => ({
    byTicker: () => mockStock,
    tradabilityFor: () => 'open',
  }),
  useGmComplexProducts: () => ({
    factorFor: () => 3, acknowledged: false, version: 1, title: 'Antes', points: ['Se reajustan cada día.'],
    refetch: mockRefetchComplex,
  }),
}));
jest.mock('../../components/StockRiskSheet', () => ({
  StockRiskSheet: (props: any) => { mockSheetProps = props; return null; },
}));
jest.mock('../../services/ondoStocks', () => ({
  getSoftStockQuote: () => Promise.resolve({tokenAmount: '1000000000000000000'}),
  buyStockWithSavings: (...args: any[]) => mockBuy(...args),
  friendlyTradeError: () => 'error',
  isComplexProductAckRequired: () => false,
}));
jest.mock('../../services/sponsored7702', () => ({createSponsoredRequestId: () => 'req_1234567890abcdef'}));
jest.mock('../../services/evmWallet', () => ({isOutcomeUnknown: () => false}));

import {BuyStockScreen} from '../BuyStockScreen';

const flush = async (ms = 0) => {
  await act(async () => {
    jest.advanceTimersByTime(ms);
    for (let i = 0; i < 10; i += 1) await Promise.resolve();
  });
};

const typeAmount = async (tree: renderer.ReactTestRenderer, value: string) => {
  const input = tree.root.findAll(n => typeof n.props.onChangeText === 'function')[0];
  await act(async () => { input.props.onChangeText(value); });
  await flush(400);
  await flush(0);
};

const pressConfirm = async (tree: renderer.ReactTestRenderer) => {
  const buttons = tree.root.findAllByType(TouchableOpacity);
  const confirm = buttons[buttons.length - 1];
  await act(async () => { await confirm.props.onPress(); });
};

beforeEach(() => {
  jest.useFakeTimers();
  mockSheetProps = null;
  mockBuy.mockReset();
  mockBuy.mockResolvedValue({tokenAmountWei: 10n ** 18n, txHash: '0xabc'});
});
afterEach(() => jest.useRealTimers());

it('asks before the first leveraged purchase, then continues the same purchase', async () => {
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<BuyStockScreen />); });
  await typeAmount(tree, '10');
  await pressConfirm(tree);
  expect(mockSheetProps.visible).toBe(true);
  expect(mockBuy).not.toHaveBeenCalled();

  const token = mockSheetProps.beginAccept();
  await act(async () => { mockSheetProps.onAccepted(token); });
  await flush(450);
  expect(mockBuy).toHaveBeenCalledTimes(1);
  expect(mockBuy.mock.calls[0][0].grossAmountUsd).toBe(10);
  await act(async () => tree.unmount());
});

it('never buys a new amount on a confirmation from a dismissed sheet', async () => {
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<BuyStockScreen />); });
  await typeAmount(tree, '10');
  await pressConfirm(tree);
  const staleToken = mockSheetProps.beginAccept();   // tapped, saving…
  await act(async () => { mockSheetProps.onClose(); }); // …then dismissed
  await typeAmount(tree, '100');
  await pressConfirm(tree);                           // reopened for $100
  expect(mockSheetProps.visible).toBe(true);

  await act(async () => { mockSheetProps.onAccepted(staleToken); }); // the old save lands
  await flush(1000);
  expect(mockBuy).not.toHaveBeenCalled();
  expect(mockSheetProps.visible).toBe(true);           // the new sheet still waits
  await act(async () => tree.unmount());
});

it('does not buy after the screen is left', async () => {
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<BuyStockScreen />); });
  await typeAmount(tree, '10');
  await pressConfirm(tree);
  const token = mockSheetProps.beginAccept();
  const accepted = mockSheetProps.onAccepted;
  await act(async () => tree.unmount());
  accepted(token);
  jest.advanceTimersByTime(1000);
  expect(mockBuy).not.toHaveBeenCalled();
});
