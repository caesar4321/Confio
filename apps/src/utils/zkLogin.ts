import { sha256 } from '@noble/hashes/sha256';
import { stringToUtf8Bytes } from './encoding';
import { AccountType } from './accountManager';

/**
 * Generates a deterministic salt for zkLogin according to Sui's specification:
 * salt = SHA256(issuer | subject | audience | account_type | account_index)
 * 
 * @param iss - The issuer from the JWT (e.g., "https://accounts.google.com")
 * @param sub - The subject from the JWT (user's unique ID)
 * @param aud - The audience from the JWT (OAuth client ID)
 * @param accountType - The account type ('personal' or 'business')
 * @param accountIndex - The account index (0, 1, 2, etc.)
 * @returns The salt as a base64-encoded string
 */
export function generateZkLoginSalt(
  iss: string, 
  sub: string, 
  aud: string, 
  accountType: AccountType = 'personal', 
  accountIndex: number = 0
): string {
  // Convert strings to UTF-8 bytes
  const issBytes = stringToUtf8Bytes(iss);
  const subBytes = stringToUtf8Bytes(sub);
  const audBytes = stringToUtf8Bytes(aud);
  const accountTypeBytes = stringToUtf8Bytes(accountType);
  const accountIndexBytes = stringToUtf8Bytes(accountIndex.toString());

  // Concatenate the bytes: iss | sub | aud | account_type | account_index
  const combined = new Uint8Array(
    issBytes.length + 
    subBytes.length + 
    audBytes.length + 
    accountTypeBytes.length + 
    accountIndexBytes.length
  );
  
  let offset = 0;
  combined.set(issBytes, offset);
  offset += issBytes.length;
  combined.set(subBytes, offset);
  offset += subBytes.length;
  combined.set(audBytes, offset);
  offset += audBytes.length;
  combined.set(accountTypeBytes, offset);
  offset += accountTypeBytes.length;
  combined.set(accountIndexBytes, offset);

  // Generate SHA-256 hash
  const salt = sha256(combined);

  // Convert to base64
  return btoa(String.fromCharCode.apply(null, Array.from(salt)));
} 