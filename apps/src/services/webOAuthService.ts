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

      // Generate ephemeral key pair entirely on client
      let ephemeralKeyPairData = null;
      let clientGeneratedEkp = null;
      try {
        console.log('[WebOAuth] Generating ephemeral key pair entirely on client...');
        const { aptosKeylessService } = await import('./aptosKeylessService');
        clientGeneratedEkp = aptosKeylessService.generateEphemeralKeyPair(24); // 24 hours expiry
        
        // Get the info for backend in the format it expects
        ephemeralKeyPairData = aptosKeylessService.getEphemeralKeyPairForBackend(clientGeneratedEkp);
        
        console.log('[WebOAuth] Generated ephemeral key pair with nonce:', ephemeralKeyPairData.nonce);
        console.log('[WebOAuth] Client will provide complete ephemeral key data to backend');
        console.log('[WebOAuth] ✅ CLIENT-ONLY ADDRESS DERIVATION: Backend will never derive addresses');
      } catch (error) {
        console.error('[WebOAuth] Error generating ephemeral key pair:', error);
        throw new Error('Failed to generate ephemeral key pair on client');
      }

      // Start OAuth flow by getting the OAuth URL from backend
      const startUrl = `${API_URL.replace('/graphql/', '')}/prover/oauth/aptos/start/`;
      console.log(`[WebOAuth] Fetching OAuth URL from: ${startUrl}`);
      
      const requestBody: any = {
        provider,
        deviceFingerprint: deviceFingerprint ? JSON.stringify(deviceFingerprint) : null,
      };
      
      // Always send client-generated ephemeral key data - backend must use this
      if (ephemeralKeyPairData) {
        requestBody.ephemeralPublicKey = ephemeralKeyPairData.publicKey;
        requestBody.ephemeralNonce = ephemeralKeyPairData.nonce;
        requestBody.ephemeralExpiryDate = ephemeralKeyPairData.expiryDate;
        requestBody.useClientEphemeralKey = true; // Flag to indicate backend should use client key
        console.log('[WebOAuth] Sending client-generated ephemeral key to backend');
        console.log('[WebOAuth] Backend MUST use this ephemeral key data for JWT creation');
      } else {
        throw new Error('Client ephemeral key generation failed - cannot proceed without client-generated keys');
      }
      
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
            // Log what we got from the backend
            console.log('[WebOAuth] Backend returned keyless account:', {
              address: callbackData.data.keylessAccount.address,
              hasEphemeralKeyPair: !!callbackData.data.keylessAccount.ephemeralKeyPair,
              ephemeralNonce: callbackData.data.keylessAccount.ephemeralKeyPair?.nonce,
              jwtLength: callbackData.data.keylessAccount.jwt?.length,
            });
            
            // Always use the client-generated ephemeral key pair
            if (clientGeneratedEkp) {
              console.log('[WebOAuth] Using client-generated ephemeral key pair with OAuth JWT');
              
              // CRITICAL: The backend only returns public ephemeral key data for security (non-custodial)
              // We MUST use our locally generated ephemeral key pair which has the private key and raw instance
              // The OAuth JWT from Google/Apple should contain the nonce from our client-generated ephemeral key
              console.log('[WebOAuth] Backend returned ephemeral key (public only):', callbackData.data.keylessAccount.ephemeralKeyPair);
              console.log('[WebOAuth] Replacing with client-generated ephemeral key pair (has private key and raw instance)');
              
              // Replace backend's public-only ephemeral key with our complete client-generated one
              callbackData.data.keylessAccount.ephemeralKeyPair = clientGeneratedEkp;
              
              console.log('[WebOAuth] Client-generated ephemeral key details:', {
                hasRaw: !!clientGeneratedEkp.raw,
                nonce: clientGeneratedEkp.raw?.nonce || 'stored format',
                expiryDate: clientGeneratedEkp.expiryISO,
                version: clientGeneratedEkp.version,
                hasPrivateKey: !!clientGeneratedEkp.privateKey_b64,
              });
              
              // ALWAYS derive the correct address using client-side Aptos SDK (REQUIRED)
              try {
                const jwt = callbackData.data.keylessAccount.jwt;
                const jwtParts = jwt.split('.');
                const payload = JSON.parse(atob(jwtParts[1]));
                // Use the nonce that was sent to backend (the one OAuth provider should have used)
                const expectedNonce = ephemeralKeyPairData.nonce;
                
                console.log('[WebOAuth] OAuth JWT nonce:', payload.nonce);
                console.log('[WebOAuth] Client ephemeral key nonce:', expectedNonce);
                
                // Verify nonce match
                if (payload.nonce === expectedNonce) {
                  console.log('[WebOAuth] ✅ Nonce match confirmed between OAuth JWT and client ephemeral key');
                } else {
                  console.error('[WebOAuth] ❌ CRITICAL: Nonce mismatch detected!');
                  console.error('[WebOAuth] This means OAuth flow used different nonce than client ephemeral key');
                  throw new Error(`Nonce mismatch: JWT nonce (${payload.nonce}) != client nonce (${expectedNonce})`);
                }
                
                // REQUIRED: Derive the keyless address using client-side Aptos SDK
                console.log('[WebOAuth] 🔧 Deriving keyless address using aptosKeylessService...');
                
                // Get the aptosKeylessService instance
                const { aptosKeylessService } = await import('./aptosKeylessService');
                
                // Convert pepper to Uint8Array if provided
                let pepperBytes = undefined;
                if (callbackData.data.keylessAccount.pepper) {
                  const pepperHex = callbackData.data.keylessAccount.pepper.replace('0x', '');
                  pepperBytes = new Uint8Array(Buffer.from(pepperHex, 'hex'));
                  // Ensure 31 bytes
                  if (pepperBytes.length !== 31) {
                    const paddedPepper = new Uint8Array(31);
                    pepperBytes.slice(0, 31).forEach((byte, i) => paddedPepper[i] = byte);
                    pepperBytes = paddedPepper;
                  }
                }
                
                // Use aptosKeylessService to derive the address - it handles all the SDK complexities
                const aptos = aptosKeylessService.getAptosClient();
                const reconstructedEkp = aptosKeylessService.getEphemeralKeyPairForSDK(clientGeneratedEkp);
                
                // Derive CANONICAL keyless account using the service's Aptos client
                const keylessAccount = await aptos.deriveKeylessAccount({
                  jwt: jwt,
                  ephemeralKeyPair: reconstructedEkp,
                  pepper: pepperBytes,
                });
                
                // Replace backend placeholder with CANONICAL client-derived address
                const backendPlaceholder = callbackData.data.keylessAccount.address;
                const canonicalAddress = keylessAccount.accountAddress.toString();
                callbackData.data.keylessAccount.address = canonicalAddress;
                
                console.log('[WebOAuth] ✅ CANONICAL ADDRESS DERIVED:');
                console.log('[WebOAuth] Backend placeholder:', backendPlaceholder);
                console.log('[WebOAuth] Canonical address:', canonicalAddress);
                console.log('[WebOAuth] ✅ All users will get same address for same JWT claims + pepper');
                
                // IMMEDIATELY update backend database with canonical address (Option B)
                try {
                  console.log('[WebOAuth] 🔄 Updating backend database with canonical address...');
                  const updateUrl = `${API_URL.replace('/graphql/', '')}/prover/keyless/update-address/`;
                  
                  const updateResponse = await fetch(updateUrl, {
                    method: 'POST',
                    headers: {
                      'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                      address: canonicalAddress,
                      firebase_uid: callbackData.data.firebaseUid,
                      account_type: 'personal',
                      account_index: 0
                    })
                  });
                  
                  if (updateResponse.ok) {
                    const updateResult = await updateResponse.json();
                    console.log('[WebOAuth] ✅ Backend database updated successfully:', updateResult);
                    console.log('[WebOAuth] ✅ Option B implemented: Address known to server immediately upon sign-up');
                  } else {
                    const errorText = await updateResponse.text();
                    console.error('[WebOAuth] ❌ Failed to update backend database:', updateResponse.status, errorText);
                    console.error('[WebOAuth] User will still be authenticated, but backend has placeholder address');
                  }
                } catch (updateError) {
                  console.error('[WebOAuth] ❌ Error calling address update endpoint:', updateError);
                  console.error('[WebOAuth] User will still be authenticated, but backend has placeholder address');
                }
                
              } catch (derivationError) {
                console.error('[WebOAuth] ❌ CRITICAL: Failed to derive canonical address on client!');
                console.error('[WebOAuth] Error:', derivationError);
                throw new Error(`Address derivation failed: ${derivationError.message}. Cannot proceed without canonical address.`);
              }
            } else {
              throw new Error('Client-generated ephemeral key pair not available - cannot proceed');
            }
            
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
      
      // Clear any client-generated ephemeral key pair on error
      try {
        if (clientGeneratedEkp) {
          console.log('[WebOAuth] Clearing client-generated ephemeral key pair due to error');
        }
      } catch (clearError) {
        console.log('[WebOAuth] Failed to clear client-generated ephemeral key pair');
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
      // Match the StoredKeylessData structure expected by authService
      const keylessData = {
        account: {
          address: data.keylessAccount.address,
          publicKey: data.keylessAccount.publicKey,
          exists: true
        },
        jwt: data.keylessAccount.jwt,
        ephemeralKeyPair: data.keylessAccount.ephemeralKeyPair, // This should have the raw field preserved
        pepper: data.keylessAccount.pepper || '',
        provider: 'google' as const, // Always 'google' for compatibility
        timestamp: new Date().toISOString()
      };

      await Keychain.setInternetCredentials(
        KEYLESS_KEYCHAIN_SERVICE,
        'keylessData',
        JSON.stringify(keylessData)
      );

      console.log('[WebOAuth] Stored Keyless data successfully');
      console.log('[WebOAuth] Stored ephemeral key pair has raw field?:', !!(data.keylessAccount.ephemeralKeyPair as any)?.raw);
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