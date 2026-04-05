/**
 * Service for handling cUSD application opt-in with sponsored transactions
 */
import { Buffer } from 'buffer';
import { secureDeterministicWallet } from './secureDeterministicWallet';
import { apolloClient } from '../apollo/client';
import { GENERATE_APP_OPT_IN, SUBMIT_SPONSORED_GROUP } from '../apollo/mutations/cusdAppOptIn';

class CUSDAppOptInService {
  /**
   * Check if user needs to opt into cUSD app and handle the opt-in flow with sponsored transactions
   */
  async handleAppOptIn(account?: any, appId?: number | string): Promise<{ success: boolean; error?: string }> {
    try {
      // Preflight: ensure the derived wallet matches the backend address; otherwise skip silently
      try {
        const { oauthStorage } = await import('../services/oauthStorageService');
        const oauth = await oauthStorage.getOAuthSubject();
        if (oauth?.subject && oauth?.provider) {
          const provider: 'google' | 'apple' = oauth.provider === 'apple' ? 'apple' : 'google';
          const { GOOGLE_CLIENT_IDS } = await import('../config/env');
          const GOOGLE_WEB_CLIENT_ID = GOOGLE_CLIENT_IDS.production.web;
          const iss = provider === 'google' ? 'https://accounts.google.com' : 'https://appleid.apple.com';
          const aud = provider === 'google' ? GOOGLE_WEB_CLIENT_ID : 'com.confio.app';
          const wallet = await secureDeterministicWallet.createOrRestoreWallet(
            iss,
            oauth.subject,
            aud,
            provider,
            account?.type || 'personal',
            account?.index || 0,
            account?.id?.startsWith('business_') ? (account.id.split('_')[1] || undefined) : undefined
          );
          const serverAddr = account?.algorandAddress;
          if (serverAddr && wallet?.address && wallet.address !== serverAddr) {
            return { 
              success: false, 
              error: 'No se pudo verificar la billetera. Por favor, asegúrate de haber restaurado tu copia de seguridad.' 
            };
          }
        }
      } catch (prefError) {
      }

      // Step 1: Generate the sponsored opt-in transaction from server
      const optInResult = await apolloClient.mutate({
        mutation: GENERATE_APP_OPT_IN,
        variables: (appId === undefined || appId === null)
          ? {}
          : { appId: String(appId) } // Will default to cUSD app if not provided
      });

      const optInData = optInResult.data?.generateAppOptInTransaction;
      if (optInData?.alreadyOptedIn) {
        return { success: true };
      }

      if (!optInData?.success) {
        console.error('[CUSDAppOptInService] Failed to generate opt-in transaction:',
          optInData?.error);
        return {
          success: false,
          error: optInData?.error || 'Failed to generate opt-in transaction'
        };
      }

      const userTransaction = optInData.userTransaction;
      const sponsorTransaction = optInData.sponsorTransaction;
      if (!userTransaction) {
        console.error('[CUSDAppOptInService] Missing user transaction data. Full optInData:', optInData);
        return {
          success: false,
          error: 'Missing user transaction data'
        };
      }

      // Check if this is a sponsored transaction or solo
      const isSponsored = !!sponsorTransaction;

      if (isSponsored) {
        // Ensure the signer scope matches the active account (business) before signing
        try {
          const { oauthStorage } = await import('../services/oauthStorageService');
          const oauth = await oauthStorage.getOAuthSubject();
          if (oauth?.subject && oauth?.provider) {
            const provider: 'google' | 'apple' = oauth.provider === 'apple' ? 'apple' : 'google';
            const { GOOGLE_CLIENT_IDS } = await import('../config/env');
            const GOOGLE_WEB_CLIENT_ID = GOOGLE_CLIENT_IDS.production.web;
            const iss = provider === 'google' ? 'https://accounts.google.com' : 'https://appleid.apple.com';
            const aud = provider === 'google' ? GOOGLE_WEB_CLIENT_ID : 'com.confio.app';
            await secureDeterministicWallet.createOrRestoreWallet(
              iss,
              oauth.subject,
              aud,
              provider,
              // Use AccountContext from AccountManager/AuthService when available
              account?.type || 'business',
              account?.index ?? 0,
              account?.businessId || (account?.id?.startsWith('business_') ? (account.id.split('_')[1] || undefined) : undefined)
            );
          }
        } catch (scopeErr) {
        }      } else {
      }

      // Step 2: Sign the user transaction
      const userTxnBytes = Buffer.from(userTransaction, 'base64');
      const signedUserTxn = await secureDeterministicWallet.signTransaction(userTxnBytes);
      const signedUserTxnB64 = Buffer.from(signedUserTxn).toString('base64');

      let executeResult;

      if (isSponsored) {
        // Step 3a: Submit the signed sponsored group
        // Sponsor is always first - no need for a flag

        executeResult = await apolloClient.mutate({
          mutation: SUBMIT_SPONSORED_GROUP,
          variables: {
            signedUserTxn: signedUserTxnB64,
            signedSponsorTxn: sponsorTransaction
            // Sponsor always goes first for proper fee payment
          }
        });
      } else {
        // Step 3b: Submit the solo signed transaction
        // We'll need to create a simple submission mutation for this
        // For now, use the sponsored group mutation with only the user transaction
        executeResult = await apolloClient.mutate({
          mutation: SUBMIT_SPONSORED_GROUP,
          variables: {
            signedUserTxn: signedUserTxnB64,
            signedSponsorTxn: null  // No sponsor for solo transaction
          }
        });
      }

      if (executeResult.data?.submitSponsoredGroup?.success) {
        return {
          success: true
        };
      } else {
        const errMsg: string = executeResult.data?.submitSponsoredGroup?.error || '';
        console.error('[CUSDAppOptInService] Failed to submit sponsored group:', errMsg);
        // Idempotency: treat "already opted in" as success
        if (/already\s+opted\s+in/i.test(errMsg)) {
          return { success: true };
        }
        return { success: false, error: errMsg || 'Failed to submit opt-in transaction' };
      }

    } catch (error) {
      console.error('[CUSDAppOptInService] Error during app opt-in:', error);
      return {
        success: false,
        error: error.message || 'Failed to opt into cUSD application'
      };
    }
  }
}

export const cusdAppOptInService = new CUSDAppOptInService();
