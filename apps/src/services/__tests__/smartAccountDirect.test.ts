// App glue of the direct claim path: biometric first, the personal wallet as
// signer, one withdraw per asset to the own wallet, stop at the first doubt.
const mockAuth = jest.fn();
jest.mock('../biometricAuthService', () => ({
  biometricAuthService: { authenticateEmergencyExit: (...a: any[]) => mockAuth(...a) },
}));
const mockWallet = jest.fn();
jest.mock('../secureDeterministicWallet', () => ({
  getActiveEvmWallet: (...a: any[]) => mockWallet(...a),
  getEvmAddressForDisplay: jest.fn(async () => null),
}));
const mockSend = jest.fn();
jest.mock('../emergencyExit/directClaim', () => {
  const actual = jest.requireActual('../emergencyExit/directClaim');
  return { ...actual, sendDirectCall: (...a: any[]) => mockSend(...a) };
});
jest.mock('../emergencyExit/store', () => ({ emergencyStore: {} }));

import { runDirectStep, type DirectSituation } from '../smartAccountDirect';

const ME = '0x19e7e376e7c213b7e7e7e46cc70a5dd086daff2a';
const ACCOUNT = '0x' + 'cd'.repeat(20);
const T1 = '0x' + '11'.repeat(20);
const T2 = '0x' + '22'.repeat(20);
const s = (over: Partial<DirectSituation> = {}): DirectSituation => ({
  me: ME, account: ACCOUNT, step: { kind: 'initiate' }, holdings: [], gas: { kind: 'enough' }, ...over,
});

beforeEach(() => {
  jest.clearAllMocks();
  mockAuth.mockResolvedValue(true);
  mockWallet.mockResolvedValue({ address: ME, privKeyHex: '11'.repeat(32) });
  mockSend.mockResolvedValue({ status: 'executed', txHash: '0x1' });
});

it('asks for the biometric before anything, and stops if refused', async () => {
  mockAuth.mockResolvedValue(false);
  expect(await runDirectStep(s())).toEqual({ status: 'cancelled' });
  expect(mockWallet).not.toHaveBeenCalled();
  expect(mockSend).not.toHaveBeenCalled();
});

it('signs with the personal wallet (personal_0)', async () => {
  await runDirectStep(s({ step: { kind: 'execute' } }));
  expect(mockWallet).toHaveBeenCalledWith({ type: 'personal', index: 0 });
  expect(mockSend.mock.calls[0][0]).toMatchObject({ account: ACCOUNT, call: { kind: 'executeClaim' } });
});

it('refuses when the wallet is not the address the chain was read for', async () => {
  mockWallet.mockResolvedValue({ address: '0x' + 'ee'.repeat(20), privKeyHex: 'x' });
  expect((await runDirectStep(s())).status).toBe('failed');
  expect(mockSend).not.toHaveBeenCalled();
});

it('withdraws each asset to the own wallet and stops at the first unknown', async () => {
  const holdings = [{ address: T1, label: 'USDT', balance: 5n }, { address: T2, label: 'CONFIO', balance: 7n }];
  mockSend.mockResolvedValueOnce({ status: 'executed', txHash: '0x1' })
    .mockResolvedValueOnce({ status: 'unknown', txHash: '0x2' });
  const out = await runDirectStep(s({ step: { kind: 'withdraw' }, holdings }));
  expect(out).toEqual({ status: 'unknown', done: 1, total: 2 });
  expect(mockSend.mock.calls.map((c) => c[0].call)).toEqual([
    { kind: 'withdraw', token: T1, amount: 5n, to: ME },
    { kind: 'withdraw', token: T2, amount: 7n, to: ME },
  ]);
});

it('reports missing BNB with the amount to send', async () => {
  mockSend.mockResolvedValue({ status: 'needs_bnb', needWei: 10n ** 13n, balanceWei: 0n, address: ME });
  expect(await runDirectStep(s())).toEqual({ status: 'failed', done: 0, total: 1, error: null, needBnb: '0.00001' });
});

it('a throw after signing is "unknown", never "failed"', async () => {
  mockSend.mockImplementationOnce(async (p: any) => {
    p.onSigned?.('0xabc');
    throw new Error('Network request failed');
  });
  expect(await runDirectStep(s())).toEqual({ status: 'unknown', done: 0, total: 1 });
});

it('a throw before signing is a plain failure (nothing moved)', async () => {
  mockSend.mockRejectedValueOnce(new Error('Network request failed'));
  expect(await runDirectStep(s())).toEqual({ status: 'failed', done: 0, total: 1, error: null });
});

it('stops a multi-asset withdraw at the first unknown send error after signing', async () => {
  const holdings = [{ address: T1, label: 'USDT', balance: 5n }, { address: T2, label: 'CONFIO', balance: 7n }];
  mockSend.mockImplementationOnce(async (p: any) => {
    p.onSigned?.('0xabc');
    throw new Error('timeout');
  });
  const out = await runDirectStep(s({ step: { kind: 'withdraw' }, holdings }));
  expect(out).toEqual({ status: 'unknown', done: 0, total: 2 });
  expect(mockSend).toHaveBeenCalledTimes(1);
});
