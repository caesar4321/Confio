import { operationUuid, transactionTimestamp, transactionDetailRoute, transactionReceiptRoute, paymentSuccessDetailRoute, unifiedDetailRoute } from '../transactionRoutes';

// Matches send/payment/payroll model generators (uuid.uuid4().hex).
const uuid = '12345678123442348234123456789abc';
const timestamp = '2026-08-28T11:17:09Z';
const hash = `0x${'a'.repeat(64)}`;

describe('shared transaction route adapters', () => {
  it('normalizes persisted notification aliases without confusing chain hashes with operation IDs', () => {
    const result = transactionDetailRoute({transactionType: 'received', transactionData: {
      id: '42', internal_id: uuid, transaction_hash: hash, created_at: timestamp,
      token_type: 'CUSD_PLUS', amount: '100', sender_phone: '57:3000000000',
      fee_amount: '0.9', net_amount: '99.1', conversion_type: 'USDT_TO_CUSD_PLUS',
    }});
    expect(result.transactionData).toMatchObject({id: uuid, internalId: uuid, hash, createdAt: timestamp,
      currency: 'CUSD_PLUS', amount: '+100', fromPhone: '57:3000000000', feeAmount: '0.9',
      netAmount: '99.1', conversion_type: 'USDT_TO_CUSD_PLUS', type: 'received'});
  });
  it('preserves a legacy source row ID for fetching, but not for verification', () => {
    const receipt = transactionReceiptRoute({transaction: {id: '42', amount: '100'}});
    expect(receipt.transaction.id).toBe('42');
    expect(receipt.transaction.verificationId).toBeUndefined();
    expect(receipt.transaction.date).toBeUndefined();
  });
  it.each([hash, 'A'.repeat(52), '#PENDING', '42'])('never treats %s as an operation UUID', value => {
    expect(operationUuid(value)).toBeUndefined();
    expect(transactionReceiptRoute({transaction: {id: value, internalId: value, verificationId: value}}).transaction.verificationId).toBeUndefined();
  });
  it('preserves both sides and fee metadata of a conversion', () => {
    const source = {internalId: uuid, createdAt: timestamp, amount: '100', currency: 'USDT',
      fromAmount: '100', toAmount: '99.1', feeAmount: '0.9', feeBps: 90,
      from_token: 'USDT', to_token: 'CUSD_PLUS', sourceAddress: 'source', destinationAddress: 'destination'};
    expect(transactionDetailRoute({transactionType: 'conversion', transactionData: source}).transactionData).toMatchObject(source);
  });
  it('keeps ramp data while excluding a unified row ID from operation identity', () => {
    const result = unifiedDetailRoute({transactionType: 'ramp', transactionData: {
      id: '2963', amount: '690', currency: 'BOB', rampDirection: 'on_ramp',
      walletAmount: '99', walletCurrency: 'CUSD_PLUS', rampProvider: 'Provider', createdAt: timestamp,
    }});
    expect(result.transactionData).toMatchObject({amount: '690', currency: 'BOB', walletAmount: '99', createdAt: timestamp});
    expect(result.transactionData?.id).toBeUndefined();
  });
  it('opens payment success as a debit with source identity, amount, merchant and date', () => {
    const result = paymentSuccessDetailRoute({internalId: uuid, transactionHash: hash, amount: '100',
      currency: 'CUSD_PLUS', merchant: 'Comercio', createdAt: timestamp, status: 'CONFIRMED'});
    expect(result).toMatchObject({transactionType: 'payment', transactionData: {
      id: uuid, amount: '-100', to: 'Comercio', hash, createdAt: timestamp, status: 'CONFIRMED',
    }});
  });
  it.each(['payment', 'transfer', 'payroll'] as const)('preserves %s receipt fields and historical dates', type => {
    const source = {internalId: uuid, createdAt: timestamp, date: '2026-10-11', amount: '100',
      payerBusiness: {id: 'business'}, recipientUser: {id: '139'}, payrollRunId: 'run', employeeName: 'Empleado'};
    expect(transactionReceiptRoute({type, transaction: source})).toMatchObject({type, transaction: {
      ...source, date: timestamp, verificationId: uuid,
    }});
  });
  it('does not invent timestamps or crash on out-of-range numeric timestamps', () => {
    expect(transactionTimestamp(undefined, null, '', 'invalid', 1e30)).toBeUndefined();
    expect(transactionTimestamp(timestamp)).toBe(timestamp);
    expect(transactionTimestamp(0)).toBe('1970-01-01T00:00:00.000Z');
  });
  it('retains numeric zero values from legacy notifications', () => {
    expect(transactionDetailRoute({transactionType: 'payment', transactionData: {
      amount: 0, fee_amount: 0, net_amount: 0, fee_bps: 0,
    }}).transactionData).toMatchObject({amount: '0', feeAmount: '0', netAmount: '0', feeBps: 0});
  });
});

it('keeps the resolved route direction authoritative over stale notification aliases', () => {
  const result = transactionDetailRoute({transactionType: 'received', transactionData: {
    transaction_type: 'send', type: 'send', internal_id: uuid,
  }});
  expect(result.transactionData).toMatchObject({type: 'received', transaction_type: 'received', transactionType: 'received'});
});

it('does not replace a real chain hash with a share payload operation UUID', () => {
  const receipt = transactionReceiptRoute({transaction: {internalId: uuid, transactionHash: uuid, hash}});
  expect(receipt.transaction.hash).toBe(hash);
  expect(receipt.transaction.transactionHash).toBe(hash);
  const missing = transactionDetailRoute({transactionType: 'sent', transactionData: {id: hash, transactionHash: uuid}});
  expect(missing.transactionData?.id).toBeUndefined();
  expect(missing.transactionData?.hash).toBeUndefined();
});

it('handles incoming legacy send notifications without turning them into outgoing sends', () => {
  const result = transactionDetailRoute({transactionType: 'send', transactionData: {
    notification_type: 'SEND_RECEIVED', amount: '100', internal_id: uuid,
  }});
  expect(result).toMatchObject({transactionType: 'received', transactionData: {type: 'received', amount: '+100'}});
});

it('accepts the backend uuid.uuid4().hex operation IDs without changing their shape', () => {
  const id = 'da847ed098a44dd6ac1d72a34f845dee';
  expect(operationUuid(id)).toBe(id);
  expect(transactionReceiptRoute({type: 'payroll', transaction: {internalId: id}}).transaction.verificationId).toBe(id);
  expect(paymentSuccessDetailRoute({internalId: id, amount: '100'}).transactionData?.id).toBe(id);
});

it('never certifies an unknown receipt status as confirmed', () => {
  expect(transactionReceiptRoute({transaction: {internalId: uuid}}).transaction.status).toBe('pending');
});

it('also accepts legacy dashed UUIDs', () => {
  const id = '12345678-1234-4234-8234-123456789abc';
  expect(operationUuid(id)).toBe(id);
});
