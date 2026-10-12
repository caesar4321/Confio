import { transactionFriendRoute } from '../transactionFriend';

describe('transaction contact history', () => {
  it('opens the recipient from account-detail transaction data', () => {
    expect(transactionFriendRoute({type: 'sent', recipientUser: {id: 139}}, true, 'Sunny', '57:3223662806'))
      .toMatchObject({friendId: '139', friendName: 'Sunny', friendPhone: '+573223662806', isOnConfio: true});
  });
  it('opens the sender for incoming transfers', () => {
    expect(transactionFriendRoute({type: 'received', senderUserId: 7, recipientUserId: 8}, true, 'Ana')?.friendId).toBe('7');
  });
  it.each([
    [{type: 'sent', recipientUser: {id: 139}, recipientBusiness: {id: 4}}, true],
    [{type: 'received', senderUserId: 139, senderBusiness: {id: 4}}, true],
    [{type: 'sent', recipientUserId: 139}, false],
    [{type: 'sent', toAddress: '0xexternal'}, true],
    [{type: 'sent', recipientUserId: 139, isInvitedFriend: true}, true],
  ])('does not route a business, unverified payload, external wallet or invitation to a personal history', (tx, verified) => {
    expect(transactionFriendRoute(tx, verified, 'Sunny')).toBeNull();
  });
});
