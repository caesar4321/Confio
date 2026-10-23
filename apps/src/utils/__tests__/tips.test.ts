import { parseTipAmount } from '../tips';

test('valid tip amounts', () => {
  expect(parseTipAmount('5')).toBe('5.00');
  expect(parseTipAmount('0.5')).toBe('0.50');
  expect(parseTipAmount('200')).toBe('200.00');
  expect(parseTipAmount('12.3')).toBe('12.30');
});

test('invalid tip amounts', () => {
  for (const text of ['', '0.49', '200.01', '1.234', 'abc', '1000', '.5', '-1']) {
    expect(parseTipAmount(text)).toBeNull();
  }
});
