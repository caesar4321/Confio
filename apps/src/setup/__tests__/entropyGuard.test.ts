/**
 * The contract entropyGuard exists to enforce: key material comes from the
 * platform CSPRNG or it does not come at all.
 *
 * Prompted by the July 2026 Coldcard incident — firmware silently fell back
 * from the hardware RNG to a software PRNG for five years, cutting seed
 * entropy from 128 to 72 bits, ~1,400 BTC drained. The defect was not weak
 * crypto; it was a fallback that never failed loud. These tests pin the
 * "never falls back" half of the contract, which is the half that rots
 * silently.
 */

import { NativeModules } from 'react-native';
import { secureRandomBytes, __resetPinnedRandomModuleForTests } from '../entropyGuard';

const realModule = NativeModules.RNGetRandomValues;

beforeEach(() => {
  // The module reference is pinned on first successful resolution, so each
  // test has to start from an unpinned state to install its own substitute.
  __resetPinnedRandomModuleForTests();
});

afterEach(() => {
  NativeModules.RNGetRandomValues = realModule;
  __resetPinnedRandomModuleForTests();
});

describe('secureRandomBytes', () => {
  it('returns exactly the requested number of bytes', () => {
    expect(secureRandomBytes(32, 'test').length).toBe(32);
    expect(secureRandomBytes(24, 'test').length).toBe(24);
    expect(secureRandomBytes(16, 'test').length).toBe(16);
  });

  it('does not repeat across calls', () => {
    const a = Buffer.from(secureRandomBytes(32, 'test')).toString('hex');
    const b = Buffer.from(secureRandomBytes(32, 'test')).toString('hex');
    expect(a).not.toBe(b);
  });

  it('throws instead of degrading when the native CSPRNG is absent', () => {
    NativeModules.RNGetRandomValues = undefined;
    expect(() => secureRandomBytes(32, 'a master secret')).toThrow(/native CSPRNG/i);
  });

  it('throws when the native module exists but cannot produce bytes', () => {
    // What Chrome remote debugging looks like: the module is present, but the
    // synchronous native call is unsupported and throws.
    NativeModules.RNGetRandomValues = {
      getRandomBase64: () => {
        throw new Error('Calling synchronous methods on native modules is not supported in Chrome');
      },
    };
    expect(() => secureRandomBytes(32, 'a master secret')).toThrow(/native CSPRNG call failed/i);
  });

  it('rejects a short read rather than returning a shrunken keyspace', () => {
    NativeModules.RNGetRandomValues = {
      // Returns 8 bytes no matter what was asked for.
      getRandomBase64: () => Buffer.alloc(8, 7).toString('base64'),
    };
    // The canonical-base64 check catches this first (12 characters where 44
    // were required), before the post-decode byte count ever runs. Either
    // rejection is correct; what matters is that no short secret escapes.
    expect(() => secureRandomBytes(32, 'a master secret')).toThrow(
      /non-canonical base64|returned 8 bytes, expected 32/
    );
  });

  it('never consults global.crypto, which may not be native-backed', () => {
    // react-native-get-random-values only installs its own getRandomValues
    // when the slot is empty, so a weaker function that got there first
    // survives. Poison the global and confirm it is not our source.
    const originalCrypto = (globalThis as any).crypto;
    (globalThis as any).crypto = {
      getRandomValues: (arr: Uint8Array) => arr.fill(0),
    };
    try {
      const bytes = secureRandomBytes(32, 'a master secret');
      expect(bytes.every((b) => b === 0)).toBe(false);
    } finally {
      (globalThis as any).crypto = originalCrypto;
    }
  });

  // base64-js maps out-of-alphabet characters to zero instead of throwing, so
  // '!'.repeat(43) + '=' decodes to exactly 32 zero bytes and passes a
  // length-only check. A count is not evidence that entropy arrived.
  it('rejects a correct-length payload that is not canonical base64', () => {
    NativeModules.RNGetRandomValues = {
      getRandomBase64: () => '!'.repeat(43) + '=',
    };
    expect(() => secureRandomBytes(32, 'a master secret')).toThrow(/non-canonical base64/i);
  });

  it('rejects a payload with padding that does not match the byte count', () => {
    NativeModules.RNGetRandomValues = {
      getRandomBase64: () => 'A'.repeat(42) + '==',
    };
    expect(() => secureRandomBytes(32, 'a master secret')).toThrow(/non-canonical base64/i);
  });

  it('rejects a non-string payload', () => {
    NativeModules.RNGetRandomValues = {
      getRandomBase64: () => ({ nope: true }),
    };
    expect(() => secureRandomBytes(32, 'a master secret')).toThrow(/expected a string/i);
  });

  it('accepts canonical payloads at every length we request', () => {
    // 32 and 16 pad differently (32 % 3 === 2, 16 % 3 === 1, 24 % 3 === 0),
    // so this pins the padding arithmetic, not just the happy path.
    for (const n of [16, 24, 32]) {
      expect(secureRandomBytes(n, 'test').length).toBe(n);
    }
  });

  it('rejects nonsensical lengths', () => {
    expect(() => secureRandomBytes(0, 'test')).toThrow(/Invalid length/);
    expect(() => secureRandomBytes(-1, 'test')).toThrow(/Invalid length/);
  });
});
