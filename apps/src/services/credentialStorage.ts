import { Platform } from 'react-native';
import * as Keychain from 'react-native-keychain';
import { bytesToBase64, base64ToBytes } from '../utils/encoding';

/**
 * Interface for platform-agnostic secure storage with cloud sync capabilities.
 */
export interface SecureStorageInterface {
    storeSecret(key: string, secret: Uint8Array): Promise<void>;
    retrieveSecret(key: string): Promise<Uint8Array | null>;
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
                    return base64ToBytes(credentials.password);
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
                    return base64ToBytes(credentials.password);
                }
                return null;
            } catch (error) {

                return null;
            }
        }
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
