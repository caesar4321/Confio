import { championLabel, goalLabel, rankMark, tickerOfSymbol } from '../teams';

test('champion months', () => {
  expect(championLabel('2026-10')).toBe('Campeón de octubre 2026');
  expect(championLabel('2026-13')).toBe('');
  expect(championLabel('x')).toBe('');
});

test('podium marks', () => {
  expect([1, 2, 3, 4].map(rankMark)).toEqual(['🥇', '🥈', '🥉', '4.']);
});

test('GM symbols map to buy-screen tickers', () => {
  expect(tickerOfSymbol('NVDAon')).toBe('NVDA');
  expect(tickerOfSymbol('BTCB')).toBe('BTCB');
});

test('goal labels', () => {
  expect(goalLabel({ kind: 'invested_usd', target: '1000.00', progress: '0', percent: 0, reached: false }))
    .toBe('Invertir juntos $1,000');
  expect(goalLabel({ kind: 'weekly_investors', target: '3.00', progress: '1', percent: 33, reached: false }))
    .toBe('3 miembros invirtiendo esta semana');
});
