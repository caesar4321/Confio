/**
 * zkLogin OAuth Service
 * Handles OAuth sign-in with pre-computed zkLogin nonce
 */

import { generateNonce } from '@mysten/sui/zklogin';
import { Ed25519Keypair } from '@mysten/sui/keypairs/ed25519';
import { appleAuth } from '@invertase/react-native-apple-authentication';
import { GoogleSignin } from '@react-native-google-signin/google-signin';
import { Platform, Linking } from 'react-native';
import { base64ToBytes, bytesToBase64 } from '../utils/encoding';
import { generateZkLoginSalt } from '../utils/zkLogin';
import { apolloClient } from '../apollo/client';
import { gql } from '@apollo/client';

const PREPARE_ZKLOGIN = gql`
  mutation PrepareZkLogin {
    prepareZkLogin {
      success
      maxEpoch
      randomness
      error
    }
  }
`;

export class ZkLoginOAuthService {
  /**
   * Sign in with Apple using pre-computed zkLogin nonce
   * Apple Sign-In natively supports custom nonce
   */
  static async signInWithApple(): Promise<{
    jwt: string;
    ephemeralKeypair: Ed25519Keypair;
    salt: string;
    maxEpoch: string;
    randomness: string;
    zkLoginNonce: string;
  }> {
    if (Platform.OS !== 'ios') {
      throw new Error('Apple Sign-In is only available on iOS');
    }

    // Step 1: Get zkLogin parameters from server
    const { data } = await apolloClient.mutate({
      mutation: PREPARE_ZKLOGIN
    });

    if (!data?.prepareZkLogin?.success) {
      throw new Error(data?.prepareZkLogin?.error || 'Failed to prepare zkLogin');
    }

    const { maxEpoch, randomness } = data.prepareZkLogin;

    // Step 2: Generate 16-byte salt
    const salt = generateZkLoginSalt(
      'https://appleid.apple.com',
      'temp-sub', // Will be replaced with actual sub from JWT
      'apple',
      'personal',
      '',
      0
    );

    // Step 3: Derive ephemeral keypair from salt
    const saltBytes = base64ToBytes(salt);
    let seed: Uint8Array;
    if (saltBytes.length === 16) {
      // Double 16-byte salt to create 32-byte seed for Ed25519
      seed = new Uint8Array(32);
      seed.set(saltBytes, 0);
      seed.set(saltBytes, 16);
    } else {
      throw new Error(`Invalid salt length: ${saltBytes.length}`);
    }
    const ephemeralKeypair = Ed25519Keypair.fromSecretKey(seed);

    // Step 4: Compute zkLogin nonce
    const randomnessBytes = base64ToBytes(randomness);
    const randomnessBigInt = BigInt('0x' + Buffer.from(randomnessBytes).toString('hex').slice(0, 32));
    
    const zkLoginNonce = generateNonce(
      ephemeralKeypair.getPublicKey(),
      Number(maxEpoch),
      randomnessBigInt
    );

    console.log('Computed zkLogin nonce for Apple:', zkLoginNonce);

    // Step 5: Perform Apple Sign-In with nonce
    const appleResponse = await appleAuth.performRequest({
      requestedOperation: appleAuth.Operation.LOGIN,
      requestedScopes: [appleAuth.Scope.EMAIL, appleAuth.Scope.FULL_NAME],
      nonce: zkLoginNonce  // Apple will SHA256 hash this
    });

    if (!appleResponse.identityToken) {
      throw new Error('No identity token received from Apple');
    }

    return {
      jwt: appleResponse.identityToken,
      ephemeralKeypair,
      salt,
      maxEpoch,
      randomness,
      zkLoginNonce
    };
  }

  /**
   * Sign in with Google using OAuth proxy
   * Since @react-native-google-signin doesn't support custom nonce,
   * we need to use a web-based OAuth flow
   */
  static async signInWithGoogle(): Promise<{
    jwt: string;
    ephemeralKeypair: Ed25519Keypair;
    salt: string;
    maxEpoch: string;
    randomness: string;
    zkLoginNonce: string;
  }> {
    // Step 1: Get zkLogin parameters from server
    const { data } = await apolloClient.mutate({
      mutation: PREPARE_ZKLOGIN
    });

    if (!data?.prepareZkLogin?.success) {
      throw new Error(data?.prepareZkLogin?.error || 'Failed to prepare zkLogin');
    }

    const { maxEpoch, randomness } = data.prepareZkLogin;

    // Step 2: Generate 16-byte salt
    const salt = generateZkLoginSalt(
      'https://accounts.google.com',
      'temp-sub', // Will be replaced with actual sub from JWT
      'google-client-id',
      'personal',
      '',
      0
    );

    // Step 3: Derive ephemeral keypair from salt
    const saltBytes = base64ToBytes(salt);
    let seed: Uint8Array;
    if (saltBytes.length === 16) {
      // Double 16-byte salt to create 32-byte seed for Ed25519
      seed = new Uint8Array(32);
      seed.set(saltBytes, 0);
      seed.set(saltBytes, 16);
    } else {
      throw new Error(`Invalid salt length: ${saltBytes.length}`);
    }
    const ephemeralKeypair = Ed25519Keypair.fromSecretKey(seed);

    // Step 4: Compute zkLogin nonce
    const randomnessBytes = base64ToBytes(randomness);
    const randomnessBigInt = BigInt('0x' + Buffer.from(randomnessBytes).toString('hex').slice(0, 32));
    
    const zkLoginNonce = generateNonce(
      ephemeralKeypair.getPublicKey(),
      Number(maxEpoch),
      randomnessBigInt
    );

    console.log('Computed zkLogin nonce for Google:', zkLoginNonce);

    // Step 5: For now, use the existing Google Sign-In
    // TODO: Implement OAuth proxy or react-native-app-auth
    console.warn('Google Sign-In needs OAuth proxy for custom nonce support');
    
    // Temporary: Use existing flow (will fail with nonce mismatch)
    await GoogleSignin.hasPlayServices();
    const userInfo = await GoogleSignin.signIn();
    const { idToken } = await GoogleSignin.getTokens();

    if (!idToken) {
      throw new Error('No ID token received from Google');
    }

    return {
      jwt: idToken,
      ephemeralKeypair,
      salt,
      maxEpoch,
      randomness,
      zkLoginNonce
    };
  }

  /**
   * Alternative: Google OAuth via Web URL
   * Opens browser for OAuth, then handles callback
   */
  static async signInWithGoogleWeb(clientId: string): Promise<{
    jwt: string;
    ephemeralKeypair: Ed25519Keypair;
    salt: string;
    maxEpoch: string;
    randomness: string;
    zkLoginNonce: string;
  }> {
    // Prepare zkLogin parameters
    const { data } = await apolloClient.mutate({
      mutation: PREPARE_ZKLOGIN
    });

    if (!data?.prepareZkLogin?.success) {
      throw new Error(data?.prepareZkLogin?.error || 'Failed to prepare zkLogin');
    }

    const { maxEpoch, randomness } = data.prepareZkLogin;

    // Generate salt and keypair
    const salt = generateZkLoginSalt(
      'https://accounts.google.com',
      'temp-sub',
      clientId,
      'personal',
      '',
      0
    );

    const saltBytes = base64ToBytes(salt);
    let seed: Uint8Array;
    if (saltBytes.length === 16) {
      seed = new Uint8Array(32);
      seed.set(saltBytes, 0);
      seed.set(saltBytes, 16);
    } else {
      throw new Error(`Invalid salt length: ${saltBytes.length}`);
    }
    const ephemeralKeypair = Ed25519Keypair.fromSecretKey(seed);

    // Compute zkLogin nonce
    const randomnessBytes = base64ToBytes(randomness);
    const randomnessBigInt = BigInt('0x' + Buffer.from(randomnessBytes).toString('hex').slice(0, 32));
    
    const zkLoginNonce = generateNonce(
      ephemeralKeypair.getPublicKey(),
      Number(maxEpoch),
      randomnessBigInt
    );

    // Create OAuth URL with nonce
    const redirectUri = 'com.confio://oauth';
    const oauthUrl = 
      `https://accounts.google.com/o/oauth2/v2/auth?` +
      `client_id=${clientId}&` +
      `redirect_uri=${encodeURIComponent(redirectUri)}&` +
      `response_type=id_token&` +
      `scope=openid%20email%20profile&` +
      `nonce=${zkLoginNonce}&` +
      `prompt=select_account`;

    // Open OAuth URL in browser
    await Linking.openURL(oauthUrl);

    // Wait for callback with id_token
    // This would need to be implemented with deep linking
    return new Promise((resolve, reject) => {
      const handleUrl = (url: string) => {
        // Parse id_token from URL
        const matches = url.match(/id_token=([^&]+)/);
        if (matches && matches[1]) {
          resolve({
            jwt: matches[1],
            ephemeralKeypair,
            salt,
            maxEpoch,
            randomness,
            zkLoginNonce
          });
        } else {
          reject(new Error('No id_token in callback URL'));
        }
      };

      // Set up deep link listener
      Linking.addEventListener('url', ({ url }) => handleUrl(url));
      
      // Timeout after 5 minutes
      setTimeout(() => {
        reject(new Error('OAuth timeout'));
      }, 5 * 60 * 1000);
    });
  }
}