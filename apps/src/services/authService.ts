import { GoogleSignin, User } from '@react-native-google-signin/google-signin';
import { Ed25519Keypair } from '@mysten/sui/keypairs/ed25519';
import { genAddressSeed, getZkLoginSignature, generateNonce as generateZkLoginNonce } from '@mysten/sui/zklogin';
import { SuiClient } from '@mysten/sui/client';
import { jwtDecode } from 'jwt-decode';
import * as Keychain from 'react-native-keychain';
import { GOOGLE_CLIENT_IDS, API_URL } from '../config/env';
import auth from '@react-native-firebase/auth';
import { Platform } from 'react-native';
// zkLogin mutations removed - using Web3Auth mutations from mutations.ts instead
import { apolloClient, AUTH_KEYCHAIN_SERVICE, AUTH_KEYCHAIN_USERNAME } from '../apollo/client';
import { gql } from '@apollo/client';
import { Buffer } from 'buffer';
import { sha256 } from '@noble/hashes/sha256';
import { base64ToBytes, bytesToBase64, stringToUtf8Bytes, bufferToHex } from '../utils/encoding';
import { ApolloClient } from '@apollo/client';
import { AccountManager, AccountContext } from '../utils/accountManager';
import { generateZkLoginSalt as generateZkLoginSaltUtil } from '../utils/zkLogin';
import { DeviceFingerprint } from '../utils/deviceFingerprint';
import algorandService from './algorandService';
// Import OAuth storage - handle gracefully if module not found
let oauthStorage: any = null;
try {
  const module = require('./oauthStorageService');
  oauthStorage = module.oauthStorage;
} catch (error) {
  console.warn('OAuth storage service not available:', error);
}

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

interface StoredZkLogin {
  salt: string;           // init.salt (base64)
  subject: string;        // sub
  clientId: string;       // oauth clientId
  maxEpoch: number;       // Number(init.maxEpoch)
  zkProof: {
    zkProof: any;        // the full proof object (points a/b/c etc)
    subject: string;     // sub
    clientId: string;    // oauth clientId
    algorandAddress: string;  // the user's Aptos address
  };
  secretKey: string;     // base64-encoded 32-byte seed
  initRandomness: string; // randomness from initializeZkLogin
  initJwt: string;       // original JWT from sign-in
}

export const ZKLOGIN_KEYCHAIN_SERVICE = 'com.confio.zklogin';
const ZKLOGIN_KEYCHAIN_USERNAME = 'zkLoginData';

export class AuthService {
  private static instance: AuthService;
  private suiKeypair: Ed25519Keypair | null = null;
  private suiClient: SuiClient;
  private userSalt: string | null = null;
  private zkProof: any | null = null;
  private maxEpoch: number | null = null;
  private auth = auth();
  private firebaseIsInitialized = false;
  private apolloClient: ApolloClient<any> | null = null;
  private token: string | null = null;

  private constructor() {
    this.suiClient = new SuiClient({ url: 'https://fullnode.devnet.sui.io' });
  }

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
      
      // Always rehydrate zkLogin data
      console.log('AuthService - Rehydrating zkLogin data');
      await this.rehydrateZkLoginData();
      console.log('AuthService - zkLogin data rehydrated');
      
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

  async signInWithGoogle(onProgress?: (message: string) => void) {
    const startTime = Date.now();
    const perfLog = (step: string) => {
      console.log(`[PERF] ${step}: ${Date.now() - startTime}ms`);
    };
    
    try {
      console.log('Starting Google Sign-In process...');
      perfLog('Start');
      // Don't show progress during Google modal
      
      // Sign out first to force account selection
      try {
        // Check if the method exists before calling (compatibility issue)
        if (GoogleSignin.signOut) {
          await GoogleSignin.signOut();
          console.log('Signed out from Google to force account selection');
        }
      } catch (error) {
        // Ignore sign-out errors - not critical
        console.log('Sign-out skipped:', error.message);
      }
      
      // 1) Sign in with Google first
      console.log('Checking Play Services...');
      perfLog('Before Play Services check');
      await GoogleSignin.hasPlayServices();
      perfLog('After Play Services check');
      console.log('Play Services check passed');
      
      console.log('Attempting Google Sign-In...');
      perfLog('Before GoogleSignin.signIn()');
      const userInfo = await GoogleSignin.signIn();
      perfLog('After GoogleSignin.signIn()');
      console.log('Google Sign-In response:', userInfo);
      
      if (!userInfo) {
        throw new Error('No user info returned from Google Sign-In');
      }

      // 2) Get the ID token after successful sign-in
      perfLog('Google Sign-In complete');
      // NOW show loading - Google modal is closed
      onProgress?.('Verificando tu cuenta...');
      console.log('Getting Google ID token...');
      const { idToken } = await GoogleSignin.getTokens();
      console.log('Got ID token:', idToken ? 'Token received' : 'No token');
      perfLog('Got Google ID token');
      
      // Debug: Check what's in the userInfo from Google Sign-In
      console.log('[AuthService] Google Sign-In userInfo - parsed:', {
        type: userInfo?.type,
        userId: userInfo?.data?.user?.id,
        userEmail: userInfo?.data?.user?.email,
        userName: userInfo?.data?.user?.name,
        idToken: userInfo?.data?.idToken,
        serverAuthCode: userInfo?.data?.serverAuthCode,
      });
      
      if (!idToken) {
        throw new Error('No ID token received from Google Sign-In');
      }

      // 3) Sign in with Firebase using the Google credential
      onProgress?.('Autenticando tu cuenta...');
      console.log('Creating Firebase credential...');
      const firebaseCred = auth.GoogleAuthProvider.credential(idToken);
      console.log('Signing in with Firebase...');
      const { user } = await this.auth.signInWithCredential(firebaseCred);
      console.log('Firebase sign-in response:', user ? 'User received' : 'No user');
      perfLog('Firebase sign-in complete');
      
      if (!user) {
        throw new Error('No user returned from Firebase sign-in');
      }

      console.log('Getting Firebase ID token...');
      const firebaseToken = await user.getIdToken();
      console.log('Firebase token received');

      // 4) Collect device fingerprint before zkLogin initialization
      console.log('Collecting device fingerprint...');
      let deviceFingerprint = null;
      try {
        deviceFingerprint = await DeviceFingerprint.generateFingerprint();
        console.log('Device fingerprint collected successfully');
      } catch (error) {
        console.error('Error collecting device fingerprint:', error);
        // Continue without fingerprint rather than failing authentication
      }

      // 5) Generate Algorand wallet first
      console.log('Generating Algorand wallet...');
      perfLog('Starting Algorand wallet generation');
      
      // Use OAuth subject directly from Google Sign-In response
      // The structure is userInfo.data.user.id based on the actual response
      const googleSubject = userInfo?.data?.user?.id;
      if (!googleSubject) {
        console.error('Failed to get Google subject. userInfo structure:', {
          hasData: !!userInfo?.data,
          hasUser: !!userInfo?.data?.user,
          hasUserId: !!userInfo?.data?.user?.id,
          fullUserInfo: JSON.stringify(userInfo)
        });
        throw new Error('No OAuth subject found in Google sign-in response. Check console for userInfo structure.');
      }
      
      // Store OAuth subject securely for future account switching
      const { oauthStorage } = await import('./oauthStorageService');
      await oauthStorage.storeOAuthSubject(googleSubject, 'google');
      console.log('Stored OAuth subject securely for future use');
      
      // Create or restore Algorand wallet
      const algorandService = (await import('./algorandService')).default;
      const algorandAddress = await algorandService.createOrRestoreWallet(firebaseToken, googleSubject);
      console.log('Algorand wallet created:', algorandAddress);
      perfLog('Algorand wallet created');
      
      // 6) Authenticate with backend using Web3Auth
      console.log('Authenticating with backend...');
      perfLog('Starting backend authentication');
      const { WEB3AUTH_LOGIN } = await import('../apollo/mutations');
      const { data: { web3AuthLogin: authData } } = await apolloClient.mutate({
        mutation: WEB3AUTH_LOGIN,
        variables: { 
          firebaseIdToken: firebaseToken,
          algorandAddress: algorandAddress,
          deviceFingerprint: deviceFingerprint ? JSON.stringify(deviceFingerprint) : null
        }
      });
      console.log('Backend authentication response:', authData ? 'Data received' : 'No data');
      perfLog('Backend authenticated');

      if (!authData || !authData.success) {
        throw new Error(authData?.error || 'Backend authentication failed');
      }

      // Store Django JWT tokens for authenticated requests using Keychain
      if (authData.accessToken) {
        console.log('About to store tokens in Keychain:', {
          service: AUTH_KEYCHAIN_SERVICE,
          username: AUTH_KEYCHAIN_USERNAME,
          hasAccessToken: !!authData.accessToken,
          hasRefreshToken: !!authData.refreshToken,
          accessTokenLength: authData.accessToken?.length,
          refreshTokenLength: authData.refreshToken?.length
        });

        try {
          await Keychain.setGenericPassword(
            AUTH_KEYCHAIN_USERNAME,
            JSON.stringify({
              accessToken: authData.accessToken,
              refreshToken: authData.refreshToken
            }),
            {
              service: AUTH_KEYCHAIN_SERVICE,
              username: AUTH_KEYCHAIN_USERNAME,
              accessible: Keychain.ACCESSIBLE.WHEN_UNLOCKED
            }
          );

          // Verify token was stored
          const checkCredentials = await Keychain.getGenericPassword({
            service: AUTH_KEYCHAIN_SERVICE,
            username: AUTH_KEYCHAIN_USERNAME
          });

          if (checkCredentials === false) {
            console.log('JWT in Keychain right after saving: No credentials');
            throw new Error('Failed to verify token storage in Keychain');
          } else {
            console.log('JWT in Keychain right after saving:', {
              hasCredentials: true,
              hasPassword: !!checkCredentials.password,
              passwordLength: checkCredentials.password.length
            });
            if (!checkCredentials.password) {
              throw new Error('Failed to verify token storage in Keychain');
            }
          }
        } catch (error) {
          console.error('Error storing or verifying tokens:', error);
          throw error;
        }
      } else {
        console.error('No auth tokens received from Web3Auth login');
        throw new Error('No auth tokens received from server');
      }

      // 7) Set default personal account context
      console.log('Setting default personal account context...');
      try {
        const accountManager = AccountManager.getInstance();
        await accountManager.setActiveAccountContext({
          type: 'personal',
          index: 0
        });
        console.log('Set default personal account context (personal_0)');
        
        // Store the Algorand address for the personal account
        const defaultAccountContext: AccountContext = {
          type: 'personal',
          index: 0
        };
        await this.storeAlgorandAddress(algorandAddress, defaultAccountContext);
      } catch (accountError) {
        console.error('Error creating default account:', accountError);
        // Don't throw here - account creation failure shouldn't break the sign-in flow
      }

      // 8) Get user info for return
      const [firstName, ...lastNameParts] = user.displayName?.split(' ') || [];
      const lastName = lastNameParts.join(' ');
      const isPhoneVerified = authData.user?.isPhoneVerified || false;
      console.log('Phone verification status from backend:', isPhoneVerified);
      
      // 9) Return user info with Algorand address
      const result = {
        userInfo: { 
          email: user.email, 
          firstName: firstName || '',
          lastName: lastName || '',
          photoURL: user.photoURL 
        },
        zkLoginData: { 
          zkProof: {
            algorandAddress: algorandAddress,
            zkProof: null
          },
          algorandAddress: algorandAddress,
          isPhoneVerified
        }
      };
      perfLog('Total sign-in time');
      console.log('Sign-in process completed successfully:', result);
      return result;
    } catch (error) {
      console.error('Error signing in with Google:', error);
      throw error;
    }
  }

  async getStoredZkLoginData() {
    try {
      const credentials = await Keychain.getGenericPassword({
        service: ZKLOGIN_KEYCHAIN_SERVICE
      });

      if (credentials === false) {
        return null;
      }

      return JSON.parse(credentials.password);
    } catch (error) {
      console.error('Error retrieving zkLogin data:', error);
      throw error;
    }
  }

  async storeZkLoginData(zkLoginData: any) {
    try {
      await Keychain.setGenericPassword(
        ZKLOGIN_KEYCHAIN_USERNAME,
        JSON.stringify(zkLoginData),
        {
          service: ZKLOGIN_KEYCHAIN_SERVICE,
        }
      );
    } catch (error) {
      console.error('Error storing zkLogin data:', error);
      throw error;
    }
  }

  async clearZkLoginData() {
    try {
      // v10 API: resetGenericPassword accepts options object with service
      await Keychain.resetGenericPassword({
        service: ZKLOGIN_KEYCHAIN_SERVICE
      });
    } catch (error) {
      console.error('Error clearing zkLogin data:', error);
      // Not critical if this fails, continue
    }
  }

  // Apple Sign-In
  public async signInWithApple(onProgress?: (message: string) => void) {
    if (Platform.OS !== 'ios') {
      throw new Error('Apple Sign In is only supported on iOS');
    }

    try {
      // Don't show progress during Apple modal
      if (!apolloClient) {
        throw new Error('Apollo client not initialized');
      }
      
      // Apple Sign In flow
      console.log('Starting Apple Sign In...');
      const { appleAuth } = await import('@invertase/react-native-apple-authentication');
      
      // Perform Apple auth (nonce will be auto-generated by the library)
      const appleAuthResponse = await appleAuth.performRequest({
        requestedOperation: appleAuth.Operation.LOGIN,
        requestedScopes: [appleAuth.Scope.EMAIL, appleAuth.Scope.FULL_NAME]
      });
      
      if (!appleAuthResponse.identityToken) {
        throw new Error('No identity token received from Apple');
      }
      
      // NOW show loading - Apple modal is closed
      onProgress?.('Verificando tu identidad con Apple...');
      
      // Sign in with Firebase
      const appleCredential = auth.AppleAuthProvider.credential(appleAuthResponse.identityToken, appleAuthResponse.nonce);
      const userCredential = await this.auth.signInWithCredential(appleCredential);
      const firebaseToken = await userCredential.user.getIdToken();
      
      console.log('Firebase sign-in successful');
      
      // Collect device fingerprint
      console.log('Collecting device fingerprint (Apple)...');
      let deviceFingerprint = null;
      try {
        deviceFingerprint = await DeviceFingerprint.generateFingerprint();
        console.log('Device fingerprint collected successfully (Apple)');
      } catch (error) {
        console.error('Error collecting device fingerprint (Apple):', error);
      }
      
      // Generate Algorand wallet first
      onProgress?.('Preparando tu cuenta segura...');
      console.log('Generating Algorand wallet for Apple sign-in...');
      
      // Use Apple user ID directly from the auth response
      let appleSub = appleAuthResponse.user;
      if (!appleSub) {
        // Fallback: decode the token if user field is not available (happens on subsequent sign-ins)
        const decodedAppleToken = jwtDecode<{ sub: string }>(appleAuthResponse.identityToken);
        appleSub = decodedAppleToken.sub;
      }
      
      // Store OAuth subject securely for future account switching
      const { oauthStorage } = await import('./oauthStorageService');
      await oauthStorage.storeOAuthSubject(appleSub, 'apple');
      console.log('Stored Apple OAuth subject securely for future use');
      
      // Create or restore Algorand wallet
      const algorandService = (await import('./algorandService')).default;
      const algorandAddress = await algorandService.createOrRestoreWallet(firebaseToken, appleSub);
      console.log('Algorand wallet created (Apple):', algorandAddress);
      
      // Authenticate with backend using Web3Auth
      console.log('Authenticating with backend (Apple)...');
      const { WEB3AUTH_LOGIN } = await import('../apollo/mutations');
      const { data: { web3AuthLogin: authData } } = await apolloClient.mutate({
        mutation: WEB3AUTH_LOGIN,
        variables: {
          firebaseIdToken: firebaseToken,
          algorandAddress: algorandAddress,
          deviceFingerprint: deviceFingerprint ? JSON.stringify(deviceFingerprint) : null
        }
      });
      
      if (!authData || !authData.success) {
        throw new Error(authData?.error || 'Backend authentication failed');
      }
      
      // Store Django JWT tokens for authenticated requests using Keychain
      if (authData.accessToken) {
        console.log('About to store tokens in Keychain (Apple):', {
          service: AUTH_KEYCHAIN_SERVICE,
          username: AUTH_KEYCHAIN_USERNAME,
          hasAccessToken: !!authData.accessToken,
          hasRefreshToken: !!authData.refreshToken,
          accessTokenLength: authData.accessToken?.length,
          refreshTokenLength: authData.refreshToken?.length
        });

        try {
          await Keychain.setGenericPassword(
            AUTH_KEYCHAIN_USERNAME,
            JSON.stringify({
              accessToken: authData.accessToken,
              refreshToken: authData.refreshToken
            }),
            {
              service: AUTH_KEYCHAIN_SERVICE,
              username: AUTH_KEYCHAIN_USERNAME,
              accessible: Keychain.ACCESSIBLE.WHEN_UNLOCKED
            }
          );

          // Verify token was stored
          const checkCredentials = await Keychain.getGenericPassword({
            service: AUTH_KEYCHAIN_SERVICE,
            username: AUTH_KEYCHAIN_USERNAME
          });

          if (checkCredentials === false) {
            console.log('JWT in Keychain right after saving (Apple): No credentials');
            throw new Error('Failed to verify token storage in Keychain');
          } else {
            console.log('JWT in Keychain right after saving (Apple):', {
              hasCredentials: true,
              hasPassword: !!checkCredentials.password,
              passwordLength: checkCredentials.password.length,
              rawCredentials: checkCredentials
            });
            if (!checkCredentials.password) {
              throw new Error('Failed to verify token storage in Keychain');
            }
          }

          // Parse and verify the stored tokens
          const stored = await Keychain.getGenericPassword({
            service: AUTH_KEYCHAIN_SERVICE,
            username: AUTH_KEYCHAIN_USERNAME
          });

          if (stored === false) {
            throw new Error('Failed to verify token storage');
          } else {
            const storedTokens = JSON.parse(stored.password);
            if (!storedTokens.accessToken || !storedTokens.refreshToken) {
              throw new Error('Invalid token format in storage');
            }
            console.log('Tokens stored and verified successfully:', {
              hasAccessToken: !!storedTokens.accessToken,
              hasRefreshToken: !!storedTokens.refreshToken,
              accessTokenLength: storedTokens.accessToken.length,
              refreshTokenLength: storedTokens.refreshToken.length
            });
          }
        } catch (error) {
          console.error('Error storing or verifying tokens:', error);
          throw error;
        }
      } else {
        console.error('No auth tokens received from Web3Auth login');
        throw new Error('No auth tokens received from server');
      }

      // Set default personal account context
      console.log('Setting default personal account context (Apple)...');
      try {
        const accountManager = AccountManager.getInstance();
        await accountManager.setActiveAccountContext({
          type: 'personal',
          index: 0
        });
        console.log('Set default personal account context (personal_0)');
        
        // Store the Algorand address for the personal account
        const defaultAccountContext: AccountContext = {
          type: 'personal',
          index: 0
        };
        await this.storeAlgorandAddress(algorandAddress, defaultAccountContext);
      } catch (accountError) {
        console.error('Error creating default account (Apple):', accountError);
        // Don't throw here - account creation failure shouldn't break the sign-in flow
      }
      
      // Get user info for return
      const [firstName, ...lastNameParts] = userCredential.user.displayName?.split(' ') || [];
      const lastName = lastNameParts.join(' ');
      const isPhoneVerified = authData.user?.isPhoneVerified || false;
      console.log('Phone verification status from backend (Apple):', isPhoneVerified);
      
      // Return user info with Algorand address
      const result = {
        userInfo: {
          email: userCredential.user.email,
          firstName: firstName || '',
          lastName: lastName || '',
          photoURL: userCredential.user.photoURL
        },
        zkLoginData: {
          zkProof: {
            algorandAddress: algorandAddress, // Store Algorand address in the zkProof object
            zkProof: null // We don't have actual zkProof when using Algorand
          },
          algorandAddress: algorandAddress, // Also store at top level for compatibility
          isPhoneVerified // Use the actual value from backend
        }
      };
      console.log('Apple sign-in process completed successfully:', result);
      return result;
    } catch (error) {
      console.error('Apple Sign In Error:', error);
      throw error;
    }
  }

  // Get ZK proof from our GraphQL server
  private async getZkProof(jwt: string, maxEpoch: number, randomness: string, apolloClient: ApolloClient<any>): Promise<any> {
    try {
      if (!this.suiKeypair) {
        throw new Error('Sui keypair not initialized');
      }

      if (!this.userSalt) {
        throw new Error('User salt not initialized');
      }

      const decodedJwt = jwtDecode(jwt);
      if (!decodedJwt.iss) {
        throw new Error('Invalid JWT: missing issuer claim');
      }

      // Get the platform-specific client ID
      const clientIds = GOOGLE_CLIENT_IDS[__DEV__ ? 'development' : 'production'];
      const platformClientId = Platform.OS === 'ios' ? clientIds.ios : 
                             Platform.OS === 'android' ? clientIds.android : 
                             clientIds.web;

      const ephemeralPublicKey = this.suiKeypair.getPublicKey().toBase64();
      
      console.log('Requesting ZK proof with params:', {
        maxEpoch,
        randomness,
        keyClaimName: 'sub',
        extendedEphemeralPublicKey: ephemeralPublicKey,
        salt: this.userSalt,
        audience: platformClientId
      });

      const { data } = await apolloClient.mutate({
        mutation: gql`
          mutation ZkLogin($input: ZkLoginInput!) {
            zkLogin(input: $input) {
              zkProof
              aptosAddress
              error
              details
            }
          }
        `,
        variables: {
          input: {
            jwt,
            maxEpoch,
            randomness,
            keyClaimName: 'sub',
            extendedEphemeralPublicKey: ephemeralPublicKey,
            salt: this.userSalt,
            audience: platformClientId
          }
        }
      });

      if (data.zkLogin.error) {
        throw new Error(`ZK proof generation failed: ${data.zkLogin.error}`);
      }

      return data.zkLogin;
    } catch (error) {
      console.error('ZK Proof Generation Error:', error);
      throw error;
    }
  }

  private async rehydrateZkLoginData() {
    try {
      const credentials = await Keychain.getGenericPassword({
        service: ZKLOGIN_KEYCHAIN_SERVICE,
      });

      if (credentials === false) {
        console.log('No stored credentials found');
        return;
      }

      const data = JSON.parse(credentials.password) as StoredZkLogin;
      
      console.log('Rehydrating zkLogin data:', {
        hasSalt: !!data.salt,
        hasSubject: !!data.subject,
        hasClientId: !!data.clientId,
        hasMaxEpoch: !!data.maxEpoch,
        hasZkProof: !!data.zkProof,
        hasSecretKey: !!data.secretKey,
        hasInitRandomness: !!data.initRandomness,
        hasInitJwt: !!data.initJwt,
        hasAlgorandAddress: !!data.zkProof?.algorandAddress,
        secretKeyLength: data.secretKey?.length
      });

      // Convert base64 secret key to Uint8Array using a more reliable method
      const secretKeyB64 = data.secretKey;
      if (!secretKeyB64) {
        throw new Error('No secret key found in stored data');
      }

      // Create a Uint8Array from the base64 string
      const binaryStr = atob(secretKeyB64);
      const secretKeyBytes = new Uint8Array(binaryStr.length);
      for (let i = 0; i < binaryStr.length; i++) {
        secretKeyBytes[i] = binaryStr.charCodeAt(i);
      }

      console.log('Secret key conversion:', {
        originalLength: secretKeyB64.length,
        binaryLength: binaryStr.length,
        bytesLength: secretKeyBytes.length,
        firstFewBytes: Array.from(secretKeyBytes.slice(0, 4))
      });

      if (secretKeyBytes.length !== 32) {
        throw new Error(`Invalid secret key length: ${secretKeyBytes.length} (expected 32)`);
      }

      // Create the keypair from the secret key
      this.suiKeypair = Ed25519Keypair.fromSecretKey(secretKeyBytes);
      
      // Store the basic data
      this.userSalt = data.salt;
      this.maxEpoch = data.maxEpoch;

      // Store the full proof object with all required fields including aptosAddress
      this.zkProof = {
        zkProof: data.zkProof.zkProof,
        subject: data.subject,
        clientId: data.clientId,
        algorandAddress: data.zkProof.algorandAddress
      };

      // Check if we need to refresh the proof
      if (this.apolloClient) {
        try {
          // Get current epoch from Sui
          const { data: epochData } = await this.apolloClient.query({
            query: gql`
              query GetCurrentEpoch {
                currentEpoch
              }
            `
          });

          const currentEpoch = epochData.currentEpoch;
          console.log('Current epoch:', currentEpoch, 'Max epoch:', this.maxEpoch);

          // Refresh one epoch before expiration to prevent signature failures
          if (currentEpoch >= this.maxEpoch - 1) {
            console.log('zkLogin proof approaching expiration, refreshing proactively...');
            await this.fetchNewProof(this.apolloClient);
          }
        } catch (error) {
          console.error('Error checking epoch or refreshing proof:', error);
          // Don't throw here, as we still have a valid proof for now
        }
      }

      console.log('Successfully rehydrated zkLogin data:', {
        hasKeypair: !!this.suiKeypair,
        hasUserSalt: !!this.userSalt,
        hasZkProof: !!this.zkProof,
        hasMaxEpoch: !!this.maxEpoch,
        proofFields: {
          hasZkProof: !!this.zkProof?.zkProof,
          hasSubject: !!this.zkProof?.subject,
          hasClientId: !!this.zkProof?.clientId,
          hasAlgorandAddress: !!this.zkProof?.algorandAddress
        }
      });
    } catch (error) {
      console.error('Error rehydrating zkLogin data:', error);
      if (error instanceof Error) {
        console.error('Error details:', {
          name: error.name,
          message: error.message,
          stack: error.stack
        });
      }
      throw error;
    }
  }

  private async storeSensitiveData(
    proof: any,
    salt: string,
    subject: string,
    clientId: string,
    maxEpoch: number,
    initRandomness: string,
    initJwt: string
  ) {
    if (!this.suiKeypair) {
      throw new Error('Sui keypair not initialized');
    }

    // Log the incoming proof structure
    console.log('Incoming proof structure:', {
      hasZkProof: !!proof.zkProof,
      hasAlgorandAddress: !!proof.algorandAddress,
      success: proof.success,
      error: proof.error,
      proof: proof
    });

    // Check for server-side errors
    if (!proof.success) {
      throw new Error(proof.error || 'Server error during zkLogin finalization');
    }

    // Get the private key (first 32 bytes of the secret key)
    const secretKey = this.suiKeypair.getSecretKey().slice(0, 32);
    const secretKeyB64 = btoa(String.fromCharCode.apply(null, Array.from(secretKey).map(Number)));

    // Ensure we have a valid Sui address
    if (!proof.algorandAddress) {
      throw new Error('No Algorand address provided in proof');
    }

    // Structure the zkProof data with only required fields
    const structuredProof = {
      zkProof: proof.zkProof,
      subject,
      clientId,
      algorandAddress: proof.algorandAddress,  // Store the Algorand address at the top level
      extendedEphemeralPublicKey: this.suiKeypair.getPublicKey().toBase64(),
      userSignature: bytesToBase64(await this.suiKeypair.sign(new Uint8Array(0)))
    };

    // Store the proof with proper structure
    const toSave: StoredZkLogin = {
      salt,
      subject,
      clientId,
      maxEpoch,
      zkProof: structuredProof,
      secretKey: secretKeyB64,
      initRandomness,
      initJwt
    };

    await Keychain.setGenericPassword(
      ZKLOGIN_KEYCHAIN_USERNAME,
      JSON.stringify(toSave),
      {
        service: ZKLOGIN_KEYCHAIN_SERVICE,
        username: ZKLOGIN_KEYCHAIN_USERNAME,
        accessible: Keychain.ACCESSIBLE.WHEN_UNLOCKED
      }
    );
  }

  // Load sensitive data from secure storage
  private async loadSensitiveData() {
    try {
      const credentials = await Keychain.getGenericPassword({
        service: ZKLOGIN_KEYCHAIN_SERVICE,
      });

      if (credentials) {
        const data = JSON.parse(credentials.password);
        this.suiKeypair = Ed25519Keypair.fromSecretKey(Buffer.from(data.suiKeypair, 'base64'));
        this.userSalt = data.userSalt;
        this.zkProof = data.zkProof;
        this.maxEpoch = Number(data.maxEpoch);
      }
    } catch (error) {
      console.error('Secure Storage Load Error:', error);
      throw error;
    }
  }

  // Get the user's Algorand address (renamed from Sui/Aptos address)
  public async getAlgorandAddress(): Promise<string> {
    if (!this.firebaseIsInitialized) {
      await this.initialize();
    }

    // Get current account context
    const accountManager = AccountManager.getInstance();
    const accountContext = await accountManager.getActiveAccountContext();
    
    console.log('🔎 getAlgorandAddress - Current account context:', {
      type: accountContext.type,
      index: accountContext.index,
      businessId: accountContext.businessId
    });
    
    // Generate cache key for this account
    let cacheKey: string;
    if (accountContext.type === 'business' && accountContext.businessId) {
      cacheKey = `algo_address_business_${accountContext.businessId}_${accountContext.index}`;
    } else {
      cacheKey = `algo_address_${accountContext.type}_${accountContext.index}`;
    }

    // Use a unique service per account to avoid overwrites
    const serviceName = `com.confio.algorand.addresses.${cacheKey}`;
    console.log('🔑 getAlgorandAddress - Using service:', serviceName);

    // Try to get the stored address for this account from Keychain (per-service entry)
    try {
      const credentials = await Keychain.getGenericPassword({ service: serviceName });
      
      if (credentials && credentials.password) {
        const address = credentials.password;
        console.log('Retrieved stored Algorand address for account:', {
          accountType: accountContext.type,
          accountIndex: accountContext.index,
          businessId: accountContext.businessId,
          address: address
        });
        return address;
      }
    } catch (error) {
      console.log('No stored address found, will need to regenerate during sign-in');
    }

    // No stored address for this account
    console.log('No Algorand address found for account:', {
      accountType: accountContext.type,
      accountIndex: accountContext.index,
      businessId: accountContext.businessId,
      cacheKey: cacheKey
    });
    
    // Return empty string or throw error - addresses should be generated during account switch
    // We should NOT fall back to a different account's address
    return ''; // Return empty string to indicate no address yet
  }

  /**
   * Store Algorand address for a specific account context
   */
  async computeAndStoreAlgorandAddress(accountContext: AccountContext): Promise<string> {
    try {
      console.log('🔐 Computing Algorand address for account context:', accountContext);
      
      // Get the Firebase ID token
      const currentUser = this.auth.currentUser;
      if (!currentUser) {
        console.error('No authenticated user');
        return '';
      }
      
      const firebaseIdToken = await currentUser.getIdToken();
      
      // Get OAuth subject from keychain
      const { oauthStorage } = await import('./oauthStorageService');
      const oauthData = await oauthStorage.getOAuthSubject();
      
      if (!oauthData || !oauthData.subject) {
        console.error('No OAuth subject found in keychain');
        return '';
      }
      
      const oauthSubject = oauthData.subject;
      const provider = oauthData.provider;
      
      // Use the secure deterministic wallet service to generate address for this account
      const { SecureDeterministicWalletService } = await import('./secureDeterministicWallet');
      const secureDeterministicWallet = SecureDeterministicWalletService.getInstance();
      
      console.log('🔐 Calling createOrRestoreWallet with:', {
        accountType: accountContext.type,
        accountIndex: accountContext.index,
        businessId: accountContext.businessId,
        provider: provider,
        oauthSubject: oauthSubject.substring(0, 20) + '...'
      });
      
      // Determine issuer and audience consistently (same as switchAccount)
      const GOOGLE_WEB_CLIENT_ID = GOOGLE_CLIENT_IDS.production.web;
      const iss = provider === 'google' ? 'https://accounts.google.com' : 'https://appleid.apple.com';
      const aud = provider === 'google' ? GOOGLE_WEB_CLIENT_ID : 'com.confio.app';

      const wallet = await secureDeterministicWallet.createOrRestoreWallet(
        iss,                    // OAuth issuer
        oauthSubject,           // OAuth subject
        aud,                    // OAuth audience
        provider,               // Provider
        accountContext.type,
        accountContext.index,
        accountContext.businessId
      );
      
      console.log('🎯 Generated Algorand address for account:', {
        accountType: accountContext.type,
        accountIndex: accountContext.index,
        businessId: accountContext.businessId,
        algorandAddress: wallet.address,
      });
      
      // Store the address for this account
      await this.storeAlgorandAddress(wallet.address, accountContext);
      
      // Also update on server
      try {
        const { UPDATE_ACCOUNT_ALGORAND_ADDRESS } = await import('../apollo/queries');
        await apolloClient.mutate({
          mutation: UPDATE_ACCOUNT_ALGORAND_ADDRESS,
          variables: { algorandAddress: wallet.address }
        });
        console.log('Updated server with new address');
      } catch (error) {
        console.error('Failed to update server with address:', error);
        // Continue even if server update fails
      }
      
      return wallet.address;
    } catch (error) {
      console.error('Error computing Algorand address:', error);
      return '';
    }
  }

  private async storeAlgorandAddress(address: string, accountContext: AccountContext): Promise<void> {
    // Generate cache key for this account
    let cacheKey: string;
    if (accountContext.type === 'business' && accountContext.businessId) {
      cacheKey = `algo_address_business_${accountContext.businessId}_${accountContext.index}`;
    } else {
      cacheKey = `algo_address_${accountContext.type}_${accountContext.index}`;
    }

    // Use a unique service per account to avoid overwrites
    const serviceName = `com.confio.algorand.addresses.${cacheKey}`;

    console.log('📝 STORING Algorand address:', {
      service: serviceName,
      cacheKey: cacheKey,
      address: address,
      accountType: accountContext.type,
      accountIndex: accountContext.index,
      businessId: accountContext.businessId
    });

    try {
      await Keychain.setGenericPassword(
        cacheKey,  // username (informational)
        address,   // password - the actual data to store
        {
          service: serviceName,
          accessible: Keychain.ACCESSIBLE.WHEN_UNLOCKED
        }
      );
      console.log('✅ Successfully stored Algorand address for account');
    } catch (error) {
      console.error('❌ Error storing Algorand address:', error);
    }
  }
  
  private async getStoredAlgorandAddress(accountContext: AccountContext): Promise<string | null> {
    // Generate cache key for this account
    let cacheKey: string;
    if (accountContext.type === 'business' && accountContext.businessId) {
      cacheKey = `algo_address_business_${accountContext.businessId}_${accountContext.index}`;
    } else {
      cacheKey = `algo_address_${accountContext.type}_${accountContext.index}`;
    }

    const serviceName = `com.confio.algorand.addresses.${cacheKey}`;
    console.log('🔍 RETRIEVING Algorand address from service:', serviceName);

    try {
      const credentials = await Keychain.getGenericPassword({ service: serviceName });
      
      if (credentials && credentials.password) {
        console.log('✅ Found stored Algorand address:', {
          service: serviceName,
          cacheKey: cacheKey,
          address: credentials.password,
          accountType: accountContext.type,
          accountIndex: accountContext.index,
          businessId: accountContext.businessId
        });
        return credentials.password;
      }
      
      console.log('⚠️ No stored address found for service:', serviceName);
      return null;
    } catch (error) {
      console.error('❌ Error retrieving stored Algorand address:', error);
      return null;
    }
  }

  // Debug utility to clear all Algorand addresses
  async debugClearAllAddresses(): Promise<void> {
    const { clearAllAlgorandAddresses, listStoredAlgorandAddresses } = await import('../utils/clearAlgorandAddresses');
    await listStoredAlgorandAddresses();
    await clearAllAlgorandAddresses();
  }
  
  // Sign out
  async signOut() {
    try {
      console.log('Starting sign out process...');
      
      // 1. Sign out from Firebase (if there's a current user)
      const currentUser = this.auth.currentUser;
      if (currentUser) {
        await this.auth.signOut();
        console.log('Firebase sign out complete');
      } else {
        console.log('No Firebase user to sign out');
      }
      
      // 2. Sign out from Google (if applicable)
      try {
        await GoogleSignin.signOut();
        console.log('Google sign out complete');
      } catch (error) {
        console.log('Google sign out skipped or failed:', error);
      }
      
      // 3. Clear zkLogin data
      await this.clearZkLoginData();
      
      // 4. Get accounts before clearing (for efficient address cleanup)
      const accountManager = AccountManager.getInstance();
      const accounts = await accountManager.getStoredAccounts();
      
      // 5. Clear Algorand wallet data (including encrypted seed cache and stored addresses)
      try {
        const algorandService = (await import('./algorandService')).default;
        await algorandService.clearWallet();
        console.log('Algorand wallet cleared');
        
        // Clear stored Algorand addresses - pass accounts for efficient cleanup
        const { clearAllStoredAlgorandAddresses } = await import('../utils/clearStoredAddresses');
        await clearAllStoredAlgorandAddresses(accounts);
      } catch (error) {
        console.error('Error clearing Algorand wallet:', error);
        // Continue with sign out even if Algorand clearing fails
      }
      
      // 6. Clear account data
      await accountManager.clearAllAccounts();
      
      // 7. Clear stored OAuth subject
      try {
        const { oauthStorage } = await import('./oauthStorageService');
        await oauthStorage.clearOAuthSubject();
        console.log('Cleared stored OAuth subject');
      } catch (error) {
        console.error('Error clearing OAuth subject:', error);
      }
      
      // 8. Clear local state
      this.suiKeypair = null;
      this.userSalt = null;
      this.zkProof = null;
      this.maxEpoch = null;
      this.firebaseIsInitialized = false;
      console.log('Local state cleared');
      
      // 7. Clear all stored credentials from Keychain
      try {
        // Check tokens before clearing
        const preReset = await Keychain.getGenericPassword({
          service: AUTH_KEYCHAIN_SERVICE,
          username: AUTH_KEYCHAIN_USERNAME
        });
        if (preReset === false) {
          console.log('JWT before reset: No credentials');
        } else {
          console.log('JWT before reset:', {
            hasCredentials: true,
            hasPassword: !!preReset.password,
            passwordLength: preReset.password.length
          });
        }

        // Clear zkLogin data - v10 API accepts options object
        await Keychain.resetGenericPassword({
          service: ZKLOGIN_KEYCHAIN_SERVICE
        });
        console.log('Cleared zkLogin data from Keychain');

        // Clear auth tokens
        await Keychain.resetGenericPassword({
          service: AUTH_KEYCHAIN_SERVICE
        });
        console.log('Cleared auth tokens from Keychain');

        // Verify tokens are cleared
        const postReset = await Keychain.getGenericPassword({
          service: AUTH_KEYCHAIN_SERVICE,
          username: AUTH_KEYCHAIN_USERNAME
        });
        if (postReset === false) {
          console.log('JWT after reset: No credentials');
        } else {
          console.log('JWT after reset:', {
            hasCredentials: true,
            hasPassword: !!postReset.password,
            passwordLength: postReset.password.length
          });
          if (postReset.password) {
            throw new Error('Failed to clear tokens from Keychain');
          }
        }
      } catch (keychainError) {
        console.error('Error clearing Keychain:', keychainError);
        // Continue with sign out even if Keychain clearing fails
      }
      
      console.log('Sign out process completed successfully');
    } catch (error) {
      console.error('Sign Out Error:', error);
      // Don't throw the error, just log it and continue with cleanup
      console.log('Continuing with cleanup despite error...');
      
      // Ensure we still clear local state and credentials even if sign out fails
      this.suiKeypair = null;
      this.userSalt = null;
      this.zkProof = null;
      this.maxEpoch = null;
      this.firebaseIsInitialized = false;
      
      // Attempt to clear all Keychain data even if previous operations failed
      // v10 API: resetGenericPassword accepts options object
      try {
        await Keychain.resetGenericPassword({
          service: ZKLOGIN_KEYCHAIN_SERVICE
        });
        await Keychain.resetGenericPassword({
          service: AUTH_KEYCHAIN_SERVICE
        });
      } catch (keychainError) {
        console.error('Error clearing Keychain during error recovery:', keychainError);
      }
    }
  }

  // Get the current Sui keypair
  getSuiKeypair(): Ed25519Keypair | null {
    return this.suiKeypair;
  }

  private async _generateNonce(ephemeralKeyPair: Ed25519Keypair, maxEpoch: string, randomness: string): Promise<string> {
    // Convert base64 randomness to BigInt
    const randomnessBytes = base64ToBytes(randomness);
    
    // Use only first 16 bytes of randomness to ensure it fits in BN254 field
    // This matches what Mysten's generateRandomness does (16 bytes)
    const truncatedRandomness = randomnessBytes.slice(0, 16);
    const randomnessBigInt = BigInt('0x' + bufferToHex(truncatedRandomness));
    
    console.log('Randomness for nonce generation:', {
      originalLength: randomnessBytes.length,
      truncatedLength: truncatedRandomness.length,
      bigIntValue: randomnessBigInt.toString()
    });
    
    // Use Mysten's generateNonce function that computes poseidon hash
    const nonce = generateZkLoginNonce(
      ephemeralKeyPair.getPublicKey(),
      Number(maxEpoch),
      randomnessBigInt
    );
    console.log('Generated zkLogin nonce:', nonce);
    return nonce;
  }

  private deriveEphemeralKeypair(saltB64: string, sub: string, clientId: string): Ed25519Keypair {
    try {
      const saltBytes = base64ToBytes(saltB64);
      const seed = saltBytes.slice(0, 32);
      
      console.log('Derived seed length:', seed.length);
      console.log('Derived seed bytes:', Array.from(seed));
      
      return Ed25519Keypair.fromSecretKey(seed);
    } catch (error) {
      console.error('Error deriving ephemeral keypair:', error);
      throw error;
    }
  }

  private async fetchNewProof(apolloClient: ApolloClient<any>): Promise<void> {
    if (!this.suiKeypair || !this.userSalt || !this.maxEpoch || !this.zkProof) {
      throw new Error("Can't refresh without keypair/salt/proof");
    }

    try {
      // Get stored data to access initJwt and initRandomness
      const credentials = await Keychain.getGenericPassword({
        service: ZKLOGIN_KEYCHAIN_SERVICE
      });

      if (credentials === false) {
        throw new Error("No stored zkLogin data found");
      }

      const stored = JSON.parse(credentials.password) as StoredZkLogin;

      // Get a fresh Firebase token
      const currentUser = this.auth.currentUser;
      if (!currentUser) {
        throw new Error("No Firebase user found");
      }
      const firebaseToken = await currentUser.getIdToken();

      // Get current account context for the refresh
      const accountManager = AccountManager.getInstance();
      const accountContext = await accountManager.getActiveAccountContext();
      
      // Collect fresh device fingerprint for proof refresh
      let deviceFingerprint = null;
      try {
        deviceFingerprint = await DeviceFingerprint.generateFingerprint();
      } catch (error) {
        console.error('Error collecting device fingerprint for refresh:', error);
      }

      // Get a fresh proof from the server
      const { data } = await apolloClient.mutate({
        mutation: FINALIZE_ZKLOGIN,
        variables: {
          input: {
            jwt: stored.initJwt,
            maxEpoch: this.maxEpoch.toString(),
            randomness: stored.initRandomness,
            salt: this.userSalt,
            extendedEphemeralPublicKey: this.suiKeypair.getPublicKey().toBase64(),
            userSignature: bytesToBase64(await this.suiKeypair.sign(new Uint8Array(0))),
            keyClaimName: 'sub',
            audience: this.zkProof.clientId,
            firebaseToken: firebaseToken,
            accountType: accountContext.type,
            accountIndex: accountContext.index,
            deviceFingerprint: deviceFingerprint ? JSON.stringify(deviceFingerprint) : null
          }
        }
      });

      if (data.finalizeZkLogin.error) {
        throw new Error(`Proof refresh failed: ${data.finalizeZkLogin.error}`);
      }

      // Update the stored proof
      this.zkProof = data.finalizeZkLogin.zkProof;
      await this.storeSensitiveData(
        data.finalizeZkLogin.zkProof,
        this.userSalt,
        data.finalizeZkLogin.subject,
        data.finalizeZkLogin.clientId,
        Number(data.finalizeZkLogin.maxEpoch),
        data.finalizeZkLogin.randomness,
        data.finalizeZkLogin.jwt
      );
    } catch (error) {
      console.error('Error refreshing zkLogin proof:', error);
      throw error;
    }
  }

  async getOrCreateSuiAddress(userData: any): Promise<string> {
    try {
      // First, check if user already has a Sui address
      const existingAddress = await this.getUserSuiAddress(userData.uid);
      if (existingAddress) {
        return existingAddress;
      }

      // If no address exists, generate a new one
      const newAddress = await this.generateSuiAddress(userData);
      
      // Store the new address
      await this.storeUserSuiAddress(userData.uid, newAddress);
      
      return newAddress;
    } catch (error) {
      console.error('Error in getOrCreateSuiAddress:', error);
      throw error;
    }
  }

  private async getUserSuiAddress(userId: string): Promise<string | null> {
    // TODO: Implement fetching from your backend
    return null;
  }

  private async generateSuiAddress(userData: any): Promise<string> {
    // TODO: Implement Sui address generation
    // This should use the Sui SDK to generate a new address
    return '0x' + Math.random().toString(16).substring(2, 42); // Placeholder
  }

  private async storeUserSuiAddress(userId: string, address: string): Promise<void> {
    // TODO: Implement storing in your backend
    console.log(`Storing Sui address ${address} for user ${userId}`);
  }

  private async refreshZkLoginProof() {
    if (!this.apolloClient) {
      throw new Error('Apollo client not initialized');
    }
    await this.fetchNewProof(this.apolloClient);
  }

  private async generateZkLoginSalt(iss: string, sub: string, clientId: string, accountContext?: AccountContext): Promise<string> {
    const accountManager = AccountManager.getInstance();
    
    // If no account context provided, get the active one
    if (!accountContext) {
      accountContext = await accountManager.getActiveAccountContext();
    }
    
    console.log('Generating zkLogin salt:', {
      accountType: accountContext.type,
      accountIndex: accountContext.index,
      note: accountContext.type === 'personal' ? 'Personal account (index 0)' : `Business account (index ${accountContext.index})`
    });
    
    // Use the updated salt generation function with account type, business_id, and index
    return generateZkLoginSaltUtil(iss, sub, clientId, accountContext.type, accountContext.businessId || '', accountContext.index);
  }

  /**
   * Create a zkLogin signature for a transaction
   * This method signs transaction bytes with the user's zkLogin credentials
   * 
   * @param transactionBytes - The transaction bytes to sign (base64 encoded)
   * @returns Base64 encoded zkLogin signature
   */
  public async createZkLoginSignatureForTransaction(transactionBytes: string): Promise<string | null> {
    try {
      console.log('AuthService - createZkLoginSignatureForTransaction called');
      
      // Check if we have all required zkLogin data
      if (!this.zkProof || !this.suiKeypair || !this.maxEpoch) {
        console.error('Missing zkLogin data for transaction signing');
        console.error('zkProof:', this.zkProof);
        console.error('suiKeypair:', this.suiKeypair ? 'present' : 'missing');
        console.error('maxEpoch:', this.maxEpoch);
        return null;
      }
      
      // Log zkProof structure for debugging
      console.log('zkProof structure:', JSON.stringify(this.zkProof, null, 2));

      // Decode transaction bytes
      const txBytes = base64ToBytes(transactionBytes);
      
      // Sign the transaction with ephemeral key
      const ephemeralSignature = await this.suiKeypair.sign(txBytes);
      const ephemeralSigBase64 = bytesToBase64(ephemeralSignature);
      
      // Get the stored zkLogin data
      const storedData = await this.getStoredZkLoginData();
      if (!storedData) {
        console.error('No stored zkLogin data found');
        return null;
      }

      // Create the zkLogin signature structure
      // This combines the zkProof with the ephemeral signature
      const zkLoginSignature = {
        signature: ephemeralSigBase64,
        publicKey: this.suiKeypair.getPublicKey().toBase64(),
        zkProof: this.zkProof,
        maxEpoch: this.maxEpoch,
        userSignature: ephemeralSigBase64
      };

      // For now, we'll use the Sui SDK's getZkLoginSignature if available
      // In production, this would properly format the zkLogin signature
      // Check if zkProof has nested zkProof property (from backend response)
      let zkProofData = this.zkProof.zkProof || this.zkProof;
      
      // Remove __typename field if present (GraphQL artifact)
      if (zkProofData.__typename) {
        zkProofData = {
          a: zkProofData.a,
          b: zkProofData.b,
          c: zkProofData.c
        };
      }
      
      // Validate zkProof structure
      if (!zkProofData || typeof zkProofData !== 'object') {
        console.error('Invalid zkProof structure:', zkProofData);
        return null;
      }
      
      // Ensure we have all required proof fields
      if (!zkProofData.a || !zkProofData.b || !zkProofData.c) {
        console.error('zkProof missing required fields. Keys:', Object.keys(zkProofData));
        return null;
      }
      
      // Log all parameters before calling getZkLoginSignature
      console.log('getZkLoginSignature parameters:');
      console.log('- signature type:', typeof ephemeralSignature, 'value:', ephemeralSignature);
      console.log('- publicKey:', this.suiKeypair.getPublicKey());
      console.log('- zkProof keys:', Object.keys(zkProofData));
      console.log('- maxEpoch type:', typeof this.maxEpoch, 'value:', this.maxEpoch);
      
      // For transaction signing with zkLogin, we need to send complete data
      // Since the zkProof is kept client-side, we need to send it along
      
      try {
        // Create a complete zkLogin signature package
        const zkLoginData = {
          ephemeralSignature: ephemeralSigBase64,
          ephemeralPublicKey: this.extendedEphemeralPublicKey || this.suiKeypair.getPublicKey().toBase64(),
          zkProof: zkProofData,
          maxEpoch: this.maxEpoch,
          subject: storedData.subject || this.zkProof.subject,
          audience: storedData.clientId || this.zkProof.clientId || 'apple',
          userSalt: storedData.userSalt || this.userSalt,
          randomness: storedData.initRandomness || this.randomness,
          jwt: storedData.initJwt  // Include the JWT for server-side zkProof regeneration
        };
        
        // Return the complete zkLogin data as base64
        const dataBytes = new TextEncoder().encode(JSON.stringify(zkLoginData));
        console.log('Returning complete zkLogin data for transaction');
        return bytesToBase64(dataBytes);
      } catch (signatureError) {
        console.error('Error in getZkLoginSignature:', signatureError);
        console.error('zkProofData:', JSON.stringify(zkProofData, null, 2));
        console.error('maxEpoch:', this.maxEpoch);
        throw signatureError;
      }
      
    } catch (error) {
      console.error('Error creating zkLogin signature:', error);
      return null;
    }
  }

  private async storeTokens(tokens: TokenStorage): Promise<void> {
    try {
      console.log('Storing tokens:', {
        hasAccessToken: !!tokens.accessToken,
        hasRefreshToken: !!tokens.refreshToken,
        accessTokenLength: tokens.accessToken?.length,
        refreshTokenLength: tokens.refreshToken?.length
      });

      // First verify the tokens before storing
      if (!tokens.accessToken || !tokens.refreshToken) {
        throw new Error('Invalid token format: missing access or refresh token');
      }

      // Verify token types
      try {
        const accessDecoded = jwtDecode<CustomJwtPayload>(tokens.accessToken);
        const refreshDecoded = jwtDecode<CustomJwtPayload>(tokens.refreshToken);

        if (accessDecoded.type !== 'access' || refreshDecoded.type !== 'refresh') {
          throw new Error('Invalid token types');
        }
      } catch (error) {
        console.error('Error verifying token types:', error);
        throw new Error('Invalid token format or type');
      }

      // Store the tokens
      const result = await Keychain.setGenericPassword(
        AUTH_KEYCHAIN_USERNAME,
        JSON.stringify(tokens),
        {
          service: AUTH_KEYCHAIN_SERVICE,
          username: AUTH_KEYCHAIN_USERNAME,
          accessible: Keychain.ACCESSIBLE.WHEN_UNLOCKED
        }
      );

      console.log('Token storage result:', result);

      // Verify the tokens were stored correctly
      const stored = await Keychain.getGenericPassword({
        service: AUTH_KEYCHAIN_SERVICE,
        username: AUTH_KEYCHAIN_USERNAME
      });

      if (stored === false) {
        throw new Error('Failed to verify token storage');
      } else {
        const storedTokens = JSON.parse(stored.password);
        if (!storedTokens.accessToken || !storedTokens.refreshToken) {
          throw new Error('Invalid token format in storage');
        }
        console.log('Tokens stored and verified successfully:', {
          hasAccessToken: !!storedTokens.accessToken,
          hasRefreshToken: !!storedTokens.refreshToken,
          accessTokenLength: storedTokens.accessToken.length,
          refreshTokenLength: storedTokens.refreshToken.length
        });
      }
    } catch (error) {
      console.error('Error storing tokens:', error);
      throw error;
    }
  }

  private async getStoredTokens(): Promise<TokenStorage | null> {
    try {
      console.log('Attempting to retrieve tokens from Keychain');
      
      const credentials = await Keychain.getGenericPassword({
        service: AUTH_KEYCHAIN_SERVICE,
        username: AUTH_KEYCHAIN_USERNAME
      });

      if (credentials === false) {
        console.log('No credentials found in Keychain');
        return null;
      } else {
        const { password } = credentials;
        console.log('Found credentials in Keychain:', {
          hasPassword: !!password,
          passwordLength: password.length
        });

        const tokens = JSON.parse(password);
        
        console.log('Parsed tokens:', {
          hasAccessToken: !!tokens.accessToken,
          hasRefreshToken: !!tokens.refreshToken,
          accessTokenLength: tokens.accessToken?.length,
          refreshTokenLength: tokens.refreshToken?.length
        });

        if (!tokens.accessToken || !tokens.refreshToken) {
          console.error('Invalid token format: missing access or refresh token');
          return null;
        }

        // Verify token types
        try {
          const accessDecoded = jwtDecode<CustomJwtPayload>(tokens.accessToken);
          const refreshDecoded = jwtDecode<CustomJwtPayload>(tokens.refreshToken);

          if (accessDecoded.type !== 'access' || refreshDecoded.type !== 'refresh') {
            console.error('Invalid token types:', {
              accessType: accessDecoded.type,
              refreshType: refreshDecoded.type
            });
            return null;
          }

          console.log('Tokens verified successfully');
          return tokens;
        } catch (error) {
          console.error('Error verifying token types:', error);
          return null;
        }
      }
    } catch (error) {
      console.error('Error retrieving tokens:', error);
      return null;
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

  /**
   * Get the currently active account context
   */
  public async getActiveAccountContext(): Promise<AccountContext> {
    const accountManager = AccountManager.getInstance();
    try {
      return await accountManager.getActiveAccountContext();
    } catch (error) {
      console.error('Error getting active account context, resetting to default:', error);
      // Reset corrupted active account data
      try {
        await accountManager.resetActiveAccount();
      } catch (resetError) {
        console.error('Error resetting active account:', resetError);
      }
      // Return default context
      return accountManager.getDefaultAccountContext();
    }
  }

  /**
   * Set the active account context
   */
  public async setActiveAccountContext(context: AccountContext): Promise<void> {
    const accountManager = AccountManager.getInstance();
    await accountManager.setActiveAccountContext(context);
  }

  /**
   * Get all stored accounts
   */
  public async getStoredAccounts(): Promise<any[]> {
    const accountManager = AccountManager.getInstance();
    return await accountManager.getStoredAccounts();
  }

  /**
   * Create a new account
   * NOTE: This method is deprecated. Account creation should be done through server mutations.
   * This method is kept for backward compatibility but should not be used for new business accounts.
   */
  public async createAccount(
    name: string,
    avatar: string,
    phone?: string,
    category?: string
  ): Promise<any> {
    console.warn('AuthService.createAccount is deprecated. Use server mutations for account creation.');
    
    // For backward compatibility, return a mock account
    // This should not be used for actual account creation
    return {
      id: 'deprecated_method',
      type: 'business',
      index: 0,
      name: name,
      avatar: avatar,
      phone: phone,
      category: category
    };
  }

  /**
   * Switch to a different account
   * Note: zkLogin data is user-level, not account-level, so we don't clear it
   */
  public async switchAccount(accountId: string, apolloClient?: any): Promise<void> {
    const accountManager = AccountManager.getInstance();
    
    console.log('AuthService - switchAccount called with accountId:', accountId);
    
    // Parse the account ID to extract type, businessId (if present), and index
    let accountContext: AccountContext;
    
    if (accountId === 'personal_0') {
      // Personal account
      accountContext = {
        type: 'personal',
        index: 0
      };
    } else if (accountId.startsWith('business_')) {
      // Business account format: business_{businessId}_0
      const parts = accountId.split('_');
      if (parts.length >= 3) {
        const businessId = parts[1];
        const index = parseInt(parts[2]) || 0;
        
        accountContext = {
          type: 'business',
          index: index,
          businessId: businessId // Required for salt generation
        };
        
        console.log('AuthService - Parsed business account with businessId:', {
          accountId,
          businessId,
          index,
          contextBusinessId: accountContext.businessId
        });
      } else {
        // Fallback for simple business_0 format
        accountContext = {
          type: 'business',
          index: 0
        };
        
        console.log('AuthService - Fallback business account (no businessId):', {
          accountId,
          type: 'business',
          index: 0
        });
      }
    } else {
      // Fallback - extract type and index
      const [accountType, indexStr] = accountId.split('_');
      const accountIndex = parseInt(indexStr) || 0;
      
      accountContext = {
        type: accountType as 'personal' | 'business',
        index: accountIndex
      };
    }
    
    console.log('AuthService - Parsed account context:', {
      accountId: accountId,
      accountType: accountContext.type,
      accountIndex: accountContext.index,
      note: accountContext.type === 'personal' ? 'Personal account (index 0)' : `Business account (index ${accountContext.index})`
    });
    
    // Set the new active account context
    await accountManager.setActiveAccountContext(accountContext);
    
    console.log('AuthService - Active account context set');
    
    // If apolloClient is provided, get a new JWT token with the updated account context
    if (apolloClient) {
      try {
        const { SWITCH_ACCOUNT_TOKEN } = await import('../apollo/queries');
        
        const variables: any = {
          accountType: accountContext.type,
          accountIndex: accountContext.index
        };
        
        // Add businessId for employee accounts switching to business accounts
        if (accountContext.businessId) {
          variables.businessId = accountContext.businessId;
          console.log('AuthService - Added businessId to variables:', {
            businessId: accountContext.businessId,
            businessIdType: typeof accountContext.businessId
          });
        } else {
          console.log('AuthService - No businessId in accountContext:', {
            accountContextType: accountContext.type,
            accountContextIndex: accountContext.index,
            accountContextBusinessId: accountContext.businessId,
            hasBusinessId: !!accountContext.businessId
          });
        }
        
        console.log('AuthService - Calling SWITCH_ACCOUNT_TOKEN with variables:', variables);
        
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
          await Keychain.setGenericPassword(
            AUTH_KEYCHAIN_USERNAME,
            JSON.stringify({
              accessToken: data.switchAccountToken.token,
              refreshToken: refreshToken
            }),
            {
              service: AUTH_KEYCHAIN_SERVICE,
              username: AUTH_KEYCHAIN_USERNAME,
              accessible: Keychain.ACCESSIBLE.WHEN_UNLOCKED
            }
          );
          
          console.log('AuthService - Updated JWT token stored');
        }
      } catch (error) {
        console.error('Error getting new JWT token for account switch:', error);
        // Continue anyway - the account context is set locally
      }
    }
    
    // Note: We do NOT clear zkLogin data because:
    // 1. zkLogin authentication is user-level, not account-level
    // 2. The same user can have multiple accounts (personal + business)
    // 3. All accounts share the same zkLogin authentication
    // 4. Only the salt generation changes based on account context
    
    // Generate new Algorand address for the switched account context
    try {
      console.log('AuthService - Generating Algorand address for account:', {
        accountId: accountId,
        accountType: accountContext.type,
        accountIndex: accountContext.index,
        businessId: accountContext.businessId
      });
      
      // Generate address for the new account
      // Get the Firebase UID and OAuth subject from stored zkLogin data
      const zkCredentials = await Keychain.getGenericPassword({
        service: ZKLOGIN_KEYCHAIN_SERVICE,
        username: ZKLOGIN_KEYCHAIN_USERNAME
      });
        
        // First, try to retrieve stored address for this account
        const storedAddress = await this.getStoredAlgorandAddress(accountContext);
        
        if (storedAddress) {
          console.log('AuthService - Using stored Algorand address for account:', {
            accountId: accountId,
            address: storedAddress
          });
          
          // Update the backend with the stored address if needed
          if (apolloClient) {
            try {
              const { UPDATE_ACCOUNT_ALGORAND_ADDRESS } = await import('../apollo/queries');
              await apolloClient.mutate({
                mutation: UPDATE_ACCOUNT_ALGORAND_ADDRESS,
                variables: { algorandAddress: storedAddress }
              });
              console.log('AuthService - Updated backend with stored Algorand address');
            } catch (updateError) {
              console.error('AuthService - Error updating backend with Algorand address:', updateError);
            }
          }
          return; // Address already exists, no need to generate
        }
        
        // Get OAuth subject from secure storage (only needed if no stored address)
        const { oauthStorage } = await import('./oauthStorageService');
        const oauthData = await oauthStorage.getOAuthSubject();
        
        if (!oauthData) {
          console.error('No OAuth subject found in secure storage - cannot generate address for new account');
          return; // Cannot generate without OAuth subject
        }
        
        const oauthSubject = oauthData.subject;
        const provider = oauthData.provider;
        
        // Use the secure deterministic wallet service to generate address for this account
        const { SecureDeterministicWalletService } = await import('./secureDeterministicWallet');
        const secureDeterministicWallet = SecureDeterministicWalletService.getInstance();
        
        // Get the actual Google web client ID from environment config
        const { GOOGLE_CLIENT_IDS } = await import('../config/env');
        const GOOGLE_WEB_CLIENT_ID = GOOGLE_CLIENT_IDS.production.web;
        
        // Determine the OAuth issuer and audience based on provider
        const iss = provider === 'google' ? 'https://accounts.google.com' : 'https://appleid.apple.com';
        const aud = provider === 'google' ? GOOGLE_WEB_CLIENT_ID : 'com.confio.app';
        
        console.log('🔐 CALLING createOrRestoreWallet with OAuth claims:', {
          iss,
          sub: oauthSubject.substring(0, 20) + '...',
          aud: aud.substring(0, 20) + '...',
          accountType: accountContext.type,
          accountIndex: accountContext.index,
          businessId: accountContext.businessId,
          provider: provider
        });
        
        const wallet = await secureDeterministicWallet.createOrRestoreWallet(
          iss,                    // OAuth issuer
          oauthSubject,           // OAuth subject
          aud,                    // OAuth audience (Google web client ID or Apple bundle ID)
          provider,
          accountContext.type,    // Use the actual account type (personal or business)
          accountContext.index,   // Use the actual account index
          accountContext.businessId // Pass the businessId for business accounts
        );
          
          console.log('🎯 GENERATED NEW Algorand address for account:', {
            accountId: accountId,
            accountType: accountContext.type,
            accountIndex: accountContext.index,
            businessId: accountContext.businessId,
            algorandAddress: wallet.address,
            provider: provider,
            isUnique: wallet.address !== 'U3A3SWOU7NHMS6UWZ3KCE5DHNYIFYQ2F4GASYJXCTYUQZ7FLUFD2ICVXUU' ? '✅ UNIQUE' : '❌ DUPLICATE'
          });
          
          // Store the address in keychain for future use
          await this.storeAlgorandAddress(wallet.address, accountContext);
          
          // Update the current account's Algorand address in the backend if needed
          if (apolloClient) {
            try {
              const { UPDATE_ACCOUNT_ALGORAND_ADDRESS } = await import('../apollo/queries');
              await apolloClient.mutate({
                mutation: UPDATE_ACCOUNT_ALGORAND_ADDRESS,
                variables: { algorandAddress: wallet.address }
              });
              console.log('AuthService - Updated backend with new Algorand address');
            } catch (updateError) {
              console.error('AuthService - Error updating backend with Algorand address:', updateError);
              // Non-fatal error - continue
            }
          }
    } catch (error) {
      console.error('AuthService - Error generating Algorand address for account switch:', error);
      // Non-fatal error - continue with the switch
    }
    
    // Verify that the address changes for the new account context
    try {
      const newAlgorandAddress = await this.getAlgorandAddress();
      console.log('AuthService - Account switch completed with address:', {
        accountId: accountId,
        accountType: accountContext.type,
        accountIndex: accountContext.index,
        address: newAlgorandAddress,
        note: accountContext.type === 'personal' ? 'Personal account (index 0)' : `Business account (index ${accountContext.index})`
      });
    } catch (error) {
      console.error('AuthService - Error getting new address after account switch:', error);
    }
  }

  /**
   * Initialize default account if no accounts exist
   */
  public async initializeDefaultAccount(): Promise<any> {
    const accountManager = AccountManager.getInstance();
    return await accountManager.initializeDefaultAccount();
  }

  /**
   * Check if we need to initialize a default account and create one if needed
   * This should only be called after proper zkLogin authentication
   */
  private async initializeDefaultAccountIfNeeded(): Promise<void> {
    try {
      const accountManager = AccountManager.getInstance();
      const storedAccounts = await accountManager.getStoredAccounts();
      
      console.log('AuthService - Checking if default account initialization is needed:', {
        storedAccountsCount: storedAccounts.length,
        storedAccounts: storedAccounts.map(acc => ({ id: acc.id, type: acc.type, index: acc.index }))
      });
      
      // Also check if there's an active account context that might indicate an account exists
      try {
        const activeContext = await accountManager.getActiveAccountContext();
        console.log('AuthService - Current active account context:', {
          activeContextType: activeContext.type,
          activeContextIndex: activeContext.index,
          activeAccountId: accountManager.generateAccountId(activeContext.type, activeContext.index)
        });
      } catch (error) {
        console.log('AuthService - No active account context found');
      }
      
      if (storedAccounts.length === 0) {
        console.log('AuthService - No accounts found, but not creating default account');
        console.log('AuthService - Note: Accounts should only be created after proper zkLogin authentication');
        return;
      } else {
        console.log('AuthService - Accounts already exist, no default initialization needed');
      }
    } catch (error) {
      console.error('AuthService - Error checking default account initialization:', error);
      // Don't throw error, just log it
    }
  }

  public async signIn(email: string, password: string): Promise<void> {
    try {
      // TODO: Replace with actual API call
      const response = await fetch('YOUR_API_ENDPOINT/login', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ email, password }),
      });

      if (!response.ok) {
        throw new Error('Login failed');
      }

      const data = await response.json();
      await this.storeTokens({
        accessToken: data.token,
        refreshToken: data.refreshToken
      });
    } catch (error) {
      console.error('Sign in error:', error);
      throw error;
    }
  }
}

// Export a singleton instance
const authService = AuthService.getInstance();
export default authService; 
