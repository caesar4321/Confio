// Polyfill for crypto.getRandomValues
import 'react-native-get-random-values';

import { GoogleSignin, User } from '@react-native-google-signin/google-signin';
import { Ed25519Keypair } from '@mysten/sui/keypairs/ed25519';
import { fromB64 } from '@mysten/sui/utils';
import { generateNonce, generateRandomness, genAddressSeed, getZkLoginSignature } from '@mysten/sui/zklogin';
import { SuiClient } from '@mysten/sui/client';
import { jwtDecode } from 'jwt-decode';
import * as Keychain from 'react-native-keychain';
import { GOOGLE_CLIENT_IDS, ZKLOGIN_CLIENT_ID, API_URL } from '../config/env';
import auth from '@react-native-firebase/auth';
import Platform from 'react-native';
import { VERIFY_TOKEN } from '../apollo/queries';
import { apolloClient } from '../apollo/client';
import { gql } from '@apollo/client';
import { GoogleAuthProvider, signInWithCredential } from '@firebase/auth';

// Helper function to generate 32 bytes of random data
const generateRandomBytes = () => {
  const bytes = new Uint8Array(32);
  global.crypto.getRandomValues(bytes);
  return Buffer.from(bytes).toString('base64');
};

export class AuthService {
  private static instance: AuthService;
  private suiKeypair: Ed25519Keypair | null = null;
  private suiClient: SuiClient;
  private userSalt: string | null = null;
  private zkProof: any = null;
  private auth = auth();

  private constructor() {
    // Initialize Sui client
    this.suiClient = new SuiClient({ url: 'https://fullnode.devnet.sui.io' });
    this.initializeFirebase();
  }

  public static getInstance(): AuthService {
    if (!AuthService.instance) {
      AuthService.instance = new AuthService();
    }
    return AuthService.instance;
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
      const config: {
        webClientId: string;
        offlineAccess: boolean;
        scopes: string[];
        iosClientId?: string;
        androidClientId?: string;
      } = {
        webClientId: clientIds.web,
        offlineAccess: true,
        scopes: ['profile', 'email'],
      };

      if (Platform.OS === 'ios') {
        config.iosClientId = clientIds.ios;
      } else if (Platform.OS === 'android') {
        config.androidClientId = clientIds.android;
      }
      
      await GoogleSignin.configure(config);
      console.log('Google Sign-In configuration successful');
    } catch (error) {
      console.error('Error configuring Google Sign-In:', error);
      throw error;
    }
  }

  async signInWithGoogle() {
    try {
      await this.configureGoogleSignIn();
      const result = await GoogleSignin.signIn();
      const { idToken } = await GoogleSignin.getTokens();
      
      // Create Firebase credential with Google token
      const googleCredential = auth.GoogleAuthProvider.credential(idToken);
      
      // Sign in with Firebase using the Google credential
      const userCredential = await this.auth.signInWithCredential(googleCredential);
      const firebaseToken = await userCredential.user.getIdToken();

      console.log('Sending tokens to GraphQL server:', {
        firebaseToken: firebaseToken.substring(0, 20) + '...',
        googleToken: idToken.substring(0, 20) + '...'
      });

      // Verify both tokens and get zkLogin data
      const { data, errors } = await apolloClient.mutate({
        mutation: VERIFY_TOKEN,
        variables: {
          firebaseToken: firebaseToken,
          googleToken: idToken,
        },
      });

      if (errors) {
        console.error('GraphQL Errors:', errors);
        throw new Error('GraphQL mutation failed');
      }

      if (!data?.verifyToken) {
        throw new Error('No data received from token verification');
      }

      if (!data.verifyToken.success) {
        throw new Error(data.verifyToken.error || 'Token verification failed');
      }

      // Store zkLogin data securely
      const zkLoginData = data.verifyToken.zkLoginData;
      if (!zkLoginData) {
        throw new Error('No zkLogin data received');
      }

      // Store all sensitive data in a single secure entry
      await Keychain.setGenericPassword(
        'zkLoginData',
        JSON.stringify({
          suiKeypair: zkLoginData.suiKeypair,
          userSalt: zkLoginData.userSalt,
          zkProof: zkLoginData.zkProof,
          ephemeralPublicKey: zkLoginData.ephemeralPublicKey,
          maxEpoch: zkLoginData.maxEpoch.toString(),
          randomness: zkLoginData.randomness
        }),
        {
          service: 'com.confio.zklogin',
          accessible: Keychain.ACCESSIBLE.WHEN_UNLOCKED_THIS_DEVICE_ONLY
        }
      );

      return {
        user: {
          uid: data.verifyToken.firebaseUser.uid,
          email: data.verifyToken.firebaseUser.email,
          name: data.verifyToken.firebaseUser.name,
          picture: data.verifyToken.firebaseUser.picture,
          __typename: data.verifyToken.firebaseUser.__typename
        },
        zkLoginData: {
          suiKeypair: zkLoginData.suiKeypair,
          userSalt: zkLoginData.userSalt,
          zkProof: zkLoginData.zkProof,
          ephemeralPublicKey: zkLoginData.ephemeralPublicKey,
          maxEpoch: zkLoginData.maxEpoch,
          randomness: zkLoginData.randomness,
          __typename: zkLoginData.__typename
        }
      };
    } catch (error) {
      console.error('Google Sign-In Error:', error);
      throw error;
    }
  }

  async getStoredZkLoginData() {
    try {
      const credentials = await Keychain.getGenericPassword({
        service: 'com.confio.zklogin'
      });

      if (!credentials) {
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
        service: 'com.confio.zklogin'
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
      const { identityToken, nonce } = appleAuthRequestResponse;
      const appleCredential = auth.AppleAuthProvider.credential(identityToken, nonce);
      console.log('Created Firebase credential');

      // Sign in with Firebase using the Apple credential
      const userCredential = await this.auth.signInWithCredential(appleCredential);
      console.log('Firebase sign-in successful:', userCredential.user);

      // Get the ID token for zkLogin
      const firebaseToken = await userCredential.user.getIdToken();
      console.log('Got Firebase ID token');

      // Initialize zkLogin with the Firebase token
      console.log('Initializing zkLogin...');
      const zkLoginData = await this.initializeZkLogin(firebaseToken);
      console.log('zkLogin initialized successfully:', zkLoginData);

      return {
        userInfo: userCredential.user,
        zkLoginData
      };
    } catch (error) {
      console.error('Apple Sign In Error:', error);
      throw error;
    }
  }

  // Get ZK proof from our GraphQL server
  private async getZkProof(jwt: string, maxEpoch: number, randomness: string): Promise<any> {
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
      
      // Generate 32 bytes of randomness using our helper function
      const jwtRandomness = generateRandomBytes();
      
      console.log('Requesting ZK proof with params:', {
        maxEpoch,
        randomness,
        keyClaimName: 'sub',
        extendedEphemeralPublicKey: ephemeralPublicKey,
        jwtRandomness,
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
        throw new Error(`Prover service error: ${data.zkLogin.error} - ${data.zkLogin.details}`);
      }

      console.log('Successfully received ZK proof and Sui address');
      return {
        zkProof: data.zkLogin.zkProof,
        suiAddress: data.zkLogin.suiAddress
      };
    } catch (error) {
      console.error('ZK Proof Generation Error:', error);
      throw error;
    }
  }

  // Initialize zkLogin with the provider's ID token
  private async initializeZkLogin(idToken: string) {
    try {
      console.log('Initializing zkLogin with ID token');
      
      // Get current epoch information
      const { epoch } = await this.suiClient.getLatestSuiSystemState();
      const maxEpoch = Number(epoch) + 2;
      console.log('Current epoch:', epoch, 'Max epoch:', maxEpoch);

      // Generate ephemeral key pair
      this.suiKeypair = new Ed25519Keypair();
      
      // Generate 32 bytes of randomness using our helper function
      const randomness = generateRandomBytes();
      
      // Generate nonce using the randomness
      const nonce = generateNonce(this.suiKeypair.getPublicKey(), maxEpoch, randomness);
      console.log('Generated ephemeral key pair and randomness');

      // Generate 32 bytes of user salt using our helper function
      this.userSalt = generateRandomBytes();
      console.log('Generated user salt');

      // Get ZK proof from our GraphQL server
      console.log('Requesting ZK proof from our GraphQL server');
      this.zkProof = await this.getZkProof(idToken, maxEpoch, randomness);
      console.log('Received ZK proof from our GraphQL server');

      // Store sensitive data securely
      await this.storeSensitiveData({
        suiKeypair: this.suiKeypair.getSecretKey(),
        userSalt: this.userSalt,
        zkProof: this.zkProof,
      });
      console.log('Stored sensitive data securely');

      return {
        maxEpoch,
        randomness,
        nonce,
        userSalt: this.userSalt
      };
    } catch (error) {
      console.error('zkLogin Initialization Error:', error);
      throw error;
    }
  }

  // Store sensitive data securely
  private async storeSensitiveData(data: {
    suiKeypair: string;
    userSalt: string;
    zkProof: any;
  }) {
    try {
      await Keychain.setGenericPassword(
        'zkLoginData',
        JSON.stringify(data),
        {
          service: 'com.Confio.Confio.zkLogin',
          accessible: Keychain.ACCESSIBLE.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
        }
      );
    } catch (error) {
      console.error('Secure Storage Error:', error);
      throw error;
    }
  }

  // Load sensitive data from secure storage
  private async loadSensitiveData() {
    try {
      const credentials = await Keychain.getGenericPassword({
        service: 'com.Confio.Confio.zkLogin',
      });

      if (credentials) {
        const data = JSON.parse(credentials.password);
        this.suiKeypair = Ed25519Keypair.fromSecretKey(fromB64(data.suiKeypair));
        this.userSalt = data.userSalt;
        this.zkProof = data.zkProof;
      }
    } catch (error) {
      console.error('Secure Storage Load Error:', error);
      throw error;
    }
  }

  // Get the user's Sui address
  async getZkLoginAddress(jwt: string): Promise<string> {
    if (!this.userSalt) {
      await this.loadSensitiveData();
    }

    if (!this.userSalt) {
      throw new Error('User salt not found');
    }

    const decodedJwt = jwtDecode(jwt);
    if (!decodedJwt.sub) {
      throw new Error('Invalid JWT: missing required claims');
    }

    // Get the platform-specific client ID
    const clientIds = GOOGLE_CLIENT_IDS[__DEV__ ? 'development' : 'production'];
    const platformClientId = Platform.OS === 'ios' ? clientIds.ios : 
                           Platform.OS === 'android' ? clientIds.android : 
                           clientIds.web;

    console.log('Using platform-specific client ID as audience:', platformClientId);

    const addressSeed = genAddressSeed(
      BigInt(this.userSalt),
      'sub',
      decodedJwt.sub,
      platformClientId  // Use platform-specific client ID
    ).toString();

    if (!this.suiKeypair) {
      throw new Error('Sui keypair not found');
    }
    const signature = await this.suiKeypair.sign(new Uint8Array(0));
    const zkLoginSignature = getZkLoginSignature({
      inputs: {
        ...this.zkProof,
        addressSeed,
      },
      maxEpoch: this.zkProof.maxEpoch,
      userSignature: signature,
    });

    // The address is derived from the signature
    return zkLoginSignature;
  }

  // Sign out
  async signOut() {
    try {
      await GoogleSignin.signOut();
      this.suiKeypair = null;
      this.userSalt = null;
      this.zkProof = null;
      await Keychain.resetGenericPassword({
        service: 'com.Confio.Confio.zkLogin',
      });
    } catch (error) {
      console.error('Sign Out Error:', error);
      throw error;
    }
  }

  // Get the current Sui keypair
  getSuiKeypair(): Ed25519Keypair | null {
    return this.suiKeypair;
  }
} 