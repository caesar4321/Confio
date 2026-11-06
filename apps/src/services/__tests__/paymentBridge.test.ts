import { bytesToHex } from '@noble/hashes/utils';
import { BridgeTransfer, bridgeRequestId, journeyReturnBridgeRequestId, authorizePaymentBridge, preparePaymentBridge } from '../paymentBridge';
import { receiveAuthorizationDigest } from '../polygonReturn';
import { signIntentDigest } from '../evmWallet';

const mockMutate = jest.fn();
const mockWallet = jest.fn();
const mockQuery = jest.fn();
jest.mock('../../apollo/client', () => ({ apolloClient: { mutate: (...args: any[]) => mockMutate(...args), query: (...args: any[]) => mockQuery(...args) } }));
jest.mock('../secureDeterministicWallet', () => ({ getActiveEvmWallet: () => mockWallet() }));

const transfer = (): BridgeTransfer => ({
  internalId: '00000000-0000-0000-0000-000000000001', status: 'prepared', providerCredited: false,
  sourceTokenId: 'POL:USDC', sourceAddress: '0x' + '11'.repeat(20), destinationAddress: '0x' + '11'.repeat(20),
  depositAddress: '0x' + '33'.repeat(20), amountUnits: '10000000', amountOut: '9900000000000000000',
  amountOutMin: '9800000000000000000', deadline: '2000000000', intentId: '0x' + '00'.repeat(32),
  authorizationNonce: '0xbef65b0c98ac9b53eae635f51b199702f3c6515d6a3b9e386280649bfae99d86',
  feeUnits: '0', grossRedeemUnits: '0', walletUsdtUnits: '0', sourceTxHash: '', destinationTxHash: '', actualOutUnits: '', calls: [],
});

beforeEach(() => { jest.clearAllMocks(); });
it('permits a fresh request after an explicit pre-transfer budget rejection', async () => {
  mockMutate.mockResolvedValueOnce({data: {quotePaymentBridge: {success: true, quote: {internalId: 'quote'}}}})
    .mockResolvedValueOnce({data: {preparePaymentBridge: {success: false,
      errors: ['Conversion fee changed; request a fresh quote within your total']}}});
  await expect(preparePaymentBridge('instruction', '50', 'to_provider', 'request'))
    .rejects.toMatchObject({quoteRefreshRequired: true});
});
it('does not allow replacing a request after an uncertain preparation result', async () => {
  const timeout = new Error('Network timeout');
  mockMutate.mockResolvedValueOnce({data: {quotePaymentBridge: {success: true, quote: {internalId: 'quote'}}}})
    .mockRejectedValueOnce(timeout);
  await expect(preparePaymentBridge('instruction', '50', 'to_provider', 'request')).rejects.toBe(timeout);
  expect(timeout).not.toHaveProperty('quoteRefreshRequired');
});
const RELAY = '0xccc88a9d1b4ed6b0eaba998850414b24f1c315be';
const NONCE = '0x' + 'cd'.repeat(32);
it('signs the Relay permit for a Polygon return, bound to amount, deadline and nonce', async () => {
  const priv = '01'.repeat(32);
  const address = '0x7e5f4552091a69125d5dfcb7b8c2659029395bdf';
  const t = { ...transfer(), sourceAddress: address, destinationAddress: address };
  mockWallet.mockResolvedValue({ address, privKeyHex: priv });
  // The screen holds a stale copy: the live transfer was rebound to a fresh
  // permit with a later deadline, and that is what must be signed.
  const liveDeadline = String(Math.floor(Date.now() / 1000) + 600);
  mockQuery.mockResolvedValue({ data: { paymentBridge: { status: 'prepared', deadline: liveDeadline,
    amountUnits: t.amountUnits, sourceAddress: address, permitReceiver: RELAY, permitNonce: NONCE } } });
  mockMutate.mockResolvedValue({ data: { submitPaymentBridge: { success: true, transfer: { ...t, status: 'submitted' } } } });
  await authorizePaymentBridge(t);
  const signature: string = mockMutate.mock.calls[0][0].variables.signature;
  const digest = receiveAuthorizationDigest({ returnId: t.internalId, amount: '0', amountOut: t.amountOut,
    fromAddress: address, toAddress: RELAY, value: t.amountUnits, validBefore: liveDeadline, nonce: NONCE });
  // RFC 6979 signing is deterministic: the exact expected permit signature.
  expect(signature).toBe(signIntentDigest(digest, priv));
});
it('refuses when the live transfer is no longer awaiting a signature', async () => {
  const t = transfer();
  mockWallet.mockResolvedValue({ address: t.sourceAddress, privKeyHex: '01'.repeat(32) });
  mockQuery.mockResolvedValue({ data: { paymentBridge: { status: 'expired', deadline: '2000000000',
    amountUnits: t.amountUnits, sourceAddress: t.sourceAddress, permitReceiver: RELAY, permitNonce: NONCE } } });
  await expect(authorizePaymentBridge(t)).rejects.toThrow('Revisa el estado');
  expect(mockMutate).not.toHaveBeenCalled();
});
it('refuses a Polygon permit naming any receiver but Relay', async () => {
  const t = transfer();
  mockWallet.mockResolvedValue({ address: t.sourceAddress, privKeyHex: '01'.repeat(32) });
  mockQuery.mockResolvedValue({ data: { paymentBridge: { status: 'prepared', deadline: '2000000000',
    amountUnits: t.amountUnits, sourceAddress: t.sourceAddress, permitReceiver: '0x' + '99'.repeat(20), permitNonce: NONCE } } });
  await expect(authorizePaymentBridge(t)).rejects.toThrow('Ruta no disponible');
  expect(mockMutate).not.toHaveBeenCalled();
});
it('does not derive a key or resubmit a pending transfer', async () => {
  await expect(authorizePaymentBridge({ ...transfer(), status: 'submitted' })).rejects.toThrow();
  expect(mockWallet).not.toHaveBeenCalled(); expect(mockMutate).not.toHaveBeenCalled();
});
it('refuses to sign after the active account changes', async () => {
  mockWallet.mockResolvedValue({ address: '0x' + '22'.repeat(20), privKeyHex: '01'.repeat(32) });
  await expect(authorizePaymentBridge(transfer())).rejects.toThrow('cuenta activa');
  expect(mockMutate).not.toHaveBeenCalled();
});
it('refuses a Polygon return to any other wallet', async () => {
  mockWallet.mockResolvedValue({ address: transfer().sourceAddress, privKeyHex: '01'.repeat(32) });
  await expect(authorizePaymentBridge({ ...transfer(), destinationAddress: '0x' + '22'.repeat(20) })).rejects.toThrow('Destino');
  expect(mockMutate).not.toHaveBeenCalled();
});
it('uses secure unique UUIDs for logical requests', () => {
  expect(bridgeRequestId()).toMatch(/^[\da-f]{8}-[\da-f]{4}-4[\da-f]{3}-[89ab][\da-f]{3}-[\da-f]{12}$/);
  expect(bridgeRequestId()).not.toEqual(bridgeRequestId());
});

it('uses the same return request after restart while isolating journeys and providers', () => {
  const id = 'abcdef01-0000-0000-0000-000000000001';
  const request = journeyReturnBridgeRequestId('infinia', id);
  expect(request).toMatch(/^[\da-f]{8}-[\da-f]{4}-8[\da-f]{3}-[89ab][\da-f]{3}-[\da-f]{12}$/);
  expect(journeyReturnBridgeRequestId('infinia', id.toUpperCase())).toBe(request);
  expect(journeyReturnBridgeRequestId('cobre', id)).not.toBe(request);
  expect(journeyReturnBridgeRequestId('infinia', 'abcdef01-0000-0000-0000-000000000002')).not.toBe(request);
  expect(() => journeyReturnBridgeRequestId('infinia', '')).toThrow();
});
