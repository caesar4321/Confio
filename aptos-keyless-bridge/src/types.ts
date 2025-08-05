export interface EphemeralKeyPairData {
  privateKey: string;
  publicKey: string;
  expiryDate: string;
  nonce?: string;
  blinder?: string;
  keyId?: string;  // Optional key ID for stored ephemeral key pairs
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

export interface GetOAuthUrlRequest {
  provider: 'google' | 'apple';
  clientId: string;
  redirectUri: string;
  ephemeralPublicKey: string;
  expiryDate: string;
  blinder?: string;
}

export interface ErrorResponse {
  error: string;
  message: string;
  details?: any;
}