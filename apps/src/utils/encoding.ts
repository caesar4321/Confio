import { toByteArray, fromByteArray } from 'base64-js';

/**
 * Converts a base64 string to a Uint8Array
 * @param base64 The base64 string to convert
 * @returns A Uint8Array containing the decoded bytes
 */
export function base64ToBytes(base64: string): Uint8Array {
  // Replace URL-safe characters with standard base64
  const standardBase64 = base64.replace(/-/g, '+').replace(/_/g, '/');
  return toByteArray(standardBase64);
}

export class NonCanonicalBase64Error extends Error {
  constructor(detail: string) {
    super(`Non-canonical base64: ${detail}`);
    this.name = 'NonCanonicalBase64Error';
  }
}

/**
 * Strict counterpart to base64ToBytes, for anything security-relevant.
 *
 * base64-js decodes LENIENTLY: characters outside the alphabet map to zero
 * instead of raising, so `'!'.repeat(43) + '='` decodes to exactly 32 ZERO
 * bytes and sails through a length check. Verified against the installed
 * decoder. Any code that treats a decoded length as evidence of content needs
 * this function, not base64ToBytes.
 *
 * Canonicality is enforced by re-encoding and comparing, which also catches
 * non-zero unused padding bits (e.g. a trailing 'B==' that decodes the same as
 * 'A==') that an alphabet-and-length check alone would let through.
 *
 * Deliberately does NOT accept URL-safe input: callers that need it should
 * normalize first and be explicit about it.
 */
export function strictBase64ToBytes(input: unknown, expectedByteLength?: number): Uint8Array {
  if (typeof input !== 'string') {
    throw new NonCanonicalBase64Error(`expected a string, got ${typeof input}`);
  }
  if (input.length === 0 || input.length % 4 !== 0) {
    throw new NonCanonicalBase64Error(`length ${input.length} is not a positive multiple of 4`);
  }
  if (!/^[A-Za-z0-9+/]+={0,2}$/.test(input)) {
    throw new NonCanonicalBase64Error('contains characters outside the base64 alphabet, or misplaced padding');
  }

  const bytes = toByteArray(input);

  // Round-trip: the only encoding of these bytes is the input we were given.
  if (fromByteArray(bytes) !== input) {
    throw new NonCanonicalBase64Error('does not round-trip; unused padding bits are set');
  }

  if (expectedByteLength !== undefined && bytes.length !== expectedByteLength) {
    throw new NonCanonicalBase64Error(`decoded ${bytes.length} bytes, expected ${expectedByteLength}`);
  }

  return bytes;
}

/**
 * Converts a Uint8Array to a base64 string
 * @param bytes The bytes to convert
 * @returns A base64 string
 */
export function bytesToBase64(bytes: Uint8Array): string {
  return fromByteArray(bytes);
}

/**
 * Converts a string to UTF-8 bytes
 * @param str The string to convert
 * @returns A Uint8Array containing the UTF-8 encoded bytes
 */
export function stringToUtf8Bytes(str: string): Uint8Array {
  return new TextEncoder().encode(str);
}

/**
 * Converts a Uint8Array to a hex string
 * @param bytes The bytes to convert
 * @returns A hex string
 */
export function bufferToHex(bytes: Uint8Array): string {
  return Array.from(bytes)
    .map(b => b.toString(16).padStart(2, '0'))
    .join('');
} 