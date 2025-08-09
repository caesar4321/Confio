/**
 * Algorand Extension for existing Firebase Authentication
 * 
 * This service adds Algorand wallet functionality to existing authenticated users
 * without changing the current authentication flow.
 */

import { web3AuthService } from './web3AuthService';
import { algorandWalletService } from './algorandWalletService';
import { apolloClient } from '../apollo/client';
import authService from './authService';

export interface AlgorandWalletInfo {
  address: string;
  balance?: number;
  isNew?: boolean;
}

class AlgorandExtension {
  private static instance: AlgorandExtension;
  private isInitialized = false;
  private algorandAddress: string | null = null;

  private constructor() {}

  public static getInstance(): AlgorandExtension {
    if (!AlgorandExtension.instance) {
      AlgorandExtension.instance = new AlgorandExtension();
    }
    return AlgorandExtension.instance;
  }

  /**
   * Initialize Algorand services
   * Call this after user has authenticated with Firebase
   */
  public async initialize(): Promise<void> {
    if (this.isInitialized) {
      console.log('AlgorandExtension - Already initialized');
      return;
    }

    try {
      console.log('AlgorandExtension - Initializing...');
      
      // Initialize Web3Auth with Single Factor Auth
      try {
        await web3AuthService.initialize();
        console.log('AlgorandExtension - Web3Auth initialized successfully');
      } catch (web3AuthError) {
        console.error('AlgorandExtension - Web3Auth initialization failed:', web3AuthError);
        // Continue without Web3Auth - we can't create Algorand wallets without it
        return;
      }
      
      // Initialize Algorand wallet service
      try {
        await algorandWalletService.initialize('testnet');
        console.log('AlgorandExtension - Algorand wallet service initialized');
      } catch (algoError) {
        console.error('AlgorandExtension - Algorand wallet service initialization failed:', algoError);
        // Continue without Algorand wallet service
        return;
      }
      
      this.isInitialized = true;
      console.log('AlgorandExtension - Initialization complete');
    } catch (error) {
      console.error('AlgorandExtension - Initialization error:', error);
      // Don't throw - Algorand is optional functionality
    }
  }

  /**
   * Create or get Algorand wallet for the current authenticated user
   * This should be called after successful Firebase authentication
   */
  public async setupAlgorandWallet(): Promise<AlgorandWalletInfo | null> {
    try {
      // Ensure user is authenticated with Firebase first
      const currentUser = authService.getCurrentAccount();
      if (!currentUser) {
        console.log('AlgorandExtension - No authenticated user, skipping wallet setup');
        return null;
      }

      console.log('AlgorandExtension - Setting up Algorand wallet for user...');
      
      // Initialize if not already done
      if (!this.isInitialized) {
        await this.initialize();
      }

      // Check if user already has a wallet
      const existingAddress = await this.checkExistingWallet();
      if (existingAddress) {
        // Check if it's an Aptos address that needs migration
        if (existingAddress.startsWith('0x')) {
          console.log('AlgorandExtension - Found Aptos address, needs migration:', existingAddress);
          // Continue to create new Algorand wallet below
        } else {
          console.log('AlgorandExtension - User already has Algorand wallet:', existingAddress);
          this.algorandAddress = existingAddress;
          
          // Get balance
          const balance = await this.getBalance();
          
          return {
            address: existingAddress,
            balance,
            isNew: false
          };
        }
      }

      // Create new Algorand wallet using Web3Auth Single Factor Auth
      console.log('AlgorandExtension - Creating new Algorand wallet...');
      
      // For Single Factor Auth with native OAuth providers
      // ID token is optional - Web3Auth can work with just the provider type
      console.log('AlgorandExtension - Getting OAuth ID token (optional)...');
      const idToken = await this.getCurrentIdToken();
      if (idToken) {
        console.log('AlgorandExtension - Got OAuth ID token (length:', idToken.length, ')');
      } else {
        console.log('AlgorandExtension - No OAuth ID token, proceeding with provider-only auth');
      }

      // Determine provider from current session
      const provider = await this.getCurrentProvider();
      console.log('AlgorandExtension - Provider detected:', provider);
      
      // Login to Web3Auth with Single Factor Auth
      console.log('AlgorandExtension - Logging into Web3Auth with SFA...');
      const session = await web3AuthService.login(provider, idToken);
      console.log('AlgorandExtension - Web3Auth session created:', !!session);
      
      // Create Algorand account from Web3Auth
      console.log('AlgorandExtension - Creating Algorand account from Web3Auth keys...');
      const algoAccount = await algorandWalletService.createAccountFromWeb3Auth();
      this.algorandAddress = algoAccount.address;
      console.log('AlgorandExtension - Algorand account created:', algoAccount.address);
      
      // Update backend with new Algorand address
      await this.updateBackendWallet(algoAccount.address, session.user?.verifierId, provider);
      
      console.log('AlgorandExtension - Wallet setup complete with address:', algoAccount.address);
      
      // Refresh Apollo cache to update UI
      await this.refreshApolloCache();
      
      return {
        address: algoAccount.address,
        balance: 0,
        isNew: true
      };
      
    } catch (error) {
      console.error('AlgorandExtension - Error setting up wallet:', error);
      return null;
    }
  }

  /**
   * Check if the current user already has an Algorand wallet
   */
  private async checkExistingWallet(): Promise<string | null> {
    try {
      const { GET_ME } = await import('../apollo/queries');
      
      const { data } = await apolloClient.query({
        query: GET_ME,
        fetchPolicy: 'network-only'
      });
      
      // Check if user has wallet address in their account
      const algorandAddress = data?.me?.accounts?.[0]?.algorandAddress;
      
      if (algorandAddress) {
        // Also check if we can restore the wallet locally
        const currentAccount = algorandWalletService.getCurrentAccount();
        if (!currentAccount) {
          // Try to restore from Web3Auth
          const session = web3AuthService.getCurrentSession();
          if (session) {
            await algorandWalletService.createAccountFromWeb3Auth();
          }
        }
        
        return algorandAddress;
      }
      
      return null;
    } catch (error) {
      console.error('AlgorandExtension - Error checking existing wallet:', error);
      return null;
    }
  }

  /**
   * Get the current OAuth ID token (Google or Apple)
   * For Web3Auth SFA, we need the original OAuth provider's ID token, not Firebase's
   */
  private async getCurrentIdToken(): Promise<string | null> {
    try {
      // Get the ID token on the fly from Google Sign-In or Apple Auth
      const provider = await this.getCurrentProvider();
      
      if (provider === 'google') {
        // Try to get current Google tokens
        const GoogleSignin = (await import('@react-native-google-signin/google-signin')).GoogleSignin;
        
        try {
          // Check if user is signed in with Google
          const isSignedIn = await GoogleSignin.isSignedIn();
          if (isSignedIn) {
            const tokens = await GoogleSignin.getTokens();
            if (tokens.idToken) {
              console.log('AlgorandExtension - Got Google ID token on the fly');
              return tokens.idToken;
            }
          }
        } catch (error) {
          console.log('AlgorandExtension - Could not get Google tokens:', error);
        }
      } else if (provider === 'apple') {
        // Apple doesn't provide easy token refresh like Google
        // Would need to trigger a new Apple sign-in flow
        console.log('AlgorandExtension - Apple token refresh not implemented');
      }
      
      // If we can't get the token on the fly, we might need to use in-app browser
      // like zkLogin and Keyless do
      console.log('AlgorandExtension - No OAuth ID token available on the fly');
      return null;
    } catch (error) {
      console.error('AlgorandExtension - Error getting OAuth ID token:', error);
      return null;
    }
  }

  /**
   * Determine the current provider (google or apple)
   */
  private async getCurrentProvider(): Promise<'google' | 'apple'> {
    try {
      const auth = (await import('@react-native-firebase/auth')).default();
      const currentUser = auth.currentUser;
      
      if (currentUser?.providerData) {
        const providerData = currentUser.providerData[0];
        if (providerData?.providerId === 'apple.com') {
          return 'apple';
        }
      }
      
      return 'google'; // Default to Google
    } catch (error) {
      console.error('AlgorandExtension - Error getting provider:', error);
      return 'google';
    }
  }

  /**
   * Update backend with Algorand wallet address
   */
  private async updateBackendWallet(address: string, web3AuthId?: string, provider?: string): Promise<void> {
    try {
      const { ADD_ALGORAND_WALLET } = await import('../apollo/mutations');
      
      const { data } = await apolloClient.mutate({
        mutation: ADD_ALGORAND_WALLET,
        variables: {
          algorandAddress: address,
          web3AuthId,
          provider
        }
      });
      
      if (data?.addAlgorandWallet?.success) {
        console.log('AlgorandExtension - Backend updated with Algorand address');
      }
    } catch (error) {
      console.error('AlgorandExtension - Error updating backend:', error);
      // Don't throw - this is optional
    }
  }

  /**
   * Get Algorand balance for the current user
   */
  public async getBalance(): Promise<number> {
    try {
      if (!this.algorandAddress) {
        return 0;
      }
      
      const balance = await algorandWalletService.getBalance(this.algorandAddress);
      return balance.amount;
    } catch (error) {
      console.error('AlgorandExtension - Error getting balance:', error);
      return 0;
    }
  }

  /**
   * Send Algorand transaction
   */
  public async sendTransaction(to: string, amount: number, note?: string): Promise<string | null> {
    try {
      if (!this.algorandAddress) {
        throw new Error('No Algorand wallet available');
      }
      
      const txId = await algorandWalletService.sendTransaction({
        from: this.algorandAddress,
        to,
        amount,
        note
      });
      
      return txId;
    } catch (error) {
      console.error('AlgorandExtension - Error sending transaction:', error);
      return null;
    }
  }

  /**
   * Get the current Algorand address
   */
  public getAddress(): string | null {
    return this.algorandAddress;
  }

  /**
   * Check if user has an Algorand wallet
   */
  public hasWallet(): boolean {
    return !!this.algorandAddress;
  }

  /**
   * Refresh Apollo cache to update UI with new wallet address
   */
  private async refreshApolloCache(): Promise<void> {
    try {
      console.log('AlgorandExtension - Refreshing Apollo cache...');
      
      // Refetch current user data to update the cache
      const { GET_ME } = await import('../apollo/queries');
      
      await apolloClient.query({
        query: GET_ME,
        fetchPolicy: 'network-only'
      });
      
      // Also try to reset the store to force all queries to refetch
      await apolloClient.resetStore();
      
      console.log('AlgorandExtension - Apollo cache refreshed');
    } catch (error) {
      console.error('AlgorandExtension - Error refreshing cache:', error);
      // Don't throw - this is optional
    }
  }
}

// Export singleton instance
export const algorandExtension = AlgorandExtension.getInstance();