import {
  assetTitle, centsToDecimal, daysLabel, daysUntil, dollarName, frequencyLabel, railLabel, ruleTitle,
  toCents, typedCents, unitsForUsd, usd,
} from '../format';

it('formats dollars with US$ and never invents a zero', () => {
  expect(usd('1234.5')).toBe('US$1,234.50');
  expect(usd(null)).toBe('—');
  expect(usd(undefined)).toBe('—');
});

it('does money arithmetic in integer cents', () => {
  expect(toCents('149.99')).toBe(14999n);
  expect(toCents('0.1')).toBe(10n);
  expect(toCents('7')).toBe(700n);
  expect(toCents('1.239')).toBe(123n);
  expect(toCents('abc')).toBeNull();
  expect(centsToDecimal(14999n)).toBe('149.99');
  expect(centsToDecimal(5n)).toBe('0.05');
  expect(typedCents('149.99')).toBe(14999n);
  expect(typedCents('')).toBeNull();
});

it('converts a dollar amount to base units from the asset itself', () => {
  const asset = { units: '500000000000000000000', valueUsd: '510.00' }; // shares worth more than 1 each
  expect(unitsForUsd(25500n, asset)).toBe('250000000000000000000');
  expect(unitsForUsd(51000n, asset)).toBe('max');
  expect(unitsForUsd(99999n, asset)).toBe('max');
  expect(unitsForUsd(0n, asset)).toBeNull();
  expect(unitsForUsd(100n, { units: '10', valueUsd: null })).toBeNull();
});

it('names the one Confío dollar, never "Dollar+" alone', () => {
  expect(dollarName('cusd_plus')).toBe('Confío Dollar+');
  expect(dollarName('cusd')).toBe('Confío Dollar');
  expect(assetTitle({ key: 'cusd_plus', name: 'cUSD+', symbol: 'cUSD+' })).toBe('Confío Dollar+');
  expect(assetTitle({ key: 'stock:AAPLon', name: 'Apple', symbol: 'AAPLon' })).toBe('Apple');
});

it('labels frequencies, rails and days in Spanish', () => {
  expect(['daily', 'weekly', 'biweekly', 'monthly'].map(frequencyLabel)).toEqual(['Diario', 'Semanal', 'Quincenal', 'Mensual']);
  expect(['co_breb', 'br_pix', 'mx_clabe'].map(railLabel)).toEqual(['Bre-B', 'Pix', 'CLABE']);
  expect(daysLabel(1)).toBe('1 día');
  expect(daysLabel(180)).toBe('180 días');
});

it('counts whole days to a date', () => {
  const now = Date.parse('2026-11-20T00:00:00Z');
  expect(daysUntil('2026-11-30T00:00:00Z', now)).toBe(10);
  expect(daysUntil('2026-11-01T00:00:00Z', now)).toBe(0);
  expect(daysUntil(null, now)).toBeNull();
});

it('writes a rule as what it does', () => {
  const base = { payeeName: null, payeeHandle: null, payoutLabel: null, payoutRail: null, assetName: null, assetSymbol: null };
  expect(ruleTitle({ ...base, kind: 'send', amountUsd: '50', payeeName: 'Ana' })).toBe('Enviar US$50.00 a Ana');
  expect(ruleTitle({ ...base, kind: 'payout', amountUsd: '20', payoutLabel: 'Bre-B · Ana P.' })).toBe('Pagar US$20.00 a Bre-B · Ana P.');
  expect(ruleTitle({ ...base, kind: 'buy', amountUsd: '10', assetName: 'Apple' })).toBe('Invertir US$10.00 en Apple');
});
