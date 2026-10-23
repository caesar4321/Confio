import { setNumberLocaleCountry } from '../numberLocale';
import { formatFeeBps, formatLocalPrice, formatRating, formatReference, formatUsd } from '../comprarFormat';

afterEach(() => setNumberLocaleCountry(null));

it('writes Comprar amounts the way a comma-decimal country does (Bolivia, Venezuela…)', () => {
  setNumberLocaleCountry('BO');
  expect(formatUsd('1508.5')).toBe('US$1.508,50');
  expect(formatLocalPrice(6060.44, 'BOB')).toBe('6.060,44 Bs');
  expect(formatLocalPrice(15, 'BOB')).toBe('15 Bs');
  expect(formatReference({ amount: '208.8', currency: 'BOB' })).toBe('≈ 208,80 Bs');
  expect(formatFeeBps(750)).toBe('7,5%');
  expect(formatRating('4.5')).toBe('4,5');
});

it('and the way a dot-decimal country does (Mexico, Peru…)', () => {
  setNumberLocaleCountry('MX');
  expect(formatUsd('1508.5')).toBe('US$1,508.50');
  expect(formatLocalPrice(1234.5, 'MXN')).toBe('$ 1,234.50');
  expect(formatFeeBps(750)).toBe('7.5%');
  expect(formatRating(4.5)).toBe('4.5');
});
