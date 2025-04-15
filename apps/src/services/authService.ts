// Polyfill for crypto.getRandomValues
import 'react-native-get-random-values';

import { GoogleSignin } from '@react-native-google-signin/google-signin';
import { Ed25519Keypair } from '@mysten/sui/keypairs/ed25519';
import { fromB64 } from '@mysten/sui/utils';
import { generateNonce, generateRandomness, genAddressSeed, getZkLoginSignature } from '@mysten/sui/zklogin';
import { SuiClient } from '@mysten/sui/client';
import { jwtDecode } from 'jwt-decode';
import * as Keychain from 'react-native-keychain';
import { getGoogleClientIds } from '../config/env';
import auth from '@react-native-firebase/auth';
import { Platform } from 'react-native';

// Sui DevNet test client ID for zkLogin
const ZKLOGIN_GOOGLE_CLIENT_ID = '1001709244115-2h2k3sdvr3ggr1t5pgob4pkb3k92ug1p.apps.googleusercontent.com';

// Configure Google Sign-In
const configureGoogleSignIn = async () => {
  try {
    console.group('Google Sign-In Configuration');
    console.log('Starting configuration...');
    const { web, ios, android } = getGoogleClientIds();
    console.log('Client IDs:', { web, ios, android });
    
    await GoogleSignin.configure({
      webClientId: web,
      iosClientId: ios,
      offlineAccess: true,
      scopes: ['profile', 'email'],
    });
    console.log('Configuration successful');
    console.groupEnd();
  } catch (error) {
    console.group('Google Sign-In Configuration Error');
    console.error('Error details:', error);
    console.groupEnd();
    throw error;
  }
};

export class AuthService {
  private static instance: AuthService;
  private suiKeypair: Ed25519Keypair | null = null;
  private suiClient: SuiClient;
  private userSalt: string | null = null;
  private zkProof: any = null;
  private readonly PROVER_URL = 'https://prover.mystenlabs.com/v1';
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
      console.group('Firebase Initialization');
      console.log('Initializing Firebase...');
      
      // Configure Google Sign-In
      const { web, ios, android } = getGoogleClientIds();
      await GoogleSignin.configure({
        webClientId: web,
        iosClientId: ios,
        offlineAccess: true,
        scopes: ['profile', 'email'],
      });

      // Configure Apple Sign-In
      await this.configureAppleSignIn();
      
      console.log('Firebase initialized successfully');
      console.groupEnd();
    } catch (error) {
      console.group('Firebase Initialization Error');
      console.error('Error details:', error);
      console.groupEnd();
      throw error;
    }
  }

  private async configureAppleSignIn() {
    if (Platform.OS !== 'ios') {
      return;
    }
    
    try {
      const { appleAuth } = await import('@invertase/react-native-apple-authentication');
      if (!appleAuth.isSupported) {
        throw new Error('Apple Sign In is not supported on this device');
      }
    } catch (error) {
      console.error('Failed to load Apple Sign In:', error);
      throw error;
    }
  }

  // Google Sign-In
  async signInWithGoogle() {
    try {
      console.group('Google Sign-In Process');
      console.log('Starting sign-in process...');
      
      // Get the users Google ID token
      const signInResult = await GoogleSignin.signIn();
      console.log('Google Sign-In successful, getting ID token...');

      // Get the ID token
      const { idToken } = await GoogleSignin.getTokens();
      if (!idToken) {
        throw new Error('Failed to get ID token');
      }

      // Create a Firebase credential with the Google ID token
      const googleCredential = auth.GoogleAuthProvider.credential(idToken);
      console.log('Created Firebase credential');

      // Sign in with Firebase using the Google credential
      const userCredential = await this.auth.signInWithCredential(googleCredential);
      console.log('Firebase sign-in successful:', userCredential.user);

      // Get the ID token for zkLogin
      const firebaseToken = await userCredential.user.getIdToken();
      console.log('Got Firebase ID token');

      // Initialize zkLogin with the Firebase token
      console.log('Initializing zkLogin...');
      const zkLoginData = await this.initializeZkLogin(firebaseToken);
      console.log('zkLogin initialized successfully:', zkLoginData);

      console.groupEnd();
      
      return {
        userInfo: userCredential.user,
        zkLoginData
      };
    } catch (error) {
      console.group('Google Sign-In Error');
      console.error('Error details:', error);
      console.groupEnd();
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

  // Get ZK proof from prover service
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

      const ephemeralPublicKey = this.suiKeypair.getPublicKey().toBase64();
      const jwtRandomness = generateRandomness();
      
      console.log('Requesting ZK proof with params:', {
        maxEpoch,
        randomness,
        keyClaimName: 'sub',
        extendedEphemeralPublicKey: ephemeralPublicKey,
        jwtRandomness,
        salt: this.userSalt,
        audience: ZKLOGIN_GOOGLE_CLIENT_ID
      });

      const response = await fetch(this.PROVER_URL, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          jwt,
          maxEpoch,
          randomness,
          keyClaimName: 'sub',
          extendedEphemeralPublicKey: ephemeralPublicKey,
          jwtRandomness,
          salt: this.userSalt,
          audience: ZKLOGIN_GOOGLE_CLIENT_ID
        }),
      });

      if (!response.ok) {
        const errorText = await response.text();
        console.error('Prover service error details:', {
          status: response.status,
          statusText: response.statusText,
          error: errorText
        });
        throw new Error(`Prover service error: ${response.status} - ${errorText}`);
      }

      const result = await response.json();
      console.log('Successfully received ZK proof');
      return result;
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

      // Generate ephemeral key pair and randomness
      this.suiKeypair = new Ed25519Keypair();
      const randomness = generateRandomness();
      const nonce = generateNonce(this.suiKeypair.getPublicKey(), maxEpoch, randomness);
      console.log('Generated ephemeral key pair and randomness');

      // Generate user salt
      this.userSalt = Math.floor(Math.random() * 2 ** 128).toString();
      console.log('Generated user salt');

      // Get ZK proof from prover service
      console.log('Requesting ZK proof from prover service');
      this.zkProof = await this.getZkProof(idToken, maxEpoch, randomness);
      console.log('Received ZK proof from prover service');

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

    console.log('Using Google Web Client ID as audience:', ZKLOGIN_GOOGLE_CLIENT_ID);

    const addressSeed = genAddressSeed(
      BigInt(this.userSalt),
      'sub',
      decodedJwt.sub,
      ZKLOGIN_GOOGLE_CLIENT_ID
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