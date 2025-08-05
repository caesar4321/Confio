import { EphemeralKeyPair } from '@aptos-labs/ts-sdk';

// In-memory store for ephemeral key pairs
// In production, you'd want to use Redis or a database
const keyPairStore = new Map<string, EphemeralKeyPair>();

export const ephemeralKeyStore = {
  store(id: string, keyPair: EphemeralKeyPair): void {
    keyPairStore.set(id, keyPair);
  },

  retrieve(id: string): EphemeralKeyPair | undefined {
    return keyPairStore.get(id);
  },

  delete(id: string): void {
    keyPairStore.delete(id);
  },

  // Clean up old entries (call periodically)
  cleanup(): void {
    const now = Date.now() / 1000;
    for (const [id, keyPair] of keyPairStore.entries()) {
      if (keyPair.expiryDateSecs < now) {
        keyPairStore.delete(id);
      }
    }
  }
};