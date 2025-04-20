import { GoogleSignin, User } from '@react-native-google-signin/google-signin';
import { Ed25519Keypair } from '@mysten/sui/keypairs/ed25519';
import { generateNonce, generateRandomness, genAddressSeed, getZkLoginSignature } from '@mysten/sui/zklogin';
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
import { base64ToBytes, bytesToBase64 } from '../utils/base64';

// Add type declarations for TextEncoder and crypto
declare global {
  interface Window {
    crypto?: {
      getRandomValues: (array: Uint8Array) => Uint8Array;
    };
  }
}

class TextEncoder {
  encode(str: string): Uint8Array {
    const bytes = new Uint8Array(str.length);
    for (let i = 0; i < str.length; i++) {
      bytes[i] = str.charCodeAt(i);
    }
    return bytes;
  }
}

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
      const config: any = {
        webClientId: clientIds.web,
        offlineAccess: true,
        scopes: ['profile', 'email']
      };

      // Add platform-specific client IDs
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
      // 1) Sign in with Google first
      await GoogleSignin.hasPlayServices();
      const userInfo = await GoogleSignin.signIn();
      if (!userInfo) {
        throw new Error('No user info returned from Google Sign-In');
      }

      // 2) Get the ID token after successful sign-in
      const { idToken } = await GoogleSignin.getTokens();
      if (!idToken) {
        throw new Error('No ID token received from Google Sign-In');
      }

      // 3) Sign in with Firebase using the Google credential
      const firebaseCred = auth.GoogleAuthProvider.credential(idToken);
      const { user } = await this.auth.signInWithCredential(firebaseCred);
      if (!user) {
        throw new Error('No user returned from Firebase sign-in');
      }

      const firebaseToken = await user.getIdToken();

      // 4) Initialize zkLogin
      const { data: { initializeZkLogin: init } } = await apolloClient.mutate({
        mutation: INITIALIZE_ZKLOGIN,
        variables: { firebaseToken, providerToken: idToken, provider: 'google' }
      });

      if (!init) {
        throw new Error('No data received from zkLogin initialization');
      }

      const maxEpochNum = Number(init.maxEpoch);
      if (isNaN(maxEpochNum)) {
        throw new Error('Invalid maxEpoch value received from server');
      }

      const randomnessBI = BigInt('0x' + Buffer.from(init.randomness, 'base64').toString('hex'));

      // 5) Derive keypair (only once!)
      const { sub } = jwtDecode<{ sub: string }>(idToken);
      if (!sub) {
        throw new Error('Invalid JWT: missing sub claim');
      }

      const clientId = Platform.OS === 'ios'
        ? GOOGLE_CLIENT_IDS.production.ios
        : GOOGLE_CLIENT_IDS.production.android;

      const saltBytes = base64ToBytes(init.salt);
      const encoder = new TextEncoder();
      const seedInput = new Uint8Array([
        ...saltBytes,
        ...encoder.encode(sub),
        ...encoder.encode(clientId)
      ]);
      const fullHash = sha256(seedInput);
      const seed = fullHash.slice(0, 32);
      this.suiKeypair = Ed25519Keypair.fromSecretKey(seed);

      // 6) Finalize zkLogin
      const extendedPub = this.suiKeypair.getPublicKey().toBase64();
      const userSig = bytesToBase64(await this.suiKeypair.sign(new Uint8Array(0)));
      const { data: { finalizeZkLogin: fin } } = await apolloClient.mutate({
        mutation: FINALIZE_ZKLOGIN,
        variables: {
          input: {
            jwt: idToken,
            maxEpoch: init.maxEpoch,
            randomness: init.randomness,
            salt: init.salt,
            extendedEphemeralPublicKey: extendedPub,
            userSignature: userSig,
            keyClaimName: 'sub',
            audience: clientId
          }
        }
      });

      if (!fin) {
        throw new Error('No data received from zkLogin finalization');
      }

      // 7) Store sensitive data securely
      await this.storeSensitiveData({
        suiKeypair: this.suiKeypair.getSecretKey(),
        userSalt: init.salt,
        zkProof: fin.zkProof,
        suiAddress: fin.suiAddress
      });

      // Split display name into first and last name
      const [firstName, ...lastNameParts] = user.displayName?.split(' ') || [];
      const lastName = lastNameParts.join(' ');

      // 8) Return user info and zkLogin data
      return {
        userInfo: { 
          email: user.email, 
          firstName: firstName || '',
          lastName: lastName || '',
          photoURL: user.photoURL 
        },
        zkLoginData: { zkProof: fin.zkProof, suiAddress: fin.suiAddress }
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
      const { identityToken, nonce: appleAuthNonce } = appleAuthRequestResponse;
      const decodedAppleJwt = jwtDecode<{ sub: string }>(identityToken);
      if (!decodedAppleJwt.sub) {
        throw new Error('Invalid Apple JWT: missing sub claim');
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

      const { maxEpoch, randomness: serverRandomness, salt: serverSalt } = initData.initializeZkLogin;

      // Derive the single, deterministic ephemeral keypair
      this.suiKeypair = await this._deriveKeypair(appleSub, 'apple', serverSalt);

      // Convert randomness to BigInt
      const randomnessBigInt = BigInt('0x' + Buffer.from(serverRandomness, 'base64').toString('hex'));

      // Generate nonce using the randomness
      const zkLoginNonce = await this._generateNonce();

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
            salt: serverSalt,
            userSignature: Buffer.from(await this.suiKeypair.sign(new Uint8Array(0))).toString('base64'),
            keyClaimName: 'sub',
            audience: 'apple'
          }
        }
      });

      if (!finalizeData?.finalizeZkLogin) {
        throw new Error('No data received from zkLogin finalization');
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
        this.suiKeypair = Ed25519Keypair.fromSecretKey(Buffer.from(data.suiKeypair, 'base64'));
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

  private async _generateNonce(): Promise<string> {
    const encoder = new TextEncoder();
    const randomBytes = new Uint8Array(32);
    if (typeof crypto !== 'undefined' && crypto.getRandomValues) {
      crypto.getRandomValues(randomBytes);
    } else {
      // Fallback for environments without crypto
      for (let i = 0; i < randomBytes.length; i++) {
        randomBytes[i] = Math.floor(Math.random() * 256);
      }
    }
    const hash = sha256(randomBytes);
    return bytesToBase64(hash);
  }

  private async _deriveKeypair(sub: string, aud: string, saltB64: string): Promise<Ed25519Keypair> {
    try {
      const saltBytes = base64ToBytes(saltB64);
      const encoder = new TextEncoder();
      const subBytes = encoder.encode(sub);
      const audBytes = encoder.encode(aud);
      
      const combinedBytes = new Uint8Array(saltBytes.length + subBytes.length + audBytes.length);
      combinedBytes.set(saltBytes);
      combinedBytes.set(subBytes, saltBytes.length);
      combinedBytes.set(audBytes, saltBytes.length + subBytes.length);
      
      const hash = sha256(combinedBytes);
      return Ed25519Keypair.fromSecretKey(hash);
    } catch (error) {
      console.error('Error deriving keypair:', error);
      throw error;
    }
  }
} 