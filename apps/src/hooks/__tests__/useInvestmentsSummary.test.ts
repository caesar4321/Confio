import { summarizeInvestments, InvestmentsSummaryInput } from '../useInvestmentsSummary';

jest.mock('../useCrypto', () => ({}));
jest.mock('../useSavingsPortfolio', () => ({}));

const ASSETS = [
  { name: 'Bitcoin', category: 'crypto' },
  { name: 'Tether Gold', category: 'metal' },
];
const btc = (valueUsd: number | null, units = '1000') => ({
  symbol: 'BTCB', ticker: 'BTC', name: 'Bitcoin', category: 'crypto', units, decimals: 18, valueUsd, dayChangePct: 1,
});
const gold = (valueUsd: number | null) => ({
  symbol: 'XAUT', ticker: 'XAUT', name: 'Tether Gold', category: 'metal', units: '5', decimals: 6, valueUsd, dayChangePct: 0,
});

const base: InvestmentsSummaryInput = {
  stocksEnabled: false,
  stockPositionCount: 0,
  stocksTotalUsd: 0,
  cryptoEnabled: false,
  cryptoHoldings: [],
  cryptoAssets: ASSETS,
};

describe('summarizeInvestments gating matrix', () => {
  it('hides the row when nothing is enabled and nothing is held', () => {
    expect(summarizeInvestments(base).visible).toBe(false);
  });

  it('stocks only: invites to stocks', () => {
    const s = summarizeInvestments({ ...base, stocksEnabled: true });
    expect(s).toMatchObject({ visible: true, holds: false, totalUsd: 0, totalKnown: true });
    expect(s.subtitle).toBe('Acciones desde US$1');
  });

  it('crypto only (e.g. Ondo-ineligible): invites to gold and bitcoin from the market', () => {
    const s = summarizeInvestments({ ...base, cryptoEnabled: true });
    expect(s.visible).toBe(true);
    expect(s.subtitle).toBe('Bitcoin y oro desde US$1');
  });

  it('both enabled, nothing held', () => {
    expect(summarizeInvestments({ ...base, stocksEnabled: true, cryptoEnabled: true }).subtitle)
      .toBe('Acciones, bitcoin y oro desde US$1');
  });

  it('holdings: one total and a short count line', () => {
    const s = summarizeInvestments({
      ...base, stocksEnabled: true, cryptoEnabled: true, stockPositionCount: 3, stocksTotalUsd: 30,
      cryptoHoldings: [gold(20), btc(10)],
    });
    expect(s).toMatchObject({ visible: true, holds: true, totalUsd: 60, totalKnown: true });
    expect(s.subtitle).toBe('3 acciones · oro · bitcoin');
  });

  it('a holder stays visible after crypto is switched off (selling is never gated)', () => {
    const s = summarizeInvestments({ ...base, cryptoHoldings: [btc(10)] });
    expect(s).toMatchObject({ visible: true, holds: true, totalUsd: 10 });
    expect(s.subtitle).toBe('bitcoin');
  });

  it('stock positions never count for a blocked geo', () => {
    const s = summarizeInvestments({ ...base, stockPositionCount: 2, stocksTotalUsd: 50 });
    expect(s).toMatchObject({ visible: false, totalUsd: 0 });
  });

  it('unknown crypto is never zero: totalKnown false, known parts still summed', () => {
    const unknown = summarizeInvestments({
      ...base, stocksEnabled: true, cryptoEnabled: true, stocksTotalUsd: 5, stockPositionCount: 1, cryptoHoldings: null,
    });
    expect(unknown).toMatchObject({ totalUsd: 5, totalKnown: false });
    const unpriced = summarizeInvestments({ ...base, cryptoEnabled: true, cryptoHoldings: [btc(null)] });
    expect(unpriced).toMatchObject({ holds: true, totalKnown: false, totalUsd: 0 });
  });

  it('an older server (no crypto at all) never turns the stocks row into "—"', () => {
    const s = summarizeInvestments({ ...base, stocksEnabled: true, stocksTotalUsd: 7, stockPositionCount: 1, cryptoHoldings: null });
    expect(s).toMatchObject({ totalKnown: true, totalUsd: 7, subtitle: '1 acción' });
  });

  it('a zero-unit row is not a holding', () => {
    expect(summarizeInvestments({ ...base, cryptoHoldings: [btc(0, '0')] }).visible).toBe(false);
  });
});
