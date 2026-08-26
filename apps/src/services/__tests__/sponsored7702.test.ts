const USER = `0x${'11'.repeat(20)}`;
const mockDelegate = `0x${'22'.repeat(20)}`;
const mockSponsorBscBatch = jest.fn();
const mockDeriveIntentId = jest.fn(
  (_calls: unknown, _requestId?: string) => `0x${'33'.repeat(32)}`,
);

jest.mock('../bscServerRpc', () => ({
  sponsorBscBatch: (...args: unknown[]) => mockSponsorBscBatch(...args),
}));
jest.mock('../../setup/entropyGuard', () => ({
  secureRandomBytes: jest.fn(() => new Uint8Array(16).fill(7)),
}));
jest.mock('../evmWallet', () => ({
  bscEthCall: jest.fn(async () => '0x0'),
  bscGetCode: jest.fn(async () => `0xef0100${mockDelegate.slice(2)}`),
  bscGetNonce: jest.fn(async () => 0n),
  bscWaitForReceipt: jest.fn(),
  deriveIntentId: (calls: unknown, requestId?: string) =>
    mockDeriveIntentId(calls, requestId),
  hashBatchIntent: jest.fn(() => new Uint8Array(32)),
  receiptExecutedBatch: jest.fn(),
  selector: jest.fn(() => '0x12345678'),
  signIntentDigest: jest.fn(() => `0x${'44'.repeat(65)}`),
  signSetCodeAuthorization: jest.fn(),
  BscReceiptTimeoutError: class BscReceiptTimeoutError extends Error {},
  BscRevertedError: class BscRevertedError extends Error {},
}));

import { executeSponsoredBatch } from '../sponsored7702';

describe('sponsored 7702 idempotency', () => {
  beforeEach(() => jest.clearAllMocks());

  it('uses stable per-attempt ids while allowing the one no-op retry', async () => {
    mockSponsorBscBatch
      .mockResolvedValueOnce({ success: true, txHash: `0x${'55'.repeat(32)}`, execution: 'noop' })
      .mockResolvedValueOnce({ success: true, txHash: `0x${'66'.repeat(32)}`, execution: 'executed' });
    const calls = [{ to: mockDelegate, valueWei: 0n, data: '0x12345678' }];

    const result = await executeSponsoredBatch({
      wallet: { address: USER, privKeyHex: '77'.repeat(32) },
      calls,
      delegateAddress: mockDelegate,
      requestId: 'gm_0123456789abcdef0123456789abcdef',
    });

    expect(result.txHash).toBe(`0x${'66'.repeat(32)}`);
    expect(mockSponsorBscBatch.mock.calls.map(([arg]) => arg.requestId)).toEqual([
      'gm_0123456789abcdef0123456789abcdef_a0',
      'gm_0123456789abcdef0123456789abcdef_a1',
    ]);
    expect(mockDeriveIntentId.mock.calls.map(([, requestId]) => requestId)).toEqual([
      'gm_0123456789abcdef0123456789abcdef_a0',
      'gm_0123456789abcdef0123456789abcdef_a1',
    ]);
  });
});
