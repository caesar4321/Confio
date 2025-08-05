import { Linking, Platform } from 'react-native';
import InAppBrowser from 'react-native-inappbrowser-reborn';
import { API_URL } from '../config/env';
import * as Keychain from 'react-native-keychain';
import { KEYLESS_KEYCHAIN_SERVICE, AUTH_KEYCHAIN_SERVICE } from './authService';

export const FIREBASE_KEYCHAIN_SERVICE = 'com.confio.firebase';

interface WebOAuthResult {
  keylessAccount: {
    address: string;
    publicKey: string;
    jwt: string;
    ephemeralKeyPair: any;
    pepper?: string;
  };
  backendToken: string;
  accessToken?: string;
  refreshToken?: string;
  userId: number;
  firebaseToken?: string;
  firebaseUid?: string;
  isPhoneVerified: boolean;
}

export class WebOAuthService {
  private static instance: WebOAuthService;

  private constructor() {}

  public static getInstance(): WebOAuthService {
    if (!WebOAuthService.instance) {
      WebOAuthService.instance = new WebOAuthService();
    }
    return WebOAuthService.instance;
  }

  /**
   * Ensure any open in-app browser is closed
   */
  public async ensureBrowserClosed(): Promise<void> {
    try {
      await InAppBrowser.close();
      console.log('[WebOAuth] Ensured browser is closed');
    } catch (error) {
      // Silent fail - no browser was open
    }
  }

  async signInWithProvider(provider: 'google' | 'apple'): Promise<WebOAuthResult> {
    try {
      console.log(`[WebOAuth] Starting ${provider} sign-in flow`);

      // Close any existing in-app browser first
      try {
        console.log('[WebOAuth] Checking for existing in-app browser...');
        await InAppBrowser.close();
        console.log('[WebOAuth] Closed existing in-app browser');
      } catch (closeError) {
        // It's okay if there's no browser to close
        console.log('[WebOAuth] No existing browser to close');
      }

      // Collect device fingerprint
      let deviceFingerprint = null;
      try {
        const { DeviceFingerprint } = await import('../utils/deviceFingerprint');
        deviceFingerprint = await DeviceFingerprint.generateFingerprint();
        console.log('[WebOAuth] Device fingerprint collected successfully');
      } catch (error) {
        console.error('[WebOAuth] Error collecting device fingerprint:', error);
        // Continue without fingerprint rather than failing authentication
      }

      // Start OAuth flow by getting the OAuth URL from backend
      const startUrl = `${API_URL.replace('/graphql/', '')}/prover/oauth/aptos/start/`;
      console.log(`[WebOAuth] Fetching OAuth URL from: ${startUrl}`);
      
      const requestBody = {
        provider,
        deviceFingerprint: deviceFingerprint ? JSON.stringify(deviceFingerprint) : null
      };
      
      const response = await fetch(startUrl, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(requestBody)
      });
      
      if (!response.ok) {
        const text = await response.text();
        console.error(`[WebOAuth] OAuth endpoint returned ${response.status}: ${text}`);
        throw new Error(`OAuth endpoint returned ${response.status}`);
      }
      
      const data = await response.json();

      if (!data.oauth_url) {
        throw new Error('Failed to get OAuth URL from backend');
      }

      console.log(`[WebOAuth] Opening OAuth URL in browser`);

      // Add a small delay to ensure the previous browser is fully closed
      await new Promise(resolve => setTimeout(resolve, 100));

      // Open OAuth URL in in-app browser
      if (await InAppBrowser.isAvailable()) {
        const result = await InAppBrowser.openAuth(data.oauth_url, 'confio://oauth-callback', {
          // iOS options
          ephemeralWebSession: false,
          preferredBarTintColor: '#72D9BC',
          preferredControlTintColor: 'white',
          readerMode: false,
          animated: true,
          modalPresentationStyle: 'fullScreen',
          modalTransitionStyle: 'coverVertical',
          modalEnabled: true,
          enableBarCollapsing: false,
          // iOS specific - ensure it stays in app
          dismissButtonStyle: 'close',
          preferredModalPresentationStyle: 'overFullScreen',
          // Android options
          showTitle: true,
          toolbarColor: '#72D9BC',
          secondaryToolbarColor: 'black',
          navigationBarColor: 'black',
          navigationBarDividerColor: 'white',
          enableUrlBarHiding: true,
          enableDefaultShare: false,
          forceCloseOnRedirection: true, // Changed to true to force close on redirect
        });

        if (result.type === 'success' && result.url) {
          console.log('[WebOAuth] OAuth callback received');
          
          // Parse the result from the callback URL
          const callbackData = this.parseCallbackUrl(result.url);
          
          if (callbackData.success && callbackData.data) {
            // Store the keyless account data
            await this.storeKeylessData(callbackData.data);
            
            // Store the backend auth tokens
            await this.storeAuthTokens({
              accessToken: callbackData.data.accessToken || callbackData.data.backendToken,
              refreshToken: callbackData.data.refreshToken || callbackData.data.backendToken
            });

            // Store Firebase credentials if available
            if (callbackData.data.firebaseToken && callbackData.data.firebaseUid) {
              await this.storeFirebaseCredentials({
                token: callbackData.data.firebaseToken,
                uid: callbackData.data.firebaseUid
              });
            }

            return callbackData.data;
          } else {
            throw new Error(callbackData.error || 'OAuth flow failed');
          }
        } else if (result.type === 'cancel') {
          console.log('[WebOAuth] OAuth flow was cancelled by user');
          throw new Error('Authentication cancelled');
        } else {
          console.log('[WebOAuth] OAuth flow failed with result:', result);
          throw new Error('OAuth flow failed');
        }
      } else {
        // Fallback to external browser
        await Linking.openURL(data.oauth_url);
        throw new Error('Please complete authentication in your browser');
      }
    } catch (error) {
      console.error(`[WebOAuth] Error during ${provider} sign-in:`, error);
      
      // Try to close the browser on error
      try {
        await InAppBrowser.close();
        console.log('[WebOAuth] Closed browser after error');
      } catch (closeError) {
        console.log('[WebOAuth] Failed to close browser after error');
      }
      
      throw error;
    }
  }

  private parseCallbackUrl(url: string): { success: boolean; data?: WebOAuthResult; error?: string } {
    try {
      console.log('[WebOAuth] Parsing callback URL:', url);
      
      // Extract query string manually (React Native doesn't have full URL API)
      const queryStart = url.indexOf('?');
      if (queryStart === -1) {
        return {
          success: false,
          error: 'No query parameters in callback URL'
        };
      }
      
      const queryString = url.substring(queryStart + 1);
      const params: { [key: string]: string } = {};
      
      // Parse query parameters manually
      queryString.split('&').forEach(pair => {
        const [key, value] = pair.split('=');
        if (key && value) {
          // Replace + with space before decoding (handles Python urlencode format)
          params[key] = decodeURIComponent(value.replace(/\+/g, ' '));
        }
      });
      
      console.log('[WebOAuth] Parsed params:', Object.keys(params));
      
      const success = params.success === 'true';
      
      if (success) {
        const keylessAccountStr = params.keyless_account;
        const backendToken = params.backend_token;
        const accessToken = params.access_token || backendToken; // Use access_token if available
        const refreshToken = params.refresh_token || backendToken; // Fallback to backend_token
        const userId = params.user_id;
        const firebaseToken = params.firebase_token;
        const firebaseUid = params.firebase_uid;
        const isPhoneVerified = params.is_phone_verified === 'true';

        if (keylessAccountStr && backendToken && userId) {
          const keylessAccount = JSON.parse(keylessAccountStr);
          
          console.log('[WebOAuth] Successfully parsed authentication data');
          console.log('[WebOAuth] Firebase data:', { hasFirebaseToken: !!firebaseToken, firebaseUid });
          console.log('[WebOAuth] Phone verified:', isPhoneVerified);
          console.log('[WebOAuth] Tokens:', { hasAccessToken: !!accessToken, hasRefreshToken: !!refreshToken });
          
          return {
            success: true,
            data: {
              keylessAccount,
              backendToken,
              accessToken,
              refreshToken,
              userId: parseInt(userId, 10),
              firebaseToken,
              firebaseUid,
              isPhoneVerified
            }
          };
        } else {
          console.log('[WebOAuth] Missing required parameters:', { 
            hasKeylessAccount: !!keylessAccountStr, 
            hasBackendToken: !!backendToken, 
            hasUserId: !!userId 
          });
        }
      }
      
      const error = params.error;
      return {
        success: false,
        error: error || 'Unknown error'
      };
    } catch (error) {
      console.error('[WebOAuth] Error parsing callback URL:', error);
      return {
        success: false,
        error: 'Failed to parse authentication response'
      };
    }
  }

  private async storeKeylessData(data: WebOAuthResult): Promise<void> {
    try {
      const keylessData = {
        account: data.keylessAccount,
        provider: 'web',
        timestamp: new Date().toISOString()
      };

      await Keychain.setInternetCredentials(
        KEYLESS_KEYCHAIN_SERVICE,
        'keylessData',
        JSON.stringify(keylessData)
      );

      console.log('[WebOAuth] Stored Keyless data successfully');
    } catch (error) {
      console.error('[WebOAuth] Error storing Keyless data:', error);
      throw error;
    }
  }

  private async storeAuthTokens(tokens: { accessToken: string; refreshToken: string }): Promise<void> {
    try {
      await Keychain.setGenericPassword(
        'auth_tokens',
        JSON.stringify(tokens),
        {
          service: AUTH_KEYCHAIN_SERVICE,
          accessible: Keychain.ACCESSIBLE.WHEN_UNLOCKED
        }
      );
      console.log('[WebOAuth] Auth tokens stored successfully');
    } catch (error) {
      console.error('[WebOAuth] Error storing auth tokens:', error);
      throw error;
    }
  }

  private async storeFirebaseCredentials(credentials: { token: string; uid: string }): Promise<void> {
    try {
      await Keychain.setInternetCredentials(
        FIREBASE_KEYCHAIN_SERVICE,
        'firebaseCredentials',
        JSON.stringify(credentials)
      );

      console.log('[WebOAuth] Firebase credentials stored successfully:', {
        uid: credentials.uid,
        tokenLength: credentials.token.length
      });
    } catch (error) {
      console.error('[WebOAuth] Error storing Firebase credentials:', error);
      throw error;
    }
  }
}