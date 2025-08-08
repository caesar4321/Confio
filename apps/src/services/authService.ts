import { GoogleSignin, User } from '@react-native-google-signin/google-signin';
import { Ed25519Keypair } from '@mysten/sui/keypairs/ed25519';
import { genAddressSeed, getZkLoginSignature, generateNonce as generateZkLoginNonce } from '@mysten/sui/zklogin';
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
import { DeviceFingerprint } from '../utils/deviceFingerprint';
import algorandService from './algorandService';

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
    aptosAddress: string;  // the user's Aptos address
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
      
      // Sign out first to force account selection
      try {
        const isSignedIn = await GoogleSignin.isSignedIn();
        if (isSignedIn) {
          console.log('User already signed in to Google, signing out to force account selection...');
          await GoogleSignin.signOut();
        }
      } catch (error) {
        console.log('Error checking/signing out from Google:', error);
      }
      
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

      // 5) Initialize zkLogin with device fingerprint
      console.log('Initializing zkLogin...');
      const { data: { initializeZkLogin: init } } = await apolloClient.mutate({
        mutation: INITIALIZE_ZKLOGIN,
        variables: { 
          firebaseToken, 
          providerToken: idToken, 
          provider: 'google',
          deviceFingerprint: deviceFingerprint ? JSON.stringify(deviceFingerprint) : null
        }
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

      // 7) Finalize zkLogin with device fingerprint
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
            firebaseToken: firebaseToken,
            accountType: accountContext.type,
            accountIndex: accountContext.index,
            deviceFingerprint: deviceFingerprint ? JSON.stringify(deviceFingerprint) : null
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
          console.log('No local accounts found, but server should have created default personal account during zkLogin initialization');
          // Set default personal account context (server should have created this)
          await accountManager.setActiveAccountContext({
            type: 'personal',
            index: 0
          });
          
          console.log('Set default personal account context (personal_0)');
        } else {
          console.log('Local accounts already exist, skipping default account creation');
        }
      } catch (accountError) {
        console.error('Error creating default account:', accountError);
        // Don't throw here - account creation failure shouldn't break the sign-in flow
      }

      // Split display name into first and last name
      const [firstName, ...lastNameParts] = user.displayName?.split(' ') || [];
      const lastName = lastNameParts.join(' ');

      // 10) Create Algorand wallet using Web3Auth and backend opt-ins
      let algorandAddress = '';
      let isPhoneVerified = false; // Default to false if we can't get the status
      try {
        console.log('Creating Algorand wallet with Web3Auth using Firebase token...');
        
        // Get fresh Firebase ID token for Web3Auth
        const freshFirebaseToken = await user.getIdToken(true);
        const firebaseUid = user.uid;
        
        // Create Algorand wallet with the Google OAuth subject for non-custodial derivation
        // Decode the ID token to get the real Google OAuth subject
        const decodedIdToken = jwtDecode<{ sub: string, iss: string }>(idToken);
        const googleSubject = decodedIdToken.sub; // The real Google OAuth subject
        console.log('Using Google OAuth subject for Algorand:', googleSubject);
        console.log('Google OAuth issuer:', decodedIdToken.iss);
        algorandAddress = await algorandService.createOrRestoreWallet(freshFirebaseToken, firebaseUid, googleSubject);
        console.log('Algorand wallet created:', algorandAddress);
        
        // Now call backend mutations for authentication and opt-ins
        console.log('Calling backend mutations for Web3Auth authentication...');
        
        const { WEB3AUTH_LOGIN, ADD_ALGORAND_WALLET } = await import('../apollo/mutations');
        
        // Step 1: Web3Auth Login (skip auth header since this IS the login)
        console.log('Calling WEB3AUTH_LOGIN mutation...');
        const { data: authData } = await apolloClient.mutate({
          mutation: WEB3AUTH_LOGIN,
          variables: {
            provider: 'google',
            web3AuthId: firebaseUid,
            email: user.email,
            firstName,
            lastName,
            algorandAddress,
            idToken: freshFirebaseToken,
          },
          context: {
            skipAuth: true, // Tell the auth link to skip adding JWT token
          },
        });
        
        if (authData?.web3AuthLogin?.success) {
          console.log('WEB3AUTH_LOGIN successful');
          
          // Store the new tokens from Web3Auth login
          if (authData.web3AuthLogin.accessToken && authData.web3AuthLogin.refreshToken) {
            await this.storeTokens({
              accessToken: authData.web3AuthLogin.accessToken,
              refreshToken: authData.web3AuthLogin.refreshToken,
            });
            console.log('Stored new authentication tokens');
          }
          
          // Get the phone verification status from the user
          isPhoneVerified = authData.web3AuthLogin.user?.isPhoneVerified || false;
          console.log('Phone verification status from backend:', isPhoneVerified);
          
          
          // Step 2: Add Algorand wallet and check opt-ins (now with proper auth)
          console.log('Calling ADD_ALGORAND_WALLET mutation...');
          const { data: walletData } = await apolloClient.mutate({
            mutation: ADD_ALGORAND_WALLET,
            variables: {
              algorandAddress,
              web3authId: firebaseUid,
              provider: 'google',
            },
            // Force refetch with new auth tokens
            fetchPolicy: 'network-only',
          });
          
          if (walletData?.addAlgorandWallet?.success) {
            console.log('ADD_ALGORAND_WALLET successful');
            console.log('ALGO balance:', walletData.addAlgorandWallet.algoBalance);
            console.log('Needs opt-in:', walletData.addAlgorandWallet.needsOptIn);
            
            // Step 3: Handle opt-ins if needed
            if (walletData.addAlgorandWallet.needsOptIn?.length > 0) {
              console.log('Handling automatic opt-ins for:', walletData.addAlgorandWallet.needsOptIn);
              // Process sponsored opt-ins directly here since algorandService has import issues
              try {
                const { ALGORAND_SPONSORED_OPT_IN } = await import('../apollo/mutations');
                
                for (const assetId of walletData.addAlgorandWallet.needsOptIn) {
                  console.log(`Processing sponsored opt-in for asset ${assetId}...`);
                  
                  // Request sponsored opt-in from backend
                  const { data: optInData } = await apolloClient.mutate({
                    mutation: ALGORAND_SPONSORED_OPT_IN,
                    variables: {
                      assetId: assetId
                    }
                  });
                  
                  const result = optInData?.algorandSponsoredOptIn;
                  
                  if (result?.success) {
                    if (result.alreadyOptedIn) {
                      console.log(`Asset ${assetId} already opted in`);
                    } else if (result.requiresUserSignature) {
                      console.log(`Asset ${assetId} requires user signature - signing and submitting...`);
                      
                      // We have the unsigned user transaction and signed sponsor transaction
                      if (result.userTransaction && result.sponsorTransaction && algorandService) {
                        try {
                          // Get the algosdk for signing
                          const algosdk = require('algosdk');
                          
                          console.log('Signing opt-in transaction for asset', assetId);
                          console.log('User transaction (base64):', result.userTransaction?.substring(0, 50) + '...');
                          console.log('Sponsor transaction (base64):', result.sponsorTransaction?.substring(0, 50) + '...');
                          
                          // Get the current Algorand account from the service
                          const currentAccount = algorandService.getCurrentAccount();
                          if (!currentAccount) {
                            throw new Error('No Algorand account available for signing');
                          }
                          console.log('Current account available for signing');
                          
                          // The transaction from backend is base64-encoded msgpack
                          const userTxnB64 = result.userTransaction;
                          const userTxnBytes = Buffer.from(userTxnB64, 'base64');
                          
                          // Decode the msgpack transaction to get the dictionary
                          const txnDict = algosdk.decodeObj(userTxnBytes);
                          console.log('Decoded transaction dict:', txnDict);
                          
                          // In JavaScript SDK, we need to use makePaymentTxnWithSuggestedParamsFromObject
                          // or makeAssetTransferTxnWithSuggestedParamsFromObject
                          // But since we already have a complete transaction, we can sign it directly
                          
                          // Since the backend is sending us a properly formatted transaction,
                          // we should be able to sign it directly without reconstruction
                          // The transaction dictionary from decodeObj needs special handling
                          
                          console.log('Signing transaction using raw signing approach...');
                          
                          // The transaction needs to be signed with the current account's key
                          // We'll manually create the signed transaction structure
                          
                          // Get the raw transaction bytes (without the signature)
                          const txnToSign = algosdk.encodeObj(txnDict);
                          
                          // Use the secure wallet to sign the transaction
                          // The secureDeterministicWallet handles the private key securely
                          const { secureDeterministicWallet } = await import('./secureDeterministicWallet');
                          
                          // Sign the transaction using the secure wallet service
                          // Pass the raw transaction bytes directly to the signing method
                          const signedTxnBytes = await secureDeterministicWallet.signTransaction(
                            firebaseUid,   // Firebase UID from earlier in the function
                            userTxnBytes   // The raw transaction bytes from the backend
                          );
                          
                          console.log('Transaction signed successfully using raw signing');
                          console.log('Signed transaction bytes length:', signedTxnBytes.length);
                          
                          // signedTxnBytes is already the properly encoded signed transaction
                          // Convert to base64 for transmission
                          const signedUserTxnBase64 = Buffer.from(signedTxnBytes).toString('base64');
                          console.log('Signed user transaction (base64):', signedUserTxnBase64.substring(0, 50) + '...');
                          console.log('Base64 length:', signedUserTxnBase64.length);
                          
                          // Submit both transactions to the network
                          const { SUBMIT_SPONSORED_GROUP } = await import('../apollo/mutations');
                          const { data: submitData } = await apolloClient.mutate({
                            mutation: SUBMIT_SPONSORED_GROUP,
                            variables: {
                              signedUserTxn: signedUserTxnBase64,
                              signedSponsorTxn: result.sponsorTransaction
                            }
                          });
                          
                          if (submitData?.submitSponsoredGroup?.success) {
                            console.log(`Successfully opted into asset ${assetId} - TxID: ${submitData.submitSponsoredGroup.transactionId}`);
                          } else {
                            console.error(`Failed to submit opt-in for asset ${assetId}:`, submitData?.submitSponsoredGroup?.error);
                          }
                        } catch (signError) {
                          console.error(`Error signing opt-in for asset ${assetId}:`, signError);
                        }
                      } else {
                        console.log(`Missing transaction data for opt-in of asset ${assetId}`);
                      }
                    } else {
                      console.log(`Successfully opted into asset ${assetId}`);
                    }
                  } else {
                    console.log(`Failed to opt into asset ${assetId}:`, result?.error);
                  }
                }
              } catch (optInError) {
                console.error('Error during sponsored opt-in:', optInError);
                // Don't fail login if opt-in fails - user can retry later
              }
            }
          } else {
            console.error('ADD_ALGORAND_WALLET failed:', walletData?.addAlgorandWallet?.error);
          }
        } else {
          console.error('WEB3AUTH_LOGIN failed:', authData?.web3AuthLogin?.error);
        }
        
        // Update the aptos_address field with Algorand address
        try {
          const { UPDATE_ACCOUNT_APTOS_ADDRESS } = await import('../apollo/queries');
          await apolloClient.mutate({
            mutation: UPDATE_ACCOUNT_APTOS_ADDRESS,
            variables: { aptosAddress: algorandAddress }
          });
          console.log('Updated account with Algorand address');
        } catch (updateError) {
          console.error('Error updating account with Algorand address:', updateError);
          // Don't fail the sign-in if this update fails
        }
        
      } catch (algorandError) {
        console.error('Error creating Algorand wallet:', algorandError);
        // Don't fail the sign-in if Algorand wallet creation fails
        // We can retry later
      }

      // 11) Return user info and zkLogin data (with Algorand address in aptosAddress field)
      const result = {
        userInfo: { 
          email: user.email, 
          firstName: firstName || '',
          lastName: lastName || '',
          photoURL: user.photoURL 
        },
        zkLoginData: { 
          zkProof: {
            aptosAddress: algorandAddress, // Store Algorand address in the zkProof object
            zkProof: null // We don't have actual zkProof when using Algorand
          },
          aptosAddress: algorandAddress, // Also store at top level for compatibility
          isPhoneVerified // Use the actual value from backend
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
      
      // Initialize zkLogin with server-side nonce generation
      const { data: initData } = await apolloClient.mutate({
        mutation: INITIALIZE_ZKLOGIN,
        variables: {
          firebaseToken: firebaseToken,
          providerToken: appleAuthResponse.identityToken,
          provider: 'apple',
          deviceFingerprint: deviceFingerprint ? JSON.stringify(deviceFingerprint) : null
        }
      });
      
      if (!initData?.initializeZkLogin) {
        throw new Error('No data received from zkLogin initialization');
      }
      
      const { maxEpoch, randomness: serverRandomness, authAccessToken, authRefreshToken } = initData.initializeZkLogin;
      
      // Store Django JWT tokens for authenticated requests using Keychain
      if (authAccessToken) {
        console.log('About to store tokens in Keychain (Apple):', {
          service: AUTH_KEYCHAIN_SERVICE,
          username: AUTH_KEYCHAIN_USERNAME,
          hasAccessToken: !!authAccessToken,
          hasRefreshToken: !!authRefreshToken,
          accessTokenLength: authAccessToken?.length,
          refreshTokenLength: authRefreshToken?.length
        });

        try {
          await Keychain.setGenericPassword(
            AUTH_KEYCHAIN_USERNAME,
            JSON.stringify({
              accessToken: authAccessToken,
              refreshToken: authRefreshToken
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

      // Generate salt and ephemeral keypair
      const decodedAppleJwt = jwtDecode<{ sub: string, iss: string }>(appleAuthResponse.identityToken);
      const appleSub = decodedAppleJwt.sub;
      console.log('Apple OAuth subject:', appleSub);
      console.log('Apple OAuth issuer:', decodedAppleJwt.iss);
      const salt = await this.generateZkLoginSalt(decodedAppleJwt.iss, appleSub, 'apple');
      const ephemeralKeypair = this.deriveEphemeralKeypair(salt, appleSub, 'apple');
      this.suiKeypair = ephemeralKeypair;
      
      // Generate the zkLogin nonce for Apple Sign In
      const computedNonce = await this._generateNonce(ephemeralKeypair, maxEpoch, serverRandomness);
      console.log('Computed zkLogin nonce for Apple:', computedNonce);
      
      // Get current account context for finalization
      const accountManager = AccountManager.getInstance();
      const accountContext = await accountManager.getActiveAccountContext();
      console.log('Account context for finalization (Apple):', {
        accountType: accountContext.type,
        accountIndex: accountContext.index,
        accountId: accountManager.generateAccountId(accountContext.type, accountContext.index)
      });

      // Get the extended ephemeral public key
      const extendedEphemeralPublicKey = this.suiKeypair.getPublicKey().toBase64();

      // Finalize zkLogin with device fingerprint
      const { data: finalizeData } = await apolloClient.mutate({
        mutation: FINALIZE_ZKLOGIN,
        variables: {
          input: {
            extendedEphemeralPublicKey,
            jwt: appleAuthResponse.identityToken,  // Send Apple JWT - server will handle nonce issue
            maxEpoch: maxEpoch.toString(),
            randomness: serverRandomness,
            salt: salt,
            userSignature: bytesToBase64(await this.suiKeypair.sign(new Uint8Array(0))),
            keyClaimName: 'sub',
            audience: 'apple',
            firebaseToken: firebaseToken,
            accountType: accountContext.type,
            accountIndex: accountContext.index,
            deviceFingerprint: deviceFingerprint ? JSON.stringify(deviceFingerprint) : null,
            computedNonce: computedNonce  // Send computed nonce for Apple Sign In
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
        appleAuthResponse.identityToken
      );

      // Automatically create default personal account after successful zkLogin
      console.log('Creating default personal account (Apple)...');
      try {
        const accountManager = AccountManager.getInstance();
        const storedAccounts = await accountManager.getStoredAccounts();
        
        if (storedAccounts.length === 0) {
          console.log('No local accounts found, but server should have created default personal account during zkLogin initialization (Apple)');
          // Set default personal account context (server should have created this)
          await accountManager.setActiveAccountContext({
            type: 'personal',
            index: 0
          });
          
          console.log('Set default personal account context (personal_0) for Apple sign-in');
        } else {
          console.log('Local accounts already exist, skipping default account creation (Apple)');
        }
      } catch (accountError) {
        console.error('Error creating default account (Apple):', accountError);
        // Don't throw here - account creation failure shouldn't break the sign-in flow
      }

      // Split display name into first and last name
      const [firstName, ...lastNameParts] = userCredential.user.displayName?.split(' ') || [];
      const lastName = lastNameParts.join(' ');

      // Create Algorand wallet using Web3Auth SFA with Firebase
      let algorandAddress = '';
      let isPhoneVerified = false;
      try {
        console.log('Creating Algorand wallet with Web3Auth SFA using Firebase (Apple)...');
        // Get fresh Firebase ID token for Web3Auth
        const freshFirebaseToken = await userCredential.user.getIdToken(true);
        const firebaseUid = userCredential.user.uid;
        // Pass the Apple OAuth subject for non-custodial wallet derivation
        algorandAddress = await algorandService.createOrRestoreWallet(freshFirebaseToken, firebaseUid, appleSub);
        console.log('Algorand wallet created (Apple):', algorandAddress);
        
        // Call WEB3AUTH_LOGIN mutation to authenticate and get user info
        const { WEB3AUTH_LOGIN, ADD_ALGORAND_WALLET } = await import('../apollo/mutations');
        
        console.log('Calling WEB3AUTH_LOGIN mutation for Apple...');
        const { data: authData } = await apolloClient.mutate({
          mutation: WEB3AUTH_LOGIN,
          variables: {
            provider: 'apple',
            web3AuthId: firebaseUid,
            email: userCredential.user.email,
            firstName: firstName || '',
            lastName: lastName || '',
            algorandAddress,
            idToken: freshFirebaseToken,
          },
          context: {
            skipAuth: true, // Tell the auth link to skip adding JWT token
          },
        });
        
        if (authData?.web3AuthLogin?.success) {
          console.log('WEB3AUTH_LOGIN successful (Apple)');
          
          // Store the new tokens from Web3Auth login
          if (authData.web3AuthLogin.accessToken && authData.web3AuthLogin.refreshToken) {
            await this.storeTokens({
              accessToken: authData.web3AuthLogin.accessToken,
              refreshToken: authData.web3AuthLogin.refreshToken,
            });
            console.log('Stored new authentication tokens (Apple)');
          }
          
          // Get the phone verification status from the user
          isPhoneVerified = authData.web3AuthLogin.user?.isPhoneVerified || false;
          console.log('Phone verification status from backend (Apple):', isPhoneVerified);
          
          // Call ADD_ALGORAND_WALLET for opt-ins
          console.log('Calling ADD_ALGORAND_WALLET mutation (Apple)...');
          const { data: walletData } = await apolloClient.mutate({
            mutation: ADD_ALGORAND_WALLET,
            variables: {
              algorandAddress,
              web3authId: firebaseUid,
              provider: 'apple'
            }
          });
          
          if (walletData?.addAlgorandWallet?.success) {
            console.log('ADD_ALGORAND_WALLET successful (Apple)');
            // Handle opt-ins if needed
            if (walletData.addAlgorandWallet.needsOptIn?.length > 0) {
              console.log('Needs opt-in for assets (Apple):', walletData.addAlgorandWallet.needsOptIn);
              // Handle opt-ins similar to Google flow
            }
          }
        } else {
          console.error('WEB3AUTH_LOGIN failed (Apple):', authData?.web3AuthLogin?.error);
        }
      } catch (algorandError) {
        console.error('Error creating Algorand wallet (Apple):', algorandError);
        // Don't fail the sign-in if Algorand wallet creation fails
        // We can retry later
      }

      return {
        userInfo: {
          email: userCredential.user.email,
          firstName: firstName || '',
          lastName: lastName || '',
          photoURL: userCredential.user.photoURL
        },
        zkLoginData: {
          zkProof: {
            aptosAddress: algorandAddress, // Store Algorand address in the zkProof object
            zkProof: null // We don't have actual zkProof when using Algorand
          },
          aptosAddress: algorandAddress, // Also store at top level for compatibility
          isPhoneVerified // Use the actual value from backend
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
        hasAptosAddress: !!data.zkProof?.aptosAddress,
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
        aptosAddress: data.zkProof.aptosAddress
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
          hasAptosAddress: !!this.zkProof?.aptosAddress
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
      hasAptosAddress: !!proof.aptosAddress,
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
    if (!proof.aptosAddress) {
      throw new Error('No Aptos address provided in proof');
    }

    // Structure the zkProof data with only required fields
    const structuredProof = {
      zkProof: proof.zkProof,
      subject,
      clientId,
      aptosAddress: proof.aptosAddress,  // Store the Aptos address at the top level
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
  public async getAptosAddress(): Promise<string> {
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
    const currentAptosAddress = currentKeypair.getPublicKey().toSuiAddress();

    console.log('Generated deterministic Sui address:', {
      accountType: accountContext.type,
      accountIndex: accountContext.index,
      accountId: accountId,
      aptosAddress: currentAptosAddress,
      note: 'Address derived from deterministic salt for current account context'
    });

    return currentAptosAddress;
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
    
    // Verify that the Sui address changes for the new account context
    try {
      const newAptosAddress = await this.getAptosAddress();
      console.log('AuthService - Account switch completed with new Sui address:', {
        accountId: accountId,
        accountType: accountContext.type,
        accountIndex: accountContext.index,
        aptosAddress: newAptosAddress,
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

// Export a singleton instance
const authService = AuthService.getInstance();
export default authService; 