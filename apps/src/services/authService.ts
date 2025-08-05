import { GoogleSignin, User } from '@react-native-google-signin/google-signin';
import { jwtDecode } from 'jwt-decode';
import * as Keychain from 'react-native-keychain';
import { GOOGLE_CLIENT_IDS, API_URL } from '../config/env';
import auth from '@react-native-firebase/auth';
import { Platform } from 'react-native';
import { apolloClient } from '../apollo/client';
import { AccountManager, AccountContext } from '../utils/accountManager';
import { generateKeylessPepper } from '../utils/aptosKeyless';

// Debug logging for environment variables
console.log('Environment variables loaded:');
console.log('GOOGLE_CLIENT_IDS:', GOOGLE_CLIENT_IDS);
console.log('API_URL:', API_URL);

// Type for storing JWT tokens
type TokenStorage = {
  accessToken: string;
  refreshToken: string;
};

// Type for decoded JWT payloads
type CustomJwtPayload = {
  type: string;
  [key: string]: any;
};

// Aptos Keyless Types
interface EphemeralKeyPair {
  privateKey: string;
  publicKey: string;
  expiryDate: string;
  nonce?: string;
  blinder?: string;
}

interface KeylessAccount {
  address: string;
  publicKey: string;
  jwt: string;
  ephemeralKeyPair: EphemeralKeyPair;
  pepper?: string;
}

interface StoredKeylessData {
  account: KeylessAccount;
  provider: 'google' | 'apple';
  timestamp: string;
  firebaseToken?: string;
  initRandomness?: string;
}

// Keychain services
export const KEYLESS_KEYCHAIN_SERVICE = 'com.confio.keyless';
export const AUTH_KEYCHAIN_SERVICE = 'com.confio.auth';
const KEYLESS_KEYCHAIN_USERNAME = 'keylessData';
export const AUTH_KEYCHAIN_USERNAME = 'auth_tokens';

export class AuthService {
  private static instance: AuthService;
  private currentAccount: KeylessAccount | null = null;
  private ephemeralKeyPair: EphemeralKeyPair | null = null;
  private auth = auth();
  private firebaseIsInitialized = false;
  private apolloClient: typeof apolloClient | null = null;
  private constructor() {}

  public static getInstance(): AuthService {
    if (!AuthService.instance) {
      AuthService.instance = new AuthService();
    }
    return AuthService.instance;
  }

  public async initialize(): Promise<void> {
    try {
      console.log('AuthService - initialize() called');
      
      // Only initialize Firebase once
      if (!this.firebaseIsInitialized) {
        console.log('AuthService - Initializing Firebase');
        await this.initializeFirebase();
        this.firebaseIsInitialized = true;
        console.log('AuthService - Firebase initialized');
      } else {
        console.log('AuthService - Firebase already initialized');
      }
      
      // Always rehydrate Keyless data
      console.log('AuthService - Rehydrating Keyless data');
      await this.rehydrateKeylessData();
      console.log('AuthService - Keyless data rehydrated');
      
      // Check if we need to initialize a default account
      console.log('AuthService - Checking for default account initialization');
      await this.initializeDefaultAccountIfNeeded();
      console.log('AuthService - Default account check completed');
    } catch (error) {
      console.error('AuthService - Failed to initialize:', error);
      throw error;
    }
  }

  private async initializeFirebase() {
    try {
      await this.configureGoogleSignIn();
    } catch (error) {
      console.error('Firebase initialization error:', error);
      throw error;
    }
  }

  private async configureGoogleSignIn() {
    try {
      const clientIds = GOOGLE_CLIENT_IDS[__DEV__ ? 'development' : 'production'];
      const config = {
        webClientId: clientIds.web,
        offlineAccess: true,
        scopes: ['profile', 'email']
      };

      await GoogleSignin.configure(config);
      console.log('Google Sign-In configuration successful');
    } catch (error) {
      console.error('Error configuring Google Sign-In:', error);
      throw error;
    }
  }


  // Derive Keyless account through Django GraphQL
  private async deriveKeylessAccount(
    jwt: string,
    ephemeralKeyPair: EphemeralKeyPair,
    accountContext?: AccountContext
  ): Promise<KeylessAccount> {
    try {
      console.log('[AuthService] Deriving Keyless account through GraphQL...');
      const { DERIVE_KEYLESS_ACCOUNT } = await import('../apollo/keylessMutations');
      
      // Decode JWT to get claims
      const decodedJwt = jwtDecode(jwt) as any;
      
      // Generate deterministic pepper based on account context
      const context = accountContext || { type: 'personal', index: 0 };
      const pepper = generateKeylessPepper(
        decodedJwt.iss,
        decodedJwt.sub,
        decodedJwt.aud,
        context.type,
        context.businessId || '',
        context.index
      );
      
      console.log('[AuthService] Using deterministic pepper for account:', context);
      console.log('[AuthService] Pepper:', pepper);
      
      // Clean the ephemeralKeyPair object to remove __typename
      const cleanEphemeralKeyPair = {
        privateKey: ephemeralKeyPair.privateKey,
        publicKey: ephemeralKeyPair.publicKey,
        expiryDate: ephemeralKeyPair.expiryDate,
        nonce: ephemeralKeyPair.nonce,
        blinder: ephemeralKeyPair.blinder
      };

      const { data } = await apolloClient.mutate({
        mutation: DERIVE_KEYLESS_ACCOUNT,
        variables: {
          jwt,
          ephemeralKeyPair: cleanEphemeralKeyPair,
          pepper
        }
      });

      if (!data?.deriveKeylessAccount?.success) {
        throw new Error(data?.deriveKeylessAccount?.error || 'Failed to derive Keyless account');
      }

      // Combine the JWT and ephemeral key pair with the account data
      return {
        ...data.deriveKeylessAccount.keylessAccount,
        jwt,
        ephemeralKeyPair,
        pepper
      };
    } catch (error) {
      console.error('[AuthService] Error deriving account:', error);
      throw error;
    }
  }

  async signInWithGoogle() {
    try {
      console.log('Starting Google Sign-In process...');
      
      // Use web-based OAuth for proper Aptos Keyless support
      try {
        const { WebOAuthService } = await import('./webOAuthService');
        const webOAuth = WebOAuthService.getInstance();
        
        console.log('Using web-based OAuth flow for Aptos Keyless compatibility');
        const result = await webOAuth.signInWithProvider('google');
        
        // Extract and store the account data
        this.currentAccount = result.keylessAccount;
        this.ephemeralKeyPair = result.keylessAccount.ephemeralKeyPair;
        
        // The backend token is already stored by WebOAuthService
        console.log('Web OAuth sign-in successful:', result.keylessAccount.address);
        
        // Sign in with Firebase if we have a Firebase token
        if (result.firebaseToken && result.firebaseUid) {
          console.log('Signing in with Firebase using custom token...');
          try {
            await this.auth.signInWithCustomToken(result.firebaseToken);
            console.log('Firebase sign-in successful with uid:', result.firebaseUid);
          } catch (firebaseError) {
            console.error('Firebase sign-in error:', firebaseError);
            // Continue without Firebase - don't break the flow
          }
        }
        
        // Get user info from the backend
        const { GET_ME } = await import('../apollo/queries');
        const { data } = await apolloClient.query({
          query: GET_ME,
          fetchPolicy: 'network-only'
        });
        
        // Use phone verification status from OAuth result instead of checking fields
        const isPhoneVerified = result.isPhoneVerified;
        
        // Create default personal account if needed
        console.log('Creating default personal account...');
        try {
          const accountManager = AccountManager.getInstance();
          const storedAccounts = await accountManager.getStoredAccounts();
          
          if (storedAccounts.length === 0) {
            console.log('No local accounts found, setting default personal account context');
            await accountManager.setActiveAccountContext({
              type: 'personal',
              index: 0
            });
            console.log('Set default personal account context (personal_0)');
          }
        } catch (accountError) {
          console.error('Error creating default account:', accountError);
        }
        
        return {
          userInfo: {
            email: data?.me?.email || '',
            firstName: data?.me?.firstName || '',
            lastName: data?.me?.lastName || '',
            photoURL: null
          },
          keylessData: {
            address: result.keylessAccount.address,
            publicKey: result.keylessAccount.publicKey,
            isPhoneVerified
          }
        };
      } catch (webOAuthError) {
        console.error('Web OAuth error:', webOAuthError);
        throw new Error('Authentication failed. Please try again.');
      }
    } catch (error) {
      console.error('Error signing in with Google:', error);
      throw error;
    }
  }

  // Apple Sign-In
  public async signInWithApple() {
    if (Platform.OS !== 'ios') {
      throw new Error('Apple Sign In is only supported on iOS');
    }

    try {
      console.log('Starting Apple Sign In...');
      
      // Use web-based OAuth for proper Aptos Keyless support
      try {
        const { WebOAuthService } = await import('./webOAuthService');
        const webOAuth = WebOAuthService.getInstance();
        
        console.log('Using web-based OAuth flow for Aptos Keyless compatibility');
        const result = await webOAuth.signInWithProvider('apple');
        
        // Extract and store the account data
        this.currentAccount = result.keylessAccount;
        this.ephemeralKeyPair = result.keylessAccount.ephemeralKeyPair;
        
        // The backend token is already stored by WebOAuthService
        console.log('Web OAuth sign-in successful:', result.keylessAccount.address);
        
        // Sign in with Firebase if we have a Firebase token
        if (result.firebaseToken && result.firebaseUid) {
          console.log('Signing in with Firebase using custom token...');
          try {
            await this.auth.signInWithCustomToken(result.firebaseToken);
            console.log('Firebase sign-in successful with uid:', result.firebaseUid);
          } catch (firebaseError) {
            console.error('Firebase sign-in error:', firebaseError);
            // Continue without Firebase - don't break the flow
          }
        }
        
        // Get user info from the backend
        const { GET_ME } = await import('../apollo/queries');
        const { data } = await apolloClient.query({
          query: GET_ME,
          fetchPolicy: 'network-only'
        });
        
        // Use phone verification status from OAuth result instead of checking fields
        const isPhoneVerified = result.isPhoneVerified;
        
        // Create default personal account if needed
        console.log('Creating default personal account...');
        try {
          const accountManager = AccountManager.getInstance();
          const storedAccounts = await accountManager.getStoredAccounts();
          
          if (storedAccounts.length === 0) {
            console.log('No local accounts found, setting default personal account context');
            await accountManager.setActiveAccountContext({
              type: 'personal',
              index: 0
            });
            console.log('Set default personal account context (personal_0)');
          }
        } catch (accountError) {
          console.error('Error creating default account:', accountError);
        }
        
        return {
          userInfo: {
            email: data?.me?.email || '',
            firstName: data?.me?.firstName || '',
            lastName: data?.me?.lastName || '',
            photoURL: null
          },
          keylessData: {
            address: result.keylessAccount.address,
            publicKey: result.keylessAccount.publicKey,
            isPhoneVerified
          }
        };
      } catch (webOAuthError) {
        console.error('Web OAuth error:', webOAuthError);
        throw new Error('Authentication failed. Please try again.');
      }
    } catch (error) {
      console.error('Apple Sign In Error:', error);
      throw error;
    }
  }

  // Store Keyless data securely
  private async storeKeylessData(
    account: KeylessAccount, 
    provider: 'google' | 'apple',
    firebaseToken?: string
  ): Promise<void> {
    try {
      const dataToStore: StoredKeylessData = {
        account,
        provider,
        timestamp: new Date().toISOString(),
        firebaseToken
      };

      // Store in Keychain for security
      await Keychain.setInternetCredentials(
        KEYLESS_KEYCHAIN_SERVICE,
        KEYLESS_KEYCHAIN_USERNAME,
        JSON.stringify(dataToStore)
      );


      console.log('[AuthService] Stored Keyless data successfully');
    } catch (error) {
      console.error('[AuthService] Error storing Keyless data:', error);
    }
  }

  // Rehydrate Keyless data from storage
  private async rehydrateKeylessData(): Promise<void> {
    try {
      // Try Keychain first
      const keychainData = await Keychain.getInternetCredentials(KEYLESS_KEYCHAIN_SERVICE);
      
      if (keychainData && keychainData.password) {
        const storedData: StoredKeylessData = JSON.parse(keychainData.password);
        
        // Check if ephemeral key is still valid
        const expiryDate = new Date(storedData.account.ephemeralKeyPair.expiryDate);
        if (expiryDate > new Date()) {
          this.currentAccount = storedData.account;
          this.ephemeralKeyPair = storedData.account.ephemeralKeyPair;
          console.log('[AuthService] Restored Keyless data from Keychain');
        } else {
          console.log('[AuthService] Stored ephemeral key has expired');
          await this.clearKeylessData();
        }
      }
    } catch (error) {
      console.error('[AuthService] Error rehydrating Keyless data:', error);
    }
  }

  // Clear stored Keyless data
  private async clearKeylessData(): Promise<void> {
    try {
      await Keychain.resetInternetCredentials(KEYLESS_KEYCHAIN_SERVICE);
      this.currentAccount = null;
      this.ephemeralKeyPair = null;
      console.log('[AuthService] Cleared Keyless data');
    } catch (error) {
      console.error('[AuthService] Error clearing Keyless data:', error);
    }
  }

  // Get stored Keyless data
  async getStoredKeylessData(): Promise<StoredKeylessData | null> {
    try {
      const credentials = await Keychain.getInternetCredentials(KEYLESS_KEYCHAIN_SERVICE);
      if (credentials && credentials.password) {
        return JSON.parse(credentials.password);
      }
      return null;
    } catch (error) {
      console.error('Error retrieving Keyless data:', error);
      return null;
    }
  }

  // Store auth tokens
  async storeTokens(tokens: TokenStorage): Promise<void> {
    try {
      await Keychain.setGenericPassword(
        AUTH_KEYCHAIN_USERNAME,
        JSON.stringify(tokens),
        {
          service: AUTH_KEYCHAIN_SERVICE,
          username: AUTH_KEYCHAIN_USERNAME,
          accessible: Keychain.ACCESSIBLE.WHEN_UNLOCKED
        }
      );
      console.log('Auth tokens stored successfully');
    } catch (error) {
      console.error('Error storing tokens:', error);
      throw error;
    }
  }

  // Get the user's Aptos address
  public async getKeylessAddress(): Promise<string> {
    if (!this.currentAccount) {
      const storedData = await this.getStoredKeylessData();
      if (!storedData) {
        throw new Error('No Keyless account available');
      }
      this.currentAccount = storedData.account;
    }
    return this.currentAccount.address;
  }

  // Sign out
  async signOut() {
    try {
      console.log('Starting sign out process...');
      
      // 1. Close any open OAuth browser
      try {
        const webOAuth = WebOAuthService.getInstance();
        await webOAuth.ensureBrowserClosed();
        console.log('OAuth browser closed');
      } catch (error) {
        console.log('OAuth browser close skipped or failed:', error);
      }
      
      // 2. Sign out from Firebase
      const currentUser = this.auth.currentUser;
      if (currentUser) {
        await this.auth.signOut();
        console.log('Firebase sign out complete');
      }
      
      // 3. Sign out from Google
      try {
        await GoogleSignin.signOut();
        console.log('Google sign out complete');
      } catch (error) {
        console.log('Google sign out skipped or failed:', error);
      }
      
      // 4. Clear Keyless data
      await this.clearKeylessData();
      
      // 4. Clear account data
      const accountManager = AccountManager.getInstance();
      await accountManager.clearAllAccounts();
      
      // 5. Clear auth tokens
      await Keychain.resetGenericPassword({
        service: AUTH_KEYCHAIN_SERVICE,
        username: AUTH_KEYCHAIN_USERNAME
      });
      
      // 6. Clear local state
      this.currentAccount = null;
      this.ephemeralKeyPair = null;
      this.firebaseIsInitialized = false;
      
      console.log('Sign out process completed successfully');
    } catch (error) {
      console.error('Sign Out Error:', error);
      // Continue with cleanup even if some operations fail
      this.currentAccount = null;
      this.ephemeralKeyPair = null;
      this.firebaseIsInitialized = false;
    }
  }

  // Get current Keyless account
  public getCurrentAccount(): KeylessAccount | null {
    return this.currentAccount;
  }

  // Check if user is signed in
  public isSignedIn(): boolean {
    return !!this.currentAccount;
  }

  // Sign and submit transaction through Django GraphQL
  public async signAndSubmitTransaction(transaction: any): Promise<any> {
    try {
      if (!this.currentAccount) {
        throw new Error('No Keyless account available');
      }

      const { SIGN_AND_SUBMIT_TRANSACTION } = await import('../apollo/keylessMutations');
      
      // Clean the ephemeralKeyPair object to remove __typename
      const cleanEphemeralKeyPair = {
        privateKey: this.currentAccount.ephemeralKeyPair.privateKey,
        publicKey: this.currentAccount.ephemeralKeyPair.publicKey,
        expiryDate: this.currentAccount.ephemeralKeyPair.expiryDate,
        nonce: this.currentAccount.ephemeralKeyPair.nonce,
        blinder: this.currentAccount.ephemeralKeyPair.blinder
      };

      const { data } = await apolloClient.mutate({
        mutation: SIGN_AND_SUBMIT_TRANSACTION,
        variables: {
          jwt: this.currentAccount.jwt,
          ephemeralKeyPair: cleanEphemeralKeyPair,
          transaction,
          pepper: this.currentAccount.pepper
        }
      });

      if (!data?.signAndSubmitTransaction?.success) {
        throw new Error(data?.signAndSubmitTransaction?.error || 'Failed to submit transaction');
      }

      return data.signAndSubmitTransaction.transactionHash;
    } catch (error) {
      console.error('[AuthService] Transaction error:', error);
      throw error;
    }
  }

  // Create keyless signature for transaction (compatibility with old zkLogin flow)
  public async createZkLoginSignatureForTransaction(transactionBytes: string): Promise<string | null> {
    try {
      console.log('AuthService - createZkLoginSignatureForTransaction called (using Aptos Keyless)');
      
      if (!this.currentAccount) {
        console.error('No keyless account available for transaction signing');
        return null;
      }

      // For now, return a mock signature since the backend will handle the actual signing
      // The backend uses the JWT and ephemeral keypair to create the real signature
      const keylessSignature = `keyless_signature_${Date.now()}_${this.currentAccount.address.slice(0, 10)}`;
      
      console.log('AuthService - Generated keyless signature placeholder:', keylessSignature.substring(0, 50) + '...');
      return keylessSignature;
      
    } catch (error) {
      console.error('AuthService - Error creating keyless signature:', error);
      return null;
    }
  }

  // Get account balance through Django GraphQL
  public async getBalance(address?: string): Promise<{ apt: string }> {
    try {
      const targetAddress = address || this.currentAccount?.address;
      if (!targetAddress) {
        throw new Error('No address available');
      }

      const { GET_KEYLESS_BALANCE } = await import('../apollo/keylessMutations');
      
      const { data } = await apolloClient.query({
        query: GET_KEYLESS_BALANCE,
        variables: { address: targetAddress },
        fetchPolicy: 'network-only'
      });

      if (!data?.keylessBalance?.success) {
        throw new Error(data?.keylessBalance?.error || 'Failed to get balance');
      }

      return { apt: data.keylessBalance.apt };
    } catch (error) {
      console.error('[AuthService] Balance error:', error);
      throw error;
    }
  }

  public async getToken(): Promise<string | null> {
    try {
      const credentials = await Keychain.getGenericPassword({
        service: AUTH_KEYCHAIN_SERVICE,
        username: AUTH_KEYCHAIN_USERNAME
      });

      if (credentials === false) {
        return null;
      }

      const tokens = JSON.parse(credentials.password);
      return tokens.accessToken || null;
    } catch (error) {
      console.error('Error getting token:', error);
      return null;
    }
  }

  // Account Management Methods

  public async getActiveAccountContext(): Promise<AccountContext> {
    const accountManager = AccountManager.getInstance();
    try {
      return await accountManager.getActiveAccountContext();
    } catch (error) {
      console.error('Error getting active account context, resetting to default:', error);
      await accountManager.resetActiveAccount();
      return accountManager.getDefaultAccountContext();
    }
  }

  public async setActiveAccountContext(context: AccountContext): Promise<void> {
    const accountManager = AccountManager.getInstance();
    await accountManager.setActiveAccountContext(context);
  }

  public async getStoredAccounts(): Promise<any[]> {
    const accountManager = AccountManager.getInstance();
    return await accountManager.getStoredAccounts();
  }

  public async switchAccount(accountId: string, apolloClient?: any): Promise<void> {
    const accountManager = AccountManager.getInstance();
    
    console.log('AuthService - switchAccount called with accountId:', accountId);
    
    // Parse the account ID to extract type, businessId (if present), and index
    let accountContext: AccountContext;
    
    if (accountId === 'personal_0') {
      accountContext = {
        type: 'personal',
        index: 0
      };
    } else if (accountId.startsWith('business_')) {
      const parts = accountId.split('_');
      if (parts.length >= 3) {
        const businessId = parts[1];
        const index = parseInt(parts[2]) || 0;
        
        accountContext = {
          type: 'business',
          index: index,
          businessId: businessId
        };
      } else {
        accountContext = {
          type: 'business',
          index: 0
        };
      }
    } else {
      const [accountType, indexStr] = accountId.split('_');
      const accountIndex = parseInt(indexStr) || 0;
      
      accountContext = {
        type: accountType as 'personal' | 'business',
        index: accountIndex
      };
    }
    
    console.log('AuthService - Parsed account context:', accountContext);
    
    // Set the new active account context
    await accountManager.setActiveAccountContext(accountContext);
    
    // If apolloClient is provided, get a new JWT token with the updated account context
    if (apolloClient) {
      try {
        const { SWITCH_ACCOUNT_TOKEN } = await import('../apollo/queries');
        
        const variables: any = {
          accountType: accountContext.type,
          accountIndex: accountContext.index
        };
        
        if (accountContext.businessId) {
          variables.businessId = accountContext.businessId;
        }
        
        const { data } = await apolloClient.mutate({
          mutation: SWITCH_ACCOUNT_TOKEN,
          variables
        });
        
        if (data?.switchAccountToken?.token) {
          console.log('AuthService - Got new JWT token with account context');
          
          // Get existing refresh token
          const credentials = await Keychain.getGenericPassword({
            service: AUTH_KEYCHAIN_SERVICE,
            username: AUTH_KEYCHAIN_USERNAME
          });
          
          let refreshToken = '';
          if (credentials && credentials.password) {
            try {
              const tokens = JSON.parse(credentials.password);
              refreshToken = tokens.refreshToken || '';
            } catch (e) {
              console.error('Error parsing existing tokens:', e);
            }
          }
          
          // Store the new access token with the existing refresh token
          await this.storeTokens({
            accessToken: data.switchAccountToken.token,
            refreshToken: refreshToken
          });
          
          console.log('AuthService - Updated JWT token stored');
        }
      } catch (error) {
        console.error('Error getting new JWT token for account switch:', error);
        // Continue anyway - the account context is set locally
      }
    }
    
    console.log('AuthService - Account switch completed');
  }

  public async initializeDefaultAccount(): Promise<any> {
    const accountManager = AccountManager.getInstance();
    return await accountManager.initializeDefaultAccount();
  }

  private async initializeDefaultAccountIfNeeded(): Promise<void> {
    try {
      const accountManager = AccountManager.getInstance();
      const storedAccounts = await accountManager.getStoredAccounts();
      
      console.log('AuthService - Checking if default account initialization is needed:', {
        storedAccountsCount: storedAccounts.length
      });
      
      if (storedAccounts.length === 0) {
        console.log('AuthService - No accounts found, but not creating default account');
        console.log('AuthService - Note: Accounts should only be created after proper authentication');
        return;
      }
    } catch (error) {
      console.error('AuthService - Error checking default account initialization:', error);
    }
  }

}

// Export a singleton instance
const authService = AuthService.getInstance();
export default authService;