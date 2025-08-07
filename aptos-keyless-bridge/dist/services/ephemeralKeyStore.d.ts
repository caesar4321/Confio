import { EphemeralKeyPair } from '@aptos-labs/ts-sdk';
export declare const ephemeralKeyStore: {
    store(id: string, keyPair: EphemeralKeyPair): void;
    retrieve(id: string): EphemeralKeyPair | undefined;
    delete(id: string): void;
    cleanup(): void;
};
//# sourceMappingURL=ephemeralKeyStore.d.ts.map