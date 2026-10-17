import {
  formatAmount,
  formatHoldTime,
  formatMemberSince,
  formatPctAbs,
  formatPctSigned,
  formatShortDate,
  formatUsd,
  isZeroAmount,
  moneyParts,
  signOf,
  tradeCountLabel,
} from '../portfolioFormat';

describe('portfolioFormat', () => {
  test('money with thousands separators', () => {
    expect(formatUsd('11658.03')).toBe('$11,658.03');
    expect(formatUsd('1234567.5')).toBe('$1,234,567.50');
    expect(formatUsd('0.00')).toBe('$0.00');
    expect(formatUsd('-25.10')).toBe('-$25.10');
    expect(formatUsd('7412.11', { signed: true })).toBe('+$7,412.11');
    expect(formatUsd('-7412.11', { signed: true })).toBe('-$7,412.11');
    expect(formatUsd('0.00', { signed: true })).toBe('$0.00');
    expect(formatUsd('-0.00')).toBe('$0.00');
    expect(formatUsd('123.4500')).toBe('$123.45');
    expect(formatUsd('0.1234')).toBe('$0.1234');
  });

  test('unknown amounts stay null, never $0', () => {
    expect(formatUsd(null)).toBeNull();
    expect(formatUsd(undefined)).toBeNull();
    expect(formatUsd('abc')).toBeNull();
    expect(formatPctAbs(null)).toBeNull();
    expect(signOf(null)).toBeNull();
  });

  test('money parts split the cents', () => {
    expect(moneyParts('11658.03')).toEqual({ sign: '', whole: '$11,658', cents: '.03' });
    expect(moneyParts('5', { signed: true })).toEqual({ sign: '+', whole: '+$5', cents: '.00' });
  });

  test('percent and sign', () => {
    expect(formatPctAbs('-12.3')).toBe('12.30%');
    expect(formatPctSigned('1.2')).toBe('+1.20%');
    expect(formatPctSigned('-0.85')).toBe('-0.85%');
    expect(formatPctSigned('0.00')).toBe('0.00%');
    expect(signOf('-0.01')).toBe(-1);
    expect(signOf('0.01')).toBe(1);
    expect(isZeroAmount('0.00')).toBe(true);
    expect(isZeroAmount('1000.00')).toBe(false);
  });

  test('token and share amounts', () => {
    expect(formatAmount('1000.00')).toBe('1,000');
    expect(formatAmount('0.500000')).toBe('0.5');
    expect(formatAmount('12345.678')).toBe('12,345.678');
  });

  test('hold time', () => {
    expect(formatHoldTime(null)).toBeNull();
    expect(formatHoldTime(30)).toBe('< 1 min');
    expect(formatHoldTime(12 * 60 + 5)).toBe('12 min');
    expect(formatHoldTime(7 * 3600 + 53 * 60)).toBe('7h 53m');
    expect(formatHoldTime(2 * 3600)).toBe('2h');
    expect(formatHoldTime(3 * 86400 + 3600)).toBe('3 d');
  });

  test('member since and dates', () => {
    expect(formatMemberSince('2026-10')).toBe('oct 2026');
    expect(formatMemberSince('2025-01')).toBe('ene 2025');
    expect(formatMemberSince(null)).toBeNull();
    expect(formatMemberSince('2026-13')).toBeNull();
    const now = new Date(2026, 9, 17);
    expect(formatShortDate('2026-03-02', now)).toBe('2 mar');
    expect(formatShortDate('2025-12-31', now)).toBe('31 dic 2025');
  });

  test('trade count', () => {
    expect(tradeCountLabel(1)).toBe('1 trade');
    expect(tradeCountLabel(14)).toBe('14 trades');
  });
});
