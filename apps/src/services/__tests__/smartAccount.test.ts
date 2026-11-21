const mockQuery = jest.fn();
const mockMutate = jest.fn();
jest.mock('../../apollo/client', () => ({ apolloClient: { query: (...a: any[]) => mockQuery(...a), mutate: (...a: any[]) => mockMutate(...a) } }));
const mockExecute = jest.fn();
const mockParams = jest.fn();
class MockSigningWindowClosedError extends Error {}
jest.mock('../sponsored7702', () => ({
  executeSponsoredBatch: (...a: any[]) => mockExecute(...a),
  fetchSponsored7702Params: (...a: any[]) => mockParams(...a),
  SigningWindowClosedError: MockSigningWindowClosedError,
}));
const mockWallet = jest.fn();
jest.mock('../secureDeterministicWallet', () => ({ getActiveEvmWallet: (...a: any[]) => mockWallet(...a) }));
jest.mock('../bscServerRpc', () => ({ installBscServerTransport: jest.fn() }));
class MockBscRevertedError extends Error {
  txHash = '0xrev';
}
jest.mock('../evmWallet', () => ({
  BscRevertedError: MockBscRevertedError,
  isOutcomeUnknown: (e: any) => Boolean(e?.broadcast),
}));

import {
  fetchSmartAccount, fetchSmartAccountCharges, fetchSmartAccountClaimAlert, hasOwnSmartAccount, isSmartAccountOpen,
  prepareSmartAccountSubscribe, prepareClaimCancel, prepareSmartAccountBuyRule, prepareSmartAccountCancelRule, signAndSubmitPrepared, toBatchCalls,
  IDENTITY_RESTRICTED_CODE, sponsorErrorCode,
  type SmartAccountPreparedBatch,
} from '../smartAccount';

const batch = (over: Partial<SmartAccountPreparedBatch> = {}): SmartAccountPreparedBatch => ({
  success: true, errorCode: null, errorMessage: null, requestId: 'req_1',
  calls: [{ to: '0x00000000000000000000000000000000000000aa', valueWei: '0', data: '0x1234' }],
  notAfter: 1900000000, summary: ['x'], ...over,
});

beforeEach(() => {
  jest.clearAllMocks();
  mockParams.mockResolvedValue({ enabled: true, delegateAddress: '0xdelegate' });
  mockWallet.mockResolvedValue({ address: '0xowner', privKeyHex: 'aa' });
});

describe('reads', () => {
  it('returns the server value, null included', async () => {
    mockQuery.mockResolvedValue({ data: { smartAccount: null } });
    expect(await fetchSmartAccount()).toEqual({ ok: true, data: null });
    mockQuery.mockResolvedValue({ data: { smartAccountClaimAlert: null } });
    expect(await fetchSmartAccountClaimAlert()).toEqual({ ok: true, data: null });
  });

  it('reports a failed read as failed, never as "nothing there"', async () => {
    mockQuery.mockRejectedValue(new Error('Cannot query field "smartAccount"'));
    expect(await fetchSmartAccount()).toEqual({ ok: false });
  });

  it('asks the network every time and sends no account id', async () => {
    mockQuery.mockResolvedValue({ data: { smartAccount: null } });
    await fetchSmartAccount();
    const options = mockQuery.mock.calls[0][0];
    expect(options.fetchPolicy).toBe('network-only');
    expect(options.variables).toBeUndefined();
  });

  it('flattens a page of charges', async () => {
    mockQuery.mockResolvedValue({ data: { smartAccountCharges: {
      edges: [{ cursor: 'c1', node: { id: '1' } }, { cursor: 'c2', node: { id: '2' } }],
      pageInfo: { hasNextPage: true, endCursor: 'c2' },
    } } });
    const result = await fetchSmartAccountCharges(2, 'c0');
    expect(result).toEqual({ ok: true, data: { items: [{ id: '1' }, { id: '2' }], hasNextPage: true, endCursor: 'c2' } });
    expect(mockQuery.mock.calls[0][0].variables).toEqual({ first: 2, after: 'c0' });
  });

  it('keeps every query in its own document', () => {
    const service = jest.requireActual('../smartAccount');
    const roots = Object.keys(service)
      .filter((k) => /^[A-Z_]+$/.test(k) && service[k]?.kind === 'Document')
      .map((k) => service[k].definitions[0].selectionSet.selections.map((s: any) => s.name.value));
    expect(roots.length).toBeGreaterThanOrEqual(9);
    roots.forEach((selections: string[]) => expect(selections).toHaveLength(1));
  });
});

describe('prepare', () => {
  it('passes the contract arguments through', async () => {
    mockMutate.mockResolvedValue({ data: { prepareSmartAccountSubscribe: batch() } });
    const deposits = [{ assetKey: 'cusd_plus', units: 'max' }];
    const out = await prepareSmartAccountSubscribe('annual', deposits, true);
    expect(out.success).toBe(true);
    expect(mockMutate.mock.calls[0][0].variables).toEqual({ plan: 'annual', deposits, disclosuresAccepted: true });
  });

  it('keeps the server message when it refuses', async () => {
    mockMutate.mockResolvedValue({ data: { prepareClaimCancel: { success: false, errorCode: 'no_claim', errorMessage: 'No hay un pedido.' } } });
    expect(await prepareClaimCancel()).toMatchObject({ success: false, errorCode: 'no_claim', errorMessage: 'No hay un pedido.' });
  });

  it('turns a transport error into a definite, worded failure', async () => {
    mockMutate.mockRejectedValue(new Error('offline'));
    const out = await prepareClaimCancel();
    expect(out.success).toBe(false);
    expect(out.errorCode).toBe('network');
    expect(out.errorMessage).toBeTruthy();
  });
});

describe('signAndSubmitPrepared', () => {
  it('signs with the personal_0 key whatever the active context is', async () => {
    mockExecute.mockResolvedValue({ txHash: '0xabc' });
    expect(await signAndSubmitPrepared(batch())).toEqual({ status: 'executed', txHash: '0xabc' });
    expect(mockWallet).toHaveBeenCalledWith({ type: 'personal', index: 0 });
    const sent = mockExecute.mock.calls[0][0];
    expect(sent.requestId).toBe('req_1');
    expect(sent.notAfter).toBe(1900000000);
    expect(sent.delegateAddress).toBe('0xdelegate');
    expect(sent.calls).toEqual([{ to: '0x00000000000000000000000000000000000000aa', valueWei: 0n, data: '0x1234' }]);
  });

  it('does not sign a refused or empty batch', async () => {
    expect(await signAndSubmitPrepared(batch({ success: false, errorCode: 'nope' }))).toEqual({ status: 'not_sent', code: 'nope' });
    expect(await signAndSubmitPrepared(batch({ calls: [] }))).toEqual({ status: 'not_sent', code: 'empty_batch' });
    expect(await signAndSubmitPrepared(batch({ requestId: null }))).toEqual({ status: 'not_sent', code: 'empty_batch' });
    expect(mockExecute).not.toHaveBeenCalled();
  });

  it('does not sign a batch it cannot read exactly', async () => {
    const bad = batch({ calls: [{ to: 'not-an-address', valueWei: '0', data: '0x' }] });
    expect(await signAndSubmitPrepared(bad)).toEqual({ status: 'not_sent', code: 'malformed_batch' });
    expect(() => toBatchCalls([{ to: '0x00000000000000000000000000000000000000aa', valueWei: '1.5', data: '0x' }])).toThrow();
    expect(mockExecute).not.toHaveBeenCalled();
  });

  it('reports an unknown outcome as unknown, not as a failure', async () => {
    mockExecute.mockRejectedValue(Object.assign(new Error('bsc tx timeout: 0xdead'), { broadcast: true, txHash: '0xdead' }));
    expect(await signAndSubmitPrepared(batch())).toEqual({ status: 'unknown', txHash: '0xdead' });
  });

  it('reports a revert as definite', async () => {
    mockExecute.mockRejectedValue(new MockBscRevertedError('bsc tx reverted'));
    expect(await signAndSubmitPrepared(batch())).toEqual({ status: 'reverted', txHash: '0xrev' });
  });

  it('reports a relay rejection with its code', async () => {
    mockExecute.mockRejectedValue(new Error('sponsored batch rejected: destination_not_allowed'));
    expect(await signAndSubmitPrepared(batch())).toEqual({ status: 'not_sent', code: 'destination_not_allowed' });
  });

  it('carries policy codes and maps the identity sentence to a code; free text is not shown', async () => {
    mockExecute.mockRejectedValueOnce(new Error('sponsored batch rejected: payment_due'));
    expect(await signAndSubmitPrepared(batch())).toEqual({ status: 'not_sent', code: 'payment_due' });
    mockExecute.mockRejectedValueOnce(new Error(
      'sponsored batch rejected: Las salidas de tu cuenta están temporalmente restringidas. Contacta con soporte para revisar tu cuenta.'));
    expect(await signAndSubmitPrepared(batch())).toEqual({ status: 'not_sent', code: IDENTITY_RESTRICTED_CODE });
    mockExecute.mockRejectedValueOnce(new Error('sponsored batch rejected: execution reverted: 0x1234'));
    expect(await signAndSubmitPrepared(batch())).toEqual({ status: 'not_sent', code: 'not_sent' });
    expect(sponsorErrorCode('smart_action_expired')).toBe('smart_action_expired');
    expect(sponsorErrorCode('sponsor rejected')).toBe('not_sent');
    // relay_policy.face_refusal sends the Confío Face sentence, not a code.
    expect(sponsorErrorCode('Confirma que eres tú con tu rostro para continuar.')).toBe('face_required');
  });

  it('reports a closed signing window as not sent', async () => {
    mockExecute.mockRejectedValue(new MockSigningWindowClosedError('late'));
    expect(await signAndSubmitPrepared(batch())).toEqual({ status: 'not_sent', code: 'signing_window_closed' });
  });

  it('stops before signing when the sponsored rail is off', async () => {
    mockParams.mockResolvedValue({ enabled: false, delegateAddress: null });
    expect(await signAndSubmitPrepared(batch())).toEqual({ status: 'not_sent', code: 'sponsored_rail_unavailable' });
    expect(mockWallet).not.toHaveBeenCalled();
  });
});

it('treats active and cancel-pending as open; expired is not a subscriber but still has a home', () => {
  expect(['active', 'cancel_pending'].every(isSmartAccountOpen)).toBe(true);
  expect(['expired', 'none', 'inherited', undefined, null].some((s) => isSmartAccountOpen(s as any))).toBe(false);
  expect(['active', 'cancel_pending', 'expired'].every(hasOwnSmartAccount)).toBe(true);
  expect(['none', 'inherited', undefined, null].some((s) => hasOwnSmartAccount(s as any))).toBe(false);
});

describe('rule prepares carry the Confío IA+ proposal step', () => {
  const opName = (call: any[]) => call[0].mutation.definitions[0].name.value;
  const unknownArg = () => Object.assign(new Error('Unknown argument "proposalMessageId" on field "prepareSmartAccountBuyRule".'),
    { graphQLErrors: [] });

  it('sends no proposal variables when the step is not tagged', async () => {
    mockMutate.mockResolvedValue({ data: { prepareSmartAccountBuyRule: batch() } });
    await prepareSmartAccountBuyRule({ ruleId: null, assetKey: 'stock:SPYon', amountUsd: '10.00', frequency: 'monthly' });
    expect(opName(mockMutate.mock.calls[0])).toBe('PrepareSmartAccountBuyRule');
    expect(mockMutate.mock.calls[0][0].variables).toEqual({
      ruleId: null, assetKey: 'stock:SPYon', amountUsd: '10.00', frequency: 'monthly' });
  });

  it('sends proposalMessageId + proposalStep when tagged', async () => {
    mockMutate.mockResolvedValue({ data: { prepareSmartAccountBuyRule: batch() } });
    const out = await prepareSmartAccountBuyRule({ ruleId: null, assetKey: 'stock:SPYon', amountUsd: '10.00', frequency: 'monthly',
      firstRunAt: '2026-12-01T10:00:00+00:00', proposalMessageId: '42', proposalStep: 1 });
    expect(out.success).toBe(true);
    expect(mockMutate).toHaveBeenCalledTimes(1);
    expect(opName(mockMutate.mock.calls[0])).toBe('PrepareSmartAccountBuyRuleAtProposal');
    expect(mockMutate.mock.calls[0][0].variables).toEqual({ ruleId: null, assetKey: 'stock:SPYon', amountUsd: '10.00',
      frequency: 'monthly', firstRunAt: '2026-12-01T10:00:00+00:00', proposalMessageId: '42', proposalStep: 1 });
  });

  it('an older server rejecting the arguments: retried once without them', async () => {
    mockMutate.mockRejectedValueOnce(unknownArg()).mockResolvedValueOnce({ data: { prepareSmartAccountBuyRule: batch() } });
    const out = await prepareSmartAccountBuyRule({ ruleId: 'r1', assetKey: 'stock:SPYon', amountUsd: '10.00', frequency: 'monthly',
      proposalMessageId: '42', proposalStep: 0 });
    expect(out.success).toBe(true);
    expect(mockMutate).toHaveBeenCalledTimes(2);
    expect(opName(mockMutate.mock.calls[1])).toBe('PrepareSmartAccountBuyRule');
    expect(mockMutate.mock.calls[1][0].variables).not.toHaveProperty('proposalStep');
  });

  it('a stop step: tagged, and retried untagged on an older server; a network failure is not retried', async () => {
    mockMutate.mockRejectedValueOnce(unknownArg()).mockResolvedValueOnce({ data: { prepareSmartAccountCancelRule: batch() } });
    const out = await prepareSmartAccountCancelRule('r1', { proposalMessageId: '42', proposalStep: 2 });
    expect(out.success).toBe(true);
    expect(opName(mockMutate.mock.calls[0])).toBe('PrepareSmartAccountCancelRuleProposal');
    expect(mockMutate.mock.calls[0][0].variables).toEqual({ ruleId: 'r1', proposalMessageId: '42', proposalStep: 2 });
    expect(mockMutate.mock.calls[1][0].variables).toEqual({ ruleId: 'r1' });
    mockMutate.mockReset();
    mockMutate.mockRejectedValue(new Error('Network request failed'));
    const failed = await prepareSmartAccountCancelRule('r1', { proposalMessageId: '42', proposalStep: 2 });
    expect(failed.errorCode).toBe('network');
    expect(mockMutate).toHaveBeenCalledTimes(1);
  });
});
