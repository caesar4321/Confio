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
