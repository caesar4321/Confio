// Spec 6.4: every personal-wallet batch carries the own account's
// cancelClaim() while a claim is pending on it.
const USER = `0x${'11'.repeat(20)}`;
const mockDelegate = `0x${'22'.repeat(20)}`;
const CUSD = `0x${'aa'.repeat(20)}`;
const ARM_SELECTOR = 'a1a1a1a1';
const ARM = { to: CUSD, data: `0x${ARM_SELECTOR}${'00'.repeat(64)}` };
const mockSponsorBscBatch = jest.fn();
const mockQuery = jest.fn();
const mockContext = jest.fn();
jest.mock('../authService', () => ({
  AuthService: { getInstance: () => ({ getActiveAccountContext: () => mockContext() }) },
}));

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
      : sig === 'cancelClaim()' ? '0xcc11aa00'
      : sig.startsWith('mintWithFee') ? '0xdeadbeef'
        : '0x12345678')),
  signIntentDigest: jest.fn(() => `0x${'44'.repeat(65)}`),
  signSetCodeAuthorization: jest.fn(),
  BscReceiptTimeoutError: class BscReceiptTimeoutError extends Error {},
  BscRevertedError: class BscRevertedError extends Error {},
}));

import { executeSponsoredBatch } from '../sponsored7702';
import { noteOwnPendingClaim, resetOwnClaimCacheForTests } from '../ownClaimCancel';

const OWN = `0x${'cd'.repeat(20)}`;
const CANCEL = { to: OWN, valueWei: '0', data: '0xcc11aa00' };
const MINT = { to: CUSD, valueWei: 0n, data: '0xdeadbeef' };
let seq = 0;
const nextRequestId = () => `gm_c${String(++seq).padStart(31, '0')}`;
const run = (calls = [MINT], extra: Record<string, unknown> = {}) =>
  executeSponsoredBatch({
    wallet: { address: USER, privKeyHex: '77'.repeat(32) },
    calls,
    delegateAddress: mockDelegate,
    requestId: nextRequestId(),
    ...extra,
  });
const sentCalls = (i: number) => mockSponsorBscBatch.mock.calls[i][0].calls;
/** Answers both isolated queries: the claim contract and the referral arm. */
const answer = (claim: unknown, arm: unknown = null) => mockQuery.mockImplementation(async ({ query }: any) => (
  String(query).includes('contractAddress')
    ? (claim instanceof Error ? Promise.reject(claim) : { data: { smartAccountClaimAlert: claim } })
    : { data: { feeReferralArm: arm } }
));

describe('spec 6.4: trailing cancelClaim on personal batches', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockQuery.mockReset();
    mockSponsorBscBatch.mockReset();
    resetOwnClaimCacheForTests();
    mockContext.mockResolvedValue({ type: 'personal', index: 0 });
    mockSponsorBscBatch.mockResolvedValue({ success: true, txHash: '0xabc', execution: 'executed' });
  });

  it('appends exactly one cancelClaim after the base calls while a claim is pending', async () => {
    answer({ contractAddress: OWN });
    await run([MINT, MINT]);
    const calls = sentCalls(0);
    expect(calls).toHaveLength(3);
    expect(calls[2]).toEqual(CANCEL);
    expect(calls.filter((c: any) => c.data === CANCEL.data)).toHaveLength(1);
  });

  it('keeps the referral arm first and the cancel last', async () => {
    answer({ contractAddress: OWN }, ARM);
    await run();
    expect(sentCalls(0)).toEqual([
      { to: ARM.to, valueWei: '0', data: ARM.data },
      { to: MINT.to, valueWei: '0', data: MINT.data },
      CANCEL,
    ]);
  });

  it('appends nothing when no claim is pending', async () => {
    answer(null);
    await run();
    expect(sentCalls(0)).toHaveLength(1);
  });

  it('appends nothing when the server lacks the field or the read fails', async () => {
    answer(new Error('Cannot query field "contractAddress"'));
    await run();
    expect(sentCalls(0)).toHaveLength(1);
    resetOwnClaimCacheForTests();
    answer({ beneficiaryName: 'Ana' });
    await run();
    expect(sentCalls(1)).toHaveLength(1);
  });

  it('appends nothing outside the personal context', async () => {
    answer({ contractAddress: OWN });
    mockContext.mockResolvedValue({ type: 'business', index: 0, businessId: '7' });
    await run();
    mockContext.mockResolvedValue({ type: 'smart', index: 0 });
    await run();
    expect(sentCalls(0)).toHaveLength(1);
    expect(sentCalls(1)).toHaveLength(1);
  });

  it('appends nothing to a Cuenta inteligente batch', async () => {
    answer({ contractAddress: OWN });
    await run([MINT], { ownClaimCancel: false });
    expect(sentCalls(0)).toHaveLength(1);
  });

  it('appends nothing when the batch already calls the account', async () => {
    answer({ contractAddress: OWN });
    await run([{ to: OWN.toUpperCase().replace('0X', '0x'), valueWei: 0n, data: '0x12345678' }]);
    expect(sentCalls(0)).toHaveLength(1);
  });

  it('reuses a recent answer instead of asking on every send', async () => {
    answer({ contractAddress: OWN });
    await run();
    // The successful cancel forgets the claim; a "no claim" from the host
    // poll is then reused without a lookup.
    mockQuery.mockClear();
    noteOwnPendingClaim(false);
    await run();
    await run();
    expect(mockQuery.mock.calls.filter(([a]: any) => String(a.query).includes('contractAddress'))).toHaveLength(0);
    expect(sentCalls(1)).toHaveLength(1);
  });

  it('a pre-flight revert drops the cancel and resends the member\'s batch', async () => {
    answer({ contractAddress: OWN });
    mockSponsorBscBatch
      .mockResolvedValueOnce({ success: false, error: 'simulation_reverted' })
      .mockResolvedValueOnce({ success: true, txHash: '0xabc', execution: 'executed' });
    await run();
    expect(sentCalls(0)).toHaveLength(2);
    expect(sentCalls(1)).toHaveLength(1);
  });

  it('a server refusal of the cancel alone drops only the cancel', async () => {
    answer({ contractAddress: OWN });
    mockSponsorBscBatch
      .mockResolvedValueOnce({ success: false, error: 'claim_cancel_not_allowed' })
      .mockResolvedValueOnce({ success: true, txHash: '0xabc', execution: 'executed' });
    await run();
    expect(sentCalls(0)).toHaveLength(2);
    expect(sentCalls(1)).toHaveLength(1);
  });

  it('claim_cancel_required: re-looks up past both caches, adds the cancel, resends once', async () => {
    // The host primed "no claim"; a claim then started.
    noteOwnPendingClaim(false);
    answer({ contractAddress: OWN });
    mockSponsorBscBatch
      .mockResolvedValueOnce({ success: false, error: 'claim_cancel_required' })
      .mockResolvedValueOnce({ success: true, txHash: '0xabc', execution: 'executed' });
    const res = await run();
    expect(res.txHash).toBe('0xabc');
    expect(mockSponsorBscBatch).toHaveBeenCalledTimes(2);
    expect(sentCalls(0)).toHaveLength(1);
    expect(sentCalls(1)).toEqual([{ to: MINT.to, valueWei: '0', data: MINT.data }, CANCEL]);
    // Same attempt slot: nothing was broadcast.
    expect(mockSponsorBscBatch.mock.calls[1][0].requestId).toBe(mockSponsorBscBatch.mock.calls[0][0].requestId);
    expect(mockQuery.mock.calls.filter(([a]: any) => String(a.query).includes('contractAddress'))).toHaveLength(1);
  });

  it('claim_cancel_required with still no claim surfaces the original error', async () => {
    noteOwnPendingClaim(false);
    answer(null);
    mockSponsorBscBatch.mockResolvedValue({ success: false, error: 'claim_cancel_required' });
    await expect(run()).rejects.toThrow('claim_cancel_required');
    expect(mockSponsorBscBatch).toHaveBeenCalledTimes(1);
  });

  it('claim_cancel_required, then simulation_reverted with the re-added cancel: surfaces the revert, no loop', async () => {
    noteOwnPendingClaim(false);
    answer({ contractAddress: OWN });
    mockSponsorBscBatch
      .mockResolvedValueOnce({ success: false, error: 'claim_cancel_required' })
      .mockResolvedValue({ success: false, error: 'simulation_reverted' });
    await expect(run()).rejects.toThrow('sponsored batch rejected: simulation_reverted');
    // Without cancel, with the re-added cancel, and nothing more: the cancel
    // is not dropped again (that would only earn claim_cancel_required).
    expect(mockSponsorBscBatch).toHaveBeenCalledTimes(2);
    expect(sentCalls(0)).toHaveLength(1);
    expect(sentCalls(1)).toEqual([{ to: MINT.to, valueWei: '0', data: MINT.data }, CANCEL]);
  });

  it('claim_cancel_required is retried only once', async () => {
    noteOwnPendingClaim(false);
    answer({ contractAddress: OWN });
    mockSponsorBscBatch.mockResolvedValue({ success: false, error: 'claim_cancel_required' });
    await expect(run()).rejects.toThrow('claim_cancel_required');
    expect(mockSponsorBscBatch).toHaveBeenCalledTimes(2);
  });
});
