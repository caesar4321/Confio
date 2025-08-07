import { EphemeralKeyPairData, KeylessAccountData, DeriveAccountRequest, GenerateAuthenticatorResponse, FeePayerSubmitResponse } from '../types';
export declare class KeylessService {
    private aptos;
    private sponsorAccount;
    constructor();
    /**
     * Generate a new ephemeral key pair
     */
    generateEphemeralKeyPair(expiryHours?: number): Promise<EphemeralKeyPairData & {
        keyId: string;
    }>;
    /**
     * Generate a deterministic ephemeral key pair from a seed
     * This ensures the same seed always produces the same address
     */
    generateDeterministicEphemeralKeyPair(seed: string, expiryHours?: number): Promise<EphemeralKeyPairData & {
        keyId: string;
    }>;
    /**
     * Generate OAuth URL with proper nonce
     */
    generateOAuthUrl(provider: 'google' | 'apple', clientId: string, redirectUri: string, ephemeralKeyPairData: EphemeralKeyPairData): Promise<string>;
    /**
     * Derive a Keyless account from JWT and ephemeral key pair
     */
    deriveKeylessAccount(request: DeriveAccountRequest): Promise<KeylessAccountData>;
    /**
     * Generate authenticator for a transaction without submitting
     * This is used for sponsored transactions where the backend needs the authenticator
     */
    generateAuthenticator(jwt: string, ephemeralKeyPairData: EphemeralKeyPairData, signingMessageBase64: string, pepper?: string): Promise<GenerateAuthenticatorResponse>;
    /**
     * Sign and submit a transaction using Keyless account
     */
    signAndSubmitTransaction(jwt: string, ephemeralKeyPairData: EphemeralKeyPairData, transaction: any, pepper?: string): Promise<any>;
    /**
     * Get account balance for multiple tokens
     */
    getAccountBalance(address: string): Promise<{
        [key: string]: string;
    }>;
    /**
     * Reconstruct EphemeralKeyPair from data
     */
    /**
     * Submit fee-payer transaction with keyless authenticator
     * Updated to use official SDK pattern from aptos-ts-sdk examples
     */
    submitFeePayerTransaction(rawTxnBcsBase64: string, senderAuthenticatorBcsBase64: string, sponsorAddressHex: string, _policyMetadata: {
        [key: string]: any;
    }): Promise<FeePayerSubmitResponse>;
    private reconstructEphemeralKeyPair;
}
//# sourceMappingURL=keylessService.d.ts.map