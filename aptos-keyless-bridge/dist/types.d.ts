export interface EphemeralKeyPairData {
    privateKey: string;
    publicKey: string;
    expiryDate: string;
    nonce?: string;
    blinder?: string;
    keyId?: string;
}
export interface KeylessAccountData {
    address: string;
    publicKey: string;
    jwt: string;
    ephemeralKeyPair: EphemeralKeyPairData;
    pepper?: string;
}
export interface DeriveAccountRequest {
    jwt: string;
    ephemeralKeyPair: EphemeralKeyPairData;
    pepper?: string;
}
export interface GenerateEphemeralKeyRequest {
    expiryHours?: number;
}
export interface CreateTransactionRequest {
    sender: string;
    payload: any;
    options?: {
        maxGasAmount?: string;
        gasUnitPrice?: string;
        expireTimestamp?: string;
    };
}
export interface SignAndSubmitRequest {
    jwt: string;
    ephemeralKeyPair: EphemeralKeyPairData;
    transaction: any;
    pepper?: string;
}
export interface GenerateAuthenticatorRequest {
    jwt: string;
    ephemeralKeyPair: EphemeralKeyPairData;
    signingMessage: string;
    pepper?: string;
}
export interface GenerateAuthenticatorResponse {
    senderAuthenticatorBcsBase64: string;
    authKeyHex: string;
    ephemeralPublicKeyHex: string;
    claims: {
        iss: string;
        aud: string;
        sub: string;
        exp: number;
        iat: number;
    };
    kid?: string;
}
export interface GetOAuthUrlRequest {
    provider: 'google' | 'apple';
    clientId: string;
    redirectUri: string;
    ephemeralPublicKey: string;
    expiryDate: string;
    blinder?: string;
}
export interface FeePayerSubmitRequest {
    rawTxnBcsBase64: string;
    senderAuthenticatorBcsBase64: string;
    sponsorAddressHex: string;
    policyMetadata: {
        [key: string]: any;
    };
}
export interface FeePayerSubmitResponse {
    transactionHash: string;
    success: boolean;
}
export interface ErrorResponse {
    error: string;
    message: string;
    details?: any;
}
//# sourceMappingURL=types.d.ts.map