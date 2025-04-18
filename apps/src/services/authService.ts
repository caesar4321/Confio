import { GoogleSignin, User } from '@react-native-google-signin/google-signin';
import { Ed25519Keypair } from '@mysten/sui/keypairs/ed25519';
import { fromB64, toB64 } from '@mysten/sui/utils';
import { generateNonce, generateRandomness, genAddressSeed, getZkLoginSignature } from '@mysten/sui/zklogin';
import { SuiClient } from '@mysten/sui/client';
import { jwtDecode } from 'jwt-decode';
import * as Keychain from 'react-native-keychain';
import { GOOGLE_CLIENT_IDS, API_URL } from '../config/env';
import auth from '@react-native-firebase/auth';
import { Platform } from 'react-native';
import { INITIALIZE_ZKLOGIN, FINALIZE_ZKLOGIN, INITIALIZE_APPLE_ZKLOGIN } from '../apollo/queries';
import { apolloClient } from '../apollo/client';
import { gql } from '@apollo/client';
import { Buffer } from 'buffer';

// Add type definitions for BigInt
declare const BigInt: (value: string | number | bigint) => bigint;

// BN254 field modulus
const BN254_MODULUS = BigInt('0x30644e72e131a029b85045b68181585d2833e84879b9709143e1f593f0000001');

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
      const config = {
        webClientId: clientIds.web,
        offlineAccess: true,
        scopes: ['profile', 'email'],
        iosClientId: Platform.OS === 'ios' ? clientIds.ios : undefined,
        androidClientid: Platform.OS === 'android' ? clientIds.android : undefined,
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
      // Check if Google Play Services is available
      await GoogleSignin.hasPlayServices();

      // Get the platform-specific client ID
      const clientIds = GOOGLE_CLIENT_IDS[__DEV__ ? 'development' : 'production'];
      const platformClientId = Platform.OS === 'ios' ? clientIds.ios : 
                             Platform.OS === 'android' ? clientIds.android : 
                             clientIds.web;

      // Configure Google Sign-In with the platform-specific client ID
      await GoogleSignin.configure({
        webClientId: platformClientId,
        offlineAccess: true,
        scopes: ['profile', 'email'],
        iosClientId: Platform.OS === 'ios' ? clientIds.ios : undefined,
        androidClientid: Platform.OS === 'android' ? clientIds.android : undefined,
      });

      // Sign in with Google
      const userInfo = await GoogleSignin.signIn();
      
      // Get the ID token with the platform-specific client ID
      const { idToken } = await GoogleSignin.getTokens();
      
      if (!idToken) {
        throw new Error('No ID token received from Google Sign-In');
      }

      // Create Firebase credential with the ID token
      const credential = auth.GoogleAuthProvider.credential(idToken);
      const userCredential = await this.auth.signInWithCredential(credential);
      
      if (!userCredential.user) {
        throw new Error('No user returned from Firebase sign-in');
      }

      const firebaseToken = await userCredential.user.getIdToken();

      // Initialize zkLogin with the Firebase token
      console.log('Initializing zkLogin...');
      const { data: initData } = await apolloClient.mutate({
        mutation: INITIALIZE_ZKLOGIN,
        variables: {
          firebaseToken,
          providerToken: idToken,
          provider: 'google'
        }
      });

      if (!initData?.initializeZkLogin) {
        throw new Error('No data received from zkLogin initialization');
      }

      const { maxEpoch, randomness: serverRandomness, salt: serverSalt } = initData.initializeZkLogin;

      // Generate ephemeral key pair
      this.suiKeypair = new Ed25519Keypair();
      const randomness = generateRandomness();
      const userSalt = generateRandomness();

      // Generate nonce using the randomness
      const nonce = generateNonce(this.suiKeypair.getPublicKey(), maxEpoch, randomness);

      // Generate address seed
      const saltBytes = fromB64(serverSalt);
      const saltHex = Buffer.from(saltBytes).toString('hex');
      const saltBigInt = BigInt('0x' + saltHex) % BN254_MODULUS;

      const addressSeed = genAddressSeed(
        saltBigInt,
        'sub',
        jwtDecode(idToken).sub,
        platformClientId
      ).toString();

      // BCS-serialize the seed to bytes (u64)
      const seedBytes = new Uint8Array(8);
      const seedBigInt = BigInt(addressSeed);
      for (let i = 0; i < 8; i++) {
        seedBytes[i] = Number((seedBigInt >> BigInt(i * 8)) & BigInt(0xFF));
      }

      // Sign the seed bytes
      const userSigBytes = await this.suiKeypair.sign(seedBytes);
      const userSignatureBase64 = toB64(userSigBytes);

      // Finalize zkLogin
      const { data: finalizeData } = await apolloClient.mutate({
        mutation: FINALIZE_ZKLOGIN,
        variables: {
          input: {
            maxEpoch: maxEpoch.toString(),
            randomness: serverRandomness,
            salt: serverSalt,
            extendedEphemeralPublicKey: this.suiKeypair.getPublicKey().toBase64(),
            userSignature: userSignatureBase64,
            jwt: idToken,
            keyClaimName: 'sub',
            audience: platformClientId
          }
        }
      });

      if (!finalizeData?.finalizeZkLogin) {
        throw new Error('No data received from zkLogin finalization');
      }

      return {
        userInfo: {
          email: userCredential.user.email,
          name: userCredential.user.displayName,
          photoURL: userCredential.user.photoURL
        },
        zkLoginData: {
          zkProof: finalizeData.finalizeZkLogin.zkProof,
          suiAddress: finalizeData.finalizeZkLogin.suiAddress
        }
      };
    } catch (error) {
      console.error('Error signing in with Google:', error);
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

      const { maxEpoch, randomness: serverRandomness, salt: serverSalt } = initData.initializeZkLogin;

      // Generate ephemeral key pair
      this.suiKeypair = new Ed25519Keypair();
      const randomness = generateRandomness();
      const userSalt = generateRandomness();

      // Generate zkLogin nonce using the randomness
      const zkLoginNonce = generateNonce(this.suiKeypair.getPublicKey(), maxEpoch, randomness);

      // Generate address seed
      const saltBytes = fromB64(serverSalt);
      const saltHex = Buffer.from(saltBytes).toString('hex');
      const saltBigInt = BigInt('0x' + saltHex) % BN254_MODULUS;

      const addressSeed = genAddressSeed(
        saltBigInt,
        'sub',
        jwtDecode(identityToken).sub,
        'apple' // Using 'apple' as the audience for Apple Sign-In
      ).toString();

      // BCS-serialize the seed to bytes (u64)
      const seedBytes = new Uint8Array(8);
      const seedBigInt = BigInt(addressSeed);
      for (let i = 0; i < 8; i++) {
        seedBytes[i] = Number((seedBigInt >> BigInt(i * 8)) & BigInt(0xFF));
      }

      // Sign the seed bytes
      const userSigBytes = await this.suiKeypair.sign(seedBytes);
      const userSignatureBase64 = toB64(userSigBytes);

      // Finalize zkLogin
      const { data: finalizeData } = await apolloClient.mutate({
        mutation: FINALIZE_ZKLOGIN,
        variables: {
          input: {
            maxEpoch: maxEpoch.toString(),
            randomness: serverRandomness,
            salt: serverSalt,
            extendedEphemeralPublicKey: this.suiKeypair.getPublicKey().toBase64(),
            userSignature: userSignatureBase64,
            jwt: identityToken,
            keyClaimName: 'sub',
            audience: 'apple'
          }
        }
      });

      if (!finalizeData?.finalizeZkLogin) {
        throw new Error('No data received from zkLogin finalization');
      }

      return {
        userInfo: {
          email: userCredential.user.email,
          name: userCredential.user.displayName,
          photoURL: userCredential.user.photoURL
        },
        zkLoginData: {
          zkProof: finalizeData.finalizeZkLogin.zkProof,
          suiAddress: finalizeData.finalizeZkLogin.suiAddress
        }
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
      
      // Generate ephemeral key pair
      this.suiKeypair = new Ed25519Keypair();
      
      // Generate randomness using @mysten/zklogin's utility
      const randomness = generateRandomness();
      
      // Generate user salt
      this.userSalt = generateRandomness();
      console.log('Generated user salt');

      // Step 1: Initialize zkLogin with the server
      const { data: initData, errors: initErrors } = await apolloClient.mutate({
        mutation: INITIALIZE_ZKLOGIN,
        variables: {
          firebaseToken: idToken,
          googleToken: idToken // Using the same token for both for now
        }
      });

      if (initErrors) {
        console.error('GraphQL Errors:', initErrors);
        throw new Error('GraphQL mutation failed');
      }

      if (!initData?.initializeZkLogin) {
        throw new Error('No data received from zkLogin initialization');
      }

      const { maxEpoch, randomness: serverRandomness, salt: serverSalt } = initData.initializeZkLogin;

      // Generate nonce using the randomness
      const nonce = generateNonce(this.suiKeypair.getPublicKey(), maxEpoch, randomness);
      console.log('Generated ephemeral key pair and randomness');

      // Get the platform-specific client ID
      const clientIds = GOOGLE_CLIENT_IDS[__DEV__ ? 'development' : 'production'];
      const platformClientId = Platform.OS === 'ios' ? clientIds.ios : 
                             Platform.OS === 'android' ? clientIds.android : 
                             clientIds.web;

      // Generate address seed
      const saltBytes = fromB64(serverSalt);
      const saltHex = Buffer.from(saltBytes).toString('hex');
      const saltBigInt = BigInt('0x' + saltHex) % BN254_MODULUS;

      const addressSeed = genAddressSeed(
        saltBigInt,
        'sub',
        jwtDecode(idToken).sub,
        platformClientId  // Use platform-specific client ID
      ).toString();

      // BCS-serialize the seed to bytes (u64)
      const seedBytes = new Uint8Array(8);
      const seedBigInt = BigInt(addressSeed);
      for (let i = 0; i < 8; i++) {
        seedBytes[i] = Number((seedBigInt >> BigInt(i * 8)) & BigInt(0xFF));
      }

      // Sign the seed bytes
      const userSigBytes = await this.suiKeypair.sign(seedBytes);
      const userSignatureBase64 = toB64(userSigBytes);

      // Log the request body for debugging
      console.log('→ calling generate-proof with', {
        jwt: idToken,
        extendedEphemeralPublicKey: this.suiKeypair.getPublicKey().toBase64(),
        maxEpoch: maxEpoch.toString(),
        randomness: serverRandomness,
        salt: serverSalt,
        keyClaimName: 'sub',
        audience: platformClientId,
        userSignature: userSignatureBase64
      });

      // Step 2: Finalize zkLogin with the server
      const { data: finalizeData, errors: finalizeErrors } = await apolloClient.mutate({
        mutation: FINALIZE_ZKLOGIN,
        variables: {
          maxEpoch: maxEpoch.toString(),
          randomness: serverRandomness,
          salt: serverSalt,
          extendedEphemeralPublicKey: this.suiKeypair.getPublicKey().toBase64(),
          userSignature: userSignatureBase64
        }
      });

      if (finalizeErrors) {
        console.error('GraphQL Errors:', finalizeErrors);
        throw new Error('GraphQL mutation failed');
      }

      if (!finalizeData?.finalizeZkLogin) {
        throw new Error('No data received from zkLogin finalization');
      }

      const { zkProof, suiAddress } = finalizeData.finalizeZkLogin;

      // Store sensitive data securely
      await this.storeSensitiveData({
        suiKeypair: this.suiKeypair.getSecretKey(),
        userSalt: serverSalt,
        zkProof,
        suiAddress
      });
      console.log('Stored sensitive data securely');

      return {
        maxEpoch,
        randomness: serverRandomness,
        nonce,
        userSalt: serverSalt,
        suiAddress
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
    suiAddress: string;
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