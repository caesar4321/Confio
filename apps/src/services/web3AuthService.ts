import Web3Auth from '@web3auth/single-factor-auth';
import { CHAIN_NAMESPACES, WEB3AUTH_NETWORK } from '@web3auth/base';
import * as Keychain from 'react-native-keychain';
import { WEB3AUTH_CONFIG } from '../config/web3auth';

export interface Web3AuthUser {
  email?: string;
  name?: string;
  profileImage?: string;
  aggregateVerifier?: string;
  verifier?: string;
  verifierId?: string;
  typeOfLogin?: string;
  dappShare?: string;
  idToken?: string;
  oAuthIdToken?: string;
  oAuthAccessToken?: string;
  privateKey?: string;
}

export interface Web3AuthSession {
  user: Web3AuthUser;
  privateKey: string;
  ed25519PrivKey?: string;
  sessionId?: string;
}

const KEYCHAIN_SERVICE = 'com.confio.web3auth';
const KEYCHAIN_USERNAME = 'web3auth_session';

export class Web3AuthService {
  private static instance: Web3AuthService;
  private web3auth: Web3Auth | null = null;
  private isInitialized = false;
  private currentSession: Web3AuthSession | null = null;

  private constructor() {}

  public static getInstance(): Web3AuthService {
    if (!Web3AuthService.instance) {
      Web3AuthService.instance = new Web3AuthService();
    }
    return Web3AuthService.instance;
  }

  public async initialize(): Promise<void> {
    if (this.isInitialized) {
      console.log('Web3Auth already initialized');
      return;
    }

    try {
      // Validate config exists
      if (!WEB3AUTH_CONFIG || !WEB3AUTH_CONFIG.clientId) {
        throw new Error('Web3Auth configuration is missing or invalid. ClientId is required.');
      }

      console.log('Web3Auth SFA - Initializing with config:', {
        clientId: WEB3AUTH_CONFIG.clientId ? WEB3AUTH_CONFIG.clientId.substring(0, 20) + '...' : 'undefined',
        network: WEB3AUTH_CONFIG.network,
      });
      
      // Initialize Web3Auth Single Factor Auth instance
      this.web3auth = new Web3Auth({
        clientId: WEB3AUTH_CONFIG.clientId,
        web3AuthNetwork: 'sapphire_devnet' as WEB3AUTH_NETWORK, // Using devnet for testing
        chainConfig: {
          chainNamespace: CHAIN_NAMESPACES.OTHER, // Use OTHER for Algorand
          chainId: '0x1', // Dummy chain ID for Algorand
          rpcTarget: WEB3AUTH_CONFIG.algorand.rpcUrl,
        },
        usePnPKey: false, // Single Factor Auth doesn't use PnP key
      });

      console.log('Web3Auth SFA - Calling init()...');
      // Initialize the SDK
      await this.web3auth.init();
      
      this.isInitialized = true;
      console.log('Web3Auth SFA - Initialized successfully');
      
      // Try to restore previous session
      await this.restoreSession();
    } catch (error) {
      console.error('Failed to initialize Web3Auth SFA:', error);
      throw error;
    }
  }

  public async login(provider: 'google' | 'apple', idToken?: string): Promise<Web3AuthSession> {
    try {
      if (!this.web3auth) {
        throw new Error('Web3Auth not initialized');
      }

      console.log(`Web3Auth SFA - Starting login with ${provider}...`);
      
      // For Single Factor Auth, we need to use the verifier and verifierId
      // The verifier should be configured in the Web3Auth dashboard
      let verifier = provider === 'google' ? 'google-auth-confio' : 'apple-sfa'; // Use your Auth Connection ID from Web3Auth Dashboard
      let verifierId = '';
      
      // Extract verifierId from the ID token if available
      if (idToken) {
        try {
          // Decode the ID token to get the user's email or sub
          const base64Url = idToken.split('.')[1];
          const base64 = base64Url.replace(/-/g, '+').replace(/_/g, '/');
          const jsonPayload = decodeURIComponent(atob(base64).split('').map(function(c) {
            return '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2);
          }).join(''));
          
          const payload = JSON.parse(jsonPayload);
          verifierId = payload.email || payload.sub || '';
          console.log('Web3Auth SFA - Extracted verifierId:', verifierId);
        } catch (error) {
          console.error('Web3Auth SFA - Failed to decode ID token:', error);
        }
      }
      
      if (!verifierId) {
        // If we don't have an ID token, we need to get the verifierId another way
        // For now, we'll need the user to be authenticated first
        console.log('Web3Auth SFA - No verifierId available, attempting to get from current auth');
        
        // Try to get email from Firebase auth
        const auth = (await import('@react-native-firebase/auth')).default();
        const currentUser = auth.currentUser;
        if (currentUser?.email) {
          verifierId = currentUser.email;
          console.log('Web3Auth SFA - Using Firebase email as verifierId:', verifierId);
        } else if (currentUser?.uid) {
          verifierId = currentUser.uid;
          console.log('Web3Auth SFA - Using Firebase UID as verifierId:', verifierId);
        }
      }
      
      if (!verifierId) {
        throw new Error('Unable to determine verifierId for Web3Auth login');
      }

      console.log(`Web3Auth SFA - Connecting with verifier: ${verifier}, verifierId: ${verifierId}`);

      // Perform Single Factor Auth login
      // For SFA, we should NOT trigger any OAuth flow - it should be invisible
      let provider_response;
      try {
        // Check if we can get the private key without OAuth flow
        // This requires the verifier to be properly configured in Web3Auth Dashboard
        if (!idToken) {
          console.warn('Web3Auth SFA - No ID token available, cannot proceed with invisible auth');
          throw new Error('ID token required for Single Factor Auth. Please ensure OAuth tokens are captured during login.');
        }
        
        provider_response = await this.web3auth.connect({
          verifier,
          verifierId,
          idToken: idToken,
        });
        console.log('Web3Auth SFA - Connection response received:', !!provider_response);
      } catch (loginError: any) {
        console.error('Web3Auth SFA - Connection failed:', loginError.message || loginError);
        
        // Check if it's a verifier error
        if (loginError.message?.includes('verifier')) {
          throw new Error(`Web3Auth verifier '${verifier}' not configured. Please ensure it is set up in Web3Auth dashboard.`);
        }
        throw loginError;
      }
      
      if (!provider_response) {
        throw new Error('Login failed - no provider response returned');
      }

      // Get private key from the provider
      const privateKey = provider_response;
      if (!privateKey) {
        throw new Error('Failed to retrieve private key');
      }

      // For Algorand, we need the ED25519 key
      // SFA returns a secp256k1 key by default, we'll need to derive ED25519
      // For now, we'll use the private key as-is and handle conversion in algorandWalletService
      
      // Get user info
      const userInfo = await this.web3auth.getUserInfo();

      // Create session object
      const session: Web3AuthSession = {
        user: {
          email: userInfo?.email,
          name: userInfo?.name,
          profileImage: userInfo?.profileImage,
          verifier: verifier,
          verifierId: verifierId,
          typeOfLogin: provider,
        },
        privateKey,
        ed25519PrivKey: privateKey, // Will be converted in algorandWalletService
        sessionId: undefined, // SFA doesn't provide sessionId
      };

      // Store session
      await this.storeSession(session);
      this.currentSession = session;

      console.log('Web3Auth SFA login successful');
      return session;
    } catch (error) {
      console.error('Web3Auth SFA login error:', error);
      throw error;
    }
  }

  public async logout(): Promise<void> {
    try {
      if (!this.web3auth) {
        console.log('Web3Auth not initialized, skipping logout');
        return;
      }

      console.log('Logging out from Web3Auth SFA...');
      
      // Logout from Web3Auth
      await this.web3auth.logout();
      
      // Clear stored session
      await this.clearSession();
      this.currentSession = null;
      
      console.log('Web3Auth SFA logout successful');
    } catch (error) {
      console.error('Web3Auth SFA logout error:', error);
      // Continue with cleanup even if logout fails
      await this.clearSession();
      this.currentSession = null;
    }
  }

  public async getPrivateKey(): Promise<string | null> {
    try {
      if (!this.web3auth) {
        throw new Error('Web3Auth not initialized');
      }

      // In SFA, the private key is returned from connect()
      // If we have a current session, return the stored key
      if (this.currentSession?.privateKey) {
        return this.currentSession.privateKey;
      }

      // Try to get from the provider
      const provider = this.web3auth.provider;
      if (provider) {
        // The provider itself is the private key in SFA
        return provider as string;
      }

      return null;
    } catch (error) {
      console.error('Error getting private key:', error);
      return null;
    }
  }

  public async getEd25519PrivateKey(): Promise<string | null> {
    try {
      // For SFA, we need to derive ED25519 from the secp256k1 key
      // This will be handled in algorandWalletService
      return this.getPrivateKey();
    } catch (error) {
      console.error('Error getting ED25519 private key:', error);
      return null;
    }
  }

  public async getUserInfo(): Promise<Web3AuthUser | null> {
    try {
      if (!this.web3auth) {
        throw new Error('Web3Auth not initialized');
      }

      const userInfo = await this.web3auth.getUserInfo();
      return userInfo as Web3AuthUser;
    } catch (error) {
      console.error('Error getting user info:', error);
      return null;
    }
  }

  public isLoggedIn(): boolean {
    return this.currentSession !== null;
  }

  public getCurrentSession(): Web3AuthSession | null {
    return this.currentSession;
  }

  private async storeSession(session: Web3AuthSession): Promise<void> {
    try {
      await Keychain.setInternetCredentials(
        KEYCHAIN_SERVICE,
        KEYCHAIN_USERNAME,
        JSON.stringify(session)
      );
      console.log('Web3Auth session stored successfully');
    } catch (error) {
      console.error('Error storing Web3Auth session:', error);
    }
  }

  private async restoreSession(): Promise<void> {
    try {
      const credentials = await Keychain.getInternetCredentials(KEYCHAIN_SERVICE);
      
      if (credentials && credentials.password) {
        const session: Web3AuthSession = JSON.parse(credentials.password);
        
        // For SFA, we can't easily verify if session is still valid without reconnecting
        // Just restore the session and let it fail on next operation if invalid
        this.currentSession = session;
        console.log('Web3Auth session restored from storage');
      }
    } catch (error) {
      console.error('Error restoring Web3Auth session:', error);
      await this.clearSession();
    }
  }

  private async clearSession(): Promise<void> {
    try {
      await Keychain.resetInternetCredentials(KEYCHAIN_SERVICE);
      console.log('Web3Auth session cleared');
    } catch (error) {
      console.error('Error clearing Web3Auth session:', error);
    }
  }

  // Helper method to integrate with existing auth flow
  public async migrateFromFirebase(firebaseUser: any): Promise<Web3AuthSession> {
    try {
      // Determine provider based on Firebase user
      let provider: 'google' | 'apple' = 'google';
      
      if (firebaseUser.providerData) {
        const providerData = firebaseUser.providerData[0];
        if (providerData.providerId === 'apple.com') {
          provider = 'apple';
        }
      }
      
      // Login with Web3Auth using the same provider
      const session = await this.login(provider);
      
      // You might want to sync additional user data here
      console.log('Successfully migrated user from Firebase to Web3Auth');
      
      return session;
    } catch (error) {
      console.error('Error migrating from Firebase:', error);
      throw error;
    }
  }
}

// Export singleton instance
export const web3AuthService = Web3AuthService.getInstance();