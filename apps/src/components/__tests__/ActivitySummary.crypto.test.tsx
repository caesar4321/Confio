import React from 'react';
import renderer, { act } from 'react-test-renderer';

const mockNavigate = jest.fn();
jest.mock('@react-navigation/native', () => ({ useNavigation: () => ({ navigate: mockNavigate }) }));
jest.mock('../../hooks/useRampCountry', () => ({ useRampCountry: () => ({ navigateToRampOrEfectivo: jest.fn() }) }));
jest.mock('../../contexts/AccountContext', () => ({ useAccount: () => ({ activeAccount: { type: 'personal' } }) }));
jest.mock('react-native-vector-icons/Feather', () => 'Icon');
jest.mock('../svg/BitcoinMark', () => 'BitcoinMark');
jest.mock('../svg/GoldMark', () => 'GoldMark');

import { ActivitySummary, activityDestination, cryptoCategoryOf, tradeSide } from '../ActivitySummary';
import { headlineFor, chipsFor } from '../CommunityShareProvider';

jest.mock('../CommunityRulesSheet', () => ({ CommunityRulesSheet: 'CommunityRulesSheet' }));
jest.mock('../PostByline', () => ({ PostByline: 'PostByline' }));
jest.mock('../../navigation/RootNavigation', () => ({ navigate: jest.fn(), navigationRef: {} }));
jest.mock('@apollo/client', () => ({ useQuery: jest.fn(), useMutation: () => [jest.fn(), {}], gql: () => '' }));
jest.mock('../../apollo/client', () => ({ apolloClient: { query: () => Promise.resolve({ data: undefined }) } }));
jest.mock('../../apollo/queries', () => ({}));
jest.mock('../../apollo/mutations', () => ({}));

const post = (over: Record<string, unknown>) => ({
  kind: 'crypto_buy', amountUsd: '10.00', ticker: 'BTC', name: 'Bitcoin', category: 'crypto',
  pnlUsd: '0.50', pnlPct: '5.00', position: 'open', headline: 'Compró BTC · US$10.00', ...over,
});

const render = async (activity: any, navigable = false) => {
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<ActivitySummary activity={activity} navigable={navigable} />); });
  return tree;
};
const text = (tree: renderer.ReactTestRenderer) => JSON.stringify(tree.toJSON());

describe('Bitcoin & gold Comunidad posts', () => {
  it.each([
    ['crypto_buy', 'crypto', 'BTC', 'Compró BTC', 'BitcoinMark'],
    ['crypto_sell', 'metal', 'XAUT', 'Vendió XAUT', 'GoldMark'],
    // Older-build spelling: the server sends stock_* with a category set.
    ['stock_buy', 'crypto', 'BTC', 'Compró BTC', 'BitcoinMark'],
    ['stock_sell', 'metal', 'XAUT', 'Vendió XAUT', 'GoldMark'],
  ])('%s/%s renders like a stock post with its own mark', async (kind, category, ticker, title, mark) => {
    const tree = await render(post({ kind, category, ticker, name: category === 'metal' ? 'Tether Gold' : 'Bitcoin' }));
    expect(text(tree)).toContain(title);
    expect(text(tree)).toContain('US$10.00');
    expect(text(tree)).toContain('+5.00%');
    expect(tree.root.findAll((n) => n.type === (mark as any)).length).toBe(1);
  });

  it('labels a sale result and a purchase since-buy, for both spellings', async () => {
    expect(text(await render(post({ kind: 'stock_sell', category: 'crypto' })))).toContain('Resultado');
    expect(text(await render(post({ kind: 'crypto_buy' })))).toContain('Desde la compra');
  });

  it('a stock post without category stays a stock post', async () => {
    const stock = post({ kind: 'stock_buy', category: null, ticker: 'NVDA', name: 'NVIDIA' });
    expect(cryptoCategoryOf(stock)).toBeNull();
    expect(activityDestination(stock as any)?.route).toBe('StockDetail');
    const tree = await render(stock);
    expect(tree.root.findAll((n) => n.props?.testID === 'activity-crypto-mark')).toHaveLength(0);
  });

  it('opens the asset page for Bitcoin and gold once the market list maps the ticker', () => {
    const assets = [{ symbol: 'BTCB', ticker: 'BTC', name: 'Bitcoin' }, { symbol: 'XAUT', ticker: 'XAUT', name: 'Oro' }];
    expect(activityDestination(post({ kind: 'crypto_buy', ticker: 'BTC' }) as any, assets))
      .toMatchObject({ route: 'CryptoDetail', params: { symbol: 'BTCB' } });
    expect(activityDestination(post({ kind: 'crypto_sell', ticker: 'xaut', category: 'metal' }) as any, assets))
      .toMatchObject({ route: 'CryptoDetail', params: { symbol: 'XAUT' } });
    // An asset no longer listed: the Invertir tab, never a broken page.
    expect(activityDestination(post({ kind: 'crypto_buy', ticker: 'DOGE' }) as any, assets))
      .toMatchObject({ route: 'BottomTabs' });
  });

  it('opens Invertir (not a stock page) for a crypto post of either spelling', async () => {
    for (const kind of ['crypto_buy', 'stock_buy']) {
      expect(activityDestination(post({ kind }) as any)).toMatchObject({ route: 'BottomTabs', params: { screen: 'Invest' } });
    }
    expect(tradeSide({ kind: 'crypto_sell' })).toBe('sell');
  });

  it('share-sheet headline and chips follow the category', () => {
    expect(headlineFor(post({ kind: 'stock_buy' }) as any, false)).toBe('¡Ya tienes BTC! 🎉');
    expect(headlineFor(post({ kind: 'crypto_sell' }) as any, false)).toBe('Venta lista ✅');
    expect(chipsFor('crypto_buy').length).toBeGreaterThan(0);
  });
});
