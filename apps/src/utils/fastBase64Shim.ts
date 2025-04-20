import { toByteArray, fromByteArray } from '../../base64';

// Base64 character set
const base64Chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';

export function base64ToBytes(str: string): Uint8Array {
  return toByteArray(str);
}

export function bytesToBase64(bytes: Uint8Array): string {
  return fromByteArray(bytes);
} 