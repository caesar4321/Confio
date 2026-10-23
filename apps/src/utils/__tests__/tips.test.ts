import { parseTipAmount } from '../tips';

test('valid tip amounts', () => {
  expect(parseTipAmount('5')).toBe('5.00');
  expect(parseTipAmount('1')).toBe('1.00');
  expect(parseTipAmount('200')).toBe('200.00');
  expect(parseTipAmount('12.3')).toBe('12.30');
});

test('invalid tip amounts', () => {
  for (const text of ['', '0.5', '0.99', '200.01', '1.234', 'abc', '1000', '-1']) {
    expect(parseTipAmount(text)).toBeNull();
  }
  // Like every amount field a leading mark reads as 0: under the $1 floor.
  expect(parseTipAmount('.5')).toBeNull();
});

describe('isTipTransaction', () => {
  const { isTipTransaction } = require('../tips');
  it('reads the tip key from lists and refetches', () => {
    expect(isTipTransaction({ idempotencyKey: 'tip-abc' })).toBe(true);
    expect(isTipTransaction({ idempotency_key: 'tip-abc' })).toBe(true);
    expect(isTipTransaction({ idempotencyKey: 'send-abc' })).toBe(false);
  });
  it('reads the push flag in any encoding', () => {
    expect(isTipTransaction({ is_tip: true })).toBe(true);
    expect(isTipTransaction({ is_tip: 'True' })).toBe(true);
    expect(isTipTransaction({ is_tip: 'false' })).toBe(false);
    expect(isTipTransaction(null)).toBe(false);
  });
});

describe('tip receipts', () => {
  it('name both sides by their Comunidad names only', () => {
    const { resolveTransferReceiptParticipants } = require('../tokenDisplay');
    const parties = resolveTransferReceiptParticipants(
      { type: 'sent', amount: '-5', idempotencyKey: 'tip-x', senderDisplayName: 'ana_inv', recipientDisplayName: 'leo_inv',
        senderAddress: '0xabc', recipientAddress: '0xdef' },
      { firstName: 'Ana', lastName: 'Real', username: 'anareal', phoneNumber: '+58412' } as any,
    );
    expect(parties.senderName).toBe('ana_inv');
    expect(parties.recipientName).toBe('leo_inv');
    expect(parties.senderPhone).toBeUndefined();
    expect(parties.senderUsername).toBeUndefined();
    expect(parties.senderAddress).toBeUndefined();
    expect(parties.recipientAddress).toBeUndefined();
  });
});

describe('country number format', () => {
  const { setNumberLocaleCountry } = require('../numberLocale');
  afterEach(() => setNumberLocaleCountry(null));
  it('reads tip amounts the way the country writes them', () => {
    const { parseTipAmount } = require('../tips');
    setNumberLocaleCountry('VE');
    expect(parseTipAmount('2,50')).toBe('2.50');
    expect(parseTipAmount('5')).toBe('5.00');
    setNumberLocaleCountry('MX');
    expect(parseTipAmount('2.50')).toBe('2.50');
  });
  it('formats Comunidad money and percents with the country separators', () => {
    const { formatUsd, formatPctSigned, formatAmount } = require('../portfolioFormat');
    setNumberLocaleCountry('VE');
    expect(formatUsd('11658.03')).toBe('$11.658,03');
    expect(formatPctSigned('-2.5')).toBe('-2,50%');
    expect(formatAmount('1000.5')).toBe('1.000,5');
    setNumberLocaleCountry('MX');
    expect(formatUsd('11658.03')).toBe('$11,658.03');
    expect(formatPctSigned('-2.5')).toBe('-2.50%');
  });
});
