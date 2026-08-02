// The client half of the "did our sponsored batch actually execute" rule.
//
// This predicate decides whether the UI reports success, keeps waiting, or
// tells the user it failed — and "it failed" is the answer that makes them
// retry. A retry whose minute-keyed idempotency key has rolled sends the
// money twice, so every case below is really a test about not double-sending.
//
// Mirror of classify_receipt_execution in cusd_plus/sponsor_7702.py; the two
// must agree, because the server's verdict lets the client skip this check.

import { receiptExecutedBatch, BATCH_EXECUTED_TOPIC } from '../evmWallet';

const EOA = '0x' + '19'.repeat(20);
const NONCE = 7n;

const topicNonce = (n: bigint) => '0x' + n.toString(16).padStart(64, '0');

const execLog = (over: Partial<{ address: string; topics: string[] }> = {}) => ({
  address: EOA,
  topics: [BATCH_EXECUTED_TOPIC, topicNonce(NONCE)],
  data: '0x',
  ...over,
});

const receipt = (over: any = {}) =>
  ({ status: '0x1', transactionHash: '0x' + 'cd'.repeat(32), blockNumber: '0x1', ...over });

describe('receiptExecutedBatch', () => {
  it('executed when BatchExecuted(nonce) is present from our EOA', () => {
    expect(receiptExecutedBatch(receipt({ logs: [execLog()] }), EOA, NONCE))
      .toBe('executed');
  });

  it('matches despite uppercase hex from the node', () => {
    // Casing is not guaranteed across RPC providers, and a case mismatch
    // reads as "did not execute" — the dangerous direction to be wrong in.
    const upper = execLog({ topics: [BATCH_EXECUTED_TOPIC.toUpperCase(), topicNonce(NONCE).toUpperCase()] });
    expect(receiptExecutedBatch(receipt({ logs: [upper] }), EOA.toUpperCase(), NONCE))
      .toBe('executed');
  });

  it('noop ONLY when the node affirmatively reports zero logs', () => {
    // A delegation that never applied left a codeless EOA, which cannot emit
    // anything — so an empty list is the only real no-op shape.
    expect(receiptExecutedBatch(receipt({ logs: [] }), EOA, NONCE)).toBe('noop');
  });

  it('unknown when the receipt carries no logs field at all', () => {
    expect(receiptExecutedBatch(receipt(), EOA, NONCE)).toBe('unknown');
  });

  it('unknown when logs exist but the trailing BatchExecuted is missing', () => {
    // ConfioBatchDelegate emits BatchExecuted LAST, so a clipped response
    // keeps the inner transfers and drops exactly our proof.
    const innerTransfer = { address: '0x' + 'aa'.repeat(20), topics: ['0x' + 'bb'.repeat(32)], data: '0x' };
    expect(receiptExecutedBatch(receipt({ logs: [innerTransfer] }), EOA, NONCE))
      .toBe('unknown');
  });

  it('unknown when the event is for a different nonce', () => {
    const other = execLog({ topics: [BATCH_EXECUTED_TOPIC, topicNonce(NONCE + 1n)] });
    expect(receiptExecutedBatch(receipt({ logs: [other] }), EOA, NONCE)).toBe('unknown');
  });

  it('unknown when the event came from a different address', () => {
    const other = execLog({ address: '0x' + 'ee'.repeat(20) });
    expect(receiptExecutedBatch(receipt({ logs: [other] }), EOA, NONCE)).toBe('unknown');
  });

  it('never throws on malformed log entries', () => {
    // This runs after broadcast; an exception here surfaces as "send failed"
    // for a transaction that is already on the network.
    expect(() => receiptExecutedBatch(receipt({ logs: [null] }) as any, EOA, NONCE)).not.toThrow();
    expect(() => receiptExecutedBatch(receipt({ logs: [{}] }) as any, EOA, NONCE)).not.toThrow();
  });
});
