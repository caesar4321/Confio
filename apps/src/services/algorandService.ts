import * as Keychain from 'react-native-keychain';
import { secureDeterministicWallet } from './secureDeterministicWallet';
import { jwtDecode } from 'jwt-decode';
import { Buffer } from 'buffer'; // RN polyfill for base64

// Type for account info
type AccountLite = { addr: string; sk: null };

class AlgorandService {
  // Web3Auth properties no longer used - we use secure deterministic wallet
  private web3auth: any = null; // Kept for compatibility checks
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
        
        // We intentionally do NOT create any direct Algod client in the app.
        // All blockchain interactions are prepared/submitted via the backend.
      
      } catch (error) {
        console.error('Error importing algosdk or other libraries:', error);
        // Set up minimal fallback for wallet generation without algosdk
        this.algosdk = null;
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
        businessId,   // Use the provided business ID (if applicable)
        firebaseIdToken
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

  /**
   * Get the current wallet address, attempting to load stored address if not in memory.
   */
  async getCurrentAddress(): Promise<string | null> {
    try {
      await this.ensureInitialized();
      if (this.currentAccount?.addr) return this.currentAccount.addr;
      const loaded = await this.loadStoredWallet();
      return loaded && this.currentAccount ? this.currentAccount.addr : null;
    } catch (e) {
      console.error('[AlgorandService] getCurrentAddress error:', e);
      return null;
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

      // Get OAuth data (needed for signing regardless)
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

      // Try fast-path signing using in-memory seed/scope. If missing, initialize once.
      let signedTxn: Uint8Array | null = null;
      try {
        signedTxn = await secureDeterministicWallet.signTransaction(txnBytes);
      } catch (e: any) {
        // Initialize scope + cache only if needed
        const { GOOGLE_CLIENT_IDS } = await import('../config/env');
        const GOOGLE_WEB_CLIENT_ID = GOOGLE_CLIENT_IDS.production.web;
        const iss = provider === 'google' ? 'https://accounts.google.com' : 'https://appleid.apple.com';
        const aud = provider === 'google' ? GOOGLE_WEB_CLIENT_ID : 'com.confio.app';

        const wallet = await secureDeterministicWallet.createOrRestoreWallet(
          iss,
          sub,
          aud,
          provider,
          accountContext.type,
          accountContext.index,
          accountContext.businessId
        );
        this.currentAccount = { addr: wallet.address, sk: null };
        signedTxn = await secureDeterministicWallet.signTransaction(txnBytes);
      }
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


  // (Removed legacy: checkConfioOptInStatus and createSponsoredSendTransaction)

  async signAndSubmitSponsoredTransaction(
    userTransaction: string | Uint8Array,
    sponsorTransaction: string | Uint8Array
  ): Promise<string | null> {
    try {
      await this.ensureInitialized();
      
      // Convert base64 strings to Uint8Array if needed
      const userTxnBytes = typeof userTransaction === 'string' 
        ? Uint8Array.from(Buffer.from(userTransaction, 'base64'))
        : userTransaction;
      const sponsorTxnBytes = typeof sponsorTransaction === 'string'
        ? Uint8Array.from(Buffer.from(sponsorTransaction, 'base64'))
        : sponsorTransaction;

      console.log('[AlgorandService] Signing user transaction...');
      // signTransactionBytes will handle wallet initialization
      const signedUserTxn = await this.signTransactionBytes(userTxnBytes);
      // Encode for submission (RN compatible)
      const signedUserTxnB64 = Buffer.from(signedUserTxn).toString('base64');
      const sponsorTxnB64 = Buffer.from(sponsorTxnBytes).toString('base64');
      
      console.log('[AlgorandService] Submitting sponsored transaction group...');
      
      // Use Apollo client for submission with proper auth and endpoint
      const { apolloClient } = await import('../apollo/client');
      const { gql } = await import('@apollo/client');
      
      const SUBMIT_SPONSORED_GROUP = gql`
        mutation SubmitSponsoredGroup($signedUserTxn: String!, $signedSponsorTxn: String!) {
          submitSponsoredGroup(signedUserTxn: $signedUserTxn, signedSponsorTxn: $signedSponsorTxn) {
            success
            error
            transactionId
            confirmedRound
            feesSaved
          }
        }
      `;
      
      const { data } = await apolloClient.mutate({
        mutation: SUBMIT_SPONSORED_GROUP,
        variables: {
          signedUserTxn: signedUserTxnB64,
          signedSponsorTxn: sponsorTxnB64
        }
      });
      
      if (!data?.submitSponsoredGroup?.success) {
        const errMsg: string = data?.submitSponsoredGroup?.error || '';
        console.error('[AlgorandService] Failed to submit sponsored transaction:', errMsg);
        // Consider idempotent success if network reports already opted in / already done
        if (/already\s+opted\s+in|already\s+opted/i.test(errMsg)) {
          console.log('[AlgorandService] Treating "already opted in" as success');
          return 'already_opted_in';
        }
        return null;
      }

      const result = data.submitSponsoredGroup;
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
      
      // Ensure a wallet is available for the active account context (personal/business)
      if (!this.currentAccount) {
        try {
          // Try loading a previously stored wallet address first
          const loaded = await this.loadStoredWallet();
          if (!loaded) {
            // Fall back to creating/restoring from active context + OAuth subject
            const { AuthService } = await import('./authService');
            const authService = AuthService.getInstance();
            const accountContext = await authService.getActiveAccountContext();

            const { oauthStorage } = await import('./oauthStorageService');
            const oauthData = await oauthStorage.getOAuthSubject();
            if (!oauthData || !oauthData.subject || !oauthData.provider) {
              throw new Error('Missing OAuth subject/provider for wallet context');
            }

            const provider: 'google' | 'apple' = oauthData.provider;
            const sub: string = oauthData.subject;
            const { GOOGLE_CLIENT_IDS } = await import('../config/env');
            const GOOGLE_WEB_CLIENT_ID = GOOGLE_CLIENT_IDS.production.web;
            const iss = provider === 'google' ? 'https://accounts.google.com' : 'https://appleid.apple.com';
            const aud = provider === 'google' ? GOOGLE_WEB_CLIENT_ID : 'com.confio.app';

            // Create/restore deterministic wallet for the active context
            const wallet = await secureDeterministicWallet.createOrRestoreWallet(
              iss,
              sub,
              aud,
              provider,
              accountContext.type,
              accountContext.index,
              accountContext.businessId
            );
            this.currentAccount = { addr: wallet.address, sk: null };
          }
        } catch (e) {
          console.error('[AlgorandService] Failed to initialize wallet context for opt-in:', e);
          return false;
        }
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
                // Sponsor is always first - no flag needed
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

      // Single-asset fallback is no longer supported (backend sends arrays)
      console.warn('[AlgorandService] processSponsoredOptIn called without array; expected array of transactions from backend');
      return false;
      
    } catch (error) {
      console.error('[AlgorandService] Error processing sponsored opt-in:', error);
      return false;
    }
  }

}

export default new AlgorandService();
