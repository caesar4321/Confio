import { Platform } from 'react-native';
import * as Keychain from 'react-native-keychain';
import { bytesToBase64, NonCanonicalBase64Error, strictBase64ToBytes } from '../utils/encoding';

/**
 * storeSecret writes with bytesToBase64 (base64-js fromByteArray), which emits
 * standard padded base64 — so reads can and must decode STRICTLY.
 *
 * The lenient decoder maps characters outside the alphabet to zero instead of
 * raising: a damaged 44-character value decodes to 32 ZERO bytes, which passes
 * a length check and becomes a valid-looking wrong wallet. Verified against the
 * installed decoder. See entropyGuard.ts for the same hazard on the RNG path.
 */
function decodeStoredSecret(stored: string, key: string): Uint8Array {
    try {
        return strictBase64ToBytes(stored);
    } catch (error) {
        if (error instanceof NonCanonicalBase64Error) {
            console.error(`[CredentialStorage] Stored value for "${key}" is not canonical base64; treating as corrupt.`, error);
        }
        throw error;
    }
}

export class SecureStorageReadError extends Error {
    readonly cause: unknown;
    constructor(key: string, cause: unknown) {
        super(`[CredentialStorage] Could not read "${key}" from secure storage: ${(cause as any)?.message || cause}`);
        this.name = 'SecureStorageReadError';
        this.cause = cause;
    }
}

/**
 * Interface for platform-agnostic secure storage with cloud sync capabilities.
 */
export interface SecureStorageInterface {
    storeSecret(key: string, secret: Uint8Array): Promise<void>;
    retrieveSecret(key: string): Promise<Uint8Array | null>;
    retrieveSecretStrict(key: string): Promise<Uint8Array | null>;
    deleteSecret(key: string): Promise<void>;
}

class CredentialStorageService implements SecureStorageInterface {
    /**
     * Store a secret securely with cloud sync enabled.
     * @param key Identifies the secret (e.g., 'confio_v2_secret')
     * @param secret The raw bytes to store
     */
    async storeSecret(key: string, secret: Uint8Array): Promise<void> {
        const base64Secret = bytesToBase64(secret);

        if (Platform.OS === 'ios') {
            // iOS: Use Keychain with iCloud Sync
            // Spec: kSecAttrSynchronizable: true, kSecAttrAccessibleAfterFirstUnlock
            // 
            // NOTE: We do NOT use ACCESS_CONTROL.USER_PRESENCE here.
            // Reason: App-level biometric auth (on foreground) already protects the user.
            // Using USER_PRESENCE would trigger iOS Face ID/Touch ID on EVERY key access
            // (every transaction signing), which is redundant and annoying UX.
            await Keychain.setGenericPassword(key, base64Secret, {
                service: key,
                synchronizable: true,
                // Rule: Accessible after device first unlock (works in background)
                accessible: Keychain.ACCESSIBLE.AFTER_FIRST_UNLOCK,
                // NO accessControl - let app-level bio auth handle security
            });
        } else {
            // Android: local-only cache. Google Drive is the durable source of
            // truth for Google accounts.
            await Keychain.setGenericPassword(key, base64Secret, {
                service: key,
                accessible: Keychain.ACCESSIBLE.AFTER_FIRST_UNLOCK,
            });
        }
    }

    /**
     * Retrieve a secret from secure storage.
     * @param key Identifies the secret
     */
    async retrieveSecret(key: string): Promise<Uint8Array | null> {
        if (Platform.OS === 'ios') {
            try {
                const credentials = await Keychain.getGenericPassword({
                    service: key,
                    synchronizable: true, // Look in iCloud Keychain too
                    authenticationPrompt: {
                        title: 'Autenticación requerida',
                        subtitle: 'Confirma tu identidad para acceder a tu billetera',
                        description: 'Confío',
                        cancel: 'Cancelar',
                    },
                });

                if (credentials && credentials.password) {
                    return decodeStoredSecret(credentials.password, key);
                }
                return null;
            } catch (error) {
                return null;
            }
        } else {
            try {
                const credentials = await Keychain.getGenericPassword({
                    service: key,
                });

                if (credentials && credentials.password) {
                    return decodeStoredSecret(credentials.password, key);
                }
                return null;
            } catch (error) {
                return null;
            }
        }
    }

    /**
     * Retrieve KEY MATERIAL, distinguishing the three outcomes that
     * retrieveSecret collapses into null:
     *
     *   - absent          -> null  (clean device, first login: safe to restore)
     *   - unreadable      -> SecureStorageReadError (locked keystore, invalidated
     *                       key, storage failure — NOT proof of absence)
     *   - malformed value -> NonCanonicalBase64Error (corruption)
     *
     * retrieveSecret returns null for all three, which is correct for
     * disposable metadata and catastrophic for secrets: "I could not read it"
     * became "there isn't one", and callers then generated a replacement over
     * the top of a funded wallet or fell back to a V1 address.
     */
    async retrieveSecretStrict(key: string): Promise<Uint8Array | null> {
        const options: any = Platform.OS === 'ios'
            ? {
                service: key,
                synchronizable: true,
                authenticationPrompt: {
                    title: 'Autenticación requerida',
                    subtitle: 'Confirma tu identidad para acceder a tu billetera',
                    description: 'Confío',
                    cancel: 'Cancelar',
                },
            }
            : { service: key };

        let credentials: any;
        try {
            credentials = await Keychain.getGenericPassword(options);
        } catch (error: any) {
            throw new SecureStorageReadError(key, error);
        }

        // react-native-keychain returns exactly `false` when the item is
        // genuinely absent. That is the ONLY shape that may read as null.
        //
        // A looser falsy check (`!credentials || !credentials.password`) also
        // swallowed null, undefined, and a credentials object holding an empty
        // password — none of which are proof of absence, and all of which would
        // let the caller generate a replacement over a funded wallet.
        if (credentials === false) return null;

        if (!credentials || typeof credentials.password !== 'string' || credentials.password.length === 0) {
            throw new SecureStorageReadError(
                key,
                new Error(`unexpected credentials shape (${typeof credentials}); refusing to treat as absent`)
            );
        }

        return decodeStoredSecret(credentials.password, key);
    }

    async deleteSecret(key: string): Promise<void> {
        if (Platform.OS === 'ios') {
            await Keychain.resetGenericPassword({ service: key, synchronizable: true });
        } else {
            await Keychain.resetGenericPassword({ service: key });
        }
    }
}

export const credentialStorage = new CredentialStorageService();
