// ActivitySummary (where the trade helpers live) pulls in navigation and icons.
jest.mock('@react-navigation/native', () => ({ useNavigation: () => ({ navigate: jest.fn() }) }));
jest.mock('../../hooks/useRampCountry', () => ({ useRampCountry: () => ({}) }));
jest.mock('../../contexts/AccountContext', () => ({ useAccount: () => ({}) }));
jest.mock('react-native-vector-icons/Feather', () => 'Icon');
jest.mock('@apollo/client', () => ({ useQuery: () => ({}) }));
jest.mock('../../apollo/queries', () => ({}));

import { activityCardContent } from '../activityShareCard';

const base = { date: '2026-11', rail: null, country: null, minutes: null, headline: '' };

describe('activityCardContent', () => {
  it('maps each investment to its product and venue', () => {
    const stock = activityCardContent({ ...base, kind: 'stock_buy', ticker: 'TSLA', amountUsd: '10' }, true)!;
    expect([stock.product, stock.venue]).toEqual(['Acciones', 'ondo']);
    const gold = activityCardContent({ ...base, kind: 'crypto_buy', ticker: 'XAUT', category: 'metal', amountUsd: '5' }, true)!;
    expect([gold.product, gold.venue]).toEqual(['Oro y Bitcoin', 'pancakeswap']);
    const perp = activityCardContent({ ...base, kind: 'perps_open', ticker: 'ZEC', pnlPct: '-0.43', category: 'perp' }, true)!;
    expect([perp.product, perp.venue, perp.tag]).toEqual(['Futuros', 'hyperliquid', null]);
  });

  it('never shows dollars when the amount is hidden; the percent stays', () => {
    const c = activityCardContent({ ...base, kind: 'stock_sell', ticker: 'AAPL', amountUsd: '40', pnlPct: '3.1', pnlUsd: '1.2' }, false)!;
    expect(c.headline).toContain('3');
    expect(c.usdLine).toBeNull();
    expect(c.rows).toEqual([]);
    expect(c.lead).not.toMatch(/US\$/);
  });

  it('a hidden-amount buy says what was bought', () => {
    const c = activityCardContent({ ...base, kind: 'stock_buy', ticker: 'NVDA', amountUsd: '25' }, false)!;
    expect(c.headline).toBe('Compré NVDA');
    expect(c.headlineIsText).toBe(true);
  });

  it('ignores non-investment movements', () => {
    expect(activityCardContent({ ...base, kind: 'top_up', amountUsd: '10' }, true)).toBeNull();
  });
});

describe('holdingCardContent', () => {
  const { holdingCardContent } = require('../activityShareCard');
  it('shows the return since purchase, dollars only when on', () => {
    const off = holdingCardContent({ kind: 'stock', ticker: 'tsla', pnlPct: '12.5', pnlUsd: '3', valueUsd: '27' }, false);
    expect([off.venue, off.kindLabel, off.usdLine, off.rows]).toEqual(['ondo', 'Desde la compra', null, []]);
    expect(off.lead).not.toMatch(/US\$/);
    const on = holdingCardContent({ kind: 'crypto', ticker: 'BTC', pnlPct: '-2', pnlUsd: '-1', valueUsd: '49' }, true);
    expect(on.venue).toBe('pancakeswap');
    expect(on.usdLine).toMatch(/US\$/);
    expect(on.rows[0].label).toBe('Valor actual');
  });
  it('without a known return it just says it is held', () => {
    const c = holdingCardContent({ kind: 'stock', ticker: 'AAPL' }, true);
    expect([c.headline, c.headlineIsText, c.kindLabel]).toEqual(['Tengo AAPL', true, null]);
  });
});

