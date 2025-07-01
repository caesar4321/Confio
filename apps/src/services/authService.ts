import { GoogleSignin, User } from '@react-native-google-signin/google-signin';
import { Ed25519Keypair } from '@mysten/sui/keypairs/ed25519';
import { genAddressSeed, getZkLoginSignature } from '@mysten/sui/zklogin';
import { SuiClient } from '@mysten/sui/client';
import { jwtDecode } from 'jwt-decode';
import * as Keychain from 'react-native-keychain';
import { GOOGLE_CLIENT_IDS, API_URL } from '../config/env';
import auth from '@react-native-firebase/auth';
import { Platform } from 'react-native';
import { INITIALIZE_ZKLOGIN, FINALIZE_ZKLOGIN } from '../apollo/queries';
import { apolloClient } from '../apollo/client';
import { gql } from '@apollo/client';
import { Buffer } from 'buffer';
import { sha256 } from '@noble/hashes/sha256';
import { base64ToBytes, bytesToBase64, stringToUtf8Bytes, bufferToHex } from '../utils/encoding';
import { ApolloClient } from '@apollo/client';
import { AccountManager, AccountContext } from '../utils/accountManager';
import { generateZkLoginSalt as generateZkLoginSaltUtil } from '../utils/zkLogin';

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
    suiAddress: string;  // the user's Sui address
  };
  secretKey: string;     // base64-encoded 32-byte seed
  initRandomness: string; // randomness from initializeZkLogin
  initJwt: string;       // original JWT from sign-in
}

export const ZKLOGIN_KEYCHAIN_SERVICE = 'com.confio.zklogin';
export const AUTH_KEYCHAIN_SERVICE = 'com.confio.auth';
const ZKLOGIN_KEYCHAIN_USERNAME = 'zkLoginData';
export const AUTH_KEYCHAIN_USERNAME = 'auth_tokens';

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

  async signInWithGoogle() {
    try {
      console.log('Starting Google Sign-In process...');
      
      // 1) Sign in with Google first
      console.log('Checking Play Services...');
      await GoogleSignin.hasPlayServices();
      console.log('Play Services check passed');
      
      console.log('Attempting Google Sign-In...');
      const userInfo = await GoogleSignin.signIn();
      console.log('Google Sign-In response:', userInfo);
      
      if (!userInfo) {
        throw new Error('No user info returned from Google Sign-In');
      }

      // 2) Get the ID token after successful sign-in
      console.log('Getting Google ID token...');
      const { idToken } = await GoogleSignin.getTokens();
      console.log('Got ID token:', idToken ? 'Token received' : 'No token');
      
      if (!idToken) {
        throw new Error('No ID token received from Google Sign-In');
      }

      // 3) Sign in with Firebase using the Google credential
      console.log('Creating Firebase credential...');
      const firebaseCred = auth.GoogleAuthProvider.credential(idToken);
      console.log('Signing in with Firebase...');
      const { user } = await this.auth.signInWithCredential(firebaseCred);
      console.log('Firebase sign-in response:', user ? 'User received' : 'No user');
      
      if (!user) {
        throw new Error('No user returned from Firebase sign-in');
      }

      console.log('Getting Firebase ID token...');
      const firebaseToken = await user.getIdToken();
      console.log('Firebase token received');

      // 4) Initialize zkLogin
      console.log('Initializing zkLogin...');
      const { data: { initializeZkLogin: init } } = await apolloClient.mutate({
        mutation: INITIALIZE_ZKLOGIN,
        variables: { firebaseToken, providerToken: idToken, provider: 'google' }
      });
      console.log('zkLogin initialization response:', init ? 'Data received' : 'No data');

      if (!init) {
        throw new Error('No data received from zkLogin initialization');
      }

      // Store Django JWT tokens for authenticated requests using Keychain
      if (init.authAccessToken) {
        console.log('About to store tokens in Keychain:', {
          service: AUTH_KEYCHAIN_SERVICE,
          username: AUTH_KEYCHAIN_USERNAME,
          hasAccessToken: !!init.authAccessToken,
          hasRefreshToken: !!init.authRefreshToken,
          accessTokenLength: init.authAccessToken?.length,
          refreshTokenLength: init.authRefreshToken?.length
        });

        try {
          await Keychain.setGenericPassword(
            AUTH_KEYCHAIN_USERNAME,
            JSON.stringify({
              accessToken: init.authAccessToken,
              refreshToken: init.authRefreshToken
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
        console.error('No auth tokens received from initializeZkLogin');
        throw new Error('No auth tokens received from server');
      }

      const maxEpochNum = Number(init.maxEpoch);
      if (isNaN(maxEpochNum)) {
        throw new Error('Invalid maxEpoch value received from server');
      }

      // 5) Decode JWT and generate salt
      const decodedJwt = jwtDecode<{ sub: string, iss: string }>(idToken);
      if (!decodedJwt.sub || !decodedJwt.iss) {
        throw new Error('Invalid JWT: missing sub or iss claim');
      }

      // Generate salt on client side
      const salt = await this.generateZkLoginSalt(decodedJwt.iss, decodedJwt.sub, GOOGLE_CLIENT_IDS.production.web);
      console.log('Generated client-side salt:', salt);
      
      // Get current account context for logging
      const accountManager = AccountManager.getInstance();
      const accountContext = await accountManager.getActiveAccountContext();
      console.log('Account context for salt generation:', {
        accountType: accountContext.type,
        accountIndex: accountContext.index,
        accountId: accountManager.generateAccountId(accountContext.type, accountContext.index)
      });

      // 6) Derive ephemeral keypair
      this.suiKeypair = this.deriveEphemeralKeypair(salt, decodedJwt.sub, GOOGLE_CLIENT_IDS.production.web);

      // 7) Finalize zkLogin
      const extendedPub = this.suiKeypair.getPublicKey().toBase64();
      const userSig = bytesToBase64(await this.suiKeypair.sign(new Uint8Array(0)));
      const { data: { finalizeZkLogin: fin } } = await apolloClient.mutate({
        mutation: FINALIZE_ZKLOGIN,
        variables: {
          input: {
            jwt: idToken,
            maxEpoch: init.maxEpoch,
            randomness: init.randomness,
            salt: salt,
            extendedEphemeralPublicKey: extendedPub,
            userSignature: userSig,
            keyClaimName: 'sub',
            audience: GOOGLE_CLIENT_IDS.production.web,
            firebaseToken: firebaseToken
          }
        }
      });

      if (!fin) {
        throw new Error('No data received from zkLogin finalization');
      }

      // 8) Store sensitive data securely
      console.log('Storing sensitive data...');
      await this.storeSensitiveData(fin, salt, decodedJwt.sub, GOOGLE_CLIENT_IDS.production.web, maxEpochNum, init.randomness, idToken);
      console.log('Sensitive data stored successfully');

      // 9) Automatically create default personal account after successful zkLogin
      console.log('Creating default personal account...');
      try {
        const accountManager = AccountManager.getInstance();
        const storedAccounts = await accountManager.getStoredAccounts();
        
        if (storedAccounts.length === 0) {
          // Create default personal account with user data
          const [firstName, ...lastNameParts] = user.displayName?.split(' ') || [];
          const lastName = lastNameParts.join(' ');
          const displayName = user.displayName || user.email || 'Mi Cuenta';
          
          const defaultAccount = await accountManager.createAccount(
            'personal',
            displayName,
            displayName.charAt(0).toUpperCase(),
            user.phoneNumber || undefined,
            undefined
          );
          
          // Set as active account
          await accountManager.setActiveAccountContext({
            type: 'personal',
            index: 0
          });
          
          console.log('Default personal account created successfully:', {
            accountId: defaultAccount.id,
            accountName: defaultAccount.name,
            accountType: defaultAccount.type,
            accountIndex: defaultAccount.index
          });
        } else {
          console.log('Accounts already exist, skipping default account creation');
        }
      } catch (accountError) {
        console.error('Error creating default account:', accountError);
        // Don't throw here - account creation failure shouldn't break the sign-in flow
      }

      // Split display name into first and last name
      const [firstName, ...lastNameParts] = user.displayName?.split(' ') || [];
      const lastName = lastNameParts.join(' ');

      // 10) Return user info and zkLogin data
      const result = {
        userInfo: { 
          email: user.email, 
          firstName: firstName || '',
          lastName: lastName || '',
          photoURL: user.photoURL 
        },
        zkLoginData: { 
          zkProof: fin.zkProof, 
          suiAddress: fin.suiAddress,
          isPhoneVerified: fin.isPhoneVerified 
        }
      };
      console.log('Sign-in process completed successfully:', result);
      return result;
    } catch (error) {
      console.error('Error signing in with Google:', error);
      if (error instanceof Error) {
        console.error('Error name:', error.name);
        console.error('Error message:', error.message);
        console.error('Error stack:', error.stack);
      }
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

  async clearZkLoginData() {
    try {
      await Keychain.resetGenericPassword({
        service: ZKLOGIN_KEYCHAIN_SERVICE,
      });
    } catch (error) {
      console.error('Error clearing zkLogin data:', error);
      throw error;
    }
  }

  // Apple Sign-In
  public async signInWithApple() {
    if (Platform.OS !== 'ios') {
      throw new Error('Apple Sign In is only supported on iOS');
    }

    try {
      if (!apolloClient) {
        throw new Error('Apollo client not initialized');
      }
      const { appleAuth } = await import('@invertase/react-native-apple-authentication');
      
      const appleAuthRequestResponse = await appleAuth.performRequest({
        requestedOperation: appleAuth.Operation.LOGIN,
        requestedScopes: [appleAuth.Scope.EMAIL, appleAuth.Scope.FULL_NAME],
      });

      console.log('Apple authentication successful');

      if (!appleAuthRequestResponse.identityToken) {
        throw new Error('No identity token received from Apple');
      }

      // Create Firebase credential with Apple token
      const { identityToken, nonce: appleAuthNonce } = appleAuthRequestResponse;
      const decodedAppleJwt = jwtDecode<{ sub: string, iss: string }>(identityToken);
      if (!decodedAppleJwt.sub || !decodedAppleJwt.iss) {
        throw new Error('Invalid Apple JWT: missing sub or iss claim');
      }
      const appleSub = decodedAppleJwt.sub;
      const appleCredential = auth.AppleAuthProvider.credential(identityToken, appleAuthNonce);
      console.log('Created Firebase credential');

      // Sign in with Firebase using the Apple credential
      const userCredential = await this.auth.signInWithCredential(appleCredential);
      console.log('Firebase sign-in successful:', userCredential.user);

      // Get the ID token for zkLogin
      const firebaseToken = await userCredential.user.getIdToken();
      console.log('Got Firebase ID token');

      // Initialize zkLogin with the Firebase token
      console.log('Initializing zkLogin...');
      const { data: initData } = await apolloClient.mutate({
        mutation: INITIALIZE_ZKLOGIN,
        variables: {
          firebaseToken,
          providerToken: identityToken,
          provider: 'apple'
        }
      });

      if (!initData?.initializeZkLogin) {
        throw new Error('No data received from zkLogin initialization');
      }

      // Store Django JWT tokens for authenticated requests using Keychain
      if (initData.initializeZkLogin.authAccessToken) {
        console.log('About to store tokens in Keychain (Apple):', {
          service: AUTH_KEYCHAIN_SERVICE,
          username: AUTH_KEYCHAIN_USERNAME,
          hasAccessToken: !!initData.initializeZkLogin.authAccessToken,
          hasRefreshToken: !!initData.initializeZkLogin.authRefreshToken,
          accessTokenLength: initData.initializeZkLogin.authAccessToken?.length,
          refreshTokenLength: initData.initializeZkLogin.authRefreshToken?.length
        });

        try {
          await Keychain.setGenericPassword(
            AUTH_KEYCHAIN_USERNAME,
            JSON.stringify({
              accessToken: initData.initializeZkLogin.authAccessToken,
              refreshToken: initData.initializeZkLogin.authRefreshToken
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
        console.error('No auth tokens received from initializeZkLogin');
        throw new Error('No auth tokens received from server');
      }

      const { maxEpoch, randomness: serverRandomness } = initData.initializeZkLogin;
      
      // Generate salt on client side
      const salt = await this.generateZkLoginSalt(decodedAppleJwt.iss, appleSub, 'apple');
      console.log('Generated client-side salt:', salt);
      
      // Get current account context for logging
      const accountManager = AccountManager.getInstance();
      const accountContext = await accountManager.getActiveAccountContext();
      console.log('Account context for salt generation (Apple):', {
        accountType: accountContext.type,
        accountIndex: accountContext.index,
        accountId: accountManager.generateAccountId(accountContext.type, accountContext.index)
      });

      // Derive the single, deterministic ephemeral keypair
      this.suiKeypair = this.deriveEphemeralKeypair(salt, appleSub, 'apple');

      // Get the extended ephemeral public key (now deterministic)
      const extendedEphemeralPublicKey = this.suiKeypair.getPublicKey().toBase64();

      // Finalize zkLogin
      const { data: finalizeData } = await apolloClient.mutate({
        mutation: FINALIZE_ZKLOGIN,
        variables: {
          input: {
            extendedEphemeralPublicKey,
            jwt: identityToken,
            maxEpoch: maxEpoch.toString(),
            randomness: serverRandomness,
            salt: salt,
            userSignature: bytesToBase64(await this.suiKeypair.sign(new Uint8Array(0))),
            keyClaimName: 'sub',
            audience: 'apple',
            firebaseToken: firebaseToken
          }
        }
      });

      if (!finalizeData?.finalizeZkLogin) {
        throw new Error('No data received from zkLogin finalization');
      }

      // Store sensitive data securely
      await this.storeSensitiveData(
        finalizeData.finalizeZkLogin,
        salt,
        appleSub,
        'apple',
        Number(maxEpoch),
        serverRandomness,
        identityToken
      );

      // Automatically create default personal account after successful zkLogin
      console.log('Creating default personal account (Apple)...');
      try {
        const accountManager = AccountManager.getInstance();
        const storedAccounts = await accountManager.getStoredAccounts();
        
        if (storedAccounts.length === 0) {
          // Create default personal account with user data
          const [firstName, ...lastNameParts] = userCredential.user.displayName?.split(' ') || [];
          const lastName = lastNameParts.join(' ');
          const displayName = userCredential.user.displayName || userCredential.user.email || 'Mi Cuenta';
          
          const defaultAccount = await accountManager.createAccount(
            'personal',
            displayName,
            displayName.charAt(0).toUpperCase(),
            userCredential.user.phoneNumber || undefined,
            undefined
          );
          
          // Set as active account
          await accountManager.setActiveAccountContext({
            type: 'personal',
            index: 0
          });
          
          console.log('Default personal account created successfully (Apple):', {
            accountId: defaultAccount.id,
            accountName: defaultAccount.name,
            accountType: defaultAccount.type,
            accountIndex: defaultAccount.index
          });
        } else {
          console.log('Accounts already exist, skipping default account creation (Apple)');
        }
      } catch (accountError) {
        console.error('Error creating default account (Apple):', accountError);
        // Don't throw here - account creation failure shouldn't break the sign-in flow
      }

      // Split display name into first and last name
      const [firstName, ...lastNameParts] = userCredential.user.displayName?.split(' ') || [];
      const lastName = lastNameParts.join(' ');

      return {
        userInfo: {
          email: userCredential.user.email,
          firstName: firstName || '',
          lastName: lastName || '',
          photoURL: userCredential.user.photoURL
        },
        zkLoginData: {
          zkProof: finalizeData.finalizeZkLogin.zkProof,
          suiAddress: finalizeData.finalizeZkLogin.suiAddress,
          isPhoneVerified: finalizeData.finalizeZkLogin.isPhoneVerified
        }
      };
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
              suiAddress
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
        hasSuiAddress: !!data.zkProof?.suiAddress,
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

      // Store the full proof object with all required fields including suiAddress
      this.zkProof = {
        zkProof: data.zkProof.zkProof,
        subject: data.subject,
        clientId: data.clientId,
        suiAddress: data.zkProof.suiAddress
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
          hasSuiAddress: !!this.zkProof?.suiAddress
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
      hasSuiAddress: !!proof.suiAddress,
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
    if (!proof.suiAddress) {
      throw new Error('No Sui address provided in proof');
    }

    // Structure the zkProof data with only required fields
    const structuredProof = {
      zkProof: proof.zkProof,
      subject,
      clientId,
      suiAddress: proof.suiAddress,  // Store the Sui address at the top level
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

  // Get the user's Sui address
  public async getZkLoginAddress(): Promise<string> {
    if (!this.firebaseIsInitialized) {
      await this.initialize();
    }

    // Get stored zkLogin data
    const storedData = await this.getStoredZkLoginData();
    if (!storedData) {
      throw new Error('No zkLogin data stored');
    }

    // Get current account context
    const accountManager = AccountManager.getInstance();
    const accountContext = await accountManager.getActiveAccountContext();
    const accountId = accountManager.generateAccountId(accountContext.type, accountContext.index);

    console.log('Getting zkLogin address for account context:', {
      accountType: accountContext.type,
      accountIndex: accountContext.index,
      accountId: accountId
    });

    // Get the original JWT issuer from the stored data
    const decodedJwt = jwtDecode(storedData.initJwt);
    const originalIssuer = decodedJwt.iss;
    
    if (!originalIssuer) {
      throw new Error('No issuer found in stored JWT');
    }
    
    // Generate the deterministic salt for the current account context
    const currentSalt = await this.generateZkLoginSalt(
      originalIssuer, 
      storedData.subject, 
      storedData.clientId, 
      accountContext
    );

    // Derive the keypair for the current account context using the deterministic salt
    const currentKeypair = this.deriveEphemeralKeypair(
      currentSalt, 
      storedData.subject, 
      storedData.clientId
    );

    // Get the Sui address for the current account context
    const currentSuiAddress = currentKeypair.getPublicKey().toSuiAddress();

    console.log('Generated deterministic Sui address:', {
      accountType: accountContext.type,
      accountIndex: accountContext.index,
      accountId: accountId,
      suiAddress: currentSuiAddress,
      note: 'Address derived from deterministic salt for current account context'
    });

    return currentSuiAddress;
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
      
      // 4. Clear account data
      const accountManager = AccountManager.getInstance();
      await accountManager.clearAllAccounts();
      
      // 5. Clear local state
      this.suiKeypair = null;
      this.userSalt = null;
      this.zkProof = null;
      this.maxEpoch = null;
      this.firebaseIsInitialized = false;
      console.log('Local state cleared');
      
      // 4. Clear all stored credentials from Keychain
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

        // Clear zkLogin data
        await Keychain.resetGenericPassword({
          service: ZKLOGIN_KEYCHAIN_SERVICE,
          username: ZKLOGIN_KEYCHAIN_USERNAME
        });
        console.log('Cleared zkLogin data from Keychain');

        // Clear auth tokens
        await Keychain.resetGenericPassword({
          service: AUTH_KEYCHAIN_SERVICE,
          username: AUTH_KEYCHAIN_USERNAME
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
      try {
        await Keychain.resetGenericPassword({
          service: ZKLOGIN_KEYCHAIN_SERVICE
        });
        await Keychain.resetGenericPassword({
          service: AUTH_KEYCHAIN_SERVICE
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

  private async _generateNonce(): Promise<string> {
    const randomBytes = new Uint8Array(32);
    for (let i = 0; i < randomBytes.length; i++) {
      randomBytes[i] = Math.floor(Math.random() * 256);
    }
    const hash = sha256(randomBytes);
    return bytesToBase64(hash);
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
            firebaseToken: firebaseToken
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
    
    // Use the updated salt generation function with account type and index
    return generateZkLoginSaltUtil(iss, sub, clientId, accountContext.type, accountContext.index);
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
   * Automatically determines account type: personal if no accounts exist, business otherwise
   */
  public async createAccount(
    name: string,
    avatar: string,
    phone?: string,
    category?: string
  ): Promise<any> {
    const accountManager = AccountManager.getInstance();
    
    console.log('Creating new account:', {
      name: name,
      avatar: avatar,
      phone: phone,
      category: category
    });
    
    const newAccount = await accountManager.createAccount('business', name, avatar, phone, category);
    
    console.log('Account created successfully:', {
      accountId: newAccount.id,
      accountType: newAccount.type,
      accountIndex: newAccount.index,
      name: newAccount.name,
      note: newAccount.type === 'personal' ? 'First account (personal)' : 'Additional account (business)'
    });
    
    return newAccount;
  }

  /**
   * Switch to a different account
   * Note: zkLogin data is user-level, not account-level, so we don't clear it
   */
  public async switchAccount(accountId: string): Promise<void> {
    const accountManager = AccountManager.getInstance();
    
    console.log('AuthService - switchAccount called with accountId:', accountId);
    
    const accountContext = accountManager.parseAccountId(accountId);
    
    console.log('AuthService - Parsed account context:', {
      accountId: accountId,
      accountType: accountContext.type,
      accountIndex: accountContext.index,
      note: accountContext.type === 'personal' ? 'Personal account (index 0)' : `Business account (index ${accountContext.index})`
    });
    
    // Set the new active account context
    await accountManager.setActiveAccountContext(accountContext);
    
    console.log('AuthService - Active account context set');
    
    // Note: We do NOT clear zkLogin data because:
    // 1. zkLogin authentication is user-level, not account-level
    // 2. The same user can have multiple accounts (personal + business)
    // 3. All accounts share the same zkLogin authentication
    // 4. Only the salt generation changes based on account context
    
    // Verify that the Sui address changes for the new account context
    try {
      const newSuiAddress = await this.getZkLoginAddress();
      console.log('AuthService - Account switch completed with new Sui address:', {
        accountId: accountId,
        accountType: accountContext.type,
        accountIndex: accountContext.index,
        suiAddress: newSuiAddress,
        note: accountContext.type === 'personal' ? 'Personal account (index 0)' : `Business account (index ${accountContext.index})`
      });
    } catch (error) {
      console.error('AuthService - Error getting new Sui address after account switch:', error);
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