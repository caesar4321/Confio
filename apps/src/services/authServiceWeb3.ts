import { jwtDecode } from 'jwt-decode';
import * as Keychain from 'react-native-keychain';
import { API_URL } from '../config/env';
import { Platform } from 'react-native';
import { apolloClient } from '../apollo/client';
import { web3AuthService, Web3AuthSession } from './web3AuthService';
import { algorandWalletService, AlgorandAccount } from './algorandWalletService';
import algorandService from './algorandService';

// Type for storing JWT tokens
type TokenStorage = {
  accessToken: string;
  refreshToken: string;
};

// Type for user info
export interface UserInfo {
  email?: string;
  firstName?: string;
  lastName?: string;
  photoURL?: string | null;
  algorandAddress?: string;
  web3AuthId?: string;
}

// Keychain services - Use same as Apollo client for token refresh to work
export const AUTH_KEYCHAIN_SERVICE = 'com.confio.auth';
export const AUTH_KEYCHAIN_USERNAME = 'auth_tokens';

export class AuthServiceWeb3 {
  private static instance: AuthServiceWeb3;
  private currentUser: UserInfo | null = null;
  private algorandAccount: AlgorandAccount | null = null;
  private web3AuthSession: Web3AuthSession | null = null;
  private isInitialized = false;

  private constructor() {}

  public static getInstance(): AuthServiceWeb3 {
    if (!AuthServiceWeb3.instance) {
      AuthServiceWeb3.instance = new AuthServiceWeb3();
    }
    return AuthServiceWeb3.instance;
  }

  public async initialize(): Promise<void> {
    try {
      console.log('AuthServiceWeb3 - initialize() called');
      
      if (this.isInitialized) {
        console.log('AuthServiceWeb3 - Already initialized');
        return;
      }

      // Initialize Web3Auth
      console.log('AuthServiceWeb3 - Initializing Web3Auth...');
      await web3AuthService.initialize();
      
      // Initialize Algorand wallet service
      console.log('AuthServiceWeb3 - Initializing Algorand wallet...');
      await algorandWalletService.initialize('testnet'); // Use testnet for development
      
      // Check if user is already logged in
      const session = web3AuthService.getCurrentSession();
      if (session) {
        console.log('AuthServiceWeb3 - Found existing Web3Auth session');
        this.web3AuthSession = session;
        
        // Restore Algorand account
        const algoAccount = algorandWalletService.getCurrentAccount();
        if (algoAccount) {
          this.algorandAccount = algoAccount;
          console.log('AuthServiceWeb3 - Restored Algorand account:', algoAccount.address);
        }
      }
      
      this.isInitialized = true;
      console.log('AuthServiceWeb3 - Initialization complete');
    } catch (error) {
      console.error('AuthServiceWeb3 - Failed to initialize:', error);
      throw error;
    }
  }

  public async signInWithGoogle(): Promise<UserInfo> {
    try {
      console.log('AuthServiceWeb3 - Starting Google Sign-In with Web3Auth...');
      
      // Ensure services are initialized
      await this.initialize();
      
      // Login with Web3Auth
      const session = await web3AuthService.login('google');
      this.web3AuthSession = session;
      
      // Create Algorand account from Web3Auth
      console.log('AuthServiceWeb3 - Creating Algorand account...');
      const algoAccount = await algorandWalletService.createAccountFromWeb3Auth();
      this.algorandAccount = algoAccount;
      
      // Auto opt-in to CONFIO token with sponsored transaction
      console.log('AuthServiceWeb3 - Processing automatic CONFIO opt-in...');
      try {
        // Ensure algorandService has the account loaded
        await algorandService.initializeWeb3Auth();
        const optInSuccess = await algorandService.processSponsoredOptIn();
        if (optInSuccess) {
          console.log('AuthServiceWeb3 - Successfully opted into CONFIO token');
        } else {
          console.log('AuthServiceWeb3 - CONFIO opt-in failed or already opted in');
        }
      } catch (optInError) {
        console.warn('AuthServiceWeb3 - Could not complete auto opt-in:', optInError);
        // Don't fail the login if opt-in fails - user can retry later
      }
      
      // Prepare user info
      const userInfo: UserInfo = {
        email: session.user.email,
        firstName: session.user.name?.split(' ')[0],
        lastName: session.user.name?.split(' ').slice(1).join(' '),
        photoURL: session.user.profileImage,
        algorandAddress: algoAccount.address,
        web3AuthId: session.user.verifierId,
      };
      
      // Send authentication to backend
      await this.authenticateWithBackend(userInfo, session);
      
      this.currentUser = userInfo;
      
      console.log('AuthServiceWeb3 - Sign-in successful');
      console.log('AuthServiceWeb3 - Algorand address:', algoAccount.address);
      
      return userInfo;
    } catch (error) {
      console.error('AuthServiceWeb3 - Error signing in with Google:', error);
      throw error;
    }
  }

  public async signInWithApple(): Promise<UserInfo> {
    if (Platform.OS !== 'ios') {
      throw new Error('Apple Sign In is only supported on iOS');
    }

    try {
      console.log('AuthServiceWeb3 - Starting Apple Sign-In with Web3Auth...');
      
      // Ensure services are initialized
      await this.initialize();
      
      // Login with Web3Auth
      const session = await web3AuthService.login('apple');
      this.web3AuthSession = session;
      
      // Create Algorand account from Web3Auth
      console.log('AuthServiceWeb3 - Creating Algorand account...');
      const algoAccount = await algorandWalletService.createAccountFromWeb3Auth();
      this.algorandAccount = algoAccount;
      
      // Auto opt-in to CONFIO token with sponsored transaction
      console.log('AuthServiceWeb3 - Processing automatic CONFIO opt-in...');
      try {
        // Ensure algorandService has the account loaded
        await algorandService.initializeWeb3Auth();
        const optInSuccess = await algorandService.processSponsoredOptIn();
        if (optInSuccess) {
          console.log('AuthServiceWeb3 - Successfully opted into CONFIO token');
        } else {
          console.log('AuthServiceWeb3 - CONFIO opt-in failed or already opted in');
        }
      } catch (optInError) {
        console.warn('AuthServiceWeb3 - Could not complete auto opt-in:', optInError);
        // Don't fail the login if opt-in fails - user can retry later
      }
      
      // Prepare user info
      const userInfo: UserInfo = {
        email: session.user.email,
        firstName: session.user.name?.split(' ')[0],
        lastName: session.user.name?.split(' ').slice(1).join(' '),
        photoURL: session.user.profileImage,
        algorandAddress: algoAccount.address,
        web3AuthId: session.user.verifierId,
      };
      
      // Send authentication to backend
      await this.authenticateWithBackend(userInfo, session);
      
      this.currentUser = userInfo;
      
      console.log('AuthServiceWeb3 - Sign-in successful');
      console.log('AuthServiceWeb3 - Algorand address:', algoAccount.address);
      
      return userInfo;
    } catch (error) {
      console.error('AuthServiceWeb3 - Error signing in with Apple:', error);
      throw error;
    }
  }

  private async authenticateWithBackend(userInfo: UserInfo, session: Web3AuthSession): Promise<void> {
    try {
      console.log('AuthServiceWeb3 - Authenticating with backend...');
      
      // Get device fingerprint for security and achievement tracking
      let deviceFingerprint = null;
      try {
        const securityService = (await import('./securityService')).SecurityService.getInstance();
        const fingerprintData = await securityService.getDeviceFingerprint();
        deviceFingerprint = JSON.stringify(fingerprintData.fingerprint);
        console.log('AuthServiceWeb3 - Device fingerprint obtained');
      } catch (fpError) {
        console.warn('AuthServiceWeb3 - Could not get device fingerprint:', fpError);
      }
      
      // Step 1: Web3Auth Login to create/update user (no JWT tokens)
      const { WEB3AUTH_LOGIN } = await import('../apollo/mutations');
      
      console.log('AuthServiceWeb3 - Calling WEB3AUTH_LOGIN mutation...');
      const { data: authData } = await apolloClient.mutate({
        mutation: WEB3AUTH_LOGIN,
        context: {
          skipAuth: true, // This is a login mutation, don't send existing token
        },
        variables: {
          provider: session.user.typeOfLogin,
          web3AuthId: session.user.verifierId,
          email: userInfo.email,
          firstName: userInfo.firstName,
          lastName: userInfo.lastName,
          algorandAddress: userInfo.algorandAddress,
          idToken: session.user.idToken,
          deviceFingerprint: deviceFingerprint,
        },
      });
      
      if (!authData?.web3AuthLogin?.success) {
        throw new Error(authData?.web3AuthLogin?.error || 'Backend user creation failed');
      }
      
      // Store JWT tokens from GraphQL response
      const tokens = {
        accessToken: authData.web3AuthLogin.accessToken,
        refreshToken: authData.web3AuthLogin.refreshToken,
      };
      await this.storeTokens(tokens);
      console.log('AuthServiceWeb3 - JWT tokens stored successfully');
      
      // Step 2: Add Algorand wallet and check for opt-ins
      const { ADD_ALGORAND_WALLET } = await import('../apollo/mutations');
      
      console.log('AuthServiceWeb3 - Calling ADD_ALGORAND_WALLET mutation...');
      const { data: walletData } = await apolloClient.mutate({
        mutation: ADD_ALGORAND_WALLET,
        variables: {
          algorandAddress: userInfo.algorandAddress,
          web3authId: session.user.verifierId,
          provider: session.user.typeOfLogin,
        },
      });
      
      if (!walletData?.addAlgorandWallet?.success) {
        throw new Error(walletData?.addAlgorandWallet?.error || 'Failed to add Algorand wallet');
      }
      
      console.log('AuthServiceWeb3 - Wallet added successfully');
      console.log('AuthServiceWeb3 - ALGO balance:', walletData.addAlgorandWallet.algoBalance);
      console.log('AuthServiceWeb3 - Needs opt-in for assets:', walletData.addAlgorandWallet.needsOptIn);
      
      // Step 3: Handle asset opt-ins if needed
      if (walletData.addAlgorandWallet.needsOptIn?.length > 0) {
        await this.handleAssetOptIns(walletData.addAlgorandWallet.needsOptIn);
      }
      
      console.log('AuthServiceWeb3 - Backend authentication complete');
    } catch (error) {
      console.error('AuthServiceWeb3 - Backend authentication error:', error);
      throw error;
    }
  }

  public async signOut(): Promise<void> {
    try {
      console.log('AuthServiceWeb3 - Starting sign out process...');
      
      // Sign out from Web3Auth
      await web3AuthService.logout();
      
      // Clear Algorand account
      await algorandWalletService.clearAccount();
      
      // Clear stored tokens
      await this.clearTokens();
      
      // Clear local state
      this.currentUser = null;
      this.algorandAccount = null;
      this.web3AuthSession = null;
      
      console.log('AuthServiceWeb3 - Sign out completed');
    } catch (error) {
      console.error('AuthServiceWeb3 - Sign out error:', error);
      // Continue with cleanup even if some operations fail
      this.currentUser = null;
      this.algorandAccount = null;
      this.web3AuthSession = null;
    }
  }

  public async getAlgorandBalance(): Promise<number> {
    try {
      if (!this.algorandAccount) {
        throw new Error('No Algorand account available');
      }
      
      const balance = await algorandWalletService.getBalance();
      return balance.amount;
    } catch (error) {
      console.error('AuthServiceWeb3 - Error getting Algorand balance:', error);
      throw error;
    }
  }

  public async sendAlgorandTransaction(to: string, amount: number, note?: string): Promise<string> {
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
      console.error('AuthServiceWeb3 - Error sending Algorand transaction:', error);
      throw error;
    }
  }

  public getAlgorandAddress(): string | null {
    return this.algorandAccount?.address || null;
  }

  public getCurrentUser(): UserInfo | null {
    return this.currentUser;
  }

  public isSignedIn(): boolean {
    return this.currentUser !== null && this.web3AuthSession !== null;
  }

  // Token management methods
  private async storeTokens(tokens: TokenStorage): Promise<void> {
    try {
      await Keychain.setGenericPassword(
        AUTH_KEYCHAIN_USERNAME,
        JSON.stringify(tokens),
        {
          service: AUTH_KEYCHAIN_SERVICE,
          accessible: Keychain.ACCESSIBLE.WHEN_UNLOCKED,
        }
      );
      console.log('AuthServiceWeb3 - Tokens stored successfully');
    } catch (error) {
      console.error('AuthServiceWeb3 - Error storing tokens:', error);
      throw error;
    }
  }

  private async clearTokens(): Promise<void> {
    try {
      await Keychain.resetGenericPassword({
        service: AUTH_KEYCHAIN_SERVICE,
      });
      console.log('AuthServiceWeb3 - Tokens cleared');
    } catch (error) {
      console.error('AuthServiceWeb3 - Error clearing tokens:', error);
    }
  }

  public async getToken(): Promise<string | null> {
    try {
      const credentials = await Keychain.getGenericPassword({
        service: AUTH_KEYCHAIN_SERVICE,
        username: AUTH_KEYCHAIN_USERNAME,
      });

      if (credentials === false) {
        return null;
      }

      const tokens = JSON.parse(credentials.password);
      return tokens.accessToken || null;
    } catch (error) {
      console.error('AuthServiceWeb3 - Error getting token:', error);
      return null;
    }
  }

  // Migration helper from existing Firebase auth
  public async migrateFromFirebase(firebaseUser: any): Promise<UserInfo> {
    try {
      console.log('AuthServiceWeb3 - Migrating user from Firebase...');
      
      // Migrate to Web3Auth
      const session = await web3AuthService.migrateFromFirebase(firebaseUser);
      this.web3AuthSession = session;
      
      // Create Algorand account
      const algoAccount = await algorandWalletService.createAccountFromWeb3Auth();
      this.algorandAccount = algoAccount;
      
      // Prepare user info
      const userInfo: UserInfo = {
        email: session.user.email || firebaseUser.email,
        firstName: firebaseUser.displayName?.split(' ')[0],
        lastName: firebaseUser.displayName?.split(' ').slice(1).join(' '),
        photoURL: firebaseUser.photoURL,
        algorandAddress: algoAccount.address,
        web3AuthId: session.user.verifierId,
      };
      
      // Authenticate with backend
      await this.authenticateWithBackend(userInfo, session);
      
      this.currentUser = userInfo;
      
      console.log('AuthServiceWeb3 - Migration successful');
      return userInfo;
    } catch (error) {
      console.error('AuthServiceWeb3 - Migration error:', error);
      throw error;
    }
  }
}

// Export singleton instance
const authServiceWeb3 = AuthServiceWeb3.getInstance();
export default authServiceWeb3;