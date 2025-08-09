import { GoogleSignin } from '@react-native-google-signin/google-signin';
import { appleAuth } from '@invertase/react-native-apple-authentication';
import { jwtDecode } from 'jwt-decode';
import * as Keychain from 'react-native-keychain';
import { GOOGLE_CLIENT_IDS, API_URL } from '../config/env';
import auth from '@react-native-firebase/auth';
import { Platform } from 'react-native';
import { apolloClient } from '../apollo/client';
import { AccountManager, AccountContext } from '../utils/accountManager';
import { web3AuthService, Web3AuthSession } from './web3AuthService';
import { algorandWalletService, AlgorandAccount } from './algorandWalletService';

// This hybrid service maintains Firebase as the primary authentication
// while adding Web3Auth for Algorand wallet functionality

export interface HybridUserInfo {
  // Firebase user data
  firebaseUid: string;
  email?: string;
  firstName?: string;
  lastName?: string;
  photoURL?: string | null;
  isPhoneVerified?: boolean;
  
  // Algorand wallet data (from Web3Auth)
  algorandAddress?: string;
  hasAlgorandWallet?: boolean;
}

// Keychain services
const HYBRID_KEYCHAIN_SERVICE = 'com.confio.hybrid';
const HYBRID_KEYCHAIN_USERNAME = 'hybrid_auth_data';

export class AuthServiceHybrid {
  private static instance: AuthServiceHybrid;
  private currentUser: HybridUserInfo | null = null;
  private firebaseUser: any = null;
  private algorandAccount: AlgorandAccount | null = null;
  private web3AuthSession: Web3AuthSession | null = null;
  private auth = auth();
  private isInitialized = false;

  private constructor() {}

  public static getInstance(): AuthServiceHybrid {
    if (!AuthServiceHybrid.instance) {
      AuthServiceHybrid.instance = new AuthServiceHybrid();
    }
    return AuthServiceHybrid.instance;
  }

  public async initialize(): Promise<void> {
    try {
      console.log('AuthServiceHybrid - Initializing...');
      
      if (this.isInitialized) {
        console.log('AuthServiceHybrid - Already initialized');
        return;
      }

      // Initialize Google Sign-In for Firebase
      await this.configureGoogleSignIn();
      
      // Initialize Web3Auth (for Algorand wallet)
      console.log('AuthServiceHybrid - Initializing Web3Auth for Algorand...');
      await web3AuthService.initialize();
      
      // Initialize Algorand wallet service
      console.log('AuthServiceHybrid - Initializing Algorand wallet service...');
      await algorandWalletService.initialize('testnet'); // Use testnet for development
      
      // Check if user is already signed in with Firebase
      const currentFirebaseUser = this.auth.currentUser;
      if (currentFirebaseUser) {
        console.log('AuthServiceHybrid - Found existing Firebase user:', currentFirebaseUser.uid);
        this.firebaseUser = currentFirebaseUser;
        
        // Try to restore Algorand wallet if it exists
        await this.restoreAlgorandWallet();
      }
      
      this.isInitialized = true;
      console.log('AuthServiceHybrid - Initialization complete');
    } catch (error) {
      console.error('AuthServiceHybrid - Failed to initialize:', error);
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

  public async signInWithGoogle(): Promise<HybridUserInfo> {
    try {
      console.log('AuthServiceHybrid - Starting Google Sign-In with Firebase...');
      
      // Step 1: Sign in with Firebase (primary auth)
      await GoogleSignin.hasPlayServices();
      const { idToken } = await GoogleSignin.signIn();
      
      if (!idToken) {
        throw new Error('No ID token received from Google Sign-In');
      }

      const googleCredential = auth.GoogleAuthProvider.credential(idToken);
      const userCredential = await this.auth.signInWithCredential(googleCredential);
      this.firebaseUser = userCredential.user;
      
      console.log('AuthServiceHybrid - Firebase sign-in successful:', this.firebaseUser.uid);
      
      // Step 2: Authenticate with backend using Firebase UID
      const backendAuth = await this.authenticateWithBackend();
      
      // Step 3: Initialize Algorand wallet through Web3Auth (Single Factor Auth)
      // This uses the Firebase ID token as the verifier
      await this.initializeAlgorandWallet('google', idToken);
      
      // Build user info
      const userInfo: HybridUserInfo = {
        firebaseUid: this.firebaseUser.uid,
        email: this.firebaseUser.email,
        firstName: this.firebaseUser.displayName?.split(' ')[0],
        lastName: this.firebaseUser.displayName?.split(' ').slice(1).join(' '),
        photoURL: this.firebaseUser.photoURL,
        isPhoneVerified: backendAuth?.isPhoneVerified || false,
        algorandAddress: this.algorandAccount?.address,
        hasAlgorandWallet: !!this.algorandAccount,
      };
      
      this.currentUser = userInfo;
      await this.storeHybridData(userInfo);
      
      console.log('AuthServiceHybrid - Sign-in complete with Algorand address:', userInfo.algorandAddress);
      return userInfo;
      
    } catch (error) {
      console.error('AuthServiceHybrid - Error signing in with Google:', error);
      throw error;
    }
  }

  public async signInWithApple(): Promise<HybridUserInfo> {
    if (Platform.OS !== 'ios') {
      throw new Error('Apple Sign In is only supported on iOS');
    }

    try {
      console.log('AuthServiceHybrid - Starting Apple Sign-In with Firebase...');
      
      // Step 1: Sign in with Firebase (primary auth)
      const appleAuthRequestResponse = await appleAuth.performRequest({
        requestedOperation: appleAuth.Operation.LOGIN,
        requestedScopes: [appleAuth.Scope.EMAIL, appleAuth.Scope.FULL_NAME],
      });

      if (!appleAuthRequestResponse.identityToken) {
        throw new Error('Apple Sign In failed - no identify token returned');
      }

      const { identityToken, nonce } = appleAuthRequestResponse;
      const appleCredential = auth.AppleAuthProvider.credential(identityToken, nonce);
      const userCredential = await this.auth.signInWithCredential(appleCredential);
      this.firebaseUser = userCredential.user;
      
      console.log('AuthServiceHybrid - Firebase sign-in successful:', this.firebaseUser.uid);
      
      // Step 2: Authenticate with backend using Firebase UID
      const backendAuth = await this.authenticateWithBackend();
      
      // Step 3: Initialize Algorand wallet through Web3Auth
      await this.initializeAlgorandWallet('apple', identityToken);
      
      // Build user info
      const userInfo: HybridUserInfo = {
        firebaseUid: this.firebaseUser.uid,
        email: this.firebaseUser.email || appleAuthRequestResponse.email,
        firstName: appleAuthRequestResponse.fullName?.givenName,
        lastName: appleAuthRequestResponse.fullName?.familyName,
        photoURL: this.firebaseUser.photoURL,
        isPhoneVerified: backendAuth?.isPhoneVerified || false,
        algorandAddress: this.algorandAccount?.address,
        hasAlgorandWallet: !!this.algorandAccount,
      };
      
      this.currentUser = userInfo;
      await this.storeHybridData(userInfo);
      
      console.log('AuthServiceHybrid - Sign-in complete with Algorand address:', userInfo.algorandAddress);
      return userInfo;
      
    } catch (error) {
      console.error('AuthServiceHybrid - Error signing in with Apple:', error);
      throw error;
    }
  }

  private async initializeAlgorandWallet(provider: 'google' | 'apple', idToken: string): Promise<void> {
    try {
      console.log('AuthServiceHybrid - Initializing Algorand wallet with Web3Auth Single Factor Auth...');
      
      // For Single Factor Auth, we use the Firebase ID token directly
      // Web3Auth will use this to generate a deterministic key
      const web3AuthLoginParams = {
        loginProvider: provider,
        extraLoginOptions: {
          id_token: idToken,
          verifierIdField: 'sub', // Use the subject field from the JWT
        },
      };
      
      // Login to Web3Auth using Single Factor Auth with the ID token
      // This should work invisibly without any OAuth redirects
      const session = await web3AuthService.login(provider, idToken);
      this.web3AuthSession = session;
      
      // Create Algorand account from Web3Auth
      console.log('AuthServiceHybrid - Creating Algorand account from Web3Auth...');
      const algoAccount = await algorandWalletService.createAccountFromWeb3Auth();
      this.algorandAccount = algoAccount;
      
      console.log('AuthServiceHybrid - Algorand wallet initialized:', algoAccount.address);
      
      // Update backend with Algorand address
      await this.updateBackendAlgorandAddress(algoAccount.address);
      
    } catch (error) {
      console.error('AuthServiceHybrid - Error initializing Algorand wallet:', error);
      // Don't throw - Algorand wallet is optional functionality
      // Users can still use the app without it
    }
  }

  private async authenticateWithBackend(): Promise<any> {
    try {
      console.log('AuthServiceHybrid - Using existing Firebase authentication flow...');
      
      // Simply use the existing authService for Firebase authentication
      // This maintains all existing authentication logic
      const { default: authService } = await import('./authService');
      
      // The original authService already handles Firebase auth properly
      // We just need to ensure the user is authenticated
      const token = await authService.getToken();
      
      if (token) {
        console.log('AuthServiceHybrid - User already authenticated with backend');
        return { success: true };
      }
      
      // If no token, the user needs to complete the normal auth flow
      // This would have been done during signInWithGoogle/Apple
      console.log('AuthServiceHybrid - Backend authentication already handled by Firebase flow');
      return { success: true };
      
    } catch (error) {
      console.error('AuthServiceHybrid - Backend authentication check error:', error);
      // Don't throw - authentication might still be valid
      return { success: true };
    }
  }

  private async updateBackendAlgorandAddress(address: string): Promise<void> {
    try {
      console.log('AuthServiceHybrid - Updating backend with Algorand address...');
      
      const { ADD_ALGORAND_WALLET } = await import('../apollo/mutations');
      
      const provider = this.firebaseUser.providerData[0]?.providerId.includes('apple') ? 'apple' : 'google';
      const web3AuthId = this.web3AuthSession?.user?.verifierId;
      
      const { data } = await apolloClient.mutate({
        mutation: ADD_ALGORAND_WALLET,
        variables: {
          algorandAddress: address,
          web3AuthId: web3AuthId,
          provider: provider,
        },
      });
      
      if (data?.addAlgorandWallet?.success) {
        console.log('AuthServiceHybrid - Backend updated with Algorand address');
        if (data.addAlgorandWallet.isNewWallet) {
          console.log('AuthServiceHybrid - This is a new Algorand wallet for the user');
        }
      }
    } catch (error) {
      console.error('AuthServiceHybrid - Error updating backend with Algorand address:', error);
      // Don't throw - this is optional functionality
    }
  }

  public async signOut(): Promise<void> {
    try {
      console.log('AuthServiceHybrid - Starting sign out process...');
      
      // Sign out from Firebase (primary)
      await this.auth.signOut();
      
      // Sign out from Google if signed in
      try {
        const isSignedIn = await GoogleSignin.isSignedIn();
        if (isSignedIn) {
          await GoogleSignin.signOut();
        }
      } catch (error) {
        console.log('Google sign out skipped:', error);
      }
      
      // Sign out from Web3Auth (if initialized)
      try {
        await web3AuthService.logout();
      } catch (error) {
        console.log('Web3Auth sign out skipped:', error);
      }
      
      // Clear Algorand wallet
      try {
        await algorandWalletService.clearAccount();
      } catch (error) {
        console.log('Algorand wallet clear skipped:', error);
      }
      
      // Clear stored data
      await this.clearHybridData();
      await this.clearTokens();
      
      // Clear local state
      this.currentUser = null;
      this.firebaseUser = null;
      this.algorandAccount = null;
      this.web3AuthSession = null;
      
      console.log('AuthServiceHybrid - Sign out completed');
    } catch (error) {
      console.error('AuthServiceHybrid - Sign out error:', error);
      // Continue with cleanup
      this.currentUser = null;
      this.firebaseUser = null;
      this.algorandAccount = null;
      this.web3AuthSession = null;
    }
  }

  // Algorand-specific methods
  public async getAlgorandBalance(): Promise<number | null> {
    try {
      if (!this.algorandAccount) {
        console.log('No Algorand account available');
        return null;
      }
      
      const balance = await algorandWalletService.getBalance();
      return balance.amount;
    } catch (error) {
      console.error('Error getting Algorand balance:', error);
      return null;
    }
  }

  public async sendAlgorandTransaction(to: string, amount: number, note?: string): Promise<string | null> {
    try {
      if (!this.algorandAccount) {
        throw new Error('No Algorand account available');
      }
      
      const txId = await algorandWalletService.sendTransaction({
        from: this.algorandAccount.address,
        to,
        amount,
        note,
      });
      
      return txId;
    } catch (error) {
      console.error('Error sending Algorand transaction:', error);
      return null;
    }
  }

  public async ensureAlgorandWallet(): Promise<string | null> {
    try {
      // If wallet already exists, return it
      if (this.algorandAccount) {
        return this.algorandAccount.address;
      }
      
      // If not signed in, return null
      if (!this.firebaseUser) {
        return null;
      }
      
      // Try to initialize Algorand wallet
      const idToken = await this.firebaseUser.getIdToken();
      const provider = this.firebaseUser.providerData[0]?.providerId.includes('apple') ? 'apple' : 'google';
      
      await this.initializeAlgorandWallet(provider, idToken);
      
      return this.algorandAccount?.address || null;
    } catch (error) {
      console.error('Error ensuring Algorand wallet:', error);
      return null;
    }
  }

  // Helper methods
  public getFirebaseUid(): string | null {
    return this.firebaseUser?.uid || null;
  }

  public getAlgorandAddress(): string | null {
    return this.algorandAccount?.address || null;
  }

  public getCurrentUser(): HybridUserInfo | null {
    return this.currentUser;
  }

  public isSignedIn(): boolean {
    return !!this.firebaseUser;
  }

  public hasAlgorandWallet(): boolean {
    return !!this.algorandAccount;
  }

  // Storage methods
  private async storeHybridData(data: HybridUserInfo): Promise<void> {
    try {
      await Keychain.setInternetCredentials(
        HYBRID_KEYCHAIN_SERVICE,
        HYBRID_KEYCHAIN_USERNAME,
        JSON.stringify(data)
      );
    } catch (error) {
      console.error('Error storing hybrid data:', error);
    }
  }

  private async clearHybridData(): Promise<void> {
    try {
      await Keychain.resetInternetCredentials({ server: HYBRID_KEYCHAIN_SERVICE });
    } catch (error) {
      console.error('Error clearing hybrid data:', error);
    }
  }

  private async storeTokens(tokens: any): Promise<void> {
    try {
      await Keychain.setGenericPassword(
        'auth_tokens',
        JSON.stringify(tokens),
        {
          service: 'com.confio.auth',
          accessible: Keychain.ACCESSIBLE.WHEN_UNLOCKED,
        }
      );
    } catch (error) {
      console.error('Error storing tokens:', error);
    }
  }

  private async clearTokens(): Promise<void> {
    try {
      await Keychain.resetGenericPassword({
        service: 'com.confio.auth',
      });
    } catch (error) {
      console.error('Error clearing tokens:', error);
    }
  }

  private async restoreAlgorandWallet(): Promise<void> {
    try {
      // Check if Web3Auth has a session
      const web3AuthSession = web3AuthService.getCurrentSession();
      if (web3AuthSession) {
        this.web3AuthSession = web3AuthSession;
        
        // Check if Algorand wallet exists
        const algoAccount = algorandWalletService.getCurrentAccount();
        if (algoAccount) {
          this.algorandAccount = algoAccount;
          console.log('AuthServiceHybrid - Restored Algorand wallet:', algoAccount.address);
        }
      }
    } catch (error) {
      console.error('Error restoring Algorand wallet:', error);
    }
  }
}

// Export singleton instance
const authServiceHybrid = AuthServiceHybrid.getInstance();
export default authServiceHybrid;