/**
 * Secure storage service for OAuth subject
 * 
 * The OAuth subject is a non-secret user identifier from Google/Apple.
 * We store it securely to enable lazy generation of Algorand addresses
 * for different accounts without requiring re-authentication.
 * 
 * Security model:
 * - OAuth subject alone cannot derive private keys
 * - Requires server pepper (fetched per session) + salt to derive keys
 * - Stored with maximum keychain security + optional app-level encryption
 */

import * as Keychain from 'react-native-keychain';
import CryptoJS from 'crypto-js';
import DeviceInfo from 'react-native-device-info';

const OAUTH_KEYCHAIN_SERVICE = 'oauth.confio.app';
const OAUTH_SUBJECT_KEY = 'oauth_subject';
const OAUTH_PROVIDER_KEY = 'oauth_provider';

export interface StoredOAuthData {
  subject: string;
  provider: 'google' | 'apple';
  timestamp: number;
}

class OAuthStorageService {
  /**
   * Generate a device-specific encryption key
   * This adds an extra layer of protection even if keychain is compromised
   */
  private getDeviceKey(): string {
    // Combine multiple device identifiers for the encryption key
    const deviceId = DeviceInfo.getUniqueId();
    const bundleId = DeviceInfo.getBundleId();
    const deviceName = DeviceInfo.getDeviceName();
    
    // Create a deterministic but device-specific key
    return CryptoJS.SHA256(`${deviceId}-${bundleId}-${deviceName}-confio-oauth`).toString();
  }

  /**
   * Store OAuth subject securely
   * 
   * @param oauthSubject - The OAuth subject from Google/Apple
   * @param provider - The OAuth provider (google or apple)
   */
  async storeOAuthSubject(
    oauthSubject: string,
    provider: 'google' | 'apple'
  ): Promise<void> {
    try {
      // Create the data object
      const data: StoredOAuthData = {
        subject: oauthSubject,
        provider: provider,
        timestamp: Date.now()
      };

      // Add app-level encryption
      const deviceKey = this.getDeviceKey();
      const encryptedData = CryptoJS.AES.encrypt(
        JSON.stringify(data),
        deviceKey
      ).toString();

      // Store in keychain with maximum security
      await Keychain.setInternetCredentials(
        OAUTH_KEYCHAIN_SERVICE,
        OAUTH_SUBJECT_KEY,
        encryptedData,
        {
          accessible: Keychain.ACCESSIBLE.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
          // Note: authenticatePrompt would require biometric every time
          // which might be too frequent for address generation
        }
      );

      console.log('OAuthStorage - Stored OAuth subject securely');
    } catch (error) {
      console.error('OAuthStorage - Error storing OAuth subject:', error);
      throw error;
    }
  }

  /**
   * Retrieve OAuth subject
   * 
   * @returns The decrypted OAuth data or null if not found
   */
  async getOAuthSubject(): Promise<StoredOAuthData | null> {
    try {
      const credentials = await Keychain.getInternetCredentials(
        OAUTH_KEYCHAIN_SERVICE
      );

      if (!credentials || !credentials.password) {
        console.log('OAuthStorage - No stored OAuth subject found');
        return null;
      }

      // Decrypt the data
      const deviceKey = this.getDeviceKey();
      const decryptedBytes = CryptoJS.AES.decrypt(credentials.password, deviceKey);
      const decryptedData = decryptedBytes.toString(CryptoJS.enc.Utf8);
      
      if (!decryptedData) {
        console.error('OAuthStorage - Failed to decrypt OAuth subject');
        return null;
      }

      const data: StoredOAuthData = JSON.parse(decryptedData);
      
      // Validate the data
      if (!data.subject || !data.provider) {
        console.error('OAuthStorage - Invalid OAuth data structure');
        return null;
      }

      console.log('OAuthStorage - Retrieved OAuth subject successfully');
      return data;
    } catch (error) {
      console.error('OAuthStorage - Error retrieving OAuth subject:', error);
      return null;
    }
  }

  /**
   * Clear stored OAuth subject (used during sign out)
   */
  async clearOAuthSubject(): Promise<void> {
    try {
      await Keychain.resetInternetCredentials({ server: OAUTH_KEYCHAIN_SERVICE });
      console.log('OAuthStorage - Cleared OAuth subject');
    } catch (error) {
      console.error('OAuthStorage - Error clearing OAuth subject:', error);
      // Don't throw - this is part of cleanup
    }
  }

  /**
   * Check if OAuth subject is stored
   */
  async hasOAuthSubject(): Promise<boolean> {
    try {
      const data = await this.getOAuthSubject();
      return data !== null;
    } catch {
      return false;
    }
  }
}

export const oauthStorage = new OAuthStorageService();
