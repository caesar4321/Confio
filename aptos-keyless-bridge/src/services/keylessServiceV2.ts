import { Aptos, AptosConfig, Network, Account, AccountAuthenticator, Deserializer } from '@aptos-labs/ts-sdk';
import loggerModule from '../logger';

const logger = loggerModule;

interface SimpleFeePayerRequest {
  senderAddress: string;
  recipientAddress: string;
  amount: number;
  tokenType: string;
  senderAuthenticator: string; // Base64 encoded authenticator
}

interface SimpleFeePayerResponse {
  success: boolean;
  transactionHash?: string;
  error?: string;
}

export class KeylessServiceV2 {
  private aptos: Aptos;
  private sponsorAccount: Account;
  private pendingTransactions?: Map<string, any>;

  constructor() {
    // Use Nodit API instead of default Aptos RPC
    const noditApiKey = process.env.NODIT_API_KEY;
    const network = (process.env.APTOS_NETWORK || 'testnet') === 'mainnet' 
      ? Network.MAINNET 
      : Network.TESTNET;
    
    // Configure to use Nodit endpoints
    const isMainnet = network === Network.MAINNET;
    const noditEndpoint = isMainnet 
      ? 'https://aptos-mainnet.nodit.io/v1'
      : 'https://aptos-testnet.nodit.io/v1';
    
    const config = new AptosConfig({ 
      network,
      // Override the default fullnode URL with Nodit
      fullnode: noditApiKey ? noditEndpoint : undefined,
      // Add API key as custom header if provided
      clientConfig: noditApiKey ? {
        HEADERS: {
          'X-API-KEY': noditApiKey
        }
      } : undefined
    });
    this.aptos = new Aptos(config);

    // Load sponsor account from environment
    const sponsorPrivateKey = process.env.APTOS_SPONSOR_PRIVATE_KEY;
    
    if (!sponsorPrivateKey) {
      throw new Error('APTOS_SPONSOR_PRIVATE_KEY not configured in environment variables');
    }
    
    // Create account from private key using Ed25519PrivateKey
    const { Ed25519PrivateKey } = require('@aptos-labs/ts-sdk');
    const privateKeyHex = sponsorPrivateKey.startsWith('0x') 
      ? sponsorPrivateKey.slice(2) 
      : sponsorPrivateKey;
    const privateKey = new Ed25519PrivateKey(privateKeyHex);
    this.sponsorAccount = Account.fromPrivateKey({ privateKey });

    logger.info('KeylessServiceV2 initialized');
    logger.info('Sponsor address:', this.sponsorAccount.accountAddress.toString());
    logger.info('Using RPC endpoint:', noditApiKey ? 'Nodit API' : 'Aptos Labs API');
  }

  /**
   * Submit a sponsored transaction using the official SDK pattern
   * Based on: https://github.com/aptos-labs/aptos-ts-sdk/blob/main/examples/typescript/simple_sponsored_transaction.ts
   */
  async submitSponsoredTransaction(request: SimpleFeePayerRequest): Promise<SimpleFeePayerResponse> {
    try {
      logger.info('Processing sponsored transaction with SDK pattern');
      logger.info('Sender:', request.senderAddress);
      logger.info('Recipient:', request.recipientAddress);
      logger.info('Amount:', request.amount);

      // Build the transaction with fee payer flag
      const transaction = await this.aptos.transaction.build.simple({
        sender: request.senderAddress,
        withFeePayer: true, // Critical flag for sponsored transactions
        data: {
          function: this.getTransferFunction(request.tokenType) as `${string}::${string}::${string}`,
          functionArguments: [request.recipientAddress, request.amount]
        }
      });

      logger.info('Transaction built with fee payer flag');

      // Sign as fee payer (sponsor)
      const sponsorSignature = this.aptos.transaction.signAsFeePayer({
        signer: this.sponsorAccount,
        transaction
      });

      logger.info('Sponsor signature created');

      // Decode the sender's authenticator from base64
      const senderAuthBytes = Buffer.from(request.senderAuthenticator, 'base64');
      
      // Create AccountAuthenticator from bytes using Deserializer
      const deserializer = new Deserializer(new Uint8Array(senderAuthBytes));
      const senderAuthenticator = AccountAuthenticator.deserialize(deserializer);

      // Submit the transaction with both authenticators
      const pendingTxn = await this.aptos.transaction.submit.simple({
        transaction,
        senderAuthenticator,
        feePayerAuthenticator: sponsorSignature
      });

      logger.info('Transaction submitted:', pendingTxn.hash);

      // Wait for confirmation
      const committedTxn = await this.aptos.waitForTransaction({
        transactionHash: pendingTxn.hash
      });

      if (committedTxn.success) {
        logger.info('✅ Sponsored transaction successful:', pendingTxn.hash);
        return {
          success: true,
          transactionHash: pendingTxn.hash
        };
      } else {
        logger.error('Transaction failed:', committedTxn.vm_status);
        return {
          success: false,
          error: `Transaction failed: ${committedTxn.vm_status}`
        };
      }

    } catch (error) {
      logger.error('Error in sponsored transaction:', error);
      return {
        success: false,
        error: error instanceof Error ? error.message : String(error)
      };
    }
  }

  /**
   * Alternative: Build and sign transaction, return for external submission
   */
  async buildSponsoredTransaction(request: SimpleFeePayerRequest) {
    try {
      logger.info('Building sponsored transaction with request:', {
        sender: request.senderAddress,
        recipient: request.recipientAddress,
        amount: request.amount,
        tokenType: request.tokenType
      });

      // Import AccountAddress
      const { AccountAddress } = require('@aptos-labs/ts-sdk');
      
      // Convert sender address to AccountAddress object
      const senderAccount = AccountAddress.from(request.senderAddress);
      
      // First, build the transaction WITHOUT fee payer for the sender to sign
      const senderTransaction = await this.aptos.transaction.build.simple({
        sender: senderAccount,
        withFeePayer: false,  // Sender signs the transaction without fee payer
        data: {
          function: this.getTransferFunction(request.tokenType) as `${string}::${string}::${string}`,
          functionArguments: [request.recipientAddress, request.amount]
        }
      });
      
      // Now build the transaction WITH fee payer for the final submission
      const transaction = await this.aptos.transaction.build.simple({
        sender: senderAccount,
        withFeePayer: true,
        data: {
          function: this.getTransferFunction(request.tokenType) as `${string}::${string}::${string}`,
          functionArguments: [request.recipientAddress, request.amount]
        }
      });
      
      logger.info('Transaction built successfully');
      logger.info('Transaction rawTransaction exists:', !!transaction.rawTransaction);
      logger.info('Transaction fee payer:', transaction.feePayerAddress?.toString());

      // Sign as sponsor (fee payer)
      const sponsorAuthenticator = this.aptos.transaction.signAsFeePayer({
        signer: this.sponsorAccount,
        transaction
      });

      // Store the transaction for later use
      const transactionId = Buffer.from(Math.random().toString()).toString('base64').substring(0, 16);
      if (!this.pendingTransactions) {
        this.pendingTransactions = new Map();
      }
      this.pendingTransactions.set(transactionId, {
        transaction,
        sponsorAuthenticator,
        timestamp: Date.now()
      });

      // Clean up old transactions (older than 5 minutes)
      const fiveMinutesAgo = Date.now() - 5 * 60 * 1000;
      for (const [id, data] of this.pendingTransactions.entries()) {
        if (data.timestamp < fiveMinutesAgo) {
          this.pendingTransactions.delete(id);
        }
      }

      // Return transaction ID and signing message for sender
      // For sponsored transactions, the sender should sign the transaction WITHOUT fee payer
      if (!senderTransaction || !senderTransaction.rawTransaction) {
        logger.error('Sender transaction object is invalid:', senderTransaction);
        throw new Error('Failed to build sender transaction - invalid transaction object');
      }
      
      // CRITICAL: The sender signs the transaction WITHOUT the fee payer
      const senderRawTxnBytes = senderTransaction.rawTransaction.bcsToBytes();
      
      // For debugging, let's log both transaction structures
      logger.info('Sender transaction structure:', {
        hasRawTransaction: !!senderTransaction.rawTransaction,
        hasFeePayerAddress: !!senderTransaction.feePayerAddress,
        rawTxnLength: senderRawTxnBytes.length
      });
      
      logger.info('Sponsor transaction structure:', {
        hasRawTransaction: !!transaction.rawTransaction,
        hasFeePayerAddress: !!transaction.feePayerAddress,
        rawTxnLength: transaction.rawTransaction.bcsToBytes().length
      });
      
      // Convert sender transaction bytes to base64 for transport
      const rawTransactionBase64 = Buffer.from(senderRawTxnBytes).toString('base64');
      
      logger.info('Transaction built successfully');
      logger.info('Sender raw transaction length:', senderRawTxnBytes.length);
      logger.info('Transaction ID:', transactionId);
      logger.info('Fee payer address in transaction:', transaction.feePayerAddress?.toString());
      
      return {
        success: true,
        transactionId,
        signingMessage: rawTransactionBase64,  // Return as base64
        rawTransaction: rawTransactionBase64,   // Also include as rawTransaction for compatibility
        sponsorAddress: this.sponsorAccount.accountAddress.toString(),
        sponsorAuthenticator,  // Include sponsor authenticator for later use
        note: 'Sign the signingMessage and return with transactionId'
      };

    } catch (error) {
      logger.error('Error building sponsored transaction:', error);
      return {
        success: false,
        error: error instanceof Error ? error.message : String(error)
      };
    }
  }

  /**
   * Submit a transaction that was previously built and signed
   * Uses the cached transaction and sponsor authenticator from buildSponsoredTransaction
   */
  async submitCachedTransaction(transactionId: string, senderAuthenticatorBase64: string) {
    try {
      if (!this.pendingTransactions) {
        throw new Error('No pending transactions found');
      }

      const cached = this.pendingTransactions.get(transactionId);
      if (!cached) {
        throw new Error('Transaction not found or expired');
      }

      logger.info('Submitting cached transaction:', transactionId);
      logger.info('Cached transaction exists:', !!cached.transaction);
      logger.info('Cached sponsor authenticator exists:', !!cached.sponsorAuthenticator);
      
      const { transaction, sponsorAuthenticator } = cached;
      
      // Log transaction details
      logger.info('Transaction rawTransaction exists:', !!transaction.rawTransaction);
      logger.info('Transaction fee payer:', transaction.feePayerAddress?.toString());
      
      // Decode the sender's authenticator from base64
      const senderAuthBytes = Buffer.from(senderAuthenticatorBase64, 'base64');
      logger.info('Sender authenticator bytes length:', senderAuthBytes.length);
      
      // Create AccountAuthenticator from bytes using Deserializer
      const deserializer = new Deserializer(new Uint8Array(senderAuthBytes));
      const senderAuthenticator = AccountAuthenticator.deserialize(deserializer);
      logger.info('Sender authenticator deserialized successfully');

      // Try a different submission approach
      // Let's properly construct the signed transaction for sponsored transactions
      try {
        // Serialize the signed transaction properly for FeePayer variant
        const { Serializer } = require('@aptos-labs/ts-sdk');
        const serializer = new Serializer();
        
        // SignedTransaction::FeePayer variant tag = 3
        serializer.serializeU8(3);
        
        // 1. Serialize the raw transaction
        transaction.rawTransaction.serialize(serializer);
        
        // 2. Serialize the sender authenticator
        senderAuthenticator.serialize(serializer);
        
        // 3. Serialize the fee payer address (required for FeePayer variant)
        transaction.feePayerAddress.serialize(serializer);
        
        // 4. Serialize the fee payer authenticator
        sponsorAuthenticator.serialize(serializer);
        
        const signedTxnBytes = serializer.toUint8Array();
        
        logger.info('Attempting manual transaction submission');
        logger.info('Signed transaction bytes length:', signedTxnBytes.length);
        
        // Try submitting directly
        const response = await fetch(`${this.aptos.config.fullnode}/transactions`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/x.aptos.signed_transaction+bcs',
            ...(process.env.NODIT_API_KEY ? { 'X-API-KEY': process.env.NODIT_API_KEY } : {})
          },
          body: signedTxnBytes
        });
        
        if (!response.ok) {
          const error = await response.text();
          logger.error('Manual submission failed:', error);
          throw new Error(`Manual submission failed: ${error}`);
        }
        
        const result: any = await response.json();
        logger.info('Transaction submitted manually:', result.hash);
        
        return {
          success: true,
          transactionHash: result.hash as string
        };
        
      } catch (manualError) {
        logger.error('Manual submission error:', manualError);
        
        // Fall back to SDK method
        logger.info('Falling back to SDK submission');
        
        // Log what we're about to submit
        logger.info('About to submit transaction with:');
        logger.info('- Transaction type:', transaction.constructor.name);
        logger.info('- Has rawTransaction:', !!transaction.rawTransaction);
        logger.info('- Sender authenticator type:', senderAuthenticator.constructor.name);
        logger.info('- Fee payer authenticator type:', sponsorAuthenticator.constructor.name);
        
        // Submit the CACHED transaction with both authenticators
        const pendingTxn = await this.aptos.transaction.submit.simple({
          transaction,  // Use the cached transaction
          senderAuthenticator,
          feePayerAuthenticator: sponsorAuthenticator  // Use the cached sponsor authenticator
        });

        logger.info('Transaction submitted:', pendingTxn.hash);

        // Wait for confirmation
        const committedTxn = await this.aptos.waitForTransaction({
          transactionHash: pendingTxn.hash
        });

        // Clean up the pending transaction
        this.pendingTransactions.delete(transactionId);

        if (committedTxn.success) {
          logger.info('✅ Sponsored transaction successful:', pendingTxn.hash);
          return {
            success: true,
            transactionHash: pendingTxn.hash
          };
        } else {
          logger.error('Transaction failed:', committedTxn.vm_status);
          return {
            success: false,
            error: `Transaction failed: ${committedTxn.vm_status}`
          };
        }
      }

    } catch (error) {
      logger.error('Error submitting cached transaction:', error);
      return {
        success: false,
        error: error instanceof Error ? error.message : String(error)
      };
    }
  }

  private getTransferFunction(tokenType: string): string {
    switch (tokenType.toLowerCase()) {
      case 'apt':
        return '0x1::aptos_account::transfer';
      case 'confio':
        // CONFIO module deployed by sponsor account
        return '0x75f38ae0c198dcedf766e0d2a39847f9b269052024e943c58970854b9cb70e2c::confio::transfer_confio';
      case 'cusd':
        // cUSD module deployed by sponsor account
        return '0x75f38ae0c198dcedf766e0d2a39847f9b269052024e943c58970854b9cb70e2c::cusd::transfer_cusd';
      default:
        throw new Error(`Unsupported token type: ${tokenType}`);
    }
  }
}

// Export singleton instance
export const keylessServiceV2 = new KeylessServiceV2();