import {
  formatDecimal, formatUsdAmount, parseAmountInput, sanitizeAmountInput, separatorsForCountry,
  setNumberLocaleCountry, toAmountInput,
} from '../numberLocale';

const VE = separatorsForCountry('VE');
const MX = separatorsForCountry('MX');

afterEach(() => setNumberLocaleCountry(null));

describe('separators by country', () => {
  it('comma-decimal LatAm vs dot-decimal LatAm', () => {
    for (const c of ['VE', 'AR', 'CO', 'BO', 'CL', 'EC', 'PY', 'UY', 'BR']) expect(separatorsForCountry(c).decimal).toBe(',');
    for (const c of ['MX', 'PE', 'DO', 'SV', 'GT', 'HN', 'NI', 'PA', 'US']) expect(separatorsForCountry(c).decimal).toBe('.');
    expect(separatorsForCountry(null).decimal).toBe('.');
    expect(separatorsForCountry('ve').decimal).toBe(',');
  });
});

describe('formatDecimal / formatUsdAmount', () => {
  it('formats with the app-wide country', () => {
    setNumberLocaleCountry('VE');
    expect(formatDecimal(1234567.891)).toBe('1.234.567,89');
    expect(formatUsdAmount(27.84)).toBe('US$27,84');
    expect(formatDecimal(1000, { decimals: 0 })).toBe('1.000'); // 4 digits are grouped (es-ES Intl did not)
    setNumberLocaleCountry('MX');
    expect(formatDecimal(1234567.891)).toBe('1,234,567.89');
    expect(formatUsdAmount(-5)).toBe('-US$5.00');
  });

  it('rounds half up without float surprises, and never prints -0', () => {
    expect(formatDecimal(1.005)).toBe('1.01');
    expect(formatDecimal(-0.001)).toBe('0.00');
    expect(formatDecimal(-1.5, { decimals: 0 })).toBe('-2');
  });

  it('minDecimals trims trailing zeros down to the minimum', () => {
    expect(formatDecimal(0.004, { decimals: 3, minDecimals: 2 })).toBe('0.004');
    expect(formatDecimal(1.5, { decimals: 6, minDecimals: 2 })).toBe('1.50');
    expect(formatDecimal(1, { decimals: 6, minDecimals: 0 })).toBe('1');
  });

  it('explicit separators override the app-wide ones', () => {
    setNumberLocaleCountry('MX');
    expect(formatDecimal(1234.5, { separators: VE })).toBe('1.234,50');
  });
});

describe('parseAmountInput (money-moving: what the user typed)', () => {
  it('either decimal key works, whatever the keypad shows', () => {
    expect(parseAmountInput('12,5', VE)).toBe(12.5);
    expect(parseAmountInput('12.5', VE)).toBe(12.5);
    expect(parseAmountInput('12,5', MX)).toBe(12.5);
    expect(parseAmountInput('12.5', MX)).toBe(12.5);
    expect(parseAmountInput('0,123456', VE)).toBe(0.123456);
  });

  it('3 digits after the country group mark = thousands', () => {
    expect(parseAmountInput('1.234', VE)).toBe(1234);
    expect(parseAmountInput('1,234', MX)).toBe(1234);
    expect(parseAmountInput('1,234', VE)).toBe(1.234); // ',' is VE's decimal
  });

  it('pasted full numbers: last mark is the decimal', () => {
    expect(parseAmountInput('1.234,56', VE)).toBe(1234.56);
    expect(parseAmountInput('1,234.56', VE)).toBe(1234.56);
    expect(parseAmountInput('1.234.567', VE)).toBe(1234567);
    expect(parseAmountInput('US$ 1.234,56', VE)).toBe(1234.56);
  });

  it('rejects garbage instead of guessing', () => {
    for (const bad of ['', 'abc', '1.2.3', '1,2,3', '12a', '1.23.456', '.', ',', '1.234,5,6']) {
      expect(Number.isNaN(parseAmountInput(bad, VE))).toBe(true);
    }
    expect(Number.isNaN(parseAmountInput(null))).toBe(true);
  });
});

describe('sanitizeAmountInput (live typing)', () => {
  it('keeps digits and one decimal mark, shown as the country mark, capped decimals', () => {
    expect(sanitizeAmountInput('12.5', 2, VE)).toBe('12,5');
    expect(sanitizeAmountInput('12,567', 2, VE)).toBe('12,56');
    expect(sanitizeAmountInput('1,2.3', 2, MX)).toBe('1.23');
    expect(sanitizeAmountInput('.5', 2, MX)).toBe('0.5');
    expect(sanitizeAmountInput('a1b2', 2, MX)).toBe('12');
    expect(sanitizeAmountInput('12.5', 0, MX)).toBe('125');
  });

  it('what sanitize shows parses back to the same value', () => {
    for (const s of [VE, MX]) {
      for (const typed of ['12.5', '12,5', '1234.56', '0.01', '999999,99']) {
        const shown = sanitizeAmountInput(typed, 2, s);
        expect(parseAmountInput(shown, s)).toBeCloseTo(Number(typed.replace(',', '.')), 6);
      }
    }
  });
});

describe('toAmountInput', () => {
  it('pre-fills an input with the country decimal mark, no grouping, no trailing zeros', () => {
    expect(toAmountInput(1234.5, 2, VE)).toBe('1234,5');
    expect(toAmountInput(10, 2, MX)).toBe('10');
  });
  it('truncates, never rounds up (Max must not exceed the balance)', () => {
    expect(toAmountInput(0.105, 2, MX)).toBe('0.1');
    expect(toAmountInput(12.345678, 2, VE)).toBe('12,34');
    expect(toAmountInput(1.13, 2, MX)).toBe('1.13');
    expect(toAmountInput(12.345678, 6, VE)).toBe('12,345678');
  });
});

describe('sanitizeAmountInput keeps pasted grouped numbers intact', () => {
  it('VE: "1.234,56" pasted into a 6-decimal field stays 1234.56', () => {
    const shown = sanitizeAmountInput('1.234,56', 6, VE);
    expect(shown).toBe('1234,56');
    expect(parseAmountInput(shown, VE)).toBe(1234.56);
  });
  it('MX: "1,234.56" and "1,234,567" pasted', () => {
    expect(parseAmountInput(sanitizeAmountInput('1,234.56', 2, MX), MX)).toBe(1234.56);
    expect(parseAmountInput(sanitizeAmountInput('1,234,567', 2, MX), MX)).toBe(1234567);
  });
});

describe('formatAmountString (server strings shown)', () => {
  it('keeps sign and exact decimals, localizes separators, passes non-numbers through', () => {
    setNumberLocaleCountry('VE');
    const { formatAmountString } = require('../numberLocale');
    expect(formatAmountString('1234.50')).toBe('1.234,50');
    expect(formatAmountString('-3.1')).toBe('-3,1');
    expect(formatAmountString('+20')).toBe('+20');
    expect(formatAmountString(7)).toBe('7');
    expect(formatAmountString('Pendiente')).toBe('Pendiente');
    expect(formatAmountString(null)).toBe('');
  });
});

describe('sanitizeAmountInput tells a paste from typing (previous value)', () => {
  it('VE: a pasted "1.234" is one thousand two hundred thirty-four', () => {
    expect(parseAmountInput(sanitizeAmountInput('1.234', 6, VE, ''), VE)).toBe(1234);
  });
  it('MX: a pasted "1,234" is 1234', () => {
    expect(parseAmountInput(sanitizeAmountInput('1,234', 2, MX, ''), MX)).toBe(1234);
  });
  it('typing key by key keeps either decimal key as the decimal mark', () => {
    expect(sanitizeAmountInput('1.23', 6, VE, '1.2')).toBe('1,23');
    expect(sanitizeAmountInput('1,234', 6, VE, '1,23')).toBe('1,234');
  });
});

describe('paste over an existing value (replacement)', () => {
  it('VE: replacing "1000" by pasting "1.234" = 1234', () => {
    expect(parseAmountInput(sanitizeAmountInput('1.234', 6, VE, '1000'), VE)).toBe(1234);
  });
  it('a single typed key still uses the simple rule', () => {
    expect(sanitizeAmountInput('100.', 6, VE, '100')).toBe('100,');
    expect(sanitizeAmountInput('10', 6, VE, '100')).toBe('10');
  });
});
