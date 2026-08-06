jest.mock('../../apollo/client', () => ({
  apolloClient: { mutate: jest.fn() },
}));

jest.mock('../../apollo/queries', () => ({
  PREPARE_SOLANA_SPONSORED_TRANSACTION: 'prepare-document',
  SPONSOR_SOLANA_TRANSACTION: 'sponsor-document',
}));

jest.mock('../secureDeterministicWallet', () => ({
  getActiveSolanaWallet: jest.fn(),
}));

import { apolloClient } from '../../apollo/client';
import {
  prepareSolanaSponsoredTransaction,
  signSolanaTransactionForSponsorship,
  sponsorSolanaTransaction,
} from '../solanaSponsor';
import { getActiveSolanaWallet } from '../secureDeterministicWallet';
import { base58Encode, deriveSolanaKeyFromMasterSecret } from '../solanaWallet';
import { bytesToBase64, strictBase64ToBytes } from '../../utils/encoding';
import * as nacl from 'tweetnacl';

const mutate = apolloClient.mutate as jest.Mock;
const activeWallet = getActiveSolanaWallet as jest.Mock;

function transactionFixture(versioned: boolean) {
  const wallet = deriveSolanaKeyFromMasterSecret(
    new Uint8Array(32).fill(7),
    { accountType: 'personal', accountIndex: 0 },
  );
  const sponsor = new Uint8Array(32).fill(3);
  const program = new Uint8Array(32).fill(9);
  const blockhash = new Uint8Array(32).fill(5);
  const message = new Uint8Array([
    ...(versioned ? [0x80] : []),
    2, 0, 1, // header: sponsor + user signatures, one readonly unsigned key
    3, ...sponsor, ...wallet.publicKey, ...program,
    ...blockhash,
    1, // instruction count
    2, // program key index
    1, 1, // one account: user key index
    0, // no instruction data
    ...(versioned ? [0] : []), // no address table lookups
  ]);
  const wire = new Uint8Array(1 + 128 + message.length);
  wire[0] = 2;
  wire.set(message, 129);
  return {
    wallet,
    wire,
    preparation: {
      sponsorAddress: base58Encode(sponsor),
      blockhash: base58Encode(blockhash),
      lastValidBlockHeight: 123,
      maxFeeLamports: 100_000,
    },
  };
}

describe('generic Solana sponsorship client', () => {
  beforeEach(() => {
    mutate.mockReset();
    activeWallet.mockReset();
  });

  it('fetches the generic fee payer and blockhash', async () => {
    mutate.mockResolvedValue({
      data: {
        prepareSolanaSponsoredTransaction: {
          success: true,
          sponsorAddress: 'sponsor',
          blockhash: 'blockhash',
          lastValidBlockHeight: 123,
          maxFeeLamports: 100_000,
        },
      },
    });
    await expect(prepareSolanaSponsoredTransaction()).resolves.toEqual({
      sponsorAddress: 'sponsor',
      blockhash: 'blockhash',
      lastValidBlockHeight: 123,
      maxFeeLamports: 100_000,
    });
  });

  it('submits any partially signed transaction through one mutation', async () => {
    mutate.mockResolvedValue({
      data: {
        sponsorSolanaTransaction: {
          success: true,
          signature: 'chain-signature',
          feeLamports: 5_000,
        },
      },
    });
    await expect(sponsorSolanaTransaction('base64-wire')).resolves.toEqual({
      signature: 'chain-signature',
      feeLamports: 5_000,
    });
    expect(mutate).toHaveBeenCalledWith(expect.objectContaining({
      variables: { transaction: 'base64-wire' },
    }));
  });

  it.each([false, true])(
    'adds the user signature while preserving an empty sponsor slot (v0=%s)',
    async versioned => {
      const fixture = transactionFixture(versioned);
      activeWallet.mockResolvedValue(fixture.wallet);
      const encoded = await signSolanaTransactionForSponsorship(
        bytesToBase64(fixture.wire),
        fixture.preparation,
      );
      const signed = strictBase64ToBytes(encoded);
      expect(Array.from(signed.subarray(1, 65))).toEqual(new Array(64).fill(0));
      expect(nacl.sign.detached.verify(
        signed.subarray(129),
        signed.subarray(65, 129),
        fixture.wallet.publicKey,
      )).toBe(true);
    },
  );

  it('refuses a transaction that is not bound to the prepared fee payer', async () => {
    const fixture = transactionFixture(true);
    activeWallet.mockResolvedValue(fixture.wallet);
    const wrong = { ...fixture.preparation, sponsorAddress: base58Encode(new Uint8Array(32).fill(8)) };
    await expect(signSolanaTransactionForSponsorship(
      bytesToBase64(fixture.wire),
      wrong,
    )).rejects.toThrow(/fee payer/);
  });
});
