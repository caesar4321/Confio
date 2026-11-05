import { bytesToHex } from '@noble/hashes/utils';
import { receiveAuthorizationDigest } from '../polygonReturn';

// Vector from payment_accounts.polygon_return.digest (server side): the app
// and the server must sign/verify the exact same ReceiveWithAuthorization.
describe('receiveAuthorizationDigest', () => {
  const permit = {
    returnId: '00000000-0000-0000-0000-000000000000', amount: '26.00', amountOut: '25.93',
    fromAddress: '0x260637e33823cCB40078E360Ebf543d3bdF72afF',
    toAddress: '0xccc88a9d1b4ed6b0eaba998850414b24f1c315be',
    value: '26000000', validBefore: '1793897703', nonce: '0x' + 'cd'.repeat(32),
  };

  it('matches the server digest', () => {
    expect(bytesToHex(receiveAuthorizationDigest(permit)))
      .toBe('d647a5cffc41986e6ab6e74e6e75f8571c5120218e115934577bc62ddd5b163a');
  });

  it('changes with the receiver', () => {
    expect(bytesToHex(receiveAuthorizationDigest({ ...permit, toAddress: '0x' + '9'.repeat(40) })))
      .not.toBe('d647a5cffc41986e6ab6e74e6e75f8571c5120218e115934577bc62ddd5b163a');
  });
});
