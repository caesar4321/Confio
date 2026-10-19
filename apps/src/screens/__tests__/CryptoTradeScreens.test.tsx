import React from 'react';
import renderer, { act } from 'react-test-renderer';
import { TouchableOpacity } from 'react-native';

let mockCaps: any;
let mockHoldings: any;
let mockSheetProps: any = null;
const mockAsset = {
  symbol: 'BTCB', ticker: 'BTC', name: 'Bitcoin', address: '0xbtc', decimals: 18, category: 'crypto',
  featured: true, custody: 'binance_peg', maxOrderUsd: null, priceUsd: 100000, dayChangePct: 1.5,
  sparkline24h: [1, 2, 3],
};
const mockBuy = jest.fn();
const mockSell = jest.fn();
const mockShare = jest.fn();
const mockNavigate = jest.fn();
let mockSellPreviewOut = 50n * 10n ** 18n;

jest.mock('@react-navigation/native', () => ({
  useNavigation: () => ({ goBack: jest.fn(), navigate: mockNavigate }),
  useRoute: () => ({ params: { symbol: 'BTCB' } }),
}));
jest.mock('@apollo/client', () => ({
  gql: () => ({}),
  useMutation: () => [jest.fn(async () => ({ data: { acknowledgeCryptoRisk: { success: true } } }))],
}));
jest.mock('react-native-safe-area-context', () => ({ SafeAreaView: 'SafeAreaView' }));
jest.mock('react-native-vector-icons/Feather', () => 'Icon');
jest.mock('../../navigation/Header', () => ({ Header: 'Header' }));
jest.mock('../../components/CryptoAssetMark', () => ({ CryptoAssetMark: 'CryptoAssetMark' }));
jest.mock('../../components/common/StockTradeLoadingOverlay', () => ({ StockTradeLoadingOverlay: () => null }));
jest.mock('../../components/common/SuccessHero', () => ({ SuccessHero: 'SuccessHero' }));
jest.mock('../../components/common/ReceiptCard', () => ({ ReceiptCard: 'ReceiptCard' }));
jest.mock('../../components/common/StockTradeSuccessContent', () => ({ StockTradeSuccessContent: ({ children }: any) => children }));
jest.mock('../../components/StockRiskSheet', () => ({ StockRiskSheet: (props: any) => { mockSheetProps = props; return null; } }));
jest.mock('../../services/communityShare', () => ({ requestActivityShare: (...a: any[]) => mockShare(...a) }));
jest.mock('../../services/sponsored7702', () => ({ createSponsoredRequestId: () => 'gm_req' }));
jest.mock('../../services/evmWallet', () => ({ isOutcomeUnknown: () => false }));
jest.mock('../../utils/numberFormatting', () => ({ useNumberFormat: () => ({ formatNumber: (v: number) => String(v) }) }));
jest.mock('../../config/features', () => ({ CRYPTO_TRADING_UI_ENABLED: true }));
jest.mock('../../hooks/useSavingsPortfolio', () => ({
  useSavingsPortfolio: () => ({ savings: { balanceUsd: 500 }, cusdBalanceUsd: 40, refetch: () => Promise.resolve() }),
}));
jest.mock('../../hooks/useCrypto', () => ({
  useCryptoCapabilities: () => ({ capabilities: mockCaps, loading: false, refetch: () => Promise.resolve() }),
  useCryptoMarket: () => ({ assets: [mockAsset], bySymbol: () => mockAsset, loading: false }),
  useCryptoHoldings: () => ({ holdings: mockHoldings, loading: false, refetch: () => Promise.resolve() }),
}));
jest.mock('../../services/cryptoTrading', () => {
  const actual = jest.requireActual('../../services/cryptoTrading');
  return {
    ...actual,
    previewCryptoBuy: async () => ({ expectedOut: '100000000000000', poolFeeBps: 5, priceImpactBps: 9, netWei: 0n }),
    previewCryptoSell: async () => ({
      expectedOut: mockSellPreviewOut.toString(), poolFeeBps: 5, priceImpactBps: 9,
      netWei: mockSellPreviewOut - (mockSellPreviewOut * 90n + 9_999n) / 10_000n,
    }),
    buyCrypto: (...a: any[]) => mockBuy(...a),
    sellCrypto: (...a: any[]) => mockSell(...a),
  };
});
jest.mock('../../apollo/client', () => ({ apolloClient: {} }));
jest.mock('../../services/bscServerRpc', () => ({}));
jest.mock('../../services/cusdPlusVault', () => ({}));
jest.mock('../../services/secureDeterministicWallet', () => ({}));

import { BuyCryptoScreen } from '../BuyCryptoScreen';
import { SellCryptoScreen } from '../SellCryptoScreen';
import { CryptoDetailScreen } from '../CryptoDetailScreen';

const caps = (over: Record<string, unknown> = {}) => ({
  enabled: true, tradingEnabled: true, buyEnabled: true, ackRequired: false, ackVersion: 1,
  disclosureTitle: 'Antes de tu primera compra de cripto u oro', disclosurePoints: ['Puedes perder'],
  fundingDollar: 'cusd_plus', feeBps: 90, maxSlippageBps: 100, routerAddress: '0xrouter', blockedMessage: null, ...over,
});

const flush = async (ms = 0) => {
  await act(async () => {
    jest.advanceTimersByTime(ms);
    for (let i = 0; i < 10; i += 1) await Promise.resolve();
  });
};
const text = (tree: renderer.ReactTestRenderer) =>
  tree.root.findAll(() => true)
    .flatMap((n) => n.children.filter((c): c is string => typeof c === 'string'))
    .join('|');
const byTestId = (tree: renderer.ReactTestRenderer, id: string) =>
  tree.root.find((n) => n.props?.testID === id && typeof n.props.onPress === 'function' || (n.props?.testID === id && typeof n.props.onChangeText === 'function'));
const typeAmount = async (tree: renderer.ReactTestRenderer, id: string, value: string) => {
  await act(async () => { byTestId(tree, id).props.onChangeText(value); });
  await flush(400);
  await flush(0);
};
const press = async (tree: renderer.ReactTestRenderer, id: string) => {
  await act(async () => { await byTestId(tree, id).props.onPress(); });
  await flush(0);
};

beforeEach(() => {
  jest.useFakeTimers();
  mockCaps = caps();
  mockHoldings = [{ symbol: 'BTCB', ticker: 'BTC', name: 'Bitcoin', category: 'crypto', units: '1000000000000000', decimals: 18, valueUsd: 100, dayChangePct: 1 }];
  mockSheetProps = null;
  mockSellPreviewOut = 50n * 10n ** 18n;
  mockBuy.mockReset().mockResolvedValue({ txHash: '0xbuytx', tokenOutUnits: 10n ** 14n });
  mockSell.mockReset().mockResolvedValue({ txHash: '0xselltx', unitsSold: 10n ** 15n, expectedNetWei: 49n * 10n ** 18n, dollar: 1 });
  mockShare.mockReset();
});
afterEach(() => jest.useRealTimers());

describe('BuyCryptoScreen', () => {
  it('shows the honest costs, buys with the displayed fee and offers the Comunidad share', async () => {
    let tree!: renderer.ReactTestRenderer;
    await act(async () => { tree = renderer.create(<BuyCryptoScreen />); });
    await typeAmount(tree, 'crypto-buy-amount', '10');
    const shown = text(tree);
    expect(shown).toContain('Confío Dollar+');
    expect(shown).toContain('Comisión de Confío ');
    expect(shown).toContain('Costo de mercado');
    expect(shown).toContain('Comprar y luego vender cuesta ≈ ');
    await press(tree, 'crypto-buy-confirm');
    expect(mockBuy).toHaveBeenCalledTimes(1);
    expect(mockBuy.mock.calls[0][0]).toMatchObject({
      grossAmountUsd: 10, expectedFeeBps: 90, expectedFunding: 'cusd_plus', previewTokenOut: 10n ** 14n,
    });
    expect(mockShare).toHaveBeenCalledWith({ group: 'crypto', reference: '0xbuytx' });
    await act(async () => tree.unmount());
  });

  it('asks for the one-time risk confirmation before the first purchase, then continues it', async () => {
    mockCaps = caps({ ackRequired: true });
    let tree!: renderer.ReactTestRenderer;
    await act(async () => { tree = renderer.create(<BuyCryptoScreen />); });
    await typeAmount(tree, 'crypto-buy-amount', '10');
    await press(tree, 'crypto-buy-confirm');
    expect(mockSheetProps.visible).toBe(true);
    expect(mockSheetProps.title).toBe('Antes de tu primera compra de cripto u oro');
    expect(mockBuy).not.toHaveBeenCalled();
    const token = mockSheetProps.beginAccept();
    await act(async () => { mockSheetProps.onAccepted(token); });
    await flush(450);
    expect(mockBuy).toHaveBeenCalledTimes(1);
    await act(async () => tree.unmount());
  });

  it('pays with Confío Dollar when that is what the person holds', async () => {
    mockCaps = caps({ fundingDollar: 'cusd' });
    let tree!: renderer.ReactTestRenderer;
    await act(async () => { tree = renderer.create(<BuyCryptoScreen />); });
    expect(text(tree)).toContain('Pagas con · ');
    expect(text(tree)).toContain('|Confío Dollar|');
    await act(async () => tree.unmount());
  });

  it('shows nothing tradeable while buying is off on the server', async () => {
    mockCaps = caps({ buyEnabled: false });
    let tree!: renderer.ReactTestRenderer;
    await act(async () => { tree = renderer.create(<BuyCryptoScreen />); });
    expect(tree.root.findAll((n) => n.props?.testID === 'crypto-buy-confirm')).toHaveLength(0);
    await act(async () => tree.unmount());
  });
});

describe('SellCryptoScreen', () => {
  it('sells and offers the Comunidad share', async () => {
    let tree!: renderer.ReactTestRenderer;
    await act(async () => { tree = renderer.create(<SellCryptoScreen />); });
    await typeAmount(tree, 'crypto-sell-amount', '50');
    await press(tree, 'crypto-sell-confirm');
    expect(mockSell.mock.calls[0][0]).toMatchObject({ expectedFeeBps: 90, expectedFunding: 'cusd_plus', intoCusd: false });
    expect(mockSell.mock.calls[0][0].units).toBe(5n * 10n ** 14n);
    expect(mockShare).toHaveBeenCalledWith({ group: 'crypto', reference: '0xselltx' });
    await act(async () => tree.unmount());
  });

  it('a cUSD+ sale under US$1 offers Confío Dollar instead, and sells into it', async () => {
    mockSellPreviewOut = 1_010_000_000_000_000_000n;
    let tree!: renderer.ReactTestRenderer;
    await act(async () => { tree = renderer.create(<SellCryptoScreen />); });
    await typeAmount(tree, 'crypto-sell-amount', '1');
    expect(text(tree)).toContain('al menos US$1.00');
    const confirm = byTestId(tree, 'crypto-sell-confirm');
    expect(confirm.props.disabled).toBe(true);
    await press(tree, 'crypto-sell-into-cusd');
    await flush(400);
    await press(tree, 'crypto-sell-confirm');
    expect(mockSell.mock.calls[0][0].intoCusd).toBe(true);
    await act(async () => tree.unmount());
  });
});

describe('CryptoDetailScreen', () => {
  it('shows price, sparkline, position, custody and the funding dollar', async () => {
    let tree!: renderer.ReactTestRenderer;
    await act(async () => { tree = renderer.create(<CryptoDetailScreen />); });
    const shown = text(tree);
    expect(shown).toContain('Bitcoin respaldado 1:1 por Binance en BNB Chain');
    expect(shown).toContain('Tu inversión');
    expect(shown).toContain('Confío Dollar+');
    expect(tree.root.findAll((n) => n.props?.testID === 'crypto-sparkline').length).toBeGreaterThan(0);
    const buttons = tree.root.findAllByType(TouchableOpacity);
    await act(async () => { buttons[0].props.onPress(); });
    expect(mockNavigate).toHaveBeenCalledWith('BuyCrypto', { symbol: 'BTCB' });
    await act(async () => tree.unmount());
  });

  it('says it is not available when the country policy blocks it', async () => {
    mockCaps = caps({ enabled: false, blockedMessage: 'No disponible en tu país.' });
    let tree!: renderer.ReactTestRenderer;
    await act(async () => { tree = renderer.create(<CryptoDetailScreen />); });
    expect(text(tree)).toContain('No disponible en tu país.');
    await act(async () => tree.unmount());
  });
});
