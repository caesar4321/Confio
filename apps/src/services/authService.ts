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

// Debug logging for environment variables
console.log('Environment variables loaded:');
console.log('GOOGLE_CLIENT_IDS:', GOOGLE_CLIENT_IDS);
console.log('API_URL:', API_URL);

interface StoredZkLogin {
  salt: string;           // init.salt (base64)
  subject: string;        // sub
  clientId: string;       // oauth clientId
  maxEpoch: number;       // Number(init.maxEpoch)
  zkProof: any;          // the full proof object (points a/b/c etc)
  secretKey: string;     // base64-encoded 32-byte seed
  initRandomness: string; // randomness from initializeZkLogin
  initJwt: string;       // original JWT from sign-in
  headerBase64: string;  // Base64-encoded header from finalization
  issBase64Details: string; // Base64-encoded issuer details from finalization
}

const KEYCHAIN_SERVICE = 'com.confio.zklogin';
const KEYCHAIN_USERNAME = 'zkLoginData';

export class AuthService {
  private static instance: AuthService;
  private suiKeypair: Ed25519Keypair | null = null;
  private suiClient: SuiClient;
  private userSalt: string | null = null;
  private zkProof: any | null = null;
  private maxEpoch: number | null = null;
  private auth = auth();
  private isInitialized = false;

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
    if (this.isInitialized) return;
    
    try {
      await this.initializeFirebase();
      await this.rehydrateZkLoginData();
      this.isInitialized = true;
    } catch (error) {
      console.error('Failed to initialize AuthService:', error);
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
      const config: any = {
        webClientId: clientIds.web,
        offlineAccess: true,
        scopes: ['profile', 'email']
      };

      // Only add Android client ID since iOS client ID is handled by native SDK
      if (Platform.OS === 'android') {
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

      const maxEpochNum = Number(init.maxEpoch);
      if (isNaN(maxEpochNum)) {
        throw new Error('Invalid maxEpoch value received from server');
      }

      // 5) Derive ephemeral keypair (only once!)
      const { sub } = jwtDecode<{ sub: string }>(idToken);
      if (!sub) {
        throw new Error('Invalid JWT: missing sub claim');
      }

      // Use the same client ID for all platforms to ensure consistent Sui addresses
      const clientId = GOOGLE_CLIENT_IDS.production.web;

      this.suiKeypair = this.deriveEphemeralKeypair(init.salt, sub, clientId);

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
      console.log('Storing sensitive data...');
      await this.storeSensitiveData(fin, init.salt, sub, clientId, maxEpochNum, init.randomness, idToken);
      console.log('Sensitive data stored successfully');

      // Split display name into first and last name
      const [firstName, ...lastNameParts] = user.displayName?.split(' ') || [];
      const lastName = lastNameParts.join(' ');

      // 8) Return user info and zkLogin data
      const result = {
        userInfo: { 
          email: user.email, 
          firstName: firstName || '',
          lastName: lastName || '',
          photoURL: user.photoURL 
        },
        zkLoginData: { zkProof: fin.zkProof, suiAddress: fin.suiAddress }
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
        service: KEYCHAIN_SERVICE
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
        service: KEYCHAIN_SERVICE,
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
      this.suiKeypair = this.deriveEphemeralKeypair(serverSalt, appleSub, 'apple');

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
            userSignature: bytesToBase64(await this.suiKeypair.sign(new Uint8Array(0))),
            keyClaimName: 'sub',
            audience: 'apple'
          }
        }
      });

      if (!finalizeData?.finalizeZkLogin) {
        throw new Error('No data received from zkLogin finalization');
      }

      // Store sensitive data securely
      await this.storeSensitiveData(finalizeData.finalizeZkLogin, serverSalt, appleSub, 'apple', Number(maxEpoch), serverRandomness, identityToken);

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
        service: KEYCHAIN_SERVICE,
      });

      if (!credentials) {
        console.log('No stored credentials found');
        return;
      }

      const data = JSON.parse(credentials.password) as StoredZkLogin;
      const { headerBase64, issBase64Details } = data;
      
      console.log('Rehydrating zkLogin data:', {
        hasSalt: !!data.salt,
        hasSubject: !!data.subject,
        hasClientId: !!data.clientId,
        hasMaxEpoch: !!data.maxEpoch,
        hasZkProof: !!data.zkProof,
        hasSecretKey: !!data.secretKey,
        hasInitRandomness: !!data.initRandomness,
        hasInitJwt: !!data.initJwt,
        hasHeaderBase64: !!headerBase64,
        hasIssBase64Details: !!issBase64Details
      });
      
      // Verify the secret key is exactly 32 bytes
      const secretKeyBytes = base64ToBytes(data.secretKey);
      if (secretKeyBytes.length !== 32) {
        throw new Error('Invalid secret key length');
      }

      // Normalize b to object form on load
      if (data.zkProof.zkProof?.b) {
        data.zkProof.zkProof.b = data.zkProof.zkProof.b.map((point: any) => {
          if (typeof point === 'object' && 'x' in point && 'y' in point) {
            return { x: point.x, y: point.y };
          }
          if (Array.isArray(point) && point.length === 2) {
            return { x: point[0], y: point[1] };
          }
          if (typeof point === 'string') {
            const [x, y] = point.split(',');
            return { x: x.trim(), y: y.trim() };
          }
          throw new Error(`Invalid stored point: ${JSON.stringify(point)}`);
        });
      }

      // Reconstruct the full proof object with all required fields
      const fullProof = {
        zkProof: data.zkProof.zkProof,
        subject: data.subject,
        clientId: data.clientId,
        suiAddress: data.zkProof.suiAddress,
        headerBase64,
        issBase64Details
      };

      this.suiKeypair = Ed25519Keypair.fromSecretKey(secretKeyBytes);
      this.userSalt = data.salt;
      this.zkProof = fullProof;  // Store the reconstructed full proof
      this.maxEpoch = data.maxEpoch;

      console.log('Successfully rehydrated zkLogin data:', {
        hasKeypair: !!this.suiKeypair,
        hasUserSalt: !!this.userSalt,
        hasZkProof: !!this.zkProof,
        hasMaxEpoch: !!this.maxEpoch,
        proofFields: {
          hasZkProof: !!this.zkProof.zkProof,
          hasSubject: !!this.zkProof.subject,
          hasClientId: !!this.zkProof.clientId,
          hasHeaderBase64: !!this.zkProof.headerBase64,
          hasIssBase64Details: !!this.zkProof.issBase64Details,
          bStructure: this.zkProof.zkProof?.b?.map((p: any) => ({
            type: typeof p,
            isArray: Array.isArray(p),
            length: p?.length,
            values: p
          }))
        }
      });
    } catch (error) {
      console.error('Error rehydrating zkLogin data:', error);
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

    const secretKey = this.suiKeypair.getSecretKey();
    console.log('Secret key type:', typeof secretKey);
    console.log('Secret key length:', secretKey.length);
    console.log('Secret key bytes:', Array.from(secretKey));

    // Convert string to Uint8Array if needed
    let secretKeyBytes: Uint8Array;
    if (typeof secretKey === 'string') {
      // The secret key string appears to be prefixed with "suiprivkey"
      // Extract just the key bytes (should be 32 bytes)
      const keyBytes = secretKey.slice('suiprivkey'.length);
      secretKeyBytes = new Uint8Array(32);
      for (let i = 0; i < 32; i++) {
        secretKeyBytes[i] = keyBytes.charCodeAt(i);
      }
    } else if (secretKey instanceof Uint8Array) {
      secretKeyBytes = secretKey;
    } else {
      throw new Error('Invalid secret key type');
    }

    if (secretKeyBytes.length !== 32) {
      throw new Error(`Invalid secret key length: ${secretKeyBytes.length} (expected 32)`);
    }

    const secretKeyB64 = bytesToBase64(secretKeyBytes);
    
    // Ensure the proof object has the required structure
    const serializedProof = {
      zkProof: {
        ...proof.zkProof,
        b: proof.zkProof.b.map((pt: any) =>
          pt && typeof pt === 'object' && 'x' in pt && 'y' in pt
            ? { x: pt.x, y: pt.y }
            : Array.isArray(pt) && pt.length === 2
            ? { x: pt[0], y: pt[1] }
            : typeof pt === 'string'
            ? (() => {
                const [x, y] = pt.split(',');
                return { x: x.trim(), y: y.trim() };
              })()
            : (() => { throw new Error(`Invalid point on store: ${JSON.stringify(pt)}`); })()
        )
      },
      subject,
      clientId,
      suiAddress: proof.suiAddress,
      headerBase64: proof.headerBase64,
      issBase64Details: proof.issBase64Details
    };

    const toSave: StoredZkLogin = {
      salt,
      subject,
      clientId,
      maxEpoch,
      zkProof: serializedProof,
      secretKey: secretKeyB64,
      initRandomness,
      initJwt,
      headerBase64: proof.headerBase64,
      issBase64Details: proof.issBase64Details
    };
    
    console.log('Storing zkLogin data with fields:', {
      hasSalt: !!salt,
      hasSubject: !!subject,
      hasClientId: !!clientId,
      hasMaxEpoch: !!maxEpoch,
      hasZkProof: !!proof.zkProof,
      hasSecretKey: !!secretKeyB64,
      hasInitRandomness: !!initRandomness,
      hasInitJwt: !!initJwt,
      hasHeaderBase64: !!proof.headerBase64,
      hasIssBase64Details: !!proof.issBase64Details,
      proofFields: {
        hasZkProof: !!proof.zkProof,
        hasSubject: !!subject,
        hasClientId: !!clientId,
        bStructure: proof.zkProof?.b?.map((p: any) => ({
          type: typeof p,
          isArray: Array.isArray(p),
          length: p?.length,
          values: p
        }))
      }
    });
    
    await Keychain.setGenericPassword(
      KEYCHAIN_USERNAME,
      JSON.stringify(toSave),
      {
        service: KEYCHAIN_SERVICE,
        accessible: Keychain.ACCESSIBLE.WHEN_UNLOCKED_THIS_DEVICE_ONLY
      }
    );

    // Store the serialized proof with subject and clientId
    this.zkProof = serializedProof;
    this.userSalt = salt;
    this.maxEpoch = maxEpoch;
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
        this.maxEpoch = Number(data.maxEpoch);
      }
    } catch (error) {
      console.error('Secure Storage Load Error:', error);
      throw error;
    }
  }

  // Get the user's Sui address
  public async getZkLoginAddress(): Promise<string> {
    if (!this.isInitialized) {
      await this.initialize();
    }

    // Validate all required data is present
    if (!this.suiKeypair || !this.zkProof || !this.userSalt || !this.maxEpoch) {
      console.error('Missing required zkLogin data:', {
        hasKeypair: !!this.suiKeypair,
        hasZkProof: !!this.zkProof,
        hasUserSalt: !!this.userSalt,
        hasMaxEpoch: !!this.maxEpoch
      });
      throw new Error('No zkLogin data stored');
    }

    // Log the full zkProof structure
    console.log('Full zkProof structure:', {
      zkProof: this.zkProof,
      hasInnerZkProof: !!this.zkProof.zkProof,
      innerZkProofType: typeof this.zkProof.zkProof,
      innerZkProofKeys: this.zkProof.zkProof ? Object.keys(this.zkProof.zkProof) : [],
      innerZkProofValue: this.zkProof.zkProof,
      hasHeaderBase64: !!this.zkProof.headerBase64,
      hasIssBase64Details: !!this.zkProof.issBase64Details
    });

    // Validate zkProof has all required fields
    if (!this.zkProof.zkProof || !this.zkProof.subject || !this.zkProof.clientId || 
        !this.zkProof.headerBase64 || !this.zkProof.issBase64Details) {
      console.error('Invalid zkProof data:', {
        hasZkProof: !!this.zkProof.zkProof,
        hasSubject: !!this.zkProof.subject,
        hasClientId: !!this.zkProof.clientId,
        hasHeaderBase64: !!this.zkProof.headerBase64,
        hasIssBase64Details: !!this.zkProof.issBase64Details,
        zkProof: this.zkProof
      });
      throw new Error('Invalid zkProof loaded - missing required fields');
    }

    // Check if we need to refresh the proof due to epoch expiration
    try {
      const state = await this.suiClient.getLatestSuiSystemState();
      const currentEpoch = Number(state.epoch);
      
      // If we're within 1 epoch of expiration, fetch a new proof
      if (currentEpoch >= this.maxEpoch - 1) {
        console.log('zkLogin proof approaching expiration, refreshing...');
        await this.fetchNewProof(apolloClient);
      }
    } catch (error) {
      console.error('Error checking epoch expiration:', error);
      // Continue with existing proof if we can't check epoch
    }

    const saltBytes = base64ToBytes(this.userSalt);
    const saltBigInt = BigInt('0x' + bufferToHex(saltBytes));
    const addressSeed = genAddressSeed(saltBigInt, 'sub', this.zkProof.subject, this.zkProof.clientId).toString();
    const userSignature = await this.suiKeypair.sign(new Uint8Array());
    const proofData = this.zkProof.zkProof;

    // Helper to structure proof points as [string, string][]
    const structureProofPoints = (points: { a: string[]; b: any[]; c: string[] }) => {
      const bPoints: [string, string][] = points.b.map(point => {
        if (Array.isArray(point)) {
          if (point.length !== 2) throw new Error(`Invalid array point: ${point}`);
          return [String(point[0]), String(point[1])] as [string, string];
        } else if (typeof point === 'string') {
          const [x, y] = point.split(',').map(s => s.trim());
          if (!x || !y) throw new Error(`Invalid string point: ${point}`);
          return [x, y] as [string, string];
        } else if (point && typeof point === 'object') {
          if (!('x' in point) || !('y' in point))
            throw new Error(`Invalid object point: ${JSON.stringify(point)}`);
          return [String(point.x), String(point.y)] as [string, string];
        }
        throw new Error(`Invalid point format: ${JSON.stringify(point)}`);
      });
      return { a: points.a, b: bPoints, c: points.c };
    };

    const inputs = {
      proofPoints: structureProofPoints({ a: proofData.a, b: proofData.b, c: proofData.c }),
      issBase64Details: this.zkProof.issBase64Details,
      headerBase64: this.zkProof.headerBase64,
      addressSeed
    };

    return getZkLoginSignature({ inputs, maxEpoch: this.maxEpoch, userSignature });
  }

  // Sign out
  async signOut() {
    try {
      await GoogleSignin.signOut();
      this.suiKeypair = null;
      this.userSalt = null;
      this.zkProof = null;
      this.maxEpoch = null;
      await Keychain.resetGenericPassword({
        service: KEYCHAIN_SERVICE,
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
      const subBytes = stringToUtf8Bytes(sub);
      const clientIdBytes = stringToUtf8Bytes(clientId);

      const seedInput = new Uint8Array([
        ...saltBytes,
        ...subBytes,
        ...clientIdBytes
      ]);

      const fullHash = sha256(seedInput);
      const seed = fullHash.slice(0, 32);
      
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
        service: KEYCHAIN_SERVICE
      });

      if (!credentials) {
        throw new Error("No stored zkLogin data found");
      }

      const stored = JSON.parse(credentials.password) as StoredZkLogin;

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
            audience: this.zkProof.clientId
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
} 