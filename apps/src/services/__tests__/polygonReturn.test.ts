import { bytesToHex } from '@noble/hashes/utils';
import { receiveAuthorizationDigest } from '../polygonReturn';

// Vector from payment_accounts.polygon_return.digest (server side): the app
// and the server must sign/verify the exact same ReceiveWithAuthorization.
describe('receiveAuthorizationDigest', () => {
  const permit = {
    returnId: '00000000-0000-0000-0000-000000000000', amount: '26.00', amountOut: '25.93',
    fromAddress: '0x' + '11'.repeat(20),
    toAddress: '0xccc88a9d1b4ed6b0eaba998850414b24f1c315be',
    value: '26000000', validBefore: '1793897703', nonce: '0x' + 'cd'.repeat(32),
  };

  it('matches the server digest', () => {
    expect(bytesToHex(receiveAuthorizationDigest(permit)))
      .toBe('dfa1b641b5098a0d2346a8b475caee45e4ebc08bbf7855beab3562fefd09d657');
  });

  it('changes with the receiver', () => {
    expect(bytesToHex(receiveAuthorizationDigest({ ...permit, toAddress: '0x' + '9'.repeat(40) })))
      .not.toBe('dfa1b641b5098a0d2346a8b475caee45e4ebc08bbf7855beab3562fefd09d657');
  });
});
