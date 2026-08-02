// The pin that decides whose code may execute AS the user's wallet.
//
// An EIP-7702 authorization installs code at the user's own address and has
// NO expiry — chainId, address, nonce, nothing else. Every sponsored flow
// (savings, sends, payroll, pay, presale) used to take that address from a
// server response, so a single bad response reached the entire wallet rather
// than one transaction, and the signature could be banked and broadcast later.
// These tests exist so nobody "simplifies" the allowlist away.

import {
  TRUSTED_BATCH_DELEGATES,
  isTrustedDelegate,
  signSetCodeAuthorization,
} from '../evmWallet';

const PINNED = TRUSTED_BATCH_DELEGATES[0];
const ATTACKER = '0x' + 'de'.repeat(20);
// Any 32-byte key works; we only care about which delegate gets signed for.
const PRIV = '11'.repeat(32);

describe('trusted batch delegates', () => {
  it('pins at least one delegate in the build', () => {
    expect(TRUSTED_BATCH_DELEGATES.length).toBeGreaterThan(0);
    // lowercase-normalised, so comparisons never depend on checksum casing
    TRUSTED_BATCH_DELEGATES.forEach((d) => expect(d).toBe(d.toLowerCase()));
  });

  it('accepts the pinned delegate regardless of casing', () => {
    expect(isTrustedDelegate(PINNED)).toBe(true);
    expect(isTrustedDelegate(PINNED.toUpperCase().replace('0X', '0x'))).toBe(true);
  });

  it('rejects anything else, including empty input', () => {
    expect(isTrustedDelegate(ATTACKER)).toBe(false);
    expect(isTrustedDelegate('')).toBe(false);
    expect(isTrustedDelegate(undefined as unknown as string)).toBe(false);
  });

  it('REFUSES to sign an authorization for an untrusted delegate', () => {
    expect(() => signSetCodeAuthorization(ATTACKER, 0n, PRIV)).toThrow(
      /untrusted_delegate/,
    );
  });

  it('still signs for the pinned delegate', () => {
    const auth = signSetCodeAuthorization(PINNED, 5n, PRIV);
    expect(auth.address).toBe(PINNED);
    expect(auth.nonce).toBe('5');
    expect(auth.r).toMatch(/^0x[0-9a-f]+$/);
    expect(auth.s).toMatch(/^0x[0-9a-f]+$/);
    expect([0, 1]).toContain(auth.yParity);
  });

  it('does not silently trust a superseded delegate (downgrade guard)', () => {
    // The pre-intentId ConfioBatchDelegate. Keeping old versions listed would
    // let a bad response force a downgrade to a delegate without the replay
    // binding, so it must NOT be trusted.
    expect(isTrustedDelegate('0xE9d9Ae4d97aE8128DF4501152540d7aA091b435C')).toBe(false);
  });
});
