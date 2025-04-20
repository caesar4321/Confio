import { toByteArray, fromByteArray } from '../../base64';

// Base64 character set (standard, not URL-safe)
const base64Chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';

export function base64ToBytes(str: string): Uint8Array {
  // Ensure we're using standard base64 (not URL-safe)
  str = str.replace(/-/g, '+').replace(/_/g, '/');
  return toByteArray(str);
}

export function bytesToBase64(bytes: Uint8Array): string {
  // Ensure we're using standard base64 (not URL-safe)
  return fromByteArray(bytes);
}

// Helper function to convert string to UTF-8 bytes
export function stringToUtf8Bytes(str: string): Uint8Array {
  return new TextEncoder().encode(str);
}

// Helper function to convert UTF-8 bytes to string
export function utf8BytesToString(bytes: Uint8Array): string {
  return new TextDecoder('utf-8').decode(bytes);
} 