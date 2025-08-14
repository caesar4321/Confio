/**
 * Chain Adapter Interface
 * 
 * Provides a unified interface for deriving addresses across different blockchain networks.
 * Each chain implementation uses the same IKM (Initial Key Material) but with chain-specific
 * info strings to ensure deterministic and unique addresses per chain.
 * 
 * This allows users to have the same recovery flow across all chains while maintaining
 * separate addresses for each network.
 */

import { hkdf } from '@noble/hashes/hkdf';
import { sha256 } from '@noble/hashes/sha256';
import { CONFIO_DERIVATION_SPEC } from './derivationSpec';

/**
 * Scope defines the context for address derivation
 */
export interface DerivationScope {
  provider: 'google' | 'apple';
  accountType: 'personal' | 'business';
  accountIndex: number;
  businessId?: string;
}

/**
 * Result of address derivation
 */
export interface DerivedAddress {
  publicKey: Uint8Array;
  address: string;
  version: 'v1';
  chainId?: string;
}

/**
 * Base interface for all chain adapters
 */
export interface ChainAdapter {
  /**
   * The chain identifier (e.g., 'algorand', 'ethereum', 'arc')
   */
  readonly chainType: string;
  
  /**
   * The derivation info prefix for this chain
   */
  readonly infoPrefix: string;
  
  /**
   * Derive an address for this chain using the provided seed and scope
   */
  deriveAddress(seed: Uint8Array, scope: DerivationScope): DerivedAddress;
  
  /**
   * Validate if an address is valid for this chain
   */
  isValidAddress(address: string): boolean;
  
  /**
   * Get the chain-specific info string for HKDF
   */
  getDerivationInfo(scope: DerivationScope): string;
}

/**
 * Algorand chain adapter implementation
 */
export class AlgorandAdapter implements ChainAdapter {
  readonly chainType = 'algorand';
  readonly infoPrefix = CONFIO_DERIVATION_SPEC.algoInfoPrefix;
  
  deriveAddress(seed: Uint8Array, scope: DerivationScope): DerivedAddress {
    // Get the info string for this derivation
    const info = this.getDerivationInfo(scope);
    
    // Derive the private key using HKDF
    const privateKey = hkdf(sha256, seed, undefined, info, 32);
    
    // Generate Algorand address (would use algosdk in actual implementation)
    // This is a placeholder - actual implementation would use algosdk
    const publicKey = this.getAlgorandPublicKey(privateKey);
    const address = this.getAlgorandAddress(publicKey);
    
    return {
      publicKey,
      address,
      version: 'v1'
    };
  }
  
  isValidAddress(address: string): boolean {
    // Algorand addresses are 58 characters long and start with a letter
    return /^[A-Z2-7]{58}$/.test(address);
  }
  
  getDerivationInfo(scope: DerivationScope): string {
    return `${this.infoPrefix}|${scope.provider}|${scope.accountType}|${scope.accountIndex}|${scope.businessId ?? ''}`;
  }
  
  private getAlgorandPublicKey(privateKey: Uint8Array): Uint8Array {
    // Placeholder - would use algosdk.secretKeyToPublicKey
    // For now, return empty array
    return new Uint8Array(32);
  }
  
  private getAlgorandAddress(publicKey: Uint8Array): string {
    // Placeholder - would use algosdk.encodeAddress
    // For now, return placeholder
    return 'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA';
  }
}

/**
 * EVM (Ethereum Virtual Machine) chain adapter implementation
 * For future support of Ethereum, Polygon, BSC, etc.
 */
export class EVMAdapter implements ChainAdapter {
  readonly chainType = 'evm';
  readonly infoPrefix = 'confio/evm/v1'; // Added to derivationSpec for future use
  
  constructor(private chainId: string = '1') {} // Default to Ethereum mainnet
  
  deriveAddress(seed: Uint8Array, scope: DerivationScope): DerivedAddress {
    const info = this.getDerivationInfo(scope);
    
    // Derive the private key using HKDF
    const privateKey = hkdf(sha256, seed, undefined, info, 32);
    
    // Generate EVM address (would use ethers.js in actual implementation)
    const publicKey = this.getEVMPublicKey(privateKey);
    const address = this.getEVMAddress(publicKey);
    
    return {
      publicKey,
      address,
      version: 'v1',
      chainId: this.chainId
    };
  }
  
  isValidAddress(address: string): boolean {
    // EVM addresses are 42 characters (0x + 40 hex chars)
    return /^0x[a-fA-F0-9]{40}$/.test(address);
  }
  
  getDerivationInfo(scope: DerivationScope): string {
    return `${this.infoPrefix}|${scope.provider}|${scope.accountType}|${scope.accountIndex}|${scope.businessId ?? ''}|chain:${this.chainId}`;
  }
  
  private getEVMPublicKey(privateKey: Uint8Array): Uint8Array {
    // Placeholder - would use secp256k1 curve operations
    return new Uint8Array(64);
  }
  
  private getEVMAddress(publicKey: Uint8Array): string {
    // Placeholder - would use keccak256 hash of public key
    return '0x0000000000000000000000000000000000000000';
  }
}

/**
 * Arc chain adapter implementation
 * For future support of Arc network
 */
export class ArcAdapter implements ChainAdapter {
  readonly chainType = 'arc';
  readonly infoPrefix = 'confio/arc/v1'; // Added to derivationSpec for future use
  
  deriveAddress(seed: Uint8Array, scope: DerivationScope): DerivedAddress {
    const info = this.getDerivationInfo(scope);
    
    // Derive the private key using HKDF
    const privateKey = hkdf(sha256, seed, undefined, info, 32);
    
    // Generate Arc address (would use Arc SDK in actual implementation)
    const publicKey = this.getArcPublicKey(privateKey);
    const address = this.getArcAddress(publicKey);
    
    return {
      publicKey,
      address,
      version: 'v1'
    };
  }
  
  isValidAddress(address: string): boolean {
    // Placeholder - implement Arc-specific validation
    return address.startsWith('arc1') && address.length === 42;
  }
  
  getDerivationInfo(scope: DerivationScope): string {
    return `${this.infoPrefix}|${scope.provider}|${scope.accountType}|${scope.accountIndex}|${scope.businessId ?? ''}`;
  }
  
  private getArcPublicKey(privateKey: Uint8Array): Uint8Array {
    // Placeholder - would use Arc-specific key derivation
    return new Uint8Array(32);
  }
  
  private getArcAddress(publicKey: Uint8Array): string {
    // Placeholder - would use Arc-specific address encoding
    return 'arc1000000000000000000000000000000000000000';
  }
}

/**
 * Factory for creating chain adapters
 */
export class ChainAdapterFactory {
  private static adapters = new Map<string, ChainAdapter>();
  
  static {
    // Register default adapters
    this.registerAdapter(new AlgorandAdapter());
    this.registerAdapter(new EVMAdapter());
    this.registerAdapter(new ArcAdapter());
  }
  
  /**
   * Register a new chain adapter
   */
  static registerAdapter(adapter: ChainAdapter): void {
    this.adapters.set(adapter.chainType, adapter);
  }
  
  /**
   * Get a chain adapter by type
   */
  static getAdapter(chainType: string): ChainAdapter | undefined {
    return this.adapters.get(chainType);
  }
  
  /**
   * Get all registered adapters
   */
  static getAllAdapters(): ChainAdapter[] {
    return Array.from(this.adapters.values());
  }
}

/**
 * Multi-chain wallet derivation helper
 * 
 * Example usage:
 * ```typescript
 * const seed = await generateSeed(clientSalt, serverPepper);
 * const scope = { provider: 'google', accountType: 'personal', accountIndex: 0 };
 * 
 * // Derive addresses for all chains from the same seed
 * const algorandAddress = ChainAdapterFactory.getAdapter('algorand')?.deriveAddress(seed, scope);
 * const evmAddress = ChainAdapterFactory.getAdapter('evm')?.deriveAddress(seed, scope);
 * const arcAddress = ChainAdapterFactory.getAdapter('arc')?.deriveAddress(seed, scope);
 * 
 * // All addresses are deterministic and can be recovered with the same seed
 * ```
 */
export function deriveMultiChainAddresses(
  seed: Uint8Array, 
  scope: DerivationScope
): Map<string, DerivedAddress> {
  const addresses = new Map<string, DerivedAddress>();
  
  for (const adapter of ChainAdapterFactory.getAllAdapters()) {
    try {
      const derived = adapter.deriveAddress(seed, scope);
      addresses.set(adapter.chainType, derived);
    } catch (error) {
      console.error(`Failed to derive ${adapter.chainType} address:`, error);
    }
  }
  
  return addresses;
}