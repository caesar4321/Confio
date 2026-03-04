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
      console.log('[CUSDAppOptInService] Starting sponsored app opt-in flow');

      // Preflight: check if deterministic wallet matches (for V2 users)
      // We do NOT return early if it fails, because V1 legacy users will legitimately have
      // a different address than the derived V2 address. 
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
            console.warn('[CUSDAppOptInService] Derived V2 address does not match server address. This is expected if the user is a V1 legacy user.');
            // Do NOT return { success: true } here, as that aborts the opt-in entirely.
          }
        }
      } catch (prefError) {
        console.warn('[CUSDAppOptInService] Preflight check failed; continuing anyway:', prefError);
      }

      // Step 1: Generate the sponsored opt-in transaction from server
      const optInResult = await apolloClient.mutate({
        mutation: GENERATE_APP_OPT_IN,
        variables: (appId === undefined || appId === null)
          ? {}
          : { appId: String(appId) } // Will default to cUSD app if not provided
      });

      const optInData = optInResult.data?.generateAppOptInTransaction;
      console.log('[CUSDAppOptInService] Opt-in mutation result:', optInData);

      if (optInData?.alreadyOptedIn) {
        console.log('[CUSDAppOptInService] Already opted into app');
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

      console.log('[CUSDAppOptInService] Transactions received:',
        'user:', userTransaction ? 'present' : 'missing',
        'sponsor:', sponsorTransaction ? 'present' : 'missing');

      if (!userTransaction) {
        console.error('[CUSDAppOptInService] Missing user transaction data. Full optInData:', optInData);
        return {
          success: false,
          error: 'Missing user transaction data'
        };
      }

      // Check if this is a sponsored transaction or solo
      const isSponsored = !!sponsorTransaction;

      // Step 2: Sign the user transaction
      // Use algorandService as it correctly routes to either V1 keychain wallet or V2 deterministic wallet
      console.log('[CUSDAppOptInService] Signing user transaction...');
      const algorandService = (await import('../services/algorandService')).default;
      const userTxnBytes = Buffer.from(userTransaction, 'base64');
      const signedLocalTxBytes = await algorandService.signTransactionBytes(new Uint8Array(userTxnBytes));
      const signedUserTxnB64 = Buffer.from(signedLocalTxBytes).toString('base64');

      let executeResult;

      if (isSponsored) {
        console.log('[CUSDAppOptInService] User transaction signed, submitting sponsored group...');

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
        console.log('[CUSDAppOptInService] Submitting solo transaction...');

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
        console.log('[CUSDAppOptInService] App opt-in successful! Transaction ID:',
          executeResult.data.submitSponsoredGroup.transactionId);
        console.log('[CUSDAppOptInService] Fees saved:',
          executeResult.data.submitSponsoredGroup.feesSaved, 'ALGO');
        return {
          success: true
        };
      } else {
        const errMsg: string = executeResult.data?.submitSponsoredGroup?.error || '';
        console.error('[CUSDAppOptInService] Failed to submit sponsored group:', errMsg);
        // Idempotency: treat "already opted in" as success
        if (/already\s+opted\s+in/i.test(errMsg)) {
          console.log('[CUSDAppOptInService] Treating "already opted in" as success');
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
