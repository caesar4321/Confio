import { Platform } from 'react-native';
import * as Keychain from 'react-native-keychain';
import { save as blockStoreSave, retrieve as blockStoreRetrieve, remove as blockStoreRemove } from 'react-native-block-store';
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
            // Android: Use BlockStore API (GMS) via react-native-block-store
            try {
                // Library stores strings as bytes (UTF-8). We pass our Base64 string.
                // We enable 'shouldBackupToCloud' explicitly.
                const result = await blockStoreSave(key, base64Secret, true);
                if (result) {
                    console.log('[CredentialStorage] Stored secret to BlockStore (Cloud Backup: true)');
                } else {
                    throw new Error('BlockStore save returned false');
                }
            } catch (error) {
                console.error('[CredentialStorage] Failed to store to BlockStore:', error);
                throw new Error('BlockStore storage failed');
            }
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
                console.warn('[CredentialStorage] Keychain retrieve failed:', error);
                return null;
            }
        } else {
            try {
                // Android BlockStore
                // Library returns the string we stored (our Base64 string)
                const val = await blockStoreRetrieve(key);
                if (val) {
                    try {
                        return base64ToBytes(val);
                    } catch (e) {
                        console.warn('[CredentialStorage] Retrieved value is not valid base64, returning raw bytes if possible or null', e);
                        // Fallback? If it returns raw bytes as string?
                        // For now assume it returns exact string we saved.
                        return null;
                    }
                }
                return null;
            } catch (error) {
                console.warn('[CredentialStorage] BlockStore retrieve failed or empty:', error);
                return null;
            }
        }
    }

    async deleteSecret(key: string): Promise<void> {
        if (Platform.OS === 'ios') {
            await Keychain.resetGenericPassword({ service: key, synchronizable: true });
        } else {
            await blockStoreRemove(key);
        }
    }
}

export const credentialStorage = new CredentialStorageService();
