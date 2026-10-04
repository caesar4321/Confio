/** Server amounts are canonical everywhere; only user input is localized. */
import { setNumberLocaleCountry, normalizeAmountInput } from '../numberLocale';
import { parseUsdMicros } from '../tokenAmount';

afterEach(() => setNumberLocaleCountry(null));

it('a canonical server "1.234" stays 1.234 even for a comma-decimal country', () => {
  setNumberLocaleCountry('VE');
  expect(parseUsdMicros('1.234')).toBe(1_234_000n);
  expect(parseUsdMicros(1.234)).toBe(1_234_000n);
});

it('user input goes through normalizeAmountInput first (VE: "1.234" typed = 1234)', () => {
  setNumberLocaleCountry('VE');
  expect(parseUsdMicros(normalizeAmountInput('1.234'))).toBe(1_234_000_000n);
  expect(parseUsdMicros(normalizeAmountInput('12,5'))).toBe(12_500_000n);
  expect(parseUsdMicros(normalizeAmountInput('abc'))).toBeNull();
});
