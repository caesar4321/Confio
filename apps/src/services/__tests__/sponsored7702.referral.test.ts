const USER = `0x${'11'.repeat(20)}`;
const mockDelegate = `0x${'22'.repeat(20)}`;
const CUSD = `0x${'aa'.repeat(20)}`;
const ARM_SELECTOR = 'a1a1a1a1';
const ARM = { to: CUSD, data: `0x${ARM_SELECTOR}${'00'.repeat(64)}` };
const mockSponsorBscBatch = jest.fn();
const mockQuery = jest.fn();

jest.mock('../bscServerRpc', () => ({
  sponsorBscBatch: (...args: unknown[]) => mockSponsorBscBatch(...args),
}));
jest.mock('@apollo/client', () => ({ gql: (s: TemplateStringsArray) => s.join('') }));
jest.mock('../../apollo/client', () => ({
  apolloClient: { query: (...args: unknown[]) => mockQuery(...args) },
}));
jest.mock('../../setup/entropyGuard', () => ({
  secureRandomBytes: jest.fn(() => new Uint8Array(16).fill(7)),
}));
jest.mock('../evmWallet', () => ({
  bscEthCall: jest.fn(async () => '0x0'),
  bscGetCode: jest.fn(async () => `0xef0100${mockDelegate.slice(2)}`),
  bscGetNonce: jest.fn(async () => 0n),
  bscWaitForReceipt: jest.fn(),
  deriveIntentId: jest.fn(() => `0x${'33'.repeat(32)}`),
  hashBatchIntent: jest.fn(() => new Uint8Array(32)),
  receiptExecutedBatch: jest.fn(),
  selector: jest.fn((sig: string) => (
    sig.startsWith('armReferral') ? `0x${ARM_SELECTOR}`
      : sig.startsWith('mintWithFee') ? '0xdeadbeef'
        : '0x12345678')),
  signIntentDigest: jest.fn(() => `0x${'44'.repeat(65)}`),
  signSetCodeAuthorization: jest.fn(),
  BscReceiptTimeoutError: class BscReceiptTimeoutError extends Error {},
  BscRevertedError: class BscRevertedError extends Error {},
}));

import { executeSponsoredBatch } from '../sponsored7702';

const MINT = { to: CUSD, valueWei: 0n, data: '0xdeadbeef' };
// A fresh request id per action: the arm decision is remembered per id.
let seq = 0;
const nextRequestId = () => `gm_${String(++seq).padStart(32, '0')}`;
const run = (calls = [MINT], requestId = nextRequestId()) =>
  executeSponsoredBatch({
    wallet: { address: USER, privKeyHex: '77'.repeat(32) },
    calls,
    delegateAddress: mockDelegate,
    requestId,
  });
const sentCalls = (i: number) => mockSponsorBscBatch.mock.calls[i][0].calls;

describe('sponsored 7702 fee referral arm', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    // Drop queued once-responses a cached arm left unconsumed.
    mockQuery.mockReset();
    mockSponsorBscBatch.mockReset();
  });

  it('puts the server-issued arm first', async () => {
    mockQuery.mockResolvedValue({ data: { feeReferralArm: ARM } });
    mockSponsorBscBatch.mockResolvedValue({ success: true, txHash: '0xabc', execution: 'executed' });
    await run();
    expect(sentCalls(0)).toEqual([
      { to: ARM.to, valueWei: '0', data: ARM.data },
      { to: MINT.to, valueWei: '0', data: MINT.data },
    ]);
  });

  it('sends the batch unchanged when there is no arm or the query fails', async () => {
    mockSponsorBscBatch.mockResolvedValue({ success: true, txHash: '0xabc', execution: 'executed' });
    mockQuery.mockResolvedValueOnce({ data: { feeReferralArm: null } });
    await run();
    mockQuery.mockRejectedValueOnce(new Error('Cannot query field "feeReferralArm"'));
    await run();
    expect(sentCalls(0)).toHaveLength(1);
    expect(sentCalls(1)).toHaveLength(1);
  });

  it('drops the arm and resends in the same slot when the server refuses it', async () => {
    mockQuery.mockResolvedValue({ data: { feeReferralArm: ARM } });
    mockSponsorBscBatch
      .mockResolvedValueOnce({ success: false, error: 'referral_not_allowed' })
      .mockResolvedValueOnce({ success: true, txHash: '0xabc', execution: 'executed' });
    const requestId = nextRequestId();
    const result = await run([MINT], requestId);
    expect(result.txHash).toBe('0xabc');
    expect(sentCalls(0)).toHaveLength(2);
    expect(sentCalls(1)).toHaveLength(1);
    expect(mockSponsorBscBatch.mock.calls.map(([a]) => a.requestId)).toEqual([
      `${requestId}_a0`,
      `${requestId}_a0`,
    ]);
    // A later retry of that same action stays unarmed.
    mockSponsorBscBatch.mockResolvedValue({ success: true, txHash: '0xabc', execution: 'executed' });
    await run([MINT], requestId);
    expect(sentCalls(2)).toHaveLength(1);
  });

  it('a retried request reuses its first arm decision, even if the lookup now fails', async () => {
    mockQuery.mockResolvedValueOnce({ data: { feeReferralArm: ARM } });
    mockSponsorBscBatch.mockResolvedValue({ success: true, txHash: '0xabc', execution: 'executed' });
    const requestId = nextRequestId();
    await run([MINT], requestId);
    mockQuery.mockRejectedValueOnce(new Error('network'));
    await run([MINT], requestId);
    expect(mockQuery).toHaveBeenCalledTimes(1);
    expect(sentCalls(0)).toEqual(sentCalls(1));
    expect(sentCalls(1)).toHaveLength(2);
  });

  it('never arms a batch that pays no border fee', async () => {
    mockQuery.mockResolvedValue({ data: { feeReferralArm: ARM } });
    mockSponsorBscBatch.mockResolvedValue({ success: true, txHash: '0xabc', execution: 'executed' });
    await run([{ to: CUSD, valueWei: 0n, data: '0xa9059cbb' }]);
    expect(mockQuery).not.toHaveBeenCalled();
    expect(sentCalls(0)).toHaveLength(1);
  });

  it('a pre-flight revert of an armed batch resends it without the arm', async () => {
    mockQuery.mockResolvedValue({ data: { feeReferralArm: ARM } });
    mockSponsorBscBatch
      .mockResolvedValueOnce({ success: false, error: 'simulation_reverted' })
      .mockResolvedValueOnce({ success: true, txHash: '0xabc', execution: 'executed' });
    await run();
    expect(sentCalls(0)).toHaveLength(2);
    expect(sentCalls(1)).toHaveLength(1);
  });

  it('arms a four-call batch (the server allows one extra slot) but never a fifth', async () => {
    mockQuery.mockResolvedValue({ data: { feeReferralArm: ARM } });
    mockSponsorBscBatch.mockResolvedValue({ success: true, txHash: '0xabc', execution: 'executed' });
    await run([MINT, MINT, MINT, MINT]);
    expect(sentCalls(0)).toHaveLength(5);
    mockQuery.mockClear();
    await run([MINT, MINT, MINT, MINT, MINT]);
    expect(mockQuery).not.toHaveBeenCalled();
    expect(sentCalls(1)).toHaveLength(5);
  });
});
