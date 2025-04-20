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