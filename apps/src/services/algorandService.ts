import * as Keychain from 'react-native-keychain';
import { secureDeterministicWallet } from './secureDeterministicWallet';
import { jwtDecode } from 'jwt-decode';
import { Buffer } from 'buffer'; // RN polyfill for base64

// CONFIO token configuration
const CONFIO_ASSET_ID = 743890784; // Testnet CONFIO asset ID

// Type for account info
type AccountLite = { addr: string; sk: null };

class AlgorandService {
  // Web3Auth properties no longer used - we use secure deterministic wallet
  private web3auth: any = null; // Kept for compatibility checks
  private algodClient: any = null;
  private currentAccount: AccountLite | null = null;
  private algosdk: any = null;
  
  // Deprecated Web3Auth properties (no longer initialized)
  private Web3Auth: any = null;
  private web3authBase: any = null;
  private CommonPrivateKeyProvider: any = null;
  private SDK_MODE: any = null;
  private WEB3AUTH_NETWORK: any = null;

  constructor() {
    // Delay initialization to avoid import errors
  }

  /**
   * Pre-initialize the SDK at app startup to avoid delays during sign-in
   * This is called from bootstrap.ts to warm up the imports
   */
  async preInitialize(): Promise<void> {
    try {
      console.log('[AlgorandService] Pre-initializing SDK...');
      await this.ensureInitialized();
      console.log('[AlgorandService] SDK pre-initialized successfully');
    } catch (error) {
      console.warn('[AlgorandService] Pre-initialization failed:', error);
      // Non-fatal - will retry on actual use
    }
  }

  private async ensureInitialized() {
    if (!this.algosdk) {
      try {
        // Lazy load the libraries (polyfills are already loaded in index.js)
        console.log('Importing algosdk...');
        const algosdk = await import('algosdk');
        console.log('algosdk imported successfully');
        
        // Web3Auth is no longer used - we use secure deterministic wallet instead
        // Skip Web3Auth imports to avoid casting errors
        
        // Debug algosdk import
        console.log('algosdk keys:', Object.keys(algosdk));
        console.log('algosdk.default:', algosdk.default);
        console.log('algosdk.Algodv2:', algosdk.Algodv2);
        
        this.algosdk = algosdk;
        
        // Clear Web3Auth references - no longer used
        this.Web3Auth = null;
        this.web3authBase = null;
        this.CommonPrivateKeyProvider = null;
        this.SDK_MODE = null;
        this.WEB3AUTH_NETWORK = null;
        
        console.log('Skipping Algodv2 client creation (not needed for wallet generation)...');
        // For now, skip Algod client creation since it's causing URL parsing issues
        // We only need algosdk for mnemonic/address generation, not for API calls
        
        this.algodClient = {
          healthCheck: async () => ({ do: async () => ({ status: 'ok' }) }),
          status: async () => ({ do: async () => ({ 'last-round': 0 }) }),
          getTransactionParams: async () => ({ do: async () => ({
            fee: 1000,
            firstRound: 1000,
            lastRound: 2000,
            genesisHash: 'SGO1GKSzyE7IEPItTxCByw9x8FmnrCDexi9/cOUJOiI=',
            genesisID: 'testnet-v1.0',
            flatFee: false
          }) }),
          accountInformation: async (address: string) => ({ do: async () => ({
            amount: 0 // Mock balance
          }) }),
          sendRawTransaction: async (signedTxn: any) => ({ do: async () => ({
            txId: 'mock-transaction-id'
          }) })
        };
        console.log('Created mock Algod client - wallet generation only');
      
      } catch (error) {
        console.error('Error importing algosdk or other libraries:', error);
        // Set up minimal fallback for wallet generation without algosdk
        this.algosdk = null;
        this.algodClient = null;
        throw new Error('Failed to initialize Algorand SDK - URL polyfill incompatible');
      }
    }
  }

  /**
   * Normalize transaction parameters to handle BigInt and different field names
   * Reusable utility for consistent parameter processing
   */
  private normalizeParams(params: any): any {
    return {
      fee: typeof params.fee === 'bigint' ? Number(params.fee) : (params.fee || 1000),
      firstRound: typeof params.firstValid === 'bigint' ? Number(params.firstValid) : (params.firstValid ?? params.firstRound ?? 0),
      lastRound: typeof params.lastValid === 'bigint' ? Number(params.lastValid) : (params.lastValid ?? params.lastRound ?? 0),
      genesisHash: params.genesisHash ?? params['genesis-hash'],
      genesisID: params.genesisID ?? params['genesis-id'],
      flatFee: params.flatFee ?? false
    };
  }

  /**
   * Safely get SDK function handling ESM/CommonJS module differences
   */
  private getSdkFn<T = any>(name: string): T {
    return (this.algosdk?.[name] ?? this.algosdk?.default?.[name]);
  }


  // Web3Auth initialization is no longer used - kept for reference only
  // We use secure deterministic wallet instead
  /*
  async initializeWeb3Auth() {
    // This method is deprecated - we use secureDeterministicWallet instead
    throw new Error('Web3Auth is no longer used. Use secureDeterministicWallet instead.');
  }
  */

  async createOrRestoreWallet(
    firebaseIdToken: string, 
    oauthSubject: string,
    accountType: 'personal' | 'business' = 'personal',
    accountIndex: number = 0,
    businessId?: string
  ): Promise<string> {
    try {
      await this.ensureInitialized();
      
      // Clear any existing account to ensure fresh wallet generation
      if (this.currentAccount) {
        console.log('Clearing existing account for fresh wallet generation');
        this.currentAccount = null;
      }
      
      // Skip Web3Auth initialization - we're not using it
      console.log(`[AlgorandService] Creating/restoring Algorand wallet with OAuth subject: ${oauthSubject}`);
      console.log(`[AlgorandService] Account context:`, { accountType, accountIndex, businessId });
      
      // BYPASS WEB3AUTH COMPLETELY - Use secure deterministic wallet
      console.log('[AlgorandService] Using secure deterministic wallet with proper KDF and salt formula from README.md');
      
      // Decode the Firebase ID token to determine provider
      const decoded = jwtDecode<{ iss: string; firebase?: { sign_in_provider?: string } }>(firebaseIdToken);
      let provider: 'google' | 'apple' = 'google';
      
      // Check the sign-in provider from Firebase token
      if (decoded.firebase?.sign_in_provider === 'apple.com') {
        provider = 'apple';
      }
      
      console.log(`Detected provider: ${provider}`);
      
      // Get the actual Google web client ID from environment
      const { GOOGLE_CLIENT_IDS } = await import('../config/env');
      const GOOGLE_WEB_CLIENT_ID = GOOGLE_CLIENT_IDS.production.web;
      
      // Determine the OAuth issuer and audience based on provider
      const iss = provider === 'google' ? 'https://accounts.google.com' : 'https://appleid.apple.com';
      const aud = provider === 'google' ? GOOGLE_WEB_CLIENT_ID : 'com.confio.app';
      
      // Use the secure deterministic wallet service with OAuth claims directly
      const wallet = await secureDeterministicWallet.createOrRestoreWallet(
        iss,          // OAuth issuer
        oauthSubject, // OAuth subject is REQUIRED for deterministic derivation
        aud,          // OAuth audience (web client ID)
        provider,
        accountType,  // Use the provided account type
        accountIndex, // Use the provided account index
        businessId    // Use the provided business ID (if applicable)
      );
      
      console.log('Secure wallet created:', wallet.address);
      
      // Store the address for later use
      this.currentAccount = {
        addr: wallet.address,
        sk: null // We don't expose the private key directly
      };
      
      await this.storeAddress(wallet.address);
      return wallet.address;
    } catch (error) {
      console.error('Error creating/restoring Algorand wallet:', error);
      throw error;
    }
  }

  async getBalance(address?: string): Promise<number> {
    try {
      await this.ensureInitialized();
      
      // Always use real Algod client for balance queries
      let realAlgodClient: any;
      if (this.algosdk?.Algodv2) {
        const token = '';
        const server = 'https://testnet-api.algonode.cloud';
        const port = ''; // Empty string for https
        realAlgodClient = new this.algosdk.Algodv2(token, server, port);
      } else {
        console.error('Algosdk not properly initialized');
        return 0;
      }

      const addr = address || this.currentAccount?.addr;
      if (!addr) {
        throw new Error('No address provided');
      }

      const accountInfo = await realAlgodClient.accountInformation(addr).do();
      // Return balance in ALGOs (microAlgos / 1,000,000)
      return accountInfo.amount / 1000000;
    } catch (error) {
      console.error('Error fetching balance:', error);
      return 0;
    }
  }

  async sendTransaction(toAddress: string, amount: number): Promise<string> {
    try {
      await this.ensureInitialized();
      if (!this.currentAccount) {
        throw new Error('Wallet not initialized');
      }

      // Always use real Algod client for transactions
      let realAlgodClient: any;
      if (this.algosdk?.Algodv2) {
        const token = '';
        const server = 'https://testnet-api.algonode.cloud';
        const port = ''; // Empty string for https
        realAlgodClient = new this.algosdk.Algodv2(token, server, port);
      } else {
        throw new Error('Algosdk not properly initialized');
      }

      // Get suggested params
      const params = await realAlgodClient.getTransactionParams().do();
      
      // Normalize parameters using shared utility
      const processedParams = this.normalizeParams(params);
      
      // Validate critical fields to catch RPC issues early
      if (!processedParams.genesisHash || !processedParams.genesisID) {
        throw new Error(`RPC missing genesisHash/genesisID (raw keys: ${Object.keys(params).join(', ')})`);
      }
      
      // Create transaction
      const makePaymentTxn = this.getSdkFn('makePaymentTxnWithSuggestedParamsFromObject');
      const txn = makePaymentTxn({
        from: this.currentAccount.addr,
        to: toAddress,
        amount: Math.floor(amount * 1000000), // Convert to microAlgos
        suggestedParams: processedParams,
      });

      // Sign transaction using secure wallet
      // Backend will handle signing with JWT context
      // For now, throw error to indicate client-side signing is not available
      throw new Error('Client-side signing not available - transaction must be signed on backend');
      
      // Submit transaction
      const { txId } = await realAlgodClient.sendRawTransaction(signedTxn).do();
      
      // Wait for confirmation
      const waitForConfirmation = this.getSdkFn('waitForConfirmation');
      await waitForConfirmation(realAlgodClient, txId, 4);
      
      console.log('Transaction sent:', txId);
      return txId;
    } catch (error) {
      console.error('Error sending transaction:', error);
      throw error;
    }
  }

  getCurrentAddress(): string | null {
    return this.currentAccount?.addr || null;
  }

  getCurrentAccount(): any {
    return this.currentAccount;
  }
  
  async signTransactionBytes(txnBytes: Uint8Array): Promise<Uint8Array> {
    // Sign a transaction using deterministic wallet derived from JWT + account context
    try {
      await this.ensureInitialized();

      // Ensure wallet scope is ready from OAuth subject and active account context
      const { oauthStorage } = await import('./oauthStorageService');
      const oauthData = await oauthStorage.getOAuthSubject();
      if (!oauthData || !oauthData.subject || !oauthData.provider) {
        throw new Error('Missing OAuth subject/provider for signing');
      }

      const provider: 'google' | 'apple' = oauthData.provider;
      const sub: string = oauthData.subject;

      // Get active account context (type/index/businessId)
      const { AuthService } = await import('./authService');
      const authService = AuthService.getInstance();
      const accountContext = await authService.getActiveAccountContext();

      // Determine issuer/audience consistently with derivation
      const { GOOGLE_CLIENT_IDS } = await import('../config/env');
      const GOOGLE_WEB_CLIENT_ID = GOOGLE_CLIENT_IDS.production.web;
      const iss = provider === 'google' ? 'https://accounts.google.com' : 'https://appleid.apple.com';
      const aud = provider === 'google' ? GOOGLE_WEB_CLIENT_ID : 'com.confio.app';

      // Create/restore wallet to ensure in-memory seed and scope are set
      const wallet = await secureDeterministicWallet.createOrRestoreWallet(
        iss,
        sub,
        aud,
        provider,
        accountContext.type,
        accountContext.index,
        accountContext.businessId
      );

      // Ensure currentAccount is set for downstream consumers
      if (!this.currentAccount) {
        this.currentAccount = { addr: wallet.address, sk: null };
      }

      // Now sign the raw transaction bytes using secure wallet
      const signedTxn = await secureDeterministicWallet.signTransaction(sub, txnBytes);
      return signedTxn;
    } catch (error) {
      console.error('Error signing transaction:', error);
      throw error;
    }
  }

  getAlgosdk(): any {
    return this.algosdk;
  }

  private async storeAddress(address: string): Promise<void> {
    try {
      await Keychain.setInternetCredentials(
        'algorand.confio.app',
        'confio',
        JSON.stringify({ address, storedAt: new Date().toISOString() })
      );
      console.log('Algorand address stored:', address);
    } catch (error) {
      console.error('Error storing address:', error);
      throw error;
    }
  }

  async clearWallet() {
    try {
      this.currentAccount = null;
      
      // Clear ALL wallet data (no multi-user support)
      try {
        console.log('Calling secureDeterministicWallet.clearWallet...');
        await secureDeterministicWallet.clearWallet();
        console.log('Cleared ALL wallet data from secureDeterministicWallet');
      } catch (error: any) {
        console.error('Error clearing secureDeterministicWallet:', error?.message || error);
        console.error('Error stack:', error?.stack);
      }
    
    // Web3Auth is no longer used - we use secure deterministic wallet instead
    // Just clear the reference if it exists
    if (this.web3auth) {
      this.web3auth = null;
      console.log('Cleared Web3Auth reference');
    }
    
    // Clear Algorand-related keychain entries
    // Note: We're skipping web3auth entries since Web3Auth is no longer used
    const keychainEntriesToClear = [
      'algorand.confio.app',
      'algorand.confio.optin'
    ];
    
    // Clear each entry using resetInternetCredentials
    for (const key of keychainEntriesToClear) {
      try {
        // resetInternetCredentials in v10 expects an options object
        await Keychain.resetInternetCredentials({ server: key });
        console.log(`Reset keychain entry: ${key}`);
      } catch (error: any) {
        // Entry might not exist, which is fine
        console.log(`Could not reset ${key}:`, error?.message);
      }
    }
    
    console.log('All Algorand wallet credentials cleared');
    } catch (error: any) {
      console.error('Error in clearWallet:', error?.message || error);
      console.error('Error stack:', error?.stack);
      // Don't re-throw, just log the error
    }
  }
  
  async getStoredAddress(): Promise<string | null> {
    try {
      const credentials = await Keychain.getInternetCredentials('algorand.confio.app');
      
      if (credentials) {
        const walletData = JSON.parse(credentials.password);
        return walletData.address;
      }
      return null;
    } catch (error) {
      console.error('Error retrieving stored Algorand address:', error);
      return null;
    }
  }

  async loadStoredWallet(): Promise<boolean> {
    try {
      console.log('[AlgorandService] Loading stored wallet address from Keychain...');
      
      const credentials = await Keychain.getInternetCredentials('algorand.confio.app');
      
      if (credentials) {
        const walletData = JSON.parse(credentials.password);
        console.log('[AlgorandService] Found stored address:', walletData.address);
        
        // Only restore the address, not the private key (which is now encrypted or in memory)
        this.currentAccount = {
          addr: walletData.address,
          sk: null  // Private key is now managed by secureDeterministicWallet
        };
        
        console.log('[AlgorandService] Address loaded successfully');
        return true;
      }
      
      console.log('[AlgorandService] No stored wallet found');
      return false;
    } catch (error) {
      console.error('[AlgorandService] Error loading stored wallet:', error);
      return false;
    }
  }

  async optInToConfioToken(): Promise<boolean> {
    try {
      console.log('[AlgorandService] Starting CONFIO token opt-in...');
      
      // Ensure we have the necessary components
      if (!this.algosdk || !this.currentAccount) {
        console.error('[AlgorandService] Algorand SDK or account not initialized');
        console.error('[AlgorandService] algosdk available:', !!this.algosdk);
        console.error('[AlgorandService] currentAccount available:', !!this.currentAccount);
        console.error('[AlgorandService] currentAccount.addr:', this.currentAccount?.addr);
        return false;
      }
      
      // Debug current account structure
      console.log('[AlgorandService] Current account keys:', Object.keys(this.currentAccount));
      console.log('[AlgorandService] Current account.addr type:', typeof this.currentAccount.addr);
      console.log('[AlgorandService] Current account.addr value:', this.currentAccount.addr);

      // Always create a fresh real Algod client for transactions
      console.log('[AlgorandService] Creating real Algod client for opt-in...');
      let realAlgodClient;
      try {
        // Use Algonode's free API for testnet
        const algodToken = '';
        const algodServer = 'https://testnet-api.algonode.cloud';
        const algodPort = '';
        
        // Create a fresh client instance using the imported algosdk
        if (this.algosdk.Algodv2) {
          realAlgodClient = new this.algosdk.Algodv2(algodToken, algodServer, algodPort);
        } else if (this.algosdk.default?.Algodv2) {
          realAlgodClient = new this.algosdk.default.Algodv2(algodToken, algodServer, algodPort);
        } else {
          console.error('[AlgorandService] Algodv2 constructor not found in algosdk');
          console.error('[AlgorandService] Available algosdk keys:', Object.keys(this.algosdk));
          throw new Error('Algodv2 constructor not available');
        }
        console.log('[AlgorandService] Real Algod client created successfully');
      } catch (clientError) {
        console.error('[AlgorandService] Failed to create Algod client:', clientError);
        return false;
      }

      console.log(`[AlgorandService] Opting in address ${this.currentAccount.addr} to CONFIO asset ${CONFIO_ASSET_ID}`);
      
      try {
        // Get suggested params using the real client
        const params = await realAlgodClient.getTransactionParams().do();
        console.log('[AlgorandService] Got transaction params:', params);
        
        // Validate params structure
        if (!params || typeof params !== 'object') {
          console.error('[AlgorandService] Invalid transaction params:', params);
          throw new Error('Transaction parameters are invalid');
        }
        
        // Normalize parameters using shared utility
        const processedParams = this.normalizeParams(params);
        console.log('[AlgorandService] Processed transaction params:', processedParams);
        
        // Validate critical fields to catch RPC issues early
        if (!processedParams.genesisHash || !processedParams.genesisID) {
          throw new Error(`RPC missing genesisHash/genesisID (raw keys: ${Object.keys(params).join(', ')})`);
        }
        
        // Validate account address before creating transaction
        if (!this.currentAccount.addr || typeof this.currentAccount.addr !== 'string') {
          console.error('[AlgorandService] Invalid account address:', this.currentAccount.addr);
          throw new Error('Account address is null or invalid');
        }
        
        console.log('[AlgorandService] Using address:', this.currentAccount.addr);
        
        // Create opt-in transaction using makeAssetTransferTxnWithSuggestedParamsFromObject
        console.log('[AlgorandService] Creating asset transfer transaction for opt-in...');
        
        // Find the correct method (try named export first, then default export)
        let makeAssetTransferTxn;
        if (this.algosdk.makeAssetTransferTxnWithSuggestedParamsFromObject) {
          makeAssetTransferTxn = this.algosdk.makeAssetTransferTxnWithSuggestedParamsFromObject;
        } else if (this.algosdk.default?.makeAssetTransferTxnWithSuggestedParamsFromObject) {
          makeAssetTransferTxn = this.algosdk.default.makeAssetTransferTxnWithSuggestedParamsFromObject;
        } else {
          console.error('[AlgorandService] makeAssetTransferTxnWithSuggestedParamsFromObject not found');
          console.error('[AlgorandService] Available algosdk methods:', Object.keys(this.algosdk).slice(0, 20));
          throw new Error('makeAssetTransferTxnWithSuggestedParamsFromObject not found in algosdk');
        }
        
        // Create the transaction
        const txn = makeAssetTransferTxn({
          from: this.currentAccount.addr,
          to: this.currentAccount.addr,
          amount: 0,  // 0 for opt-in
          assetIndex: CONFIO_ASSET_ID,
          suggestedParams: processedParams
        });
        console.log('[AlgorandService] Created opt-in transaction');

        // Sign transaction using secure wallet
        // Backend will handle signing with JWT context
        // For now, throw error to indicate client-side signing is not available
        throw new Error('Client-side signing not available - transaction must be signed on backend');
        console.log('[AlgorandService] Transaction signed');
        
        // Submit transaction using the real client
        const { txId } = await realAlgodClient.sendRawTransaction(signedTxn).do();
        console.log(`[AlgorandService] Transaction submitted. TxID: ${txId}`);
        
        // Wait for confirmation using the real client
        const waitForConfirmation = this.getSdkFn('waitForConfirmation');
        const confirmedTxn = await waitForConfirmation(realAlgodClient, txId, 4);
        console.log(`[AlgorandService] Transaction confirmed in round ${confirmedTxn['confirmed-round']}`);
        
        // Store successful opt-in status
        await Keychain.setInternetCredentials(
          'algorand.confio.optin',
          'confio',
          JSON.stringify({
            assetId: CONFIO_ASSET_ID,
            address: this.currentAccount.addr,
            optedInAt: new Date().toISOString(),
            status: 'confirmed',
            txId: txId,
            confirmedRound: confirmedTxn['confirmed-round']
          })
        );
        
        console.log(`[AlgorandService] Successfully opted in to CONFIO token. TxID: ${txId}`);
        return true;
        
      } catch (txError: any) {
        // Check if already opted in
        if (txError?.message?.includes('already owns this asset')) {
          console.log('[AlgorandService] Already opted in to CONFIO token');
          
          // Store the opt-in status even though it was already done
          await Keychain.setInternetCredentials(
            'algorand.confio.optin',
            'confio',
            JSON.stringify({
              assetId: CONFIO_ASSET_ID,
              address: this.currentAccount.addr,
              optedInAt: new Date().toISOString(),
              status: 'already_opted_in'
            })
          );
          
          return true;
        }
        
        console.error('[AlgorandService] Transaction error:', txError);
        throw txError;
      }
      
    } catch (error) {
      console.error('[AlgorandService] Error opting in to CONFIO token:', error);
      return false;
    }
  }

  async checkConfioOptInStatus(): Promise<boolean> {
    try {
      const credentials = await Keychain.getInternetCredentials('algorand.confio.optin');
      
      if (credentials) {
        const optInData = JSON.parse(credentials.password);
        return optInData.assetId === CONFIO_ASSET_ID;
      }
      return false;
    } catch (error) {
      console.error('[AlgorandService] Error checking CONFIO opt-in status:', error);
      return false;
    }
  }

  async createSponsoredSendTransaction(
    toAddress: string,
    amount: number,
    assetType: 'CUSD' | 'CONFIO' | 'USDC' = 'CUSD'
  ): Promise<{
    userTransaction: Uint8Array;
    sponsorTransaction: Uint8Array;
    groupId: string;
    totalFee: number;
  } | null> {
    try {
      await this.ensureInitialized();
      
      if (!this.currentAccount) {
        console.error('[AlgorandService] No account available for sponsored send');
        return null;
      }

      console.log(`[AlgorandService] Creating sponsored send: ${amount} ${assetType} to ${toAddress}`);
      
      // Call the backend to create sponsored transaction
      const response = await fetch('https://api.confio.app/graphql', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          // Add auth token if available
        },
        body: JSON.stringify({
          query: `
            mutation AlgorandSponsoredSend($recipient: String!, $amount: Float!, $assetType: String!) {
              algorandSponsoredSend(recipient: $recipient, amount: $amount, assetType: $assetType) {
                success
                error
                userTransaction
                sponsorTransaction
                groupId
                totalFee
                feeInAlgo
              }
            }
          `,
          variables: {
            recipient: toAddress,
            amount: amount,
            assetType: assetType
          }
        })
      });

      const data = await response.json();
      
      if (!data.data?.algorandSponsoredSend?.success) {
        console.error('[AlgorandService] Failed to create sponsored transaction:', data.data?.algorandSponsoredSend?.error);
        return null;
      }

      const result = data.data.algorandSponsoredSend;
      
      // Decode base64 transactions (RN compatible)
      const userTxn = Uint8Array.from(Buffer.from(result.userTransaction, 'base64'));
      const sponsorTxn = Uint8Array.from(Buffer.from(result.sponsorTransaction, 'base64'));
      
      return {
        userTransaction: userTxn,
        sponsorTransaction: sponsorTxn,
        groupId: result.groupId,
        totalFee: result.totalFee
      };
      
    } catch (error) {
      console.error('[AlgorandService] Error creating sponsored send:', error);
      return null;
    }
  }

  async signAndSubmitSponsoredTransaction(
    userTransaction: Uint8Array,
    sponsorTransaction: Uint8Array
  ): Promise<string | null> {
    try {
      await this.ensureInitialized();
      
      if (!this.currentAccount) {
        console.error('[AlgorandService] No account available for signing');
        return null;
      }

      console.log('[AlgorandService] Signing user transaction...');
      const signedUserTxn = await this.signTransactionBytes(userTransaction);
      // Encode for submission (RN compatible)
      const signedUserTxnB64 = Buffer.from(signedUserTxn).toString('base64');
      const sponsorTxnB64 = Buffer.from(sponsorTransaction).toString('base64');
      
      console.log('[AlgorandService] Submitting sponsored transaction group...');
      
      // Submit to backend
      const response = await fetch('https://api.confio.app/graphql', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          // Add auth token if available
        },
        body: JSON.stringify({
          query: `
            mutation SubmitSponsoredGroup($signedUserTxn: String!, $signedSponsorTxn: String!) {
              submitSponsoredGroup(signedUserTxn: $signedUserTxn, signedSponsorTxn: $signedSponsorTxn) {
                success
                error
                transactionId
                confirmedRound
                feesSaved
              }
            }
          `,
          variables: {
            signedUserTxn: signedUserTxnB64,
            signedSponsorTxn: sponsorTxnB64
          }
        })
      });

      const data = await response.json();
      
      if (!data.data?.submitSponsoredGroup?.success) {
        console.error('[AlgorandService] Failed to submit sponsored transaction:', data.data?.submitSponsoredGroup?.error);
        return null;
      }

      const result = data.data.submitSponsoredGroup;
      console.log(`[AlgorandService] Transaction confirmed! ID: ${result.transactionId}, Round: ${result.confirmedRound}`);
      console.log(`[AlgorandService] Fees saved: ${result.feesSaved} ALGO`);
      
      return result.transactionId;
      
    } catch (error) {
      console.error('[AlgorandService] Error signing/submitting sponsored transaction:', error);
      return null;
    }
  }

  async processSponsoredOptIn(
    assetIdOrTransactions?: number | any[] // Can be assetId or array of opt-in transactions
  ): Promise<boolean> {
    try {
      await this.ensureInitialized();
      
      if (!this.currentAccount) {
        console.error('[AlgorandService] No account available for opt-in');
        return false;
      }

      // Check if we received an array of transactions from backend
      if (Array.isArray(assetIdOrTransactions)) {
        console.log(`[AlgorandService] Processing ${assetIdOrTransactions.length} opt-in transactions from backend`);
        
        // The backend sends an array with the structure from GenerateOptInTransactionsMutation
        // Find the sponsor transaction (marked with type: 'sponsor' and signed: true)
        const sponsorTxnData = assetIdOrTransactions.find(t => t.type === 'sponsor' && t.signed === true);
        
        if (!sponsorTxnData) {
          console.error('[AlgorandService] No sponsor transaction found in array');
          console.error('[AlgorandService] Available transactions:', assetIdOrTransactions.map(t => ({ type: t.type, signed: t.signed })));
          return false;
        }
        
        // Process each opt-in transaction (skip the sponsor transaction)
        const optInTransactions = assetIdOrTransactions.filter(t => t.type === 'opt-in');
        
        // We need to sign all user transactions first, then submit as a group
        const signedUserTxns = [];
        
        for (const optInData of optInTransactions) {
          try {
            const assetName = optInData.assetName || 'Unknown';
            const assetId = optInData.assetId;
            console.log(`[AlgorandService] Signing opt-in transaction for ${assetName} (${assetId})`);
            
            // Decode and sign the user transaction
            const userTxnBytes = Uint8Array.from(Buffer.from(optInData.transaction, 'base64'));
            const signedUserTxn = await this.signTransactionBytes(userTxnBytes);
            const signedUserTxnB64 = Buffer.from(signedUserTxn).toString('base64');
            
            signedUserTxns.push({
              assetId,
              assetName,
              signedTxn: signedUserTxnB64
            });
          } catch (error) {
            console.error(`[AlgorandService] Error signing opt-in for asset ${optInData.assetId}:`, error);
            return false;
          }
        }
        
        // Now submit all signed transactions together with the sponsor transaction
        // For atomic group, we need to concatenate all transactions
        console.log(`[AlgorandService] Submitting atomic group with ${signedUserTxns.length} opt-ins...`);
        
        // The backend's GenerateOptInTransactionsMutation creates an atomic group
        // We need to submit them all together
        try {
          // Concatenate all signed user transactions (they're already base64)
          // We need to decode each, concatenate the bytes, then re-encode
          let concatenatedUserTxns = new Uint8Array(0);
          for (const txnData of signedUserTxns) {
            const txnBytes = Uint8Array.from(Buffer.from(txnData.signedTxn, 'base64'));
            const newArray = new Uint8Array(concatenatedUserTxns.length + txnBytes.length);
            newArray.set(concatenatedUserTxns);
            newArray.set(txnBytes, concatenatedUserTxns.length);
            concatenatedUserTxns = newArray;
          }
          const allUserTxnsB64 = Buffer.from(concatenatedUserTxns).toString('base64');
          
          // Submit the complete atomic group (all user txns + sponsor txn)
          console.log(`[AlgorandService] Submitting atomic group to backend...`);
          console.log(`[AlgorandService] User transactions size: ${allUserTxnsB64.length} chars`);
          console.log(`[AlgorandService] Sponsor transaction size: ${sponsorTxnData.transaction.length} chars`);
          
          // Use Apollo client for authenticated GraphQL request
          console.log(`[AlgorandService] Importing Apollo client and mutation...`);
          
          // Import at the top to avoid issues
          const apolloModule = await import('../apollo/client');
          const mutationsModule = await import('../apollo/mutations');
          
          const apolloClient = apolloModule.apolloClient || apolloModule.default;
          const SUBMIT_SPONSORED_GROUP = mutationsModule.SUBMIT_SPONSORED_GROUP;
          
          console.log(`[AlgorandService] Apollo client imported:`, !!apolloClient);
          console.log(`[AlgorandService] Mutation imported:`, !!SUBMIT_SPONSORED_GROUP);
          
          if (!apolloClient) {
            console.error(`[AlgorandService] Apollo client not initialized`);
            return false;
          }
          
          if (!SUBMIT_SPONSORED_GROUP) {
            console.error(`[AlgorandService] SUBMIT_SPONSORED_GROUP mutation not found`);
            return false;
          }
          
          console.log(`[AlgorandService] Using Apollo client to submit sponsored group...`);
          
          try {
            const timeoutMs = 20000;
            console.log(`[AlgorandService] Calling apolloClient.mutate with ${timeoutMs/1000}s timeout...`);
            
            const timeoutPromise = new Promise((_, reject) => {
              setTimeout(() => reject(new Error(`Request timed out after ${timeoutMs/1000} seconds`)), timeoutMs);
            });
            
            const mutationPromise = apolloClient.mutate({
              mutation: SUBMIT_SPONSORED_GROUP,
              variables: {
                signedUserTxn: allUserTxnsB64,
                signedSponsorTxn: sponsorTxnData.transaction
              }
            });
            
            const mutateResult: any = await Promise.race([mutationPromise, timeoutPromise]);
            console.log(`[AlgorandService] Mutation completed, extracting data...`);
            
            const submitData = (mutateResult as any)?.data;
            const submitResult = submitData?.submitSponsoredGroup;
            
            if (submitResult?.success) {
            console.log(`[AlgorandService] Successfully submitted atomic opt-in group!`);
            console.log(`[AlgorandService] Transaction ID: ${submitResult.transactionId}`);
            console.log(`[AlgorandService] Confirmed in round: ${submitResult.confirmedRound}`);
            console.log(`[AlgorandService] Fees saved: ${submitResult.feesSaved} ALGO`);
            
            // Store opt-in status for all assets
            for (const optInData of optInTransactions) {
              const assetName = optInData.assetName || 'Unknown';
              const assetId = optInData.assetId;
              
              await Keychain.setInternetCredentials(
                'algorand.confio.optin',
                assetName.toLowerCase(),
                JSON.stringify({
                  assetId: assetId,
                  address: this.currentAccount.addr,
                  optedInAt: new Date().toISOString(),
                  status: 'confirmed',
                  txId: submitResult.transactionId,
                  confirmedRound: submitResult.confirmedRound
                })
              );
              console.log(`[AlgorandService] Stored opt-in status for ${assetName}`);
            }
            return true;
          } else {
            console.error(`[AlgorandService] Failed to submit atomic opt-in group:`, submitResult?.error);
            return false;
          }
          } catch (apolloError) {
            console.error(`[AlgorandService] Apollo error during submission:`, apolloError);
            // Check if it's an authentication error
            if (apolloError.message && apolloError.message.includes('permission')) {
              console.error(`[AlgorandService] Authentication issue - user may need to re-login`);
            }
            return false;
          }
        } catch (error) {
          console.error(`[AlgorandService] Error submitting atomic opt-in group:`, error);
          return false;
        }
        
        // Should not reach here; handled in branches
        return false;
      }

      // Original single asset opt-in logic
      const assetId = assetIdOrTransactions || 743890784; // Default to old CONFIO ID
      console.log(`[AlgorandService] Processing sponsored opt-in for asset ${assetId}`);
      
      // Step 1: Request sponsored opt-in from backend using Apollo client
      // Import at the top of the function to avoid Metro bundler issues
      const apolloClient = require('../apollo/client').apolloClient;
      const ALGORAND_SPONSORED_OPT_IN = require('../apollo/mutations').ALGORAND_SPONSORED_OPT_IN;
      
      const { data } = await apolloClient.mutate({
        mutation: ALGORAND_SPONSORED_OPT_IN,
        variables: {
          assetId: assetId
        }
      });

      const result = data?.algorandSponsoredOptIn;
      
      if (!result?.success) {
        console.error('[AlgorandService] Failed to create sponsored opt-in:', result?.error);
        return false;
      }

      // Check if already opted in
      if (result.alreadyOptedIn) {
        console.log(`[AlgorandService] Already opted into ${result.assetName} (${result.assetId})`);
        return true;
      }

      // Check if user signature is required
      if (!result.requiresUserSignature) {
        console.log(`[AlgorandService] Opt-in completed server-side for ${result.assetName}`);
        return true;
      }

      console.log(`[AlgorandService] Signing opt-in transaction for ${result.assetName}...`);
      
      // Step 2: Decode and sign the user transaction (RN compatible)
      const userTxnBytes = Uint8Array.from(Buffer.from(result.userTransaction, 'base64'));
      const signedUserTxn = await this.signTransactionBytes(userTxnBytes);
      // Convert to base64 (RN compatible)
      const signedUserTxnB64 = Buffer.from(signedUserTxn).toString('base64');
      
      console.log(`[AlgorandService] Submitting signed opt-in for ${result.assetName}...`);
      
      // Step 3: Submit the signed transaction group
      const submitResponse = await fetch('https://api.confio.app/graphql', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          // Add auth token if available
        },
        body: JSON.stringify({
          query: `
            mutation SubmitSponsoredGroup($signedUserTxn: String!, $signedSponsorTxn: String!) {
              submitSponsoredGroup(
                signedUserTxn: $signedUserTxn
                signedSponsorTxn: $signedSponsorTxn
              ) {
                success
                error
                transactionId
                confirmedRound
                feesSaved
              }
            }
          `,
          variables: {
            signedUserTxn: signedUserTxnB64,
            signedSponsorTxn: result.sponsorTransaction // Already signed by server
          }
        })
      });

      const submitData = await submitResponse.json();
      const submitResult = submitData.data?.submitSponsoredGroup;
      
      if (!submitResult?.success) {
        console.error('[AlgorandService] Failed to submit opt-in:', submitResult?.error);
        return false;
      }

      console.log(`[AlgorandService] Successfully opted into ${result.assetName}!`);
      console.log(`[AlgorandService] Transaction ID: ${submitResult.transactionId}`);
      console.log(`[AlgorandService] Fees saved: ${submitResult.feesSaved} ALGO`);
      
      // Store opt-in status in keychain
      await Keychain.setInternetCredentials(
        'algorand.confio.optin',
        result.assetName.toLowerCase(),
        JSON.stringify({
          assetId: result.assetId,
          address: this.currentAccount.addr,
          optedInAt: new Date().toISOString(),
          status: 'confirmed',
          txId: submitResult.transactionId,
          confirmedRound: submitResult.confirmedRound
        })
      );
      
      return true;
      
    } catch (error) {
      console.error('[AlgorandService] Error processing sponsored opt-in:', error);
      return false;
    }
  }

  async sponsoredSend(
    toAddress: string,
    amount: number,
    assetType: 'CUSD' | 'CONFIO' | 'USDC' = 'CUSD'
  ): Promise<string | null> {
    try {
      console.log(`[AlgorandService] Initiating sponsored send of ${amount} ${assetType} to ${toAddress}`);
      
      // Step 1: Create sponsored transaction
      const sponsoredTx = await this.createSponsoredSendTransaction(toAddress, amount, assetType);
      if (!sponsoredTx) {
        console.error('[AlgorandService] Failed to create sponsored transaction');
        return null;
      }
      
      console.log(`[AlgorandService] Created sponsored transaction. Group ID: ${sponsoredTx.groupId}`);
      
      // Step 2: Sign and submit
      const txId = await this.signAndSubmitSponsoredTransaction(
        sponsoredTx.userTransaction,
        sponsoredTx.sponsorTransaction
      );
      
      if (!txId) {
        console.error('[AlgorandService] Failed to submit sponsored transaction');
        return null;
      }
      
      console.log(`[AlgorandService] Successfully sent ${amount} ${assetType} with sponsored fees. TxID: ${txId}`);
      return txId;
      
    } catch (error) {
      console.error('[AlgorandService] Error in sponsored send:', error);
      return null;
    }
  }

  async getConfioBalance(address?: string): Promise<number> {
    try {
      await this.ensureInitialized();
      
      // Create Algod client if needed
      if (!this.algodClient || typeof this.algodClient.accountInformation !== 'function') {
        const algodToken = '';
        const algodServer = 'https://testnet-api.algonode.cloud';
        const algodPort = '';
        this.algodClient = new this.algosdk.Algodv2(algodToken, algodServer, algodPort);
      }

      const addr = address || this.currentAccount?.addr;
      if (!addr) {
        console.error('[AlgorandService] No address provided for CONFIO balance check');
        return 0;
      }

      try {
        const accountInfo = await this.algodClient.accountInformation(addr).do();
        
        // Find CONFIO asset in the account's assets
        const confioAsset = accountInfo.assets?.find((asset: any) => asset['asset-id'] === CONFIO_ASSET_ID);
        
        if (confioAsset) {
          // CONFIO has 6 decimals, so divide by 1,000,000
          const balance = confioAsset.amount / 1000000;
          console.log(`[AlgorandService] CONFIO balance for ${addr}: ${balance}`);
          return balance;
        } else {
          console.log(`[AlgorandService] Address ${addr} not opted in to CONFIO`);
          return 0;
        }
      } catch (error) {
        console.error('[AlgorandService] Error fetching CONFIO balance:', error);
        return 0;
      }
    } catch (error) {
      console.error('[AlgorandService] Error in getConfioBalance:', error);
      return 0;
    }
  }
}

export default new AlgorandService();
