import * as Keychain from 'react-native-keychain';

// CONFIO token configuration
const CONFIO_ASSET_ID = 743890784; // Testnet CONFIO asset ID

class AlgorandService {
  private web3auth: any = null;
  private algodClient: any = null;
  private currentAccount: any = null;
  private algosdk: any = null;
  private Web3Auth: any = null;
  private web3authBase: any = null;
  private CommonPrivateKeyProvider: any = null;
  private SDK_MODE: any = null;
  private WEB3AUTH_NETWORK: any = null;

  constructor() {
    // Delay initialization to avoid import errors
  }

  private async ensureInitialized() {
    if (!this.algosdk) {
      try {
        // Lazy load the libraries (polyfills are already loaded in index.js)
        console.log('Importing algosdk...');
        const algosdk = await import('algosdk');
        console.log('algosdk imported successfully');
        
        console.log('Importing @web3auth/single-factor-auth...');
        const web3authSFA = await import('@web3auth/single-factor-auth');
        
        console.log('Importing @web3auth/base...');
        const web3authBase = await import('@web3auth/base');
        
        console.log('Importing @web3auth/base-provider...');
        const baseProvider = await import('@web3auth/base-provider');
        
        // Debug algosdk import
        console.log('algosdk keys:', Object.keys(algosdk));
        console.log('algosdk.default:', algosdk.default);
        console.log('algosdk.Algodv2:', algosdk.Algodv2);
        
        this.algosdk = algosdk;
        this.Web3Auth = web3authSFA.Web3Auth || web3authSFA.default?.Web3Auth;
        this.SDK_MODE = web3authSFA.SDK_MODE;
        this.WEB3AUTH_NETWORK = web3authSFA.WEB3AUTH_NETWORK || web3authBase.WEB3AUTH_NETWORK;
        
        // Debug what's actually in the imported modules
        console.log('web3authBase keys:', Object.keys(web3authBase));
        console.log('web3authBase.default keys:', web3authBase.default ? Object.keys(web3authBase.default) : 'no default');
        console.log('baseProvider keys:', Object.keys(baseProvider));
        console.log('baseProvider.default keys:', baseProvider.default ? Object.keys(baseProvider.default) : 'no default');
        
        // Try different ways to access CHAIN_NAMESPACES
        let chainNamespaces = web3authBase.CHAIN_NAMESPACES || 
                             web3authBase.default?.CHAIN_NAMESPACES ||
                             web3authBase.CHAIN_NAMESPACES?.CHAIN_NAMESPACES;
        
        // Try different ways to access CommonPrivateKeyProvider
        let commonProvider = baseProvider.CommonPrivateKeyProvider || 
                            baseProvider.default?.CommonPrivateKeyProvider;
        
        console.log('Found CHAIN_NAMESPACES:', !!chainNamespaces);
        console.log('Found CommonPrivateKeyProvider:', !!commonProvider);
        
        if (chainNamespaces) {
          console.log('CHAIN_NAMESPACES keys:', Object.keys(chainNamespaces));
        }
        
        // Store the imported modules with proper destructuring
        this.web3authBase = {
          CHAIN_NAMESPACES: chainNamespaces,
          ...web3authBase
        };
        this.CommonPrivateKeyProvider = commonProvider;
        
        console.log('CHAIN_NAMESPACES available:', !!this.web3authBase.CHAIN_NAMESPACES);
        console.log('CommonPrivateKeyProvider available:', !!this.CommonPrivateKeyProvider);
        
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

  async initializeWeb3Auth() {
    await this.ensureInitialized();
    if (this.web3auth) return;

    try {
      console.log('Initializing Web3Auth with CommonPrivateKeyProvider...');
      
      // Configure chain for Algorand
      const chainConfig = {
        chainNamespace: this.web3authBase.CHAIN_NAMESPACES.OTHER,
        chainId: 'algorand:testnet', // Testnet
        rpcTarget: 'https://testnet-api.algonode.cloud',
        displayName: 'Algorand Testnet',
        blockExplorerUrl: 'https://testnet.algoexplorer.io',
        ticker: 'ALGO',
        tickerName: 'Algorand',
      };
      
      // Create CommonPrivateKeyProvider for OTHER chain (Algorand)
      console.log('Creating CommonPrivateKeyProvider...');
      const privateKeyProvider = new this.CommonPrivateKeyProvider({
        config: { chainConfig }
      });
      
      // Custom storage adapter for React Native using Keychain
      const storageAdapter = {
        getItem: async (key: string) => {
          try {
            const credentials = await Keychain.getInternetCredentials(`web3auth.${key}`);
            return credentials ? credentials.password : null;
          } catch (error) {
            console.error('Storage getItem error:', error);
            return null;
          }
        },
        setItem: async (key: string, value: string) => {
          try {
            await Keychain.setInternetCredentials(
              `web3auth.${key}`,
              key,
              value
            );
          } catch (error) {
            console.error('Storage setItem error:', error);
          }
        },
        removeItem: async (key: string) => {
          try {
            await Keychain.resetInternetCredentials(`web3auth.${key}`);
          } catch (error) {
            console.error('Storage removeItem error:', error);
          }
        }
      };
      
      console.log('Creating Web3Auth instance...');
      this.web3auth = new this.Web3Auth({
        clientId: 'BKPbVLK-kIWlnwKwgYrcVFtOhkKIt4Sp1dxnF-qIPOdRAHLII_mfoJKpjfWwhOUIMwGYqjEX5n_5uQXtsEEPakE',
        web3AuthNetwork: this.WEB3AUTH_NETWORK.SAPPHIRE_DEVNET,
        privateKeyProvider, // Required for SFA
        storage: storageAdapter, // Custom storage for RN
        mode: this.SDK_MODE.REACT_NATIVE, // Set React Native mode
      });

      await this.web3auth.init();
      console.log('Web3Auth initialized successfully with CommonPrivateKeyProvider');
    } catch (error) {
      console.error('Failed to initialize Web3Auth:', error);
      throw error;
    }
  }

  async createOrRestoreWallet(firebaseIdToken: string, firebaseUid: string): Promise<string> {
    try {
      await this.ensureInitialized();
      await this.initializeWeb3Auth();
      
      if (!this.web3auth) {
        throw new Error('Web3Auth not initialized');
      }

      console.log(`Creating/restoring Algorand wallet for Firebase user: ${firebaseUid}`);
      
      // Pre-Web3Auth check - verify WebCrypto is available
      console.log('[pre-web3auth] global.crypto exists:', !!global.crypto);
      console.log('[pre-web3auth] global.crypto.subtle exists:', !!global.crypto?.subtle);
      console.log('[pre-web3auth] subtle.digest type:', typeof global.crypto?.subtle?.digest);
      console.log('[pre-web3auth] subtle.importKey type:', typeof global.crypto?.subtle?.importKey);
      
      // Check Node-style path that Web3Auth might use
      try {
        const nodeCrypto = require('crypto');
        console.log('[pre-web3auth] require("crypto").webcrypto exists:', !!nodeCrypto.webcrypto);
        console.log('[pre-web3auth] require("crypto").webcrypto.subtle exists:', !!nodeCrypto.webcrypto?.subtle);
        console.log('[pre-web3auth] require("crypto").webcrypto.subtle.importKey type:', typeof nodeCrypto.webcrypto?.subtle?.importKey);
      } catch (e) {
        console.log('[pre-web3auth] require("crypto") error:', e.message);
      }
      
      if (typeof global.crypto?.subtle?.digest !== 'function') {
        console.error('[pre-web3auth] WebCrypto digest is not available! This will fail.');
      }
      if (typeof global.crypto?.subtle?.importKey !== 'function') {
        console.error('[pre-web3auth] WebCrypto importKey is not available! This will fail.');
      }
      
      // Use Firebase verifier - one wallet per Firebase user regardless of login method
      const verifierName = 'firebase-confio-test';
      const verifierId = firebaseUid; // Firebase UID (sub claim) for consistent wallet
      
      console.log(`Using verifier: ${verifierName} with verifierId: ${verifierId}`);
      
      // Check if already connected before attempting to connect
      let web3authProvider;
      if (this.web3auth.status === 'connected') {
        console.log('Web3Auth already connected, getting existing provider...');
        web3authProvider = this.web3auth.provider;
        if (!web3authProvider) {
          throw new Error('Web3Auth is connected but provider is null');
        }
      } else {
        console.log('Web3Auth not connected, connecting...');
        // Connect using Single Factor Auth with Firebase ID token
        web3authProvider = await this.web3auth.connect({
          verifier: verifierName,
          verifierId: verifierId, // Firebase UID for consistent wallet
          idToken: firebaseIdToken, // Firebase ID token
        });
      }

      if (!web3authProvider) {
        throw new Error('Failed to connect to Web3Auth');
      }

      console.log('Web3Auth connected, requesting private key...');
      
      // Get the private key from Web3Auth using the correct RPC method for OTHER chain
      const hexPrivateKey = await web3authProvider.request({
        method: 'private_key' // For OTHER chain (CommonPrivateKeyProvider), use 'private_key'
      }) as string;
      
      console.log('Got private key from Web3Auth, converting to Algorand format...');
      console.log('Web3Auth hex private key:', hexPrivateKey);
      
      // Convert hex private key to Buffer (remove 0x prefix if present)
      const cleanHex = hexPrivateKey.replace(/^0x/, '');
      const privateKeyBuffer = Buffer.from(cleanHex, 'hex');
      console.log('Private key buffer length:', privateKeyBuffer.length);
      
      // For Algorand, we need a 32-byte seed
      let seed;
      if (privateKeyBuffer.length === 32) {
        // Perfect size, use as-is
        seed = privateKeyBuffer;
        console.log('Using 32-byte private key as seed directly');
      } else if (privateKeyBuffer.length > 32) {
        // Too long, take first 32 bytes
        seed = privateKeyBuffer.slice(0, 32);
        console.log('Truncating private key to 32 bytes for seed');
      } else {
        // Too short, pad with zeros
        seed = Buffer.alloc(32);
        privateKeyBuffer.copy(seed);
        console.log('Padding private key to 32 bytes for seed');
      }
      
      console.log('Converting seed to Algorand mnemonic and account...');
      
      // Check if algosdk has the methods we need
      if (!this.algosdk || !this.algosdk.secretKeyToMnemonic) {
        console.error('algosdk methods not available, skipping Algorand account creation');
        console.log('Available algosdk keys:', this.algosdk ? Object.keys(this.algosdk) : 'algosdk is null');
        
        // For debugging, let's manually derive an Algorand address from the seed
        // Algorand address = base32(publicKey + checksum)
        console.log('=== ALGORAND WALLET DEBUG INFO ===');
        console.log('Seed (hex):', seed.toString('hex'));
        console.log('Seed (base64):', seed.toString('base64'));
        console.log('Note: Without algosdk, cannot derive proper Algorand address');
        console.log('===================================');
        
        this.currentAccount = {
          addr: 'ALGORAND_ADDRESS_PENDING',
          sk: seed
        };
        return this.currentAccount.addr;
      }
      
      // Convert to Algorand account using mnemonic
      const mnemonic = this.algosdk.secretKeyToMnemonic(seed);
      const account = this.algosdk.mnemonicToSecretKey(mnemonic);
      
      // Fix address conversion - algosdk sometimes returns address as object with publicKey
      let algorandAddress;
      if (typeof account.addr === 'string') {
        // Already a string address
        algorandAddress = account.addr;
      } else if (account.addr && account.addr.publicKey) {
        // Address is an object with publicKey - convert to string
        const publicKeyBytes = new Uint8Array(account.addr.publicKey);
        algorandAddress = this.algosdk.encodeAddress(publicKeyBytes);
      } else {
        // Fallback - extract public key from secret key and encode
        const publicKeyBytes = account.sk.slice(32); // Public key is last 32 bytes of 64-byte secret key
        algorandAddress = this.algosdk.encodeAddress(publicKeyBytes);
      }
      
      // Log the Algorand wallet details (for debugging only - remove in production!)
      console.log('=== ALGORAND WALLET GENERATED ===');
      console.log('Raw account.addr:', account.addr);
      console.log('Converted Algorand Address:', algorandAddress);
      console.log('Account object keys:', Object.keys(account));
      console.log('Algorand Private Key (hex):', Buffer.from(account.sk).toString('hex'));
      console.log('Algorand Mnemonic:', mnemonic);
      console.log('==================================');
      
      // Create corrected account object with proper string address
      this.currentAccount = {
        ...account,
        addr: algorandAddress
      };
      
      // Store the wallet data securely in Keychain (avoid freezing binary objects)
      const walletData = {
        address: algorandAddress, // Use the corrected string address
        mnemonic: mnemonic,
        privateKey: Buffer.from(account.sk).toString('hex') // Convert to hex string
      };
      
      await Keychain.setInternetCredentials(
        'algorand.confio.app',
        'wallet',
        JSON.stringify(walletData),
        {
          service: 'com.confio.algorand'
        }
      );
      
      console.log('Algorand wallet created/restored:', algorandAddress);
      
      // Skip automatic opt-in for now due to algosdk React Native compatibility issues
      // The backend will handle opt-ins through the newer authServiceWeb3.ts flow
      console.log('[AlgorandService] Skipping automatic opt-in - will be handled by backend');
      
      return algorandAddress;
    } catch (error) {
      console.error('Error creating/restoring Algorand wallet:', error);
      throw error;
    }
  }

  async getBalance(address?: string): Promise<number> {
    try {
      await this.ensureInitialized();
      if (!this.algodClient) {
        throw new Error('Algod client not initialized');
      }

      const addr = address || this.currentAccount?.addr;
      if (!addr) {
        throw new Error('No address provided');
      }

      const accountInfo = await this.algodClient.accountInformation(addr).do();
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
      if (!this.currentAccount || !this.algodClient) {
        throw new Error('Wallet not initialized');
      }

      // Get suggested params
      const params = await this.algodClient.getTransactionParams().do();
      
      // Create transaction
      const txn = this.algosdk.makePaymentTxnWithSuggestedParamsFromObject({
        from: this.currentAccount.addr,
        to: toAddress,
        amount: Math.floor(amount * 1000000), // Convert to microAlgos
        suggestedParams: params,
      });

      // Sign transaction
      const signedTxn = txn.signTxn(this.currentAccount.sk);
      
      // Submit transaction
      const { txId } = await this.algodClient.sendRawTransaction(signedTxn).do();
      
      // Wait for confirmation
      await this.algosdk.waitForConfirmation(this.algodClient, txId, 4);
      
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

  getAlgosdk(): any {
    return this.algosdk;
  }

  async clearWallet() {
    this.currentAccount = null;
    // Clear from Keychain
    await Keychain.resetInternetCredentials('algorand.confio.app', {
      service: 'com.confio.algorand'
    });
  }
  
  async getStoredAddress(): Promise<string | null> {
    try {
      const credentials = await Keychain.getInternetCredentials('algorand.confio.app', {
        service: 'com.confio.algorand'
      });
      
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
        
        // Convert BigInt values to regular numbers and clean the object
        const processedParams = {
          fee: typeof params.fee === 'bigint' ? Number(params.fee) : (params.fee || 1000),
          firstRound: typeof params.firstValid === 'bigint' ? Number(params.firstValid) : (params.firstValid || params.firstRound || 1000),
          lastRound: typeof params.lastValid === 'bigint' ? Number(params.lastValid) : (params.lastValid || params.lastRound || 2000),
          genesisHash: params.genesisHash || 'SGO1GKSzyE7IEPItTxCByw9x8FmnrCDexi9/cOUJOiI=',
          genesisID: params.genesisID || params['genesis-id'] || 'testnet-v1.0',
          flatFee: params.flatFee !== undefined ? params.flatFee : false
        };
        console.log('[AlgorandService] Processed transaction params:', processedParams);
        
        // Validate account address before creating transaction
        if (!this.currentAccount.addr || typeof this.currentAccount.addr !== 'string') {
          console.error('[AlgorandService] Invalid account address:', this.currentAccount.addr);
          throw new Error('Account address is null or invalid');
        }
        
        console.log('[AlgorandService] Using address:', this.currentAccount.addr);
        
        // Create opt-in transaction using direct method
        console.log('[AlgorandService] Creating asset transfer transaction for opt-in...');
        
        let txn;
        try {
          // Try using Transaction constructor directly - most reliable approach
          console.log('[AlgorandService] Trying direct Transaction constructor...');
          
          const txnParams = {
            type: 'axfer',  // Asset transfer
            from: this.currentAccount.addr,
            to: this.currentAccount.addr,
            assetIndex: CONFIO_ASSET_ID,
            amount: 0,
            fee: processedParams.fee,
            firstRound: processedParams.firstRound,
            lastRound: processedParams.lastRound,
            genesisHash: processedParams.genesisHash,
            genesisID: processedParams.genesisID,
            flatFee: processedParams.flatFee
          };
          
          console.log('[AlgorandService] Transaction params for constructor:', txnParams);
          
          if (this.algosdk.Transaction) {
            txn = new this.algosdk.Transaction(txnParams);
            console.log('[AlgorandService] Direct Transaction constructor succeeded');
          } else {
            throw new Error('Transaction constructor not found');
          }
          
        } catch (directError) {
          console.error('[AlgorandService] Direct constructor failed:', directError);
          
          try {
            // Fallback to makeAssetTransferTxn if it exists
            console.log('[AlgorandService] Trying makeAssetTransferTxn...');
            if (this.algosdk.makeAssetTransferTxn) {
              txn = this.algosdk.makeAssetTransferTxn(
                this.currentAccount.addr,  // from
                this.currentAccount.addr,  // to  
                undefined,                 // closeRemainderTo
                undefined,                 // revocationTarget
                0,                        // amount (0 for opt-in)
                undefined,                // note
                CONFIO_ASSET_ID,          // assetIndex
                processedParams           // suggestedParams
              );
              console.log('[AlgorandService] makeAssetTransferTxn succeeded');
            } else {
              throw new Error('makeAssetTransferTxn not found');
            }
          } catch (makeError) {
            console.error('[AlgorandService] makeAssetTransferTxn failed:', makeError);
            
            // Final fallback to object method
            let makeAssetTransferTxn;
            if (this.algosdk.makeAssetTransferTxnWithSuggestedParamsFromObject) {
              makeAssetTransferTxn = this.algosdk.makeAssetTransferTxnWithSuggestedParamsFromObject;
            } else if (this.algosdk.default?.makeAssetTransferTxnWithSuggestedParamsFromObject) {
              makeAssetTransferTxn = this.algosdk.default.makeAssetTransferTxnWithSuggestedParamsFromObject;
            } else {
              console.error('[AlgorandService] makeAssetTransferTxnWithSuggestedParamsFromObject not found');
              console.error('[AlgorandService] Available algosdk methods:', Object.keys(this.algosdk));
              throw new Error('No suitable asset transfer transaction method found');
            }
            
            console.log('[AlgorandService] Creating transaction with object method and params:', {
              from: this.currentAccount.addr,
              to: this.currentAccount.addr,
              amount: 0,
              assetIndex: CONFIO_ASSET_ID,
              suggestedParams: processedParams
            });
            
            txn = makeAssetTransferTxn({
              from: this.currentAccount.addr,
              to: this.currentAccount.addr,
              amount: 0,
              assetIndex: CONFIO_ASSET_ID,
              suggestedParams: processedParams,
            });
          }
        }
        console.log('[AlgorandService] Created opt-in transaction');

        // Sign transaction
        const signedTxn = txn.signTxn(this.currentAccount.sk);
        console.log('[AlgorandService] Transaction signed');
        
        // Submit transaction using the real client
        const { txId } = await realAlgodClient.sendRawTransaction(signedTxn).do();
        console.log(`[AlgorandService] Transaction submitted. TxID: ${txId}`);
        
        // Wait for confirmation using the real client
        const confirmedTxn = await this.algosdk.waitForConfirmation(realAlgodClient, txId, 4);
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
          }),
          {
            service: 'com.confio.algorand.optin'
          }
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
            }),
            {
              service: 'com.confio.algorand.optin'
            }
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
      const credentials = await Keychain.getInternetCredentials('algorand.confio.optin', {
        service: 'com.confio.algorand.optin'
      });
      
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
      
      // Decode base64 transactions
      const userTxn = Uint8Array.from(atob(result.userTransaction), c => c.charCodeAt(0));
      const sponsorTxn = Uint8Array.from(atob(result.sponsorTransaction), c => c.charCodeAt(0));
      
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
      
      // Decode and sign the user transaction
      const txn = this.algosdk.decodeObj(userTransaction);
      const signedUserTxn = txn.signTxn(this.currentAccount.sk);
      
      // Encode for submission
      const signedUserTxnB64 = btoa(String.fromCharCode(...signedUserTxn));
      const sponsorTxnB64 = btoa(String.fromCharCode(...sponsorTransaction));
      
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
    assetId: number = 743890784 // Default to CONFIO
  ): Promise<boolean> {
    try {
      await this.ensureInitialized();
      
      if (!this.currentAccount) {
        console.error('[AlgorandService] No account available for opt-in');
        return false;
      }

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
      
      // Step 2: Decode and sign the user transaction
      const userTxnBytes = Uint8Array.from(atob(result.userTransaction), c => c.charCodeAt(0));
      
      // Decode the transaction object
      const txn = this.algosdk.decodeObj(userTxnBytes);
      
      // Sign with user's private key from Web3Auth
      const signedUserTxn = txn.signTxn(this.currentAccount.sk);
      
      // Convert to base64
      const signedUserTxnB64 = btoa(String.fromCharCode(...signedUserTxn));
      
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
        }),
        {
          service: 'com.confio.algorand.optin'
        }
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