import {
  dollarSlot, formatLocal, isPastDay, paceCopy, paceLine, paceTone, projection, quoteTime, shortDate,
} from '../monthInsights';
import { setNumberLocaleCountry } from '../numberLocale';
import type { MonthSummary } from '../../apollo/monthSummary';

const totals = (spending: string, income = '0', count = 1) => ({
  incomeUsd: income, spendingUsd: spending, topUpsUsd: '0', withdrawalsUsd: '0', savingsNetUsd: '0',
  investmentNetUsd: '0', movementCount: count, spendingByCategory: [],
});
const summary = (cur: string, prev: string): MonthSummary => ({
  year: 2026, month: 10, timezone: 'UTC', previousIsPartial: true,
  current: totals(cur), previous: totals(prev), counterparties: [],
});

describe('pace (tu-mes-insights §6, 12B)', () => {
  it('compares the same period with 0.9 / 1.1 boundaries and defined zero rules', () => {
    expect(paceTone(90, 100)).toBe('less');
    expect(paceTone(91, 100)).toBe('same');
    expect(paceTone(110, 100)).toBe('more');
    expect(paceTone(0, 0)).toBe('same');
    expect(paceTone(5, 0)).toBe('more');
  });

  it('speaks warmly to people and plainly to businesses', () => {
    expect(paceCopy('less', 'septiembre', false)).toBe('Vas bien: gastas menos que en septiembre');
    expect(paceCopy('less', 'septiembre', true)).toBe('Hasta hoy salió menos que a esta altura de septiembre');
    expect(paceCopy('more', 'septiembre', true)).toBe('Hasta hoy salió más que a esta altura de septiembre');
  });

  it('projects linearly', () => {
    expect(projection(120, 12, 31)).toBeCloseTo(310);
  });

  it('starts on day 5, projects from day 7, current month only, needs last month', () => {
    const s = summary('100', '150');
    expect(paceLine(s, '390', new Date(2026, 9, 4), false)).toBeNull();
    const day5 = paceLine(s, '390', new Date(2026, 9, 5), false)!;
    expect([day5.tone, day5.projectionUsd, day5.previousMonthLabel]).toEqual(['less', null, 'Septiembre']);
    expect(paceLine(s, '390', new Date(2026, 9, 7), false)!.projectionUsd).toBeCloseTo(100 / 7 * 31);
    expect(paceLine(s, '390', new Date(2026, 10, 7), false)).toBeNull();   // viewing a past month
    expect(paceLine(s, '0.00', new Date(2026, 9, 9), false)).toBeNull();    // last month had no Salió
    expect(paceLine(s, null, new Date(2026, 9, 9), false)).toBeNull();      // insights missing
  });
});

describe('dollar slot (R21)', () => {
  const protection = { currency: 'BOB', basis: 'purchase' as const, source: 'binance_p2p', protectedUsd: '100.00', paidLocal: '690', todayLocal: '740', gainLocal: '50',
    avgRate: '6.90', todayRate: '7.40', quotedAt: '2026-10-04T10:42:00Z' };
  it('prefers protection, then savings of at least a cent, else nothing', () => {
    expect(dollarSlot(protection, { earnedUsd: '0.42', daily: [] })?.kind).toBe('protection');
    expect(dollarSlot(null, { earnedUsd: '0.42', daily: [] })?.kind).toBe('savings');
    expect(dollarSlot(null, { earnedUsd: '0.00', daily: [] })).toBeNull();
    expect(dollarSlot(null, null)).toBeNull();
  });
});

describe('dates and money', () => {
  it('greys a day only once it has passed (7A)', () => {
    const today = new Date(2026, 9, 12, 15);
    expect(isPastDay(2026, 10, 5, today)).toBe(true);
    expect(isPastDay(2026, 10, 12, today)).toBe(false);
    expect(isPastDay(2026, 9, 30, today)).toBe(true);        // every day of a past month
    expect(shortDate(10, 5)).toBe('5 oct');
  });

  it('formats bolivianos with the user separators', () => {
    setNumberLocaleCountry('BO');
    expect(formatLocal('3990', 'BOB')).toBe('Bs 3.990');
    expect(formatLocal('36.5', 'BOB', 2)).toBe('Bs 36,50');
    setNumberLocaleCountry('US');
  });

  it('says "hoy" for a quote from today', () => {
    const now = new Date(2026, 9, 4, 18, 0);
    const at = new Date(2026, 9, 4, 10, 42);
    expect(quoteTime(at.toISOString(), now)).toBe('hoy, 10:42');
    expect(quoteTime(new Date(2026, 9, 3, 9, 5).toISOString(), now)).toBe('3 oct, 09:05');
  });
});
