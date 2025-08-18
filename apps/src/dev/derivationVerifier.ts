import { SecureDeterministicWalletService } from '../services/secureDeterministicWallet';
import { AccountManager } from '../utils/accountManager';
import authService from '../services/authService';
import { oauthStorage } from '../services/oauthStorageService';
import { GOOGLE_CLIENT_IDS } from '../config/env';

export interface DerivationVerifyResult {
  success: boolean;
  context: {
    type: 'personal' | 'business';
    index: number;
    businessId?: string;
  };
  pepperPresent: boolean;
  storedAddress?: string | null;
  derivedAddress?: string;
  matches: boolean;
  notes?: string[];
}

/**
 * Developer-only helper to verify pepper-based derivation for the active account context.
 * Logs a concise PASS/FAIL with details and returns a structured result.
 */
export async function verifyDerivationForActiveContext(): Promise<DerivationVerifyResult> {
  const notes: string[] = [];
  try {
    const accountContext = await AccountManager.getInstance().getActiveAccountContext();
    notes.push(`Active context: ${accountContext.type}_${accountContext.businessId ?? ''}_${accountContext.index}`);

    // Get pepper presence (will require valid JWT for the current context)
    const sdw = SecureDeterministicWalletService.getInstance();
    const { pepper } = await sdw.getDerivationPepper();
    const pepperPresent = !!pepper;
    if (!pepperPresent) notes.push('No derivation pepper returned (check JWT context/network)');

    // Get stored address managed by AuthService
    const storedAddress = await authService.getAlgorandAddress();
    if (storedAddress) {
      notes.push(`Stored address: ${storedAddress}`);
    } else {
      notes.push('No stored address found for this context');
    }

    // Derive fresh using OAuth claims + pepper (will use cache if available internally)
    const oauthData = await oauthStorage.getOAuthSubject();
    if (!oauthData || !oauthData.subject) {
      notes.push('Missing OAuth subject; cannot derive');
      return {
        success: false,
        context: accountContext as any,
        pepperPresent,
        storedAddress,
        derivedAddress: undefined,
        matches: false,
        notes,
      };
    }

    const provider = oauthData.provider;
    const iss = provider === 'google' ? 'https://accounts.google.com' : 'https://appleid.apple.com';
    const aud = provider === 'google' ? GOOGLE_CLIENT_IDS.production.web : 'com.confio.app';

    const wallet = await sdw.createOrRestoreWallet(
      iss,
      oauthData.subject,
      aud,
      provider,
      accountContext.type,
      accountContext.index,
      accountContext.businessId
    );

    const derivedAddress = wallet.address;
    notes.push(`Derived address: ${derivedAddress}`);

    const matches = !!storedAddress && storedAddress === derivedAddress;
    const success = pepperPresent && matches;

    console.log('[DerivationVerify] Result:', {
      context: accountContext,
      pepperPresent,
      storedAddress,
      derivedAddress,
      matches,
      success,
    });

    if (success) {
      console.log('✅ [DerivationVerify] PASS: Derived address matches stored and pepper present');
    } else {
      console.warn('❌ [DerivationVerify] FAIL: See details above');
    }

    return {
      success,
      context: accountContext as any,
      pepperPresent,
      storedAddress,
      derivedAddress,
      matches,
      notes,
    };
  } catch (error) {
    console.error('[DerivationVerify] Error:', error);
    return {
      success: false,
      context: { type: 'personal', index: 0 },
      pepperPresent: false,
      storedAddress: undefined,
      derivedAddress: undefined,
      matches: false,
      notes: ['Unexpected error: ' + (error as any)?.message],
    } as DerivationVerifyResult;
  }
}

// Auto-expose for dev builds for quick access from console/Flipper
if (__DEV__) {
  try {
    (global as any).ConfioDev = (global as any).ConfioDev || {};
    (global as any).ConfioDev.verifyDerivation = verifyDerivationForActiveContext;
    console.log('[DerivationVerify] Dev hook attached: ConfioDev.verifyDerivation()');
  } catch {
    // ignore
  }
}

