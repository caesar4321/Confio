import { GoogleSignin, User } from '@react-native-google-signin/google-signin';
import { jwtDecode } from 'jwt-decode';
import * as Keychain from 'react-native-keychain';
import { GOOGLE_CLIENT_IDS, API_URL } from '../config/env';
import auth from '@react-native-firebase/auth';
import { Platform } from 'react-native';
import { apolloClient } from '../apollo/client';
import { AccountManager, AccountContext } from '../utils/accountManager';
import { generateKeylessPepper } from '../utils/aptosKeyless';
import { sha256 } from '@noble/hashes/sha256';
import { sha512 } from '@noble/hashes/sha512';
import { randomBytes } from 'react-native-randombytes';
import * as ed25519 from '@noble/ed25519';

// Configure @noble/ed25519 for React Native
ed25519.etc.sha512Sync = (...m) => sha512(ed25519.etc.concatBytes(...m));

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
      // If we already have a valid current account, don't clear it
      if (this.currentAccount && this.ephemeralKeyPair) {
        console.log('[AuthService] Current account already exists, skipping rehydration');
        return;
      }
      
      // Try Keychain first
      const keychainData = await Keychain.getInternetCredentials(KEYLESS_KEYCHAIN_SERVICE);
      
      if (keychainData && keychainData.password) {
        const storedData: StoredKeylessData = JSON.parse(keychainData.password);
        
        // Validate the stored data structure
        if (!storedData.account || !storedData.account.ephemeralKeyPair) {
          console.log('[AuthService] Invalid stored keyless data structure, clearing');
          await this.clearKeylessData();
          return;
        }
        
        // Check if ephemeral key is still valid
        const expiryDate = new Date(storedData.account.ephemeralKeyPair.expiryDate);
        if (expiryDate > new Date()) {
          this.currentAccount = storedData.account;
          this.ephemeralKeyPair = storedData.account.ephemeralKeyPair;
          console.log('[AuthService] Restored Keyless data from Keychain');
          console.log('[AuthService] Restored ephemeral key nonce:', this.ephemeralKeyPair?.nonce);
          console.log('[AuthService] Restored account address:', this.currentAccount?.address);
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
    // Clear local state first
    this.currentAccount = null;
    this.ephemeralKeyPair = null;
    
    // Try to clear keychain data
    try {
      // Instead of resetInternetCredentials, we'll overwrite with empty data
      // This works on both iOS and Android
      await Keychain.setInternetCredentials(
        KEYLESS_KEYCHAIN_SERVICE,
        KEYLESS_KEYCHAIN_USERNAME,
        JSON.stringify({})
      );
      console.log('[AuthService] Cleared Keyless data from keychain');
    } catch (error) {
      console.log('[AuthService] Error clearing keychain data:', error);
      // Continue anyway - local state is cleared
    }
    
    console.log('[AuthService] Cleared Keyless data');
  }

  // Get stored Keyless data
  async getStoredKeylessData(): Promise<StoredKeylessData | null> {
    try {
      const credentials = await Keychain.getInternetCredentials(KEYLESS_KEYCHAIN_SERVICE);
      if (credentials && credentials.password) {
        const parsed = JSON.parse(credentials.password);
        // Validate the structure - return null if it's just an empty object
        if (!parsed.account || !parsed.account.address) {
          return null;
        }
        return parsed;
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
      if (!storedData || !storedData.account || !storedData.account.address) {
        throw new Error('No Keyless account available');
      }
      this.currentAccount = storedData.account;
    }
    return this.currentAccount.address;
  }

  // Minimal sign out for testing
  async signOutMinimal() {
    try {
      console.log('Starting minimal sign out...');
      
      // Test 1: Close OAuth browser
      try {
        const { WebOAuthService } = await import('./webOAuthService');
        const webOAuth = WebOAuthService.getInstance();
        await webOAuth.ensureBrowserClosed();
        console.log('OAuth browser closed');
      } catch (error) {
        console.log('OAuth browser close error:', error);
      }
      
      // Test 2: Firebase sign out
      try {
        const currentUser = this.auth.currentUser;
        if (currentUser) {
          await this.auth.signOut();
          console.log('Firebase sign out complete');
        }
      } catch (error) {
        console.log('Firebase sign out error:', error);
      }
      
      // Test 3: Google sign out
      try {
        console.log('Attempting Google sign out...');
        await GoogleSignin.signOut();
        console.log('Google sign out complete');
      } catch (error) {
        console.log('Google sign out error:', error);
      }
      
      // Test 4: Clear Keyless data from keychain
      try {
        console.log('Clearing keyless data from keychain...');
        await this.clearKeylessData();
        console.log('Keyless data cleared from keychain');
      } catch (error) {
        console.log('Keyless keychain clear error:', error);
      }
      
      // Test 5: Clear account data
      try {
        console.log('About to clear account data...');
        const accountManager = AccountManager.getInstance();
        await accountManager.clearAllAccounts();
        console.log('Account data cleared');
      } catch (error) {
        console.error('Error clearing account data:', error);
      }
      
      // Test 6: Clear auth tokens - using resetGenericPassword (like zkLogin did)
      try {
        console.log('About to clear auth tokens...');
        await Keychain.resetGenericPassword({
          service: AUTH_KEYCHAIN_SERVICE
        });
        console.log('Auth tokens cleared');
      } catch (error) {
        console.log('Error clearing auth tokens:', error);
      }
      
      // Clear local state
      this.currentAccount = null;
      this.ephemeralKeyPair = null;
      this.firebaseIsInitialized = false;
      
      console.log('Minimal sign out completed');
    } catch (error) {
      console.error('Minimal sign out error:', error);
    }
  }

  // Sign out
  async signOut() {
    try {
      console.log('Starting sign out process...');
      
      // 1. Close any open OAuth browser
      try {
        const { WebOAuthService } = await import('./webOAuthService');
        const webOAuth = WebOAuthService.getInstance();
        await webOAuth.ensureBrowserClosed();
        console.log('OAuth browser closed');
      } catch (error) {
        console.log('OAuth browser close skipped or failed:', error);
      }
      
      // 2. Sign out from Firebase
      try {
        const currentUser = this.auth.currentUser;
        if (currentUser) {
          await this.auth.signOut();
          console.log('Firebase sign out complete');
        }
      } catch (error) {
        console.log('Firebase sign out error:', error);
      }
      
      // 3. Sign out from Google - check if GoogleSignin is configured first
      try {
        const isConfigured = await GoogleSignin.isSignedIn();
        if (isConfigured) {
          console.log('Attempting Google sign out...');
          await GoogleSignin.signOut();
          console.log('Google sign out complete');
        }
      } catch (error) {
        console.log('Google sign out skipped or failed:', error);
      }
      
      // 4. Clear Keyless data using try-catch for each operation
      try {
        console.log('About to clear Keyless data...');
        await this.clearKeylessData();
        console.log('Keyless data cleared');
      } catch (error) {
        console.error('Error clearing Keyless data:', error);
      }
      
      // 5. Clear account data
      try {
        console.log('About to clear account data...');
        const accountManager = AccountManager.getInstance();
        await accountManager.clearAllAccounts();
        console.log('Account data cleared');
      } catch (error) {
        console.error('Error clearing account data:', error);
      }
      
      // 6. Clear auth tokens - using simpler approach
      try {
        console.log('About to clear auth tokens...');
        // Just clear the credentials without any options
        const credentials = await Keychain.getGenericPassword({
          service: AUTH_KEYCHAIN_SERVICE
        });
        
        if (credentials && credentials !== false) {
          // Found credentials, try to reset
          await Keychain.resetGenericPassword({
            service: AUTH_KEYCHAIN_SERVICE
          });
        }
        console.log('Auth tokens cleared');
      } catch (keychainError) {
        console.log('Error with auth tokens:', keychainError);
        // Don't throw, just continue
      }
      
      // 7. Clear local state
      console.log('Clearing local state...');
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

  // Create keyless signature for transaction (using Aptos Keyless accounts)
  public async createZkLoginSignatureForTransaction(transactionBytes: string): Promise<string | null> {
    try {
      console.log('AuthService - createZkLoginSignatureForTransaction called (using Aptos Keyless)');
      
      if (!this.currentAccount) {
        console.error('No keyless account available for transaction signing');
        return null;
      }

      if (!this.ephemeralKeyPair) {
        console.error('No ephemeral keypair available for transaction signing');
        return null;
      }

      if (!this.currentAccount.jwt) {
        console.error('No JWT available for keyless signing');
        return null;
      }

      // Decode the transaction bytes from base64
      const txBytesString = atob(transactionBytes);
      const txData = JSON.parse(txBytesString);
      
      console.log('AuthService - Signing transaction with Aptos Keyless account:', this.currentAccount.address);
      console.log('AuthService - Transaction data:', txData);

      // Use the Aptos Keyless Service to generate proper authenticator
      try {
        console.log('AuthService - Using Aptos Keyless Service for authentication');
        console.log('AuthService - Current ephemeral key pair:', {
          hasPrivateKey: !!this.ephemeralKeyPair?.privateKey,
          hasPublicKey: !!this.ephemeralKeyPair?.publicKey,
          nonce: this.ephemeralKeyPair?.nonce,
          expiryDate: this.ephemeralKeyPair?.expiryDate,
          hasBlinder: !!this.ephemeralKeyPair?.blinder,
        });
        console.log('AuthService - JWT length:', this.currentAccount.jwt?.length);
        
        // Check if this is a sponsored transaction
        if (!txData.signing_message) {
          console.error('AuthService - No signing_message provided in transaction data');
          return null;
        }
        
        // Import the keyless service with error handling
        let aptosKeylessService;
        try {
          const module = await import('./aptosKeylessService');
          aptosKeylessService = module.aptosKeylessService;
          
          if (!aptosKeylessService) {
            console.error('AuthService - aptosKeylessService is undefined after import');
            return null;
          }
        } catch (importError) {
          console.error('AuthService - Failed to import aptosKeylessService:', importError);
          return null;
        }
        
        // Generate the authenticator
        console.log('AuthService - Generating keyless authenticator...');
        
        // Handle pepper conversion
        let pepperBytes: Uint8Array | undefined;
        if (this.currentAccount.pepper) {
          console.log('AuthService - Original pepper:', this.currentAccount.pepper);
          console.log('AuthService - Pepper type:', typeof this.currentAccount.pepper);
          
          // Remove 0x prefix if present
          const pepperHex = this.currentAccount.pepper.replace(/^0x/, '');
          console.log('AuthService - Pepper hex (no 0x):', pepperHex);
          console.log('AuthService - Pepper hex length:', pepperHex.length);
          
          const pepperBuffer = Buffer.from(pepperHex, 'hex');
          console.log('AuthService - Pepper buffer length:', pepperBuffer.length);
          
          // Ensure pepper is exactly 31 bytes
          if (pepperBuffer.length !== 31) {
            console.warn(`AuthService - Pepper length is ${pepperBuffer.length}, expected 31. Padding/truncating...`);
            // Create a 31-byte buffer
            const paddedPepper = Buffer.alloc(31);
            // Copy the pepper, truncating if too long or padding with zeros if too short
            pepperBuffer.copy(paddedPepper, 0, 0, Math.min(31, pepperBuffer.length));
            pepperBytes = new Uint8Array(paddedPepper);
          } else {
            pepperBytes = new Uint8Array(pepperBuffer);
          }
          
          console.log('AuthService - Final pepper bytes length:', pepperBytes.length);
          console.log('AuthService - Final pepper bytes (first 10):', Array.from(pepperBytes.slice(0, 10)));
        }
        
        const authenticatorResponse = await aptosKeylessService.generateAuthenticator({
          jwt: this.currentAccount.jwt,
          ephemeralKeyPair: this.ephemeralKeyPair,
          signingMessage: txData.signing_message,
          pepper: pepperBytes,
        });
        
        console.log('AuthService - Generated keyless authenticator:', {
          addressHex: authenticatorResponse.addressHex,
          ephemeralPublicKeyHex: authenticatorResponse.ephemeralPublicKeyHex,
          authenticatorLength: authenticatorResponse.senderAuthenticatorBcsBase64.length,
        });
        
        // Create the response structure that the backend expects
        const keylessSignatureData = {
          // For compatibility with existing backend
          transaction_hash: txData.signing_message,
          ephemeral_public_key: authenticatorResponse.ephemeralPublicKeyHex,
          account_address: this.currentAccount.address,
          jwt: this.currentAccount.jwt,
          keyless_signature_type: 'aptos_keyless_authenticator',
          
          // New fields with the actual authenticator
          sender_authenticator_bcs_base64: authenticatorResponse.senderAuthenticatorBcsBase64,
          auth_key_hex: authenticatorResponse.authKeyHex,
          address_hex: authenticatorResponse.addressHex,
          signing_message_base64: txData.signing_message,
        };

        const signatureJson = JSON.stringify(keylessSignatureData);
        const signatureBase64 = btoa(signatureJson);
        
        console.log('AuthService - Created keyless authenticator response');
        return signatureBase64;
      } catch (error) {
        console.error('AuthService - Error creating keyless signature:', error);
        return null;
      }
    } catch (error) {
      console.error('AuthService - Error creating keyless signature:', error);
      return null;
    }
  }

  /**
   * Sign a sponsored transaction (V2 flow)
   * This method signs the raw transaction bytes for a fee payer transaction
   * @param rawTransaction - Base64 encoded raw transaction from prepare phase
   * @returns Base64 encoded sender authenticator
   */
  public async signSponsoredTransaction(rawTransaction: string): Promise<string | null> {
    try {
      console.log('AuthService - signSponsoredTransaction called');
      
      if (!this.currentAccount) {
        console.error('AuthService - No active account available for signing');
        return null;
      }

      if (!this.ephemeralKeyPair) {
        console.error('AuthService - No ephemeral key pair available');
        return null;
      }

      // Import Aptos keyless service
      const { AptosKeylessService } = await import('./aptosKeylessService');
      const aptosKeylessService = new AptosKeylessService();

      // Ensure rawTransaction is a string
      let rawTxString: string;
      if (typeof rawTransaction === 'string') {
        rawTxString = rawTransaction;
      } else if (rawTransaction && typeof rawTransaction === 'object') {
        // If it's an object, try to convert it
        rawTxString = JSON.stringify(rawTransaction);
        console.log('AuthService - Raw transaction was an object, converted to JSON string');
      } else {
        console.error('AuthService - Invalid raw transaction type:', typeof rawTransaction);
        return null;
      }

      // Decode the raw transaction from base64 to get signing message
      const rawTxBytes = Buffer.from(rawTxString, 'base64');
      const signingMessage = Buffer.from(rawTxBytes).toString('hex');
      
      console.log('AuthService - Signing sponsored transaction');
      console.log('AuthService - Raw transaction length:', rawTxBytes.length);
      console.log('AuthService - Signing message (hex):', signingMessage.substring(0, 100) + '...');

      // Get pepper from account proof
      let pepperBytes: Uint8Array | undefined;
      if (this.currentAccount.proof?.pepper) {
        const pepperHex = this.currentAccount.proof.pepper.startsWith('0x') 
          ? this.currentAccount.proof.pepper.slice(2) 
          : this.currentAccount.proof.pepper;
        
        const pepperBuffer = Buffer.from(pepperHex, 'hex');
        
        // Ensure pepper is exactly 31 bytes
        if (pepperBuffer.length !== 31) {
          console.warn(`AuthService - Pepper length is ${pepperBuffer.length}, expected 31. Padding/truncating...`);
          const paddedPepper = Buffer.alloc(31);
          pepperBuffer.copy(paddedPepper, 0, 0, Math.min(31, pepperBuffer.length));
          pepperBytes = new Uint8Array(paddedPepper);
        } else {
          pepperBytes = new Uint8Array(pepperBuffer);
        }
      }

      // Generate the authenticator for the sponsored transaction
      const authenticatorResponse = await aptosKeylessService.generateAuthenticator({
        jwt: this.currentAccount.jwt,
        ephemeralKeyPair: this.ephemeralKeyPair,
        signingMessage: signingMessage,
        pepper: pepperBytes,
      });

      console.log('AuthService - Generated sponsored transaction authenticator');
      console.log('AuthService - Authenticator length:', authenticatorResponse.senderAuthenticatorBcsBase64.length);

      // Return the base64 encoded authenticator directly
      // This is what the backend expects for V2 sponsored transactions
      return authenticatorResponse.senderAuthenticatorBcsBase64;
      
    } catch (error) {
      console.error('AuthService - Error signing sponsored transaction:', error);
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