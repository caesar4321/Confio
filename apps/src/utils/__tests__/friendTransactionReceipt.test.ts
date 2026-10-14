import { unifiedTransactionReceipt as friendTransactionReceipt } from '../transactionReceipt';

const operationId = '12345678-1234-4234-8234-123456789abc';

describe('friend-history receipt metadata', () => {
  it('preserves the operation UUID and historical timestamp, not the unified row ID', () => {
    const receipt = friendTransactionReceipt({id: '2963', internalId: operationId, createdAt: '2026-08-28T11:17:09Z'});
    expect(receipt).toMatchObject({id: operationId, internalId: operationId, createdAt: '2026-08-28T11:17:09Z', timestamp: '2026-08-28T11:17:09Z'});
  });
  it('does not invent IDs or dates when the source has none', () => {
    const receipt = friendTransactionReceipt({id: '2963'});
    expect(receipt.id).toBeUndefined();
    expect(receipt.internalId).toBeUndefined();
    expect(receipt.createdAt).toBeUndefined();
    expect(receipt.timestamp).toBeUndefined();
  });
  it('preserves verified identities, business context, phones and actual fees', () => {
    const senderUser = {id: '5', phoneKey: '57:3000000000'};
    const recipientUser = {id: '139', phoneKey: '57:3000000001'};
    const recipientBusiness = {id: '8'};
    expect(friendTransactionReceipt({senderUser, counterpartyUser: recipientUser, counterpartyBusiness: recipientBusiness, feeAmount: '0.9', feeBps: 90, netAmount: '99.1'}))
      .toMatchObject({senderUser, recipientUser, recipientBusiness, fromPhone: senderUser.phoneKey, toPhone: recipientUser.phoneKey, feeAmount: '0.9', feeBps: 90, netAmount: '99.1'});
  });
});

 it('does not forward an invalid timestamp to receipt rendering', () => {
   const receipt = friendTransactionReceipt({createdAt: 'not-a-date'});
   expect(receipt.createdAt).toBeUndefined();
   expect(receipt.timestamp).toBeUndefined();
 });
