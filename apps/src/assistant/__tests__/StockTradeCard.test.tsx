// A stock bought or sold from a card in the conversation.
import React from 'react';
import { Text as RNText } from 'react-native';
import renderer, { act } from 'react-test-renderer';

const mockBuy = jest.fn();
const mockSell = jest.fn();
const mockSoftQuote = jest.fn();
const mockShare = jest.fn();
const mockNavigate = jest.fn();
const mockRecheck = jest.fn();
const mockRefetchPortfolio = jest.fn(async () => ({}));
let mockStatus: string | undefined = 'none';
let mockStatusError: Error | undefined;
const mockMutate = jest.fn();
let mockClaim: any;
let mockRelease: any;
let mockPortfolio: any;
let mockTradability = 'open';
let mockComplex: any;

jest.mock('react-native-vector-icons/Feather', () => 'Icon');
jest.mock('../../components/common/AppText', () => ({ Text: require('react-native').Text }));
jest.mock('../../config/features', () => ({ STOCKS_TRADING_UI_ENABLED: true }));
jest.mock('../../navigation/RootNavigation', () => ({
  navigationRef: { isReady: () => true, navigate: (...a: unknown[]) => mockNavigate(...a) },
}));
jest.mock('../../utils/numberLocale', () => ({
  formatDecimal: (value: number, options: { decimals: number; minDecimals?: number }) => {
    const fixed = Number(value).toFixed(options.decimals);
    return options.minDecimals === 0 ? String(Number(fixed)) : fixed;
  },
  parseAmountInput: (text: string) => Number(text),
  toAmountInput: (value: number) => (Math.floor(value * 100) / 100).toFixed(2),
}));
// Like Apollo's, the same client on every render.
const mockClient = { mutate: (...a: unknown[]) => mockMutate(...a) };
jest.mock('@apollo/client', () => ({
  gql: jest.requireActual('graphql-tag').gql,
  useApolloClient: () => mockClient,
  useQuery: () => ({
    data: mockStatus ? { assistantStockTrade: { status: mockStatus, txHash: mockStatus === 'done' ? '0xserved' : null } } : undefined,
    error: mockStatusError,
    refetch: (...a: unknown[]) => mockRecheck(...a),
  }),
}));
jest.mock('../stockTrade', () => ({
  ...jest.requireActual('../stockTrade'),
  GET_MESSAGE_STOCK_TRADE: 'status', CLAIM_STOCK_TRADE: 'claim', RELEASE_STOCK_TRADE: 'release',
}));
jest.mock('../../hooks/useSavingsPortfolio', () => ({ useSavingsPortfolio: () => mockPortfolio }));
jest.mock('../../hooks/useGmMarket', () => ({
  useGmMarket: () => ({
    byTicker: (ticker: string) => (ticker === 'AAPL' ? { symbol: 'AAPLon', ticker: 'AAPL', name: 'Apple Inc.' } : undefined),
    tradabilityFor: () => mockTradability,
    loading: false,
  }),
  useGmComplexProducts: () => mockComplex,
}));
jest.mock('../../hooks/useStockFeePolicy', () => ({ useStockFeePolicy: () => ({ feeBps: 30n, mode: 'perimeter' }) }));
jest.mock('../../services/stockFeeMath', () => ({
  feePercent: (policy: { feeBps: bigint }) => Number(policy.feeBps) / 100,
  sellFee: (wei: bigint, policy: { feeBps: bigint }) => (wei * policy.feeBps) / 10000n,
}));
jest.mock('../../services/communityShare', () => ({ requestActivityShare: (...a: unknown[]) => mockShare(...a) }));
jest.mock('../../services/evmWallet', () => ({ isOutcomeUnknown: (e: any) => !!e?.broadcast }));
jest.mock('../../services/ondoStocks', () => ({
  SELL_NET_MIN_WEI: 1_000_000_000_000_000_000n,
  buyStockWithSavings: (...a: unknown[]) => mockBuy(...a),
  sellStockToSavings: (...a: unknown[]) => mockSell(...a),
  getSoftStockQuote: (...a: unknown[]) => mockSoftQuote(...a),
  friendlyTradeError: (e: Error) => e.message,
  isComplexProductAckRequired: (e: any) => e?.code === 'ACK',
}));

import { StockTradeCard } from '../StockTradeCard';
import { resolveTrade } from '../stockTrade';

const WEI = 10n ** 18n;
const texts = (tree: renderer.ReactTestRenderer) =>
  tree.root.findAllByType(RNText).map((n) => [n.props.children].flat(Infinity).join(''));
const button = (tree: renderer.ReactTestRenderer, label: string) =>
  tree.root.findAll((n) => n.props.accessibilityLabel === label && typeof n.props.onPress === 'function')[0];
const press = async (tree: renderer.ReactTestRenderer, label: string) => {
  const node = button(tree, label);
  if (!node) throw new Error(`no button ${label}; texts: ${texts(tree).join(' | ')}`);
  await act(async () => { await node.props.onPress(); });
};
const trade = (target: string, label = 'Comprar US$20 de Apple Inc.') => resolveTrade({ type: 'trade', ticker: 'AAPL', target, label })!;
async function mount(target = 'buy:20.00', messageId = '4512') {
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<StockTradeCard messageId={messageId} action={trade(target)} />); });
  await act(async () => { await Promise.resolve(); });
  return tree;
}

beforeEach(() => {
  jest.clearAllMocks();
  mockStatus = 'none';
  mockStatusError = undefined;
  mockTradability = 'open';
  mockComplex = { factorFor: () => undefined, acknowledged: false };
  mockPortfolio = {
    loading: false, refetch: mockRefetchPortfolio, savings: { balanceUsd: 150 },
    stocks: { enabled: true, buyEnabled: true, tradingEnabled: true, positions: [{ ticker: 'AAPL', valueUsd: 35.109 }] },
  };
  mockRecheck.mockResolvedValue({ data: { assistantStockTrade: { status: 'none' } } });
  mockClaim = { requestId: 'chat-trade-0000004512-abc123abc123', status: 'none' };
  mockRelease = { status: 'none' };
  mockMutate.mockImplementation(async ({ mutation }: { mutation: string }) => (
    mutation === 'claim' ? { data: { claimAssistantStockTrade: mockClaim } }
      : { data: { releaseAssistantStockTrade: mockRelease } }));
  // A buy quote: 0.0834 tokens. A sell quote: the same tokens at US$240.
  mockSoftQuote.mockResolvedValue({ tokenAmount: String((WEI * 834n) / 10000n), price: String(240n * WEI) });
});

describe('what the app accepts', () => {
  it('only a trade of the shape the server writes', () => {
    expect(trade('buy:20.00')).toEqual({ side: 'buy', ticker: 'AAPL', amountUsd: 20, label: 'Comprar US$20 de Apple Inc.' });
    expect(trade('sell:all')).toMatchObject({ side: 'sell', amountUsd: null });
    for (const target of ['buy:all', 'buy:20', 'buy:-5.00', 'buy:0.00', 'swap:20.00', 'sell:20.00;drop', '']) {
      expect(resolveTrade({ type: 'trade', ticker: 'AAPL', target, label: 'x' })).toBeNull();
    }
    expect(resolveTrade({ type: 'do', ticker: 'AAPL', target: 'buy:20.00', label: 'x' })).toBeNull();
    expect(resolveTrade({ type: 'trade', ticker: 'AA PL', target: 'buy:20.00', label: 'x' })).toBeNull();
    expect(resolveTrade({ type: 'trade', ticker: 'AAPL', target: 'buy:20.00', label: '' })).toBeNull();
  });
});

describe('buying', () => {
  it('shows what leaves, about what arrives and the fee, and buys only on the tap', async () => {
    const tree = await mount();
    expect(mockSoftQuote).toHaveBeenCalledWith('AAPLon', 'buy', 20);
    expect(texts(tree)).toEqual(expect.arrayContaining(
      ['Comprar US$20 de Apple Inc.', 'US$20.00', '≈ 0.0834 AAPL', 'US$0.06 (0.3%)', 'Confío Dollar+']));
    expect(mockBuy).not.toHaveBeenCalled();
    mockBuy.mockResolvedValue({ txHash: '0xabc', tokenAmountWei: (WEI * 83n) / 1000n, feeWei: 0n });
    await press(tree, 'Aprobar compra');
    // It signs the one request the server handed this card, never one of its own.
    expect(mockMutate).toHaveBeenCalledWith({ mutation: 'claim', variables: { messageId: '4512' }, fetchPolicy: 'no-cache' });
    expect(mockBuy).toHaveBeenCalledWith({
      symbol: 'AAPLon', grossAmountUsd: 20, minTokenAmountWei: ((WEI * 834n) / 10000n * 99n) / 100n,
      expectedFeeBps: 30n, requestId: 'chat-trade-0000004512-abc123abc123',
    });
    expect(texts(tree)).toContain('Listo: compraste ≈ 0.083 AAPL');
    expect(button(tree, 'Aprobar compra')).toBeUndefined();
    // The share sheet opens by itself, as after a trade on the stock screens...
    expect(mockShare).toHaveBeenCalledTimes(1);
    expect(mockShare).toHaveBeenCalledWith({ group: 'stock', reference: '0xabc' });
    // ...and the card keeps the button for whoever closed it.
    await press(tree, 'Compartir');
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
    expect(mockShare).toHaveBeenCalledTimes(2);
    await act(async () => tree.unmount());
  });

  it('in the floating chat nothing opens by itself: the button closes the box, then shares', async () => {
    const onLeave = jest.fn();
    let tree!: renderer.ReactTestRenderer;
    await act(async () => { tree = renderer.create(<StockTradeCard messageId="4512" action={trade('buy:20.00')} onLeave={onLeave} />); });
    await act(async () => { await Promise.resolve(); });
    mockBuy.mockResolvedValue({ txHash: '0xabc', tokenAmountWei: WEI, feeWei: 0n });
    await press(tree, 'Aprobar compra');
    expect(mockShare).not.toHaveBeenCalled();
    jest.useFakeTimers();
    try {
      const node = button(tree, 'Compartir');
      await act(async () => { node.props.onPress(); });
      expect(onLeave).toHaveBeenCalledTimes(1);
      await act(async () => { jest.advanceTimersByTime(300); });
      expect(mockShare).toHaveBeenCalledWith({ group: 'stock', reference: '0xabc', again: true });
    } finally {
      jest.useRealTimers();
    }
    await act(async () => tree.unmount());
  });

  it('a card that already traded cannot be approved again, here or after a reload', async () => {
    mockStatus = 'done';
    let tree = await mount();
    expect(texts(tree)).toContain('Listo: esta compra ya se hizo.');
    expect(button(tree, 'Aprobar compra')).toBeUndefined();
    expect(button(tree, 'Compartir')).toBeDefined();
    await act(async () => tree.unmount());
    // The other open copy of the chat, or another phone, is already at it: no request, no trade.
    mockStatus = 'none';
    tree = await mount();
    mockClaim = { requestId: null, status: 'pending' };
    await press(tree, 'Aprobar compra');
    expect(mockBuy).not.toHaveBeenCalled();
    expect(mockRecheck).toHaveBeenCalled();
    await act(async () => tree.unmount());
    // A day old, or not a card of theirs.
    mockStatus = 'expired';
    tree = await mount();
    expect(texts(tree)).toEqual(['Esta tarjeta venció. Pídemelo de nuevo.']);
    await act(async () => tree.unmount());
    mockStatus = 'gone';
    tree = await mount();
    expect(button(tree, 'Aprobar compra')).toBeUndefined();
    await act(async () => tree.unmount());
    // Until the server has answered, there is nothing to approve.
    mockStatus = undefined;
    mockSoftQuote.mockClear();
    tree = await mount();
    expect(button(tree, 'Aprobar compra')).toBeUndefined();
    expect(mockSoftQuote).not.toHaveBeenCalled();
    await act(async () => tree.unmount());
    mockStatusError = new Error('network');
    tree = await mount();
    expect(texts(tree).join(' ')).toContain('No pude comprobar esta tarjeta');
    await act(async () => tree.unmount());
  });

  it('a price that moved sends nothing: the request goes back, the reason is said, the next try is a new request', async () => {
    const tree = await mount();
    mockBuy.mockRejectedValueOnce(new Error('El precio cambió más de 1%.'));
    await press(tree, 'Aprobar compra');
    expect(mockMutate).toHaveBeenLastCalledWith({
      mutation: 'release', variables: { messageId: '4512', requestId: 'chat-trade-0000004512-abc123abc123' }, fetchPolicy: 'no-cache',
    });
    expect(texts(tree)).toContain('El precio cambió más de 1%.');
    // The price is read again.
    expect(mockSoftQuote).toHaveBeenCalledTimes(2);
    mockClaim = { requestId: 'chat-trade-0000004512-fff000fff000', status: 'none' };
    mockBuy.mockResolvedValue({ txHash: '0xdef', tokenAmountWei: WEI, feeWei: 0n });
    await press(tree, 'Aprobar compra');
    expect(mockBuy.mock.calls[1][0].requestId).toBe('chat-trade-0000004512-fff000fff000');
    await act(async () => tree.unmount());
  });

  it('an error after the send is not "nothing happened": the server\'s record decides', async () => {
    // A receipt that could not be read: the trade is on record, so the request is not given back.
    let tree = await mount();
    mockBuy.mockRejectedValueOnce(new Error('bsc relay: no response'));
    mockRelease = { status: 'pending' };
    await press(tree, 'Aprobar compra');
    expect(texts(tree).join(' ')).toContain('Tu compra está en curso.');
    expect(texts(tree).join(' ')).not.toContain('bsc relay');
    expect(button(tree, 'Aprobar compra')).toBeUndefined();
    await act(async () => tree.unmount());
    // It reverted: said as not done, with no second tap on this card.
    tree = await mount();
    mockBuy.mockRejectedValueOnce(new Error('bsc tx reverted: 0x1'));
    mockRelease = { status: 'failed' };
    mockRecheck.mockImplementation(async () => { mockStatus = 'failed'; return { data: { assistantStockTrade: { status: 'failed' } } }; });
    await press(tree, 'Aprobar compra');
    await act(async () => { tree.update(<StockTradeCard messageId="4512" action={trade('buy:20.00')} />); });
    expect(texts(tree).join(' ')).toContain('No se hizo la compra');
    expect(button(tree, 'Aprobar compra')).toBeUndefined();
    await act(async () => tree.unmount());
    // The server could not be asked: nothing is assumed.
    mockStatus = 'none';
    mockRecheck.mockResolvedValue({ data: { assistantStockTrade: { status: 'none' } } });
    tree = await mount();
    mockBuy.mockRejectedValueOnce(new Error('algo'));
    mockMutate.mockImplementation(async ({ mutation }: { mutation: string }) => {
      if (mutation === 'claim') return { data: { claimAssistantStockTrade: mockClaim } };
      throw new Error('network');
    });
    await press(tree, 'Aprobar compra');
    expect(texts(tree).join(' ')).toContain('Tu compra está en curso.');
    await act(async () => tree.unmount());
  });

  it('sent but unseen: in progress, watched on the server, no second tap; and never "in progress" for ever', async () => {
    jest.useFakeTimers();
    try {
      const tree = await mount();
      mockBuy.mockRejectedValueOnce(Object.assign(new Error('bsc tx timeout'), { broadcast: true }));
      await press(tree, 'Aprobar compra');
      expect(texts(tree).join(' ')).toContain('Tu compra está en curso.');
      expect(button(tree, 'Aprobar compra')).toBeUndefined();
      // The request stays out (it is not given back) and the server is asked again and again.
      expect(mockMutate.mock.calls.filter(([a]) => a.mutation === 'release')).toHaveLength(0);
      mockRecheck.mockClear();
      mockRecheck.mockResolvedValue({ data: { assistantStockTrade: { status: 'pending' } } });
      await act(async () => { jest.advanceTimersByTime(6000); await Promise.resolve(); });
      expect(mockRecheck).toHaveBeenCalledTimes(1);
      // The request ran out with no trade on record: nothing was sent, and the card says so.
      mockRecheck.mockResolvedValue({ data: { assistantStockTrade: { status: 'none' } } });
      await act(async () => { jest.advanceTimersByTime(6000); await Promise.resolve(); await Promise.resolve(); });
      expect(texts(tree)).toContain('No se envió nada. Puedes intentarlo de nuevo.');
      expect(button(tree, 'Aprobar compra')).toBeDefined();
      await act(async () => tree.unmount());

      // After a reload the server says a trade is on its way: watched too, and when the
      // watch runs out without an answer the person is told to look before asking again.
      mockStatus = 'pending';
      mockRecheck.mockResolvedValue({ data: { assistantStockTrade: { status: 'pending' } } });
      const reloaded = await mount();
      expect(texts(reloaded).join(' ')).toContain('Tu compra está en curso.');
      await act(async () => { jest.advanceTimersByTime(13 * 60 * 1000); await Promise.resolve(); });
      expect(texts(reloaded).join(' ')).toContain('No pude confirmar si la compra se hizo');
      await act(async () => reloaded.unmount());
    } finally {
      jest.useRealTimers();
    }
  });

  it('a price that cannot be read can be asked again', async () => {
    mockSoftQuote.mockRejectedValueOnce(new Error('Demasiadas consultas. Espera un momento.'));
    const tree = await mount();
    expect(texts(tree)).toContain('Demasiadas consultas. Espera un momento.');
    await press(tree, 'Actualizar precio');
    await act(async () => { await Promise.resolve(); });
    expect(mockSoftQuote).toHaveBeenCalledTimes(2);
    expect(texts(tree)).not.toContain('Demasiadas consultas. Espera un momento.');
    expect(texts(tree)).toContain('≈ 0.0834 AAPL');
    await act(async () => tree.unmount());
  });

  it('says why it cannot be approved: not enough, market closed, a fund with a risk read, not open to them', async () => {
    mockPortfolio.savings.balanceUsd = 12;
    let tree = await mount();
    expect(texts(tree)).toContain('No alcanza: tienes US$12.00 en tu Confío Dollar+.');
    expect(button(tree, 'Aprobar compra')).toBeUndefined();
    await act(async () => tree.unmount());

    mockPortfolio.savings.balanceUsd = 150;
    mockTradability = 'closed';
    tree = await mount();
    expect(texts(tree).join(' ')).toContain('El mercado está cerrado ahora');
    expect(mockSoftQuote).not.toHaveBeenCalled();
    await act(async () => tree.unmount());

    mockTradability = 'open';
    mockComplex = { factorFor: () => 3, acknowledged: false };
    tree = await mount();
    expect(texts(tree).join(' ')).toContain('hay que leer sus riesgos');
    await press(tree, 'Abrir AAPL');
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
    expect(mockNavigate).toHaveBeenCalledWith('StockDetail', { ticker: 'AAPL' });
    await act(async () => tree.unmount());

    mockComplex = { factorFor: () => undefined, acknowledged: false };
    mockPortfolio.stocks.buyEnabled = false;
    tree = await mount();
    expect(texts(tree)).toContain('Esta acción no se puede operar desde aquí ahora.');
    await act(async () => tree.unmount());
  });

  it('"No comprar" closes the card and sends nothing', async () => {
    const tree = await mount();
    await press(tree, 'No comprar');
    expect(texts(tree)).toEqual(['No se compró nada.']);
    expect(mockBuy).not.toHaveBeenCalled();
    await act(async () => tree.unmount());
  });
});

describe('selling', () => {
  it('a dollar amount: what comes back after the fee, into Confío Dollar+', async () => {
    const tree = await mount('sell:10.00');
    expect(mockSoftQuote).toHaveBeenCalledWith('AAPLon', 'sell', 10);
    // 0.0834 × 240 = 20.016 gross, minus 0.3%.
    expect(texts(tree)).toEqual(expect.arrayContaining(['US$10.00', 'US$19.96', 'Vuelve a']));
    mockSell.mockResolvedValue({ txHash: '0x123', tokenAmountWei: WEI, expectedNetWei: (WEI * 995n) / 100n });
    await press(tree, 'Aprobar venta');
    expect(mockSell).toHaveBeenCalledWith(expect.objectContaining({
      symbol: 'AAPLon', grossAmountUsd: 10, sellAll: false, expectedFeeBps: 30n,
      requestId: 'chat-trade-0000004512-abc123abc123',
    }));
    expect(texts(tree)).toContain('Listo: US$9.95 en tu Confío Dollar+');
    await act(async () => tree.unmount());
  });

  it('all of it sells the whole position, as the screen\'s MAX', async () => {
    const tree = await mount('sell:all');
    expect(mockSoftQuote).toHaveBeenCalledWith('AAPLon', 'sell', 35.1);
    mockSell.mockResolvedValue({ txHash: '0x123', tokenAmountWei: WEI, expectedNetWei: 35n * WEI });
    await press(tree, 'Aprobar venta');
    expect(mockSell).toHaveBeenCalledWith(expect.objectContaining({ grossAmountUsd: 35.1, sellAll: true }));
    await act(async () => tree.unmount());
  });

  it('nothing to sell, or more than they hold, is said instead of offered', async () => {
    let tree = await mount('sell:50.00');
    expect(texts(tree)).toContain('Tienes US$35.11 de AAPL.');
    await act(async () => tree.unmount());
    mockPortfolio.stocks.positions = [];
    tree = await mount('sell:10.00');
    expect(texts(tree)).toContain('No tienes AAPL para vender.');
    expect(button(tree, 'Aprobar venta')).toBeUndefined();
    await act(async () => tree.unmount());
  });
});
