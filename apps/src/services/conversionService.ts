/**
 * Service for handling cUSD conversions with transaction signing
 */
import { Buffer } from 'buffer';
import { secureDeterministicWallet } from './secureDeterministicWallet';
import { apolloClient } from '../apollo/client';
import { EXECUTE_PENDING_CONVERSION } from '../apollo/mutations';

export interface ConversionTransaction {
  txn: string; // Base64 encoded transaction
  signers: string[]; // Addresses that need to sign
  message: string; // Description
}

export interface SponsorTransaction {
  txn: string; // Base64 encoded transaction
  index: number; // Position in group
}

class ConversionService {
  private algosdk: any = null;

  /**
   * Initialize algosdk for transaction handling
   */
  private async ensureInitialized() {
    if (!this.algosdk) {
      const algosdk = await import('algosdk');
      this.algosdk = algosdk;
    }
  }

  /**
   * Sign and execute a conversion with sponsored fees
   * Automatically signs the transactions and submits them
   */
  async signAndExecuteConversion(
    transactions: ConversionTransaction[],
    sponsorTransaction: SponsorTransaction,
    groupId: string,
    conversionId: string,
    account?: any // Pass the account to ensure wallet is initialized
  ): Promise<{ success: boolean; transactionId?: string; error?: string }> {
    try {
      await this.ensureInitialized();
      
      console.log('[ConversionService] Signing conversion transactions');
      
      // Log account info for debugging
      if (account) {
        console.log('[ConversionService] Account info:', {
          type: account.type,
          index: account.index,
          algorandAddress: account.algorandAddress
        });
      } else {
        console.log('[ConversionService] No account provided, proceeding with existing wallet scope');
      }

      // Ensure signer scope matches active account (especially for business)
      try {
        const { oauthStorage } = await import('../services/oauthStorageService');
        const oauth = await oauthStorage.getOAuthSubject();
        if (oauth?.subject && oauth?.provider) {
          const provider: 'google' | 'apple' = oauth.provider === 'apple' ? 'apple' : 'google';
          const { GOOGLE_CLIENT_IDS } = await import('../config/env');
          const GOOGLE_WEB_CLIENT_ID = GOOGLE_CLIENT_IDS.production.web;
          const iss = provider === 'google' ? 'https://accounts.google.com' : 'https://appleid.apple.com';
          const aud = provider === 'google' ? GOOGLE_WEB_CLIENT_ID : 'com.confio.app';
          // Extract businessId if available
          const businessId = account?.businessId 
            || (account?.id?.startsWith('business_') ? (account.id.split('_')[1] || undefined) : undefined);
          await secureDeterministicWallet.createOrRestoreWallet(
            iss,
            oauth.subject,
            aud,
            provider,
            account?.type || 'personal',
            account?.index ?? 0,
            businessId
          );
        }
      } catch (scopeErr) {
        console.warn('[ConversionService] Could not initialize signer scope (will attempt anyway):', scopeErr);
      }
      
      // The wallet should already be initialized from login
      // The scope would have been set during wallet creation/restoration
      // If not, the signing will fail with a clear error message
      
      // Decode and sign user transactions
      const signedTxns: Uint8Array[] = [];
      
      for (const tx of transactions) {
        // Parse the transaction if it's a JSON string (GraphQL returns JSONString)
        const txData = typeof tx === 'string' ? JSON.parse(tx) : tx;
        
        // Decode the transaction from base64
        const txnBytes = Buffer.from(txData.txn, 'base64');
        
        // Sign with the wallet
        const signedTxn = await secureDeterministicWallet.signTransaction(
          txnBytes
        );
        
        signedTxns.push(signedTxn);
      }
      
      // Combine signed transactions into base64 for sending to server
      const signedTransactionsB64 = signedTxns.map(txn => 
        Buffer.from(txn).toString('base64')
      );
      
      // Include sponsor transaction if provided (for 3-tx sponsored groups)
      let allTransactions = [];
      
      console.log('[ConversionService] Sponsor transaction:', sponsorTransaction);
      console.log('[ConversionService] User signed transactions count:', signedTransactionsB64.length);
      
      if (sponsorTransaction) {
        // Parse sponsor tx if it's a JSON string
        const sponsorData = typeof sponsorTransaction === 'string' ? JSON.parse(sponsorTransaction) : sponsorTransaction;
        
        console.log('[ConversionService] Sponsor data:', sponsorData);
        
        // Check the index of sponsor transaction
        const sponsorIndex = sponsorData.index !== undefined ? sponsorData.index : 0;
        
        if (sponsorIndex === 2) {
          // New order: [user_txn0, user_txn1, sponsor]
          allTransactions = signedTransactionsB64.slice(); // User transactions first
          
          // Add sponsor at the end
          if (sponsorData.signed) {
            console.log('[ConversionService] Adding pre-signed sponsor transaction at index 2');
            allTransactions.push(sponsorData.signed);
          } else if (sponsorData.txn) {
            console.log('[ConversionService] Adding unsigned sponsor transaction at index 2');
            allTransactions.push(sponsorData.txn);
          }
        } else {
          // Old order: [sponsor, user_txn0, user_txn1]
          if (sponsorData.signed) {
            console.log('[ConversionService] Adding pre-signed sponsor transaction at index 0');
            allTransactions.push(sponsorData.signed);
          } else if (sponsorData.txn) {
            console.log('[ConversionService] Adding unsigned sponsor transaction at index 0');
            allTransactions.push(sponsorData.txn);
          }
          // Then add user transactions
          allTransactions = allTransactions.concat(signedTransactionsB64);
        }
        
        console.log('[ConversionService] Total transactions to send:', allTransactions.length);
      } else {
        // No sponsor, just user transactions
        console.log('[ConversionService] No sponsor transaction provided');
        allTransactions = signedTransactionsB64;
      }
      
      // Send to server for execution
      const result = await apolloClient.mutate({
        mutation: EXECUTE_PENDING_CONVERSION,
        variables: {
          conversionId,
          signedTransactions: JSON.stringify({
            userSignedTxns: allTransactions,
            groupId,
            sponsorTxIndex: sponsorTransaction ? 0 : -1
          })
        }
      });
      
      if (result.data?.executePendingConversion?.success) {
        return {
          success: true,
          transactionId: result.data.executePendingConversion.transactionId
        };
      } else {
        return {
          success: false,
          error: result.data?.executePendingConversion?.errors?.[0] || 'Failed to execute conversion'
        };
      }
      
    } catch (error) {
      console.error('[ConversionService] Error signing conversion:', error);
      return {
        success: false,
        error: error.message || 'Failed to sign conversion'
      };
    }
  }

  /**
   * Sign and execute conversion with multiple sponsor transactions
   * Used for true sponsorship where sponsor sends app call
   */
  async signAndExecuteWithMultipleSponsorTxs(
    userTransactions: ConversionTransaction[],
    sponsorTransactions: any[],
    groupId: string,
    conversionId: string,
    account?: any
  ): Promise<{ success: boolean; transactionId?: string; error?: string }> {
    try {
      await this.ensureInitialized();
      
      console.log('[ConversionService] Signing with multiple sponsor transactions');
      
      // Sign user transactions (should be just the asset transfer)
      const signedUserTxns: string[] = [];
      
      for (const tx of userTransactions) {
        // Parse the transaction if it's a JSON string
        const txData = typeof tx === 'string' ? JSON.parse(tx) : tx;
        
        // Decode the transaction from base64
        const txnBytes = Buffer.from(txData.txn, 'base64');
        
        // Sign with the wallet
        const signedTxn = await secureDeterministicWallet.signTransaction(txnBytes);
        
        // Convert back to base64
        signedUserTxns.push(Buffer.from(signedTxn).toString('base64'));
      }
      
      // Build complete transaction array in correct order
      // Expected order: [sponsor_payment, user_asset_transfer, sponsor_app_call]
      const allTransactions: string[] = [];
      
      // Parse sponsor transactions
      const sponsorTxsData = sponsorTransactions.map(tx => 
        typeof tx === 'string' ? JSON.parse(tx) : tx
      );
      
      // Sort sponsor transactions by index
      sponsorTxsData.sort((a, b) => a.index - b.index);
      
      console.log('[ConversionService] Sponsor transaction indices:', 
        sponsorTxsData.map(tx => tx.index));
      
      // Build the complete transaction array
      // We need to interleave sponsor and user transactions based on indices
      let userTxIndex = 0;
      for (let i = 0; i < 3; i++) { // Assuming 3 total transactions
        // Check if there's a sponsor transaction for this index
        const sponsorTx = sponsorTxsData.find(tx => tx.index === i);
        
        if (sponsorTx) {
          // Add sponsor transaction (already signed)
          if (sponsorTx.signed) {
            console.log(`[ConversionService] Adding sponsor transaction at index ${i}`);
            allTransactions.push(sponsorTx.signed);
          } else if (sponsorTx.txn) {
            console.log(`[ConversionService] Adding unsigned sponsor transaction at index ${i}`);
            allTransactions.push(sponsorTx.txn);
          }
        } else {
          // Add user transaction
          if (userTxIndex < signedUserTxns.length) {
            console.log(`[ConversionService] Adding user transaction at index ${i}`);
            allTransactions.push(signedUserTxns[userTxIndex]);
            userTxIndex++;
          }
        }
      }
      
      console.log('[ConversionService] Final transaction order:', allTransactions.length, 'transactions');
      
      // Send to server for execution
      const result = await apolloClient.mutate({
        mutation: EXECUTE_PENDING_CONVERSION,
        variables: {
          conversionId,
          signedTransactions: JSON.stringify({
            userSignedTxns: allTransactions,
            groupId,
            sponsorTxIndex: 0 // Not used in new structure
          })
        }
      });
      
      if (result.data?.executePendingConversion?.success) {
        return {
          success: true,
          transactionId: result.data.executePendingConversion.transactionId
        };
      } else {
        return {
          success: false,
          error: result.data?.executePendingConversion?.errors?.[0] || 'Failed to execute conversion'
        };
      }
      
    } catch (error) {
      console.error('[ConversionService] Error with multiple sponsor txs:', error);
      return {
        success: false,
        error: error.message || 'Failed to sign conversion'
      };
    }
  }

  /**
   * Process a conversion response and execute if transactions are present
   * This is called from the USDCConversionScreen after mutation
   */
  async processConversionResponse(
    mutationResult: any,
    conversionId: string,
    account?: any // Pass the account to ensure wallet is initialized
  ): Promise<{ success: boolean; error?: string }> {
    try {
      // Check if we have transactions to sign
      const transactions = mutationResult.transactionsToSign;
      const sponsorTxs = mutationResult.sponsorTransactions || []; // Array of sponsor transactions
      const sponsorTx = mutationResult.sponsorTransaction; // Legacy single sponsor tx
      const groupId = mutationResult.groupId;
      
      if (!transactions || transactions.length === 0) {
        // No transactions means it was processed server-side
        return { success: true };
      }
      
      console.log('[ConversionService] Processing conversion with transactions to sign');
      console.log('[ConversionService] User transactions:', transactions.length);
      console.log('[ConversionService] Sponsor transactions:', sponsorTxs.length);
      
      // Handle new structure with multiple sponsor transactions
      if (sponsorTxs && sponsorTxs.length > 0) {
        // New structure: build complete transaction group
        return await this.signAndExecuteWithMultipleSponsorTxs(
          transactions,
          sponsorTxs,
          groupId,
          conversionId || mutationResult.conversion?.id,
          account
        );
      }
      
      // Legacy: single sponsor transaction
      const result = await this.signAndExecuteConversion(
        transactions,
        sponsorTx,
        groupId,
        conversionId || mutationResult.conversion?.id,
        account
      );
      
      return result;
      
    } catch (error) {
      console.error('[ConversionService] Error processing conversion:', error);
      return {
        success: false,
        error: error.message || 'Failed to process conversion'
      };
    }
  }
}

export const conversionService = new ConversionService();
