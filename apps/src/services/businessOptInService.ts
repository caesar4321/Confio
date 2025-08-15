/**
 * Business Account Opt-In Service
 * 
 * Handles one-time asset opt-ins for business accounts.
 * Only business owners can opt-in the business account (not employees).
 * Opt-ins are checked once and cached to avoid repeated blockchain queries.
 */

import * as Keychain from 'react-native-keychain';
import { apolloClient } from '../apollo/client';
import { gql } from '@apollo/client';
import algorandService from './algorandService';
import { AccountManager } from '../utils/accountManager';
import authService from './authService';
import { jwtDecode } from 'jwt-decode';
import { CHECK_BUSINESS_OPT_IN, COMPLETE_BUSINESS_OPT_IN, SUBMIT_SPONSORED_GROUP } from '../apollo/mutations';
import { UPDATE_ACCOUNT_ALGORAND_ADDRESS } from '../apollo/queries';

class BusinessOptInService {
  private static instance: BusinessOptInService;
  private KEYCHAIN_SERVICE = 'com.confio.business.optins';
  private KEYCHAIN_USERNAME = 'opt_in_statuses'; // Fixed username

  private constructor() {}

  public static getInstance(): BusinessOptInService {
    if (!BusinessOptInService.instance) {
      BusinessOptInService.instance = new BusinessOptInService();
    }
    return BusinessOptInService.instance;
  }

  /**
   * Get all opt-in statuses from Keychain
   */
  private async getAllOptInStatuses(): Promise<Record<string, any>> {
    try {
      const credentials = await Keychain.getGenericPassword({
        service: this.KEYCHAIN_SERVICE,
        username: this.KEYCHAIN_USERNAME
      });

      if (credentials && credentials.password) {
        return JSON.parse(credentials.password);
      }
      return {};
    } catch (error) {
      console.log('No opt-in statuses found in Keychain');
      return {};
    }
  }

  /**
   * Save all opt-in statuses to Keychain
   */
  private async saveAllOptInStatuses(statuses: Record<string, any>): Promise<void> {
    try {
      await Keychain.setGenericPassword(
        this.KEYCHAIN_USERNAME,
        JSON.stringify(statuses),
        {
          service: this.KEYCHAIN_SERVICE,
          username: this.KEYCHAIN_USERNAME,
          accessible: Keychain.ACCESSIBLE.WHEN_UNLOCKED
        }
      );
      console.log('Saved opt-in statuses to Keychain');
    } catch (error) {
      console.error('Error saving opt-in statuses to Keychain:', error);
    }
  }

  /**
   * Get opt-in status for a specific business from Keychain
   */
  private async getOptInStatus(businessId: string): Promise<boolean | null> {
    try {
      const allStatuses = await this.getAllOptInStatuses();
      const businessStatus = allStatuses[businessId];
      
      if (businessStatus && businessStatus.optedIn) {
        console.log(`BusinessOptInService - Found cached opt-in status for business ${businessId}: ${businessStatus.optedIn}`);
        return true;
      }
      return null; // Not found or not opted in
    } catch (error) {
      console.log('Error loading opt-in status from Keychain:', error);
      return null;
    }
  }

  /**
   * Save opt-in status for a specific business to Keychain
   */
  private async saveOptInStatus(businessId: string, optedIn: boolean): Promise<void> {
    try {
      const allStatuses = await this.getAllOptInStatuses();
      allStatuses[businessId] = {
        businessId,
        optedIn,
        timestamp: new Date().toISOString()
      };
      
      await this.saveAllOptInStatuses(allStatuses);
      console.log(`Saved opt-in status for business ${businessId}: ${optedIn}`);
    } catch (error) {
      console.error('Error saving opt-in status to Keychain:', error);
    }
  }

  /**
   * Check if current user is a business owner (not employee)
   */
  private async isBusinessOwner(): Promise<boolean> {
    try {
      const token = await authService.getToken();
      if (!token) return false;

      const decoded: any = jwtDecode(token);
      
      // Check if this is a business account
      if (decoded.account_type !== 'business') return false;
      
      // Check if user is owner
      // In JWT, business_employee_role would be set for employees
      // But 'owner' role is still considered an owner
      const role = decoded.business_employee_role;
      return !role || role === 'owner';
    } catch (error) {
      console.error('Error checking if user is business owner:', error);
      return false;
    }
  }

  /**
   * Get business ID from current JWT
   */
  private async getBusinessId(): Promise<string | null> {
    try {
      const token = await authService.getToken();
      if (!token) return null;

      const decoded: any = jwtDecode(token);
      return decoded.business_id || null;
    } catch (error) {
      console.error('Error getting business ID:', error);
      return null;
    }
  }


  /**
   * Check and handle business account opt-ins if needed
   * Should be called when:
   * 1. User is a business owner (not employee)
   * 2. Wallet is connected and ready
   * 3. About to perform a payment or other asset operation
   * 
   * @param progressCallback Optional callback to report progress messages
   * Returns true if opt-ins were handled successfully or not needed
   */
  public async checkAndHandleOptIns(progressCallback?: (message: string) => void): Promise<boolean> {
    try {
      console.log('BusinessOptInService - Checking if opt-ins are needed...');

      // 1. Check if current user is a business owner
      const isOwner = await this.isBusinessOwner();
      if (!isOwner) {
        console.log('BusinessOptInService - User is not a business owner (non-owner employee), skipping opt-in check');
        // Non-owner employees cannot opt-in business accounts as they don't have the owner's OAuth credentials
        // The business account's Algorand address was derived from the owner's OAuth sub
        return true; // Skip opt-in for non-owner employees - they can't sign for the business
      }

      // 2. Get business ID
      const businessId = await this.getBusinessId();
      if (!businessId) {
        console.log('BusinessOptInService - No business ID found');
        return false;
      }

      // 3. Check if already opted in (from Keychain cache)
      const isOptedIn = await this.getOptInStatus(businessId);
      if (isOptedIn === true) {
        console.log('BusinessOptInService - Business already opted in (from Keychain cache)');
        return true;
      }
      console.log('BusinessOptInService - Not in cache, checking with backend...');

      // 4. Check with backend if opt-ins are needed
      console.log('BusinessOptInService - Checking with backend for opt-in status...');
      progressCallback?.('Preparando factura...');

      const { data } = await apolloClient.mutate({
        mutation: CHECK_BUSINESS_OPT_IN
      });

      console.log('BusinessOptInService - Backend response:', {
        needsOptIn: data.checkBusinessOptIn.needsOptIn,
        assets: data.checkBusinessOptIn.assets,
        error: data.checkBusinessOptIn.error,
        hasTransactions: !!data.checkBusinessOptIn.optInTransactions,
        transactionsType: typeof data.checkBusinessOptIn.optInTransactions,
        transactionsLength: data.checkBusinessOptIn.optInTransactions?.length
      });
      
      // Log the actual transactions structure for debugging
      if (data.checkBusinessOptIn.optInTransactions) {
        console.log('BusinessOptInService - Transactions structure:', 
          JSON.stringify(data.checkBusinessOptIn.optInTransactions, null, 2).substring(0, 500));
      }

      if (data.checkBusinessOptIn.error) {
        const backendError: string = data.checkBusinessOptIn.error || '';
        console.error('BusinessOptInService - Backend error:', backendError);

        // If the error is about employee permissions, handle it gracefully
        if (backendError.includes('empleados') || 
            backendError.includes('employee') ||
            backendError.includes('dueño')) {
          console.log('BusinessOptInService - Employee cannot opt-in; blocking until owner configures');
          return false; // Block employees here
        }

        // If the business has no Algorand address, try to generate and push it, then retry once
        if (backendError.toLowerCase().includes('no algorand address')) {
          const isOwner = await this.isBusinessOwner();
          const accountManager = AccountManager.getInstance();
          const ctx = await accountManager.getActiveAccountContext();

          // Employees cannot fix this; block and surface owner-required message upstream
          if (!isOwner) {
            console.log('BusinessOptInService - Non-owner employee on missing address; blocking');
            return false;
          }

          if (ctx.type === 'business' && ctx.businessId) {
            try {
              progressCallback?.('Configurando cuenta...');

              // Load OAuth subject/provider to derive deterministic business address
              const { oauthStorage } = await import('./oauthStorageService');
              const oauth = await oauthStorage.getOAuthSubject();
              if (!oauth?.subject || !oauth?.provider) {
                console.warn('BusinessOptInService - Missing OAuth subject; cannot derive business address');
                return false;
              }

              const provider: 'google' | 'apple' = oauth.provider === 'apple' ? 'apple' : 'google';
              const { GOOGLE_CLIENT_IDS } = await import('../config/env');
              const GOOGLE_WEB_CLIENT_ID = GOOGLE_CLIENT_IDS.production.web;
              const iss = provider === 'google' ? 'https://accounts.google.com' : 'https://appleid.apple.com';
              const aud = provider === 'google' ? GOOGLE_WEB_CLIENT_ID : 'com.confio.app';

              const { SecureDeterministicWalletService } = await import('./secureDeterministicWallet');
              const sdw = SecureDeterministicWalletService.getInstance();
              const wallet = await sdw.createOrRestoreWallet(
                iss,
                oauth.subject,
                aud,
                provider,
                'business',
                ctx.index || 0,
                ctx.businessId
              );

              if (wallet?.address) {
                console.log('BusinessOptInService - Derived business address, updating backend');
                const upd2 = await apolloClient.mutate({
                  mutation: UPDATE_ACCOUNT_ALGORAND_ADDRESS,
                  variables: { algorandAddress: wallet.address }
                });
                const ok2 = upd2?.data?.updateAccountAlgorandAddress?.success;
                const err2 = upd2?.data?.updateAccountAlgorandAddress?.error;
                console.log('BusinessOptInService - Address update result:', { ok: ok2, error: err2 });

                // Retry the opt-in check once after updating address
                const retry = await apolloClient.mutate({ mutation: CHECK_BUSINESS_OPT_IN });
                const retryErr = retry?.data?.checkBusinessOptIn?.error as string | undefined;
                if (!retryErr) {
                  // Continue with the now-updated response object
                  data.checkBusinessOptIn = retry.data.checkBusinessOptIn;
                  console.log('BusinessOptInService - Retry succeeded after address update');
                } else {
                  console.warn('BusinessOptInService - Retry still failing:', retryErr);
                  return false;
                }
              } else {
                console.warn('BusinessOptInService - Could not derive business address');
                return false;
              }
            } catch (deriveError) {
              console.error('BusinessOptInService - Error deriving/updating business address:', deriveError);
              return false;
            }
          } else {
            console.warn('BusinessOptInService - Not in a business context while handling address error');
            return false;
          }
        } else {
          // Unknown backend error; block to avoid partial/incorrect setup
          return false;
        }
      }

      if (!data.checkBusinessOptIn.needsOptIn) {
        console.log('BusinessOptInService - No opt-ins needed');
        await this.saveOptInStatus(businessId, true);
        return true;
      }

      // 5. Opt-ins are needed - but double-check we're not an employee
      // This should never happen because server checks, but be defensive
      const doubleCheckOwner = await this.isBusinessOwner();
      if (!doubleCheckOwner) {
        console.error('BusinessOptInService - CRITICAL: Employee reached opt-in signing stage! This should not happen.');
        progressCallback?.('Error: Solo el dueño puede configurar la cuenta');
        return false;
      }
      
      const { assets, optInTransactions } = data.checkBusinessOptIn;
      console.log('BusinessOptInService - Opt-ins needed for assets:', assets);
      
      progressCallback?.('Configurando cuenta...');

      if (!optInTransactions) {
        console.error('BusinessOptInService - No opt-in transactions provided');
        return false;
      }

      // Parse the transactions if they come as a JSON string (may be double-encoded)
      let transactions;
      try {
        if (typeof optInTransactions === 'string') {
          // First parse
          let parsed = JSON.parse(optInTransactions);
          console.log('BusinessOptInService - First parse result type:', typeof parsed);
          
          // If it's still a string, parse again (double-encoded)
          if (typeof parsed === 'string') {
            console.log('BusinessOptInService - Double-encoded JSON detected, parsing again...');
            transactions = JSON.parse(parsed);
          } else {
            transactions = parsed;
          }
          console.log('BusinessOptInService - Final parsed transactions:', transactions?.length);
        } else {
          transactions = optInTransactions;
          console.log('BusinessOptInService - Using transactions as-is:', transactions?.length);
        }
        
        // Debug: Log the parsed structure
        console.log('BusinessOptInService - Transactions type:', typeof transactions);
        console.log('BusinessOptInService - Is array?:', Array.isArray(transactions));
        if (Array.isArray(transactions) && transactions.length > 0) {
          console.log('BusinessOptInService - First transaction:', JSON.stringify(transactions[0], null, 2).substring(0, 200));
        }
      } catch (error) {
        console.error('BusinessOptInService - Failed to parse transactions:', error);
        console.error('BusinessOptInService - Raw optInTransactions:', optInTransactions);
        return false;
      }

      if (!transactions || !Array.isArray(transactions) || transactions.length === 0) {
        console.error('BusinessOptInService - Invalid or empty transactions array');
        console.error('BusinessOptInService - Transactions value:', transactions);
        return false;
      }

      // 6. For business accounts, we need to handle opt-ins differently
      // Business accounts don't have currentAccount set in algorandService
      // But the signing will work because signTransactionBytes gets context from AuthService
      
      const accountManager = AccountManager.getInstance();
      const activeAccount = await accountManager.getActiveAccountContext();
      
      if (!activeAccount || activeAccount.type !== 'business') {
        console.error('BusinessOptInService - No active business account');
        return false;
      }

      // Process opt-ins - we'll sign the transactions directly
      console.log('BusinessOptInService - Processing opt-in transactions...');
      progressCallback?.('Procesando...');
      
      // Since processSponsoredOptIn checks for currentAccount which doesn't exist for business,
      // we need to process the transactions directly here
      try {
        // Find the sponsor transaction
        const sponsorTxnData = transactions.find(t => t.type === 'sponsor' && t.signed === true);
        
        if (!sponsorTxnData) {
          console.error('BusinessOptInService - No sponsor transaction found');
          return false;
        }
        
        // Get opt-in transactions
        const optInTransactions = transactions.filter(t => t.type === 'opt-in');
        console.log(`BusinessOptInService - Found ${optInTransactions.length} opt-in transactions to sign`);
        
        // Start group with the sponsor transaction FIRST to fund fees/MBR
        // Then append each signed opt-in transaction
        const signedTransactions: string[] = [];
        
        for (const optInData of optInTransactions) {
          try {
            const assetName = optInData.assetName || 'Unknown';
            console.log(`BusinessOptInService - Signing opt-in for ${assetName}`);
            
            // Decode and sign the transaction
            const userTxnBytes = Uint8Array.from(Buffer.from(optInData.transaction, 'base64'));
            const signedUserTxn = await algorandService.signTransactionBytes(userTxnBytes);
            const signedUserTxnB64 = Buffer.from(signedUserTxn).toString('base64');
            
            signedTransactions.push(signedUserTxnB64);
          } catch (error) {
            console.error(`BusinessOptInService - Error signing opt-in:`, error);
            return false;
          }
        }
        
        // Add the pre-signed sponsor transaction at the BEGINNING
        console.log('BusinessOptInService - Sponsor transaction type:', typeof sponsorTxnData.transaction);
        console.log('BusinessOptInService - Sponsor transaction length:', sponsorTxnData.transaction?.length);
        console.log('BusinessOptInService - Sponsor transaction first 100 chars:', sponsorTxnData.transaction?.substring(0, 100));
        
        // Ensure the sponsor transaction is properly padded
        let sponsorTxn = sponsorTxnData.transaction;
        if (typeof sponsorTxn === 'string') {
          // Add base64 padding if needed
          const padding = sponsorTxn.length % 4;
          if (padding) {
            sponsorTxn += '='.repeat(4 - padding);
            console.log(`BusinessOptInService - Added ${4 - padding} padding chars to sponsor transaction`);
          }
          
          // Validate it's valid base64
          try {
            const decoded = Buffer.from(sponsorTxn, 'base64');
            console.log(`BusinessOptInService - Sponsor transaction decodes to ${decoded.length} bytes`);
          } catch (e) {
            console.error('BusinessOptInService - Invalid base64 in sponsor transaction:', e);
          }
        }
        
        // Place sponsor first so funding lands before opt-ins are validated
        signedTransactions.unshift(sponsorTxn);
        
        // Submit the group transaction
        // For group transactions with multiple opt-ins, we need a different approach
        console.log('BusinessOptInService - Submitting group transaction...');
        console.log('BusinessOptInService - Total transactions:', signedTransactions.length);
        console.log('BusinessOptInService - Transaction types:', signedTransactions.map(t => typeof t));
        
        // Import the mutation for submitting business opt-in group
        const SUBMIT_BUSINESS_OPT_IN_GROUP = gql`
          mutation SubmitBusinessOptInGroup($signedTransactions: JSONString!) {
            submitBusinessOptInGroup(signedTransactions: $signedTransactions) {
              success
              error
              transactionId
              confirmedRound
            }
          }
        `;
        
        const { data: submitData } = await apolloClient.mutate({
          mutation: SUBMIT_BUSINESS_OPT_IN_GROUP,
          variables: {
            signedTransactions: JSON.stringify(signedTransactions)
          }
        });
        
        if (!submitData.submitBusinessOptInGroup.success) {
          console.error('BusinessOptInService - Failed to submit group:', submitData.submitBusinessOptInGroup.error);
          return false;
        }
        
        console.log('BusinessOptInService - Group transaction submitted successfully');
        
        // 7. Notify backend of completion
        progressCallback?.('Casi listo...');
        
        const txId = submitData.submitBusinessOptInGroup.transactionId || 'group-opt-in';
        await apolloClient.mutate({
          mutation: COMPLETE_BUSINESS_OPT_IN,
          variables: { txIds: [txId] }
        });

        // 8. Save the successful opt-in to Keychain
        await this.saveOptInStatus(businessId, true);

        console.log('BusinessOptInService - All opt-ins completed successfully');
        progressCallback?.('¡Listo!');
        
        // Brief delay to show success message
        await new Promise(resolve => setTimeout(resolve, 500));
        
        return true;
        
      } catch (error) {
        console.error('BusinessOptInService - Error processing opt-ins:', error);
        progressCallback?.('Error al procesar. Por favor intenta de nuevo.');
        return false;
      }

    } catch (error) {
      console.error('BusinessOptInService - Error during opt-in process:', error);
      return false;
    }
  }

  /**
   * Clear opt-in status for a specific business or all businesses
   */
  public async clearOptInStatus(businessId?: string): Promise<void> {
    try {
      if (businessId) {
        // Clear specific business
        const allStatuses = await this.getAllOptInStatuses();
        delete allStatuses[businessId];
        await this.saveAllOptInStatuses(allStatuses);
        console.log(`Cleared opt-in status for business ${businessId}`);
      } else {
        // Clear all
        await Keychain.resetGenericPassword({
          service: this.KEYCHAIN_SERVICE,
          username: this.KEYCHAIN_USERNAME
        });
        console.log('Cleared all business opt-in statuses');
      }
    } catch (error) {
      console.error('Error clearing opt-in status:', error);
    }
  }
}

// Export singleton instance
const businessOptInService = BusinessOptInService.getInstance();
export default businessOptInService;
