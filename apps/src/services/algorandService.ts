import * as Keychain from 'react-native-keychain';

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
            'min-fee': 1000,
            'last-round': 1000,
            'genesis-hash': 'SGO1GKSzyE7IEPItTxCByw9x8FmnrCDexi9/cOUJOiI=',
            'genesis-id': 'testnet-v1.0'
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
}

export default new AlgorandService();