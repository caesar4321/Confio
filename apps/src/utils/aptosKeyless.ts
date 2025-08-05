import { sha256 } from '@noble/hashes/sha256';
import { AccountType } from './accountManager';
import { stringToUtf8Bytes } from './encoding';

/**
 * Generates a deterministic pepper (salt) for Aptos Keyless according to the formula:
 * - Personal accounts: SHA256(issuer_subject_audience_account_type_account_index)
 * - Business accounts: SHA256(issuer_subject_audience_account_type_business_id_account_index)
 * 
 * Components are joined with underscore separators. Empty business_id is omitted.
 * This ensures the same user with the same account parameters always gets the same address,
 * making the system truly non-custodial.
 * 
 * @param iss - The issuer from the JWT (e.g., "https://accounts.google.com")
 * @param sub - The subject from the JWT (user's unique ID)
 * @param aud - The audience from the JWT (OAuth client ID)
 * @param accountType - The account type ('personal' or 'business')
 * @param businessId - The business ID (empty string for personal accounts)
 * @param accountIndex - The account index (0, 1, 2, etc.)
 * @returns The pepper as a hex string (31 bytes for Aptos)
 */
export function generateKeylessPepper(
  iss: string,
  sub: string,
  aud: string,
  accountType: AccountType = 'personal',
  businessId: string = '',
  accountIndex: number = 0
): string {
  // Concatenate all components with underscore separator
  // Format: iss_sub_aud_account_type_business_id_account_index
  // For personal accounts (no business_id), format: iss_sub_aud_account_type_account_index
  const components = [iss, sub, aud, accountType];
  
  // Only include business_id if it's not empty
  if (businessId) {
    components.push(businessId);
  }
  
  components.push(accountIndex.toString());
  
  const combinedString = components.join('_');
  
  // Convert to UTF-8 bytes
  const combinedBytes = stringToUtf8Bytes(combinedString);

  // Generate SHA-256 hash (32 bytes)
  const fullHash = sha256(combinedBytes);

  // Aptos pepper is 31 bytes (248 bits)
  // Take the first 31 bytes of the hash
  const pepper = fullHash.slice(0, 31);

  // Return as hex string with 0x prefix
  return '0x' + Array.from(pepper).map(b => b.toString(16).padStart(2, '0')).join('');
}

/**
 * Generates an ephemeral key pair for Aptos Keyless on the client side.
 * This ensures the private key never leaves the device (non-custodial).
 */
export async function generateEphemeralKeyPair(): Promise<{
  privateKey: string;
  publicKey: string;
  nonce: string;
  expiryDate: string;
}> {
  // This will be implemented using the Aptos SDK
  // For now, we'll use the GraphQL mutation but this should be replaced
  // with client-side generation using @aptos-labs/ts-sdk
  
  // TODO: Implement using Aptos SDK's EphemeralKeyPair.generate()
  // const ephemeralKeyPair = EphemeralKeyPair.generate();
  
  throw new Error('Client-side ephemeral key generation not yet implemented. Install @aptos-labs/ts-sdk.');
}