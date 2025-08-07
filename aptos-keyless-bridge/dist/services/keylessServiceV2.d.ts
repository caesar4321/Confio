import { AccountAuthenticator } from '@aptos-labs/ts-sdk';
interface SimpleFeePayerRequest {
    senderAddress: string;
    recipientAddress: string;
    amount: number;
    tokenType: string;
    senderAuthenticator: string;
    senderAuthenticatorBcs?: string;
    jwt?: string;
    ephemeralKeyPair?: {
        privateKey: string;
        publicKey: string;
        nonce: string;
    };
}
interface SimpleFeePayerResponse {
    success: boolean;
    transactionHash?: string;
    error?: string;
}
export declare class KeylessServiceV2 {
    private aptos;
    private sponsorAccount;
    private pendingTransactions?;
    constructor();
    /**
     * Submit a sponsored transaction using the official SDK pattern
     * EXPERIMENTAL: Recreate keyless account on bridge side for direct signing
     */
    submitSponsoredTransaction(request: SimpleFeePayerRequest): Promise<SimpleFeePayerResponse>;
    /**
     * Build a sponsored transaction using the CORRECT pattern for Aptos SDK
     * The key insight: sender must sign the SAME transaction that will be submitted
     */
    buildSponsoredTransaction(request: SimpleFeePayerRequest): Promise<{
        success: boolean;
        transactionId: string;
        signingMessage: string;
        rawTransaction: string;
        rawBcs: string;
        sponsorAddress: `0x${string}`;
        sponsorAuthenticator: AccountAuthenticator;
        note: string;
        error?: undefined;
    } | {
        success: boolean;
        error: string;
        transactionId?: undefined;
        signingMessage?: undefined;
        rawTransaction?: undefined;
        rawBcs?: undefined;
        sponsorAddress?: undefined;
        sponsorAuthenticator?: undefined;
        note?: undefined;
    }>;
    /**
     * Submit a transaction that was previously prepared
     * A/B Test: Also accepts BCS authenticator to test alternative signing approach
     */
    submitCachedTransaction(transactionId: string, senderAuthenticatorBase64: string, senderAuthenticatorBcsBase64?: string): Promise<{
        success: boolean;
        transactionHash: string;
        error?: undefined;
    } | {
        success: boolean;
        error: string;
        transactionHash?: undefined;
    }>;
    private getTransferFunction;
}
export declare const keylessServiceV2: KeylessServiceV2;
export {};
//# sourceMappingURL=keylessServiceV2.d.ts.map