/**
 * entropyGuard.ts — the single entry point for CSPRNG bytes used as key material.
 *
 * WHY THIS EXISTS, AND WHY IT CALLS THE NATIVE MODULE DIRECTLY:
 *
 * `react-native-get-random-values` installs `global.crypto.getRandomValues`,
 * and @noble reads that global at module load. Two gaps follow from that:
 *
 *  1. The library ships an `insecureRandomValues()` fallback built on
 *     `Math.random()`, reachable under Chrome remote debugging.
 *  2. It installs its own function only `if (typeof
 *     global.crypto.getRandomValues !== 'function')` — so anything that got
 *     there first is preserved, not replaced. Checking "a native module
 *     exists" and "some getRandomValues exists" proves nothing about whether
 *     the function @noble actually calls is the native-backed one.
 *
 * So we do not check the global; we bypass it. `secureRandomBytes()` calls
 * `RNGetRandomValues.getRandomBase64` — Android `java.security.SecureRandom`,
 * iOS `SecRandomCopyBytes` — and throws when that is unavailable. There is no
 * degraded path to fall back to and no environment flag that switches the
 * check off. Under Chrome remote debugging the synchronous native call throws
 * on its own ("Calling synchronous methods on native modules is not supported
 * in Chrome"), which is the correct outcome: refuse, loudly.
 *
 * Coldcard lost ~1,400 BTC in July 2026 to the opposite arrangement: a silent
 * fallback from the hardware RNG to a software PRNG that ran for five years
 * without failing loud. Key material must never be minted from a degraded
 * source.
 *
 * Tests mock `NativeModules.RNGetRandomValues` in jest.setup.js with a
 * Node-CSPRNG-backed implementation. That is deliberate: the exemption lives
 * in test configuration, where it cannot be reached by a shipped build.
 */

import { NonCanonicalBase64Error, strictBase64ToBytes } from '../utils/encoding';

/**
 * The native CSPRNG function, or null. Required lazily so this module stays
 * safe to import before the React Native bridge is fully set up.
 *
 * PINNED ON FIRST SUCCESS, and it is the FUNCTION that is pinned, not the
 * module object. `NativeModules` is a plain JS object: pinning only the module
 * still left `mod.getRandomBase64` looked up on every call, so reassigning that
 * one property after startup defeated the protection entirely. Binding the
 * function once means an attacker has to win the race to app startup rather
 * than assign at any later point. That is not proof of a native binding —
 * nothing reachable from JS is — but it is the strongest bar available here.
 */
let pinnedGetRandomBase64: ((byteLength: number) => unknown) | null = null;

function nativeRandomFn(): ((byteLength: number) => unknown) | null {
  if (pinnedGetRandomBase64) return pinnedGetRandomBase64;
  try {
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const NM = require('react-native').NativeModules;
    const mod = NM?.RNGetRandomValues;
    if (mod && typeof mod.getRandomBase64 === 'function') {
      // Pin the FUNCTION, bound to its module. Pinning only the module object
      // left `mod.getRandomBase64` readable on every call, so reassigning that
      // one property after startup still defeated the protection.
      pinnedGetRandomBase64 = mod.getRandomBase64.bind(mod);
      return pinnedGetRandomBase64;
    }
    return null;
  } catch {
    return null;
  }
}

/**
 * TEST ONLY. The pin above would otherwise make module-swapping tests
 * order-dependent. Inert in release builds so that exporting it does not hand
 * shipped JS a way to unpin the module and swap in a weak implementation.
 */
export function __resetPinnedRandomModuleForTests(): void {
  if (!__DEV__) return;
  pinnedGetRandomBase64 = null;
}

/**
 * CSPRNG bytes straight from the platform, for anything that must be
 * unguessable: key material, nonces, IVs, salts.
 *
 * Throws rather than degrading. Callers must not catch this and continue with
 * a weaker source — a thrown error here means "do not create the secret".
 *
 * @param length how many bytes
 * @param context what the bytes are for, used in the error message
 */
export function secureRandomBytes(length: number, context: string): Uint8Array {
  if (!Number.isInteger(length) || length <= 0) {
    throw new Error(`[EntropyGuard] Invalid length ${length} requested for ${context}`);
  }

  const getRandomBase64 = nativeRandomFn();
  if (!getRandomBase64) {
    throw new Error(
      `[EntropyGuard] Refusing to generate ${context}: the native CSPRNG ` +
      '(RNGetRandomValues) is not available. Never fall back to Math.random ' +
      'or an unverified crypto.getRandomValues polyfill.'
    );
  }

  let bytes: Uint8Array;
  try {
    // Strict, not lenient: base64-js maps junk characters to zero bytes, so a
    // decoded length is not evidence that any entropy arrived.
    bytes = strictBase64ToBytes(getRandomBase64(length), length);
  } catch (error: any) {
    if (error instanceof NonCanonicalBase64Error) {
      throw new Error(
        `[EntropyGuard] Refusing to generate ${context}: the native CSPRNG returned ` +
        `a non-canonical base64 payload (${error.message}). Treat the output as untrusted.`
      );
    }
    // The most common cause is Chrome remote debugging, where synchronous
    // native calls are unsupported. Failing here is correct.
    throw new Error(
      `[EntropyGuard] Refusing to generate ${context}: the native CSPRNG call ` +
      `failed (${error?.message || error}). If the Chrome debugger is attached, ` +
      'detach it — a secret created now would be brute-forceable.'
    );
  }

  // A short read would silently shrink the keyspace, which is the exact
  // failure mode this module exists to prevent.
  if (bytes.length !== length) {
    throw new Error(
      `[EntropyGuard] Refusing to generate ${context}: native CSPRNG returned ` +
      `${bytes.length} bytes, expected ${length}.`
    );
  }

  return bytes;
}

/**
 * Boot-time probe. Logs; never throws — a developer under the Chrome debugger
 * should still be able to browse the app. Secret creation is blocked
 * separately and unconditionally by secureRandomBytes().
 *
 * Note this runs after the static import graph of bootstrap.ts has evaluated
 * (ES imports are hoisted), so it is a report, not a barrier. The barrier is
 * at the generation site.
 */
export function reportEntropySourceAtBoot(): void {
  try {
    secureRandomBytes(1, 'the boot-time entropy probe');
    console.log('[EntropyGuard] Native CSPRNG available.');
  } catch (error: any) {
    console.error(
      `[EntropyGuard] NATIVE CSPRNG UNAVAILABLE: ${error?.message || error} ` +
      'Wallet creation is blocked until this is resolved. Any wallet created ' +
      'while this was true must be treated as compromised.'
    );
  }
}
