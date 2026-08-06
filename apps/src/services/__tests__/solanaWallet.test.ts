import { base58Decode, base58Encode, deriveSolanaKeyFromMasterSecret } from '../solanaWallet';

describe('Solana master-secret derivation', () => {
  const masterSecret = new Uint8Array(32).fill(7);
  const personal = { accountType: 'personal', accountIndex: 0 };

  it('encodes canonical base58 vectors', () => {
    expect(base58Encode(new Uint8Array([]))).toBe('');
    expect(base58Encode(new Uint8Array([0]))).toBe('1');
    expect(base58Encode(new Uint8Array([0, 0, 1]))).toBe('112');
    expect(base58Encode(new Uint8Array([97, 98, 99]))).toBe('ZiCa');
    for (const value of [new Uint8Array([0]), new Uint8Array([0, 0, 1]), new Uint8Array([97, 98, 99])]) {
      expect(base58Decode(base58Encode(value))).toEqual(value);
    }
  });

  it('is deterministic and produces a canonical Solana address', () => {
    const first = deriveSolanaKeyFromMasterSecret(masterSecret, personal);
    const second = deriveSolanaKeyFromMasterSecret(masterSecret, personal);

    expect(second.address).toBe(first.address);
    expect(second.seedHex).toBe(first.seedHex);
    // Frozen derivation vector: changing either value would strand any funds
    // sent to addresses created under this V2 Solana domain.
    expect(first.seedHex).toBe('89bfd44306820e0310aecbf5b2dee716a6feed79272781c8f4b1f1d6cb3193af');
    expect(first.address).toBe('BL6BTzEhFsJJhpctdpDs7EB7bMrPEMGn4ZigNey6YkLU');
    expect(first.publicKey).toHaveLength(32);
    expect(first.seedHex).toHaveLength(64);
    expect(first.address).toMatch(/^[1-9A-HJ-NP-Za-km-z]{32,44}$/);
  });

  it('domain-separates account contexts', () => {
    const personal0 = deriveSolanaKeyFromMasterSecret(masterSecret, personal).address;
    const personal1 = deriveSolanaKeyFromMasterSecret(masterSecret, {
      accountType: 'personal', accountIndex: 1,
    }).address;
    const business = deriveSolanaKeyFromMasterSecret(masterSecret, {
      accountType: 'business', accountIndex: 0, businessId: '42',
    }).address;

    expect(new Set([personal0, personal1, business]).size).toBe(3);
  });

  it('rejects malformed master secrets', () => {
    expect(() => deriveSolanaKeyFromMasterSecret(new Uint8Array(31), personal))
      .toThrow(/expected 32/);
  });
});
