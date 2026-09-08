import { bytesToHex } from '@noble/hashes/utils';
import { BridgeTransfer, bridgeRequestId, journeyReturnBridgeRequestId, polygonAuthorizationDigest, authorizePaymentBridge } from '../paymentBridge';

const mockMutate = jest.fn();
const mockWallet = jest.fn();
jest.mock('../../apollo/client', () => ({ apolloClient: { mutate: (...args: any[]) => mockMutate(...args) } }));
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
it('matches the independently encoded Python EIP-3009 digest', () => {
  expect(bytesToHex(polygonAuthorizationDigest(transfer()))).toBe('0d887782902b68ed55499706dbd35f1ea0e3918577673aa978f9c8def745eb00');
});
it('binds the signature to the exact deposit, amount, nonce and deadline', () => {
  const t = transfer(), digest = bytesToHex(polygonAuthorizationDigest(t));
  for (const changed of [{ amountUnits: '10000001' }, { deadline: '2000000001' }, { depositAddress: '0x' + '44'.repeat(20) }, { authorizationNonce: '0x' + '55'.repeat(32) }]) {
    expect(bytesToHex(polygonAuthorizationDigest({ ...t, ...changed }))).not.toBe(digest);
  }
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
