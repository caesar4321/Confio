import { sha256 } from '@noble/hashes/sha256';
import { stringToUtf8Bytes } from './encoding';

/**
 * Generates a deterministic salt for zkLogin according to Sui's specification:
 * salt = SHA256(issuer | subject | audience)
 * 
 * @param iss - The issuer from the JWT (e.g., "https://accounts.google.com")
 * @param sub - The subject from the JWT (user's unique ID)
 * @param aud - The audience from the JWT (OAuth client ID)
 * @returns The salt as a base64-encoded string
 */
export function generateZkLoginSalt(iss: string, sub: string, aud: string): string {
  // Convert strings to UTF-8 bytes
  const issBytes = stringToUtf8Bytes(iss);
  const subBytes = stringToUtf8Bytes(sub);
  const audBytes = stringToUtf8Bytes(aud);

  // Concatenate the bytes
  const combined = new Uint8Array(issBytes.length + subBytes.length + audBytes.length);
  combined.set(issBytes, 0);
  combined.set(subBytes, issBytes.length);
  combined.set(audBytes, issBytes.length + subBytes.length);

  // Generate SHA-256 hash
  const salt = sha256(combined);

  // Convert to base64
  return btoa(String.fromCharCode.apply(null, Array.from(salt)));
} 