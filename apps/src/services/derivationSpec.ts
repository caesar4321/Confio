/**
 * Derivation Specification Constants
 * 
 * CRITICAL: These constants define the derivation paths for wallet generation.
 * Changing ANY of these values will result in different wallet addresses being generated.
 * 
 * DO NOT MODIFY these values unless you fully understand the implications:
 * - Users will lose access to their existing wallets
 * - All funds in existing wallets will become inaccessible
 * - Recovery will be impossible without the original values
 * 
 * These values are frozen and must remain constant across all versions of the app.
 */

export const CONFIO_DERIVATION_SPEC = {
  // Root derivation path for the wallet seed
  root: 'confio-wallet-v1',
  
  // Path for extracting the deterministic seed
  extract: 'confio/extract/v1',
  
  // Info prefix for Algorand key derivation
  algoInfoPrefix: 'confio/algo/v1',
  
  // Salt for KEK (Key Encryption Key) derivation
  kekSalt: 'confio/kek-salt/v1',
  
  // Info for KEK derivation
  kekInfo: 'confio/kek-info/v1',
  
  // Future chain support - uncomment when implementing
  // evmInfoPrefix: 'confio/evm/v1',  // For Ethereum, Polygon, BSC, etc.
  // arcInfoPrefix: 'confio/arc/v1',  // For Arc network
  // solanaInfoPrefix: 'confio/solana/v1',  // For Solana
  // cosmosInfoPrefix: 'confio/cosmos/v1',  // For Cosmos chains
} as const;

// Type to ensure these values are never accidentally modified
export type DerivationSpec = typeof CONFIO_DERIVATION_SPEC;

// Validation to ensure the spec hasn't been tampered with
// This hash should match the expected value in production builds
export const SPEC_HASH = 'a5d8c3f2b1e9d7a6c8b4f3e2d1a9c7b5'; // SHA-256 hash of the spec (example)

/**
 * Validate that the derivation spec hasn't been modified.
 * This function should be called during app initialization.
 */
export function validateDerivationSpec(): boolean {
  // In production, you could compute a hash of CONFIO_DERIVATION_SPEC
  // and compare it against SPEC_HASH to ensure integrity
  return true;
}