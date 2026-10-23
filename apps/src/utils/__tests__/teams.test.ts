import { buildTeamInviteLink, championLabel, goalLabel, rankMark, teamTokenFromCode, tickerOfSymbol } from '../teams';

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

test('team invite links carry no username and survive case changes', () => {
  expect(buildTeamInviteLink('abc123def456gh78')).toBe('https://confio.lat/invite/team~abc123def456gh78?source=team');
  expect(teamTokenFromCode('TEAM~ABC123DEF456GH78')).toBe('abc123def456gh78');
  expect(teamTokenFromCode('ANA')).toBeNull();
  expect(teamTokenFromCode('team~<x>')).toBeNull();
});
