import { GoogleSignin, User } from '@react-native-google-signin/google-signin';
import { jwtDecode } from 'jwt-decode';
import * as Keychain from 'react-native-keychain';
import { GOOGLE_CLIENT_IDS, API_URL } from '../config/env';
import auth from '@react-native-firebase/auth';
import { Platform } from 'react-native';
// Using Web3Auth mutations from mutations.ts
import { apolloClient, AUTH_KEYCHAIN_SERVICE, AUTH_KEYCHAIN_USERNAME } from '../apollo/client';
import { gql } from '@apollo/client';
import { Buffer } from 'buffer';
import { sha256 } from '@noble/hashes/sha256';
import { base64ToBytes, bytesToBase64, stringToUtf8Bytes, bufferToHex } from '../utils/encoding';
import { ApolloClient } from '@apollo/client';
import { AccountManager, AccountContext } from '../utils/accountManager';
import { DeviceFingerprint } from '../utils/deviceFingerprint';
import algorandService from './algorandService';
// Import OAuth storage - handle gracefully if module not found
let oauthStorage: any = null;
try {
  const module = require('./oauthStorageService');
  oauthStorage = module.oauthStorage;
} catch (error) {
  console.warn('OAuth storage service not available:', error);
}

// Debug logging for environment variables
console.log('Environment variables loaded:');
console.log('GOOGLE_CLIENT_IDS:', GOOGLE_CLIENT_IDS);
console.log('API_URL:', API_URL);

// Type for storing JWT tokens
type TokenStorage = {
  accessToken: string;
  refreshToken: string;
};

// Type for decoded JWT payloads
type CustomJwtPayload = {
  type: string;
  [key: string]: any;
};


export class AccountDeactivatedError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'AccountDeactivatedError';
  }
}


export class AuthService {
  private static instance: AuthService;
  private auth = auth();
  private firebaseIsInitialized = false;
  private apolloClient: ApolloClient<any> | null = null;
  private token: string | null = null;

  private constructor() {
  }

  public static getInstance(): AuthService {
    if (!AuthService.instance) {
      AuthService.instance = new AuthService();
    }
    return AuthService.instance;
  }

  public async initialize(): Promise<void> {
    try {
      console.log('AuthService - initialize() called');

      // Only initialize Firebase once
      if (!this.firebaseIsInitialized) {
        console.log('AuthService - Initializing Firebase');
        await this.initializeFirebase();
        this.firebaseIsInitialized = true;
        console.log('AuthService - Firebase initialized');
      } else {
        console.log('AuthService - Firebase already initialized');
      }


      // Check if we need to initialize a default account
      console.log('AuthService - Checking for default account initialization');
      await this.initializeDefaultAccountIfNeeded();
      console.log('AuthService - Default account check completed');
    } catch (error) {
      console.error('AuthService - Failed to initialize:', error);
      throw error;
    }
  }

  private async initializeFirebase() {
    try {
      await this.configureGoogleSignIn();
    } catch (error) {
      console.error('Firebase initialization error:', error);
      throw error;
    }
  }

  private async configureGoogleSignIn(enableDrive: boolean = false) {
    // perfLog is not defined here, it's defined within signInWithGoogle.
    // If perfLog is needed here, it should be passed as an argument or defined globally.
    // For now, removing the perfLog call as it would cause a lint error.
    // perfLog('Before GoogleSignin.configure()');
    try {
      // Build scopes dynamically based on user backup preference
      // NOTE: post_refund_status scope was removed as it was causing ApiException 12500
      const scopes = [
        'email',
        'profile',
      ];

      // Only add Drive scope if user consented to backup
      if (enableDrive) {
        scopes.push('https://www.googleapis.com/auth/drive.appdata');
        console.log('[AuthService] Drive scope ADDED to configuration');
      } else {
        console.log('[AuthService] Drive scope SKIPPED (user rejected backup)');
      }

      const clientIds = GOOGLE_CLIENT_IDS[__DEV__ ? 'development' : 'production'];

      const config: any = {
        scopes: scopes,
        webClientId: clientIds.web, // ALWAYS use the Web Client ID for Backend Verification
        offlineAccess: true,
        forceCodeForRefreshToken: true,
      };

      // Only add optional params if they are defined/needed
      // Empty strings can cause 'A non-recoverable sign in failure occurred' (12500) on Android
      // config.hostedDomain = ''; 
      // config.loginHint = '';
      // config.accountName = '';

      await GoogleSignin.configure(config);
      console.log('Google Sign-In configuration successful');
    } catch (error) {
      console.error('Error configuring Google Sign-In:', error);
      throw error;
    }
  }

  /**
   * Check if the user has granted Google Drive backup permission (scope).
   */
  async checkDriveBackupEnabled(): Promise<boolean> {
    try {
      const tokens = await GoogleSignin.getTokens();
      // On Android, scopes might not be directly inspectable from tokens in all versions,
      // but let's check current user scopes if available or assume based on successful configure.
      // A more reliable way is to check the currentUser object from GoogleSignin
      const currentUser = await GoogleSignin.getCurrentUser();
      if (currentUser && currentUser.scopes) {
        return currentUser.scopes.includes('https://www.googleapis.com/auth/drive.appdata');
      }
      return false;
    } catch (error) {
      console.warn('[AuthService] Failed to check Drive status', error);
      return false;
    }
  }

  /**
   * Get a Google Drive access token WITHOUT signing into Firebase.
   * This is used when an Apple Sign-In user wants to backup to Google Drive.
   * It gets the Drive access token but preserves the existing user's JWT.
   */
  async getDriveAccessTokenOnly(): Promise<string | null> {
    try {
      console.log('[AuthService] Getting Drive access token only (preserving current user)...');

      // Configure Google Sign-In with Drive scope
      await this.configureGoogleSignIn(true);

      // Check Play Services
      await GoogleSignin.hasPlayServices({ showPlayServicesUpdateDialog: true });

      // Sign in with Google to get Drive access (this doesn't affect Firebase/backend auth)
      await GoogleSignin.signIn();

      // Get the access token for Drive
      const { accessToken } = await GoogleSignin.getTokens();

      console.log('[AuthService] Got Drive access token:', accessToken ? 'obtained' : 'failed');

      // Sign out from Google to clean up (we only needed the token)
      // This does NOT affect our Firebase auth or backend JWT
      try {
        await GoogleSignin.signOut();
      } catch (e) {
        // Ignore sign out errors
      }

      return accessToken || null;
    } catch (error) {
      console.error('[AuthService] Failed to get Drive access token:', error);
      return null;
    }
  }

  /**
   * Enable Google Drive backup for the CURRENT user (works for Apple Sign-In users too).
   * This gets a Drive access token, syncs the master secret to Drive, and reports the backup
   * status to the CURRENT user (not a new Google user).
   * 
   * @param forceBackup - If true, skip the existing backup check and proceed
   * @returns Object with success, existingBackups info, or error
   */
  async enableDriveBackup(forceBackup: boolean = false): Promise<{
    success: boolean;
    existingBackups?: {
      hasBackup: boolean;
      entries: any[];
      hasLegacy: boolean;
      hasCrossPlatformBackup: boolean;
      crossPlatformEntries: any[];
      entriesToShow?: any[]; // All entries to display in modal
    };
    error?: string;
  }> {
    try {
      console.log('[AuthService] Enabling Drive backup for current user...');

      // Get Drive access token without changing current user
      const accessToken = await this.getDriveAccessTokenOnly();

      if (!accessToken) {
        console.error('[AuthService] Failed to get Drive access token');
        return { success: false, error: 'No se pudo obtener acceso a Google Drive' };
      }

      // Get the stored OAuth subject (from Apple or Google sign-in)
      const { oauthStorage } = await import('./oauthStorageService');
      const oauthData = await oauthStorage.getOAuthSubject();
      if (!oauthData?.subject) {
        console.error('[AuthService] No OAuth subject found for backup');
        return { success: false, error: 'No se encontró información de la cuenta' };
      }

      // Check for existing backups (unless forceBackup is true)
      // Show modal if there are multiple entries OR any cross-platform backup
      if (!forceBackup) {
        const { checkExistingBackups } = await import('./secureDeterministicWallet');
        const existingBackups = await checkExistingBackups(accessToken, oauthData.subject);

        // Show modal if:
        // 1. Multiple backup entries exist (user can choose which to restore)
        // 2. OR any cross-platform backup exists
        const hasMultipleEntries = existingBackups.entries.length > 1;
        if (existingBackups.hasCrossPlatformBackup || hasMultipleEntries) {
          console.log('[AuthService] Existing backups found, showing modal:', {
            totalEntries: existingBackups.entries.length,
            hasCrossPlatform: existingBackups.hasCrossPlatformBackup
          });
          // Return all entries so user can choose any of them
          return {
            success: false,
            existingBackups: {
              ...existingBackups,
              // Use all entries for the modal, not just cross-platform
              entriesToShow: existingBackups.entries
            }
          };
        }
        // Single same-platform backup proceeds automatically (no prompt needed)
      }

      // Sync to Drive using the access token
      const { getOrCreateMasterSecret, reportBackupStatus } = await import('./secureDeterministicWallet');
      await getOrCreateMasterSecret(oauthData.subject, accessToken);
      console.log('[AuthService] Master secret synced to Drive');

      // Report backup status for the CURRENT user (uses existing JWT)
      await reportBackupStatus('google_drive');
      console.log('[AuthService] Backup status reported for current user');

      return { success: true };
    } catch (error: any) {
      console.error('[AuthService] Failed to enable Drive backup:', error);
      return { success: false, error: error?.message || 'Error desconocido' };
    }
  }

  /**
   * Restore wallet from a specific backup in Google Drive.
   * This OVERWRITES the current local wallet with the backup.
   * 
   * @param walletId - The wallet ID to restore (from manifest entry)
   * @param lastBackupAt - Optional timestamp to help identify file if ID is null
   * @returns Object with success flag or error
   */
  async restoreFromDriveBackup(walletId?: string, lastBackupAt?: string): Promise<{ success: boolean; error?: string }> {
    try {
      console.log('[AuthService] Restoring from Drive backup:', walletId, 'timestamp:', lastBackupAt);

      // Get Drive access token
      const accessToken = await this.getDriveAccessTokenOnly();
      if (!accessToken) {
        return { success: false, error: 'No se pudo obtener acceso a Google Drive' };
      }

      // Get OAuth subject
      const { oauthStorage } = await import('./oauthStorageService');
      const oauthData = await oauthStorage.getOAuthSubject();
      if (!oauthData?.subject) {
        return { success: false, error: 'No se encontró información de la cuenta' };
      }

      // Restore from backup
      const { restoreFromBackup } = await import('./secureDeterministicWallet');
      const success = await restoreFromBackup(accessToken, walletId, oauthData.subject, lastBackupAt);

      if (success) {
        console.log('[AuthService] Wallet restored successfully');

        // AUTO-RELOAD: Force the wallet service to refresh its memory cache
        // This prevents the user from needing to restart the app or re-login
        try {
          // 4. Update Local Address Cache & Backend
          // We use computeAndStoreAlgorandAddress because it:
          // A) Re-derives the wallet (updating in-memory seeds)
          // B) Updates the Backend (UPDATE_ACCOUNT_ALGORAND_ADDRESS)
          // C) KEYCHAIN CACHE: Updates the stored address cache (Fixes DepositScreen stale data)
          const { AccountManager } = await import('../utils/accountManager');
          const accountManager = AccountManager.getInstance();
          const context = await accountManager.getActiveAccountContext();

          console.log('[AuthService] Restore complete. auto-refreshing address cache for context:', context);
          await this.computeAndStoreAlgorandAddress(context);

          console.log('[AuthService] Wallet restore & address sync complete.');
        } catch (reloadErr) {
          console.warn('[AuthService] Failed to auto-reload wallet state:', reloadErr);
          // Non-fatal, user might just need to restart if this fails
        }

        // Report backup status to track in dashboard
        try {
          const { reportBackupStatus } = await import('./secureDeterministicWallet');
          await reportBackupStatus('google_drive');
          console.log('[AuthService] Backup status reported for restored user');
        } catch (reportErr) {
          console.warn('[AuthService] Failed to report backup status:', reportErr);
        }

        return { success: true };
      } else {
        return { success: false, error: 'No se pudo restaurar la billetera' };
      }
    } catch (error: any) {
      console.error('[AuthService] Failed to restore from Drive backup:', error);
      return { success: false, error: error?.message || 'Error desconocido' };
    }
  }

  async signInWithGoogle(onProgress?: (message: string) => void, enableDrive: boolean = true) {
    const startTime = Date.now();
    const perfLog = (step: string) => {
      console.log(`[PERF] ${step}: ${Date.now() - startTime}ms`);
    };

    try {
      console.log(`Starting Google Sign-In process (Drive Scope: ${enableDrive})...`);

      // Configure with appropriate scopes based on user's backup choice
      // NOTE: This is safe now that we removed the post_refund_status scope
      await this.configureGoogleSignIn(enableDrive);

      perfLog('Start');
      // Don't show progress during Google modal



      // 1) Sign in with Google first
      console.log('Checking Play Services...');
      perfLog('Before Play Services check');
      await GoogleSignin.hasPlayServices();
      perfLog('After Play Services check');
      console.log('Play Services check passed');

      console.log('Attempting Google Sign-In...');
      perfLog('Before GoogleSignin.signIn()');
      const userInfo = await GoogleSignin.signIn();
      perfLog('After GoogleSignin.signIn()');
      console.log('Google Sign-In response received');

      if (!userInfo) {
        throw new Error('No user info returned from Google Sign-In');
      }

      // 2) Get the ID token after successful sign-in
      perfLog('Google Sign-In complete');
      // NOW show loading - Google modal is closed
      onProgress?.('Verificando tu cuenta...');
      console.log('Getting Google ID/Access tokens...');
      const { idToken, accessToken } = await GoogleSignin.getTokens();
      console.log('Got tokens:', {
        hasIdToken: !!idToken,
        hasAccessToken: !!accessToken
      });
      perfLog('Got Google ID/Access token');

      // Use the accessToken for Drive sync if user chose "Accept"
      const driveAccessToken = enableDrive ? accessToken : undefined;
      console.log(`[AuthService] enableDrive=${enableDrive}, driveAccessToken=${driveAccessToken ? 'obtained' : 'skipped'}`);

      // Debug: Check what's in the userInfo from Google Sign-In
      console.log('[AuthService] Google Sign-In userInfo - parsed:', {
        type: userInfo?.type,
        userId: userInfo?.data?.user?.id,
        userEmail: userInfo?.data?.user?.email,
        userName: userInfo?.data?.user?.name,
        idToken: userInfo?.data?.idToken ? '***REDACTED***' : undefined,
        serverAuthCode: userInfo?.data?.serverAuthCode ? '***REDACTED***' : undefined,
      });

      if (!idToken) {
        throw new Error('No ID token received from Google Sign-In');
      }

      // 3) Sign in with Firebase using the Google credential
      onProgress?.('Autenticando tu cuenta...');
      console.log('Creating Firebase credential...');
      const firebaseCred = auth.GoogleAuthProvider.credential(idToken);
      console.log('Signing in with Firebase...');
      const { user } = await this.auth.signInWithCredential(firebaseCred);
      console.log('Firebase sign-in response:', user ? 'User received' : 'No user');
      perfLog('Firebase sign-in complete');

      if (!user) {
        throw new Error('No user returned from Firebase sign-in');
      }

      console.log('Getting Firebase ID token...');
      const firebaseToken = await user.getIdToken();
      console.log('Firebase token received');

      // 4) Collect device fingerprint
      console.log('Collecting device fingerprint...');
      let deviceFingerprint = null;
      try {
        deviceFingerprint = await DeviceFingerprint.generateFingerprint();
        console.log('Device fingerprint collected successfully');
      } catch (error) {
        console.error('Error collecting device fingerprint:', error);
        // Continue without fingerprint rather than failing authentication
      }

      // 5) Generate/Sync Algorand wallet (V2 Master Secret)
      // CRITICAL: This ensures roaming works. We fetch from Drive (Android) or Keychain (iOS).
      console.log('Ensuring Master Secret exists (Syncing if needed)...');
      perfLog('Start Master Secret Sync');

      const googleSubject = userInfo?.data?.user?.id;
      if (!googleSubject) {
        throw new Error('No OAuth subject found in Google sign-in response.');
      }

      let driveSyncSucceeded = false;
      try {
        const { getOrCreateMasterSecret } = await import('./secureDeterministicWallet');
        // Inject Access Token for Drive Sync (Android AND iOS for roaming)
        // iOS will first check Keychain, but if empty, it needs this token to check Drive.
        const tokenForDrive = enableDrive ? driveAccessToken : undefined;

        console.log(`[AuthService] Calling getOrCreateMasterSecret with:`, {
          platform: Platform.OS,
          enableDrive,
          hasAccessToken: !!driveAccessToken,
          tokenForDriveProvided: !!tokenForDrive
        });

        await getOrCreateMasterSecret(googleSubject, tokenForDrive || undefined);
        console.log('Master Secret synced/verified successfully.');
        driveSyncSucceeded = true;

        // Report backup status if Drive was used (after backend auth completes below)
      } catch (walletErr) {
        console.error('Failed to sync Master Secret:', walletErr);
        // We do NOT block login here, but wallet creation might fail later.
        // Ideally we should block if critical, but for now log.
        driveSyncSucceeded = false;
      }
      perfLog('End Master Secret Sync');

      console.log('Store OAuth subject for later wallet derivation');
      perfLog('Store OAuth subject for later wallet derivation');

      // Use OAuth subject directly from Google Sign-In response
      // (googleSubject is already retrieved and verified above)

      // Store OAuth subject securely for future account switching
      const { oauthStorage } = await import('./oauthStorageService');
      await oauthStorage.storeOAuthSubject(googleSubject, 'google');
      console.log('Stored OAuth subject securely for future use');

      // 6) Authenticate with backend using Web3Auth (derive wallet after JWT is stored)
      console.log('Authenticating with backend...');
      perfLog('Starting backend authentication');
      const { WEB3AUTH_LOGIN } = await import('../apollo/mutations');
      const { data: { web3AuthLogin: authData } } = await apolloClient.mutate({
        mutation: WEB3AUTH_LOGIN,
        variables: {
          firebaseIdToken: firebaseToken,
          algorandAddress: null,
          deviceFingerprint: deviceFingerprint ? JSON.stringify(deviceFingerprint) : null,
          platformOs: Platform.OS
        }
      });
      console.log('Backend authentication response:', authData ? 'Data received' : 'No data');
      perfLog('Backend authenticated');

      if (!authData || !authData.success) {
        const backendError = authData?.error || 'Backend authentication failed';
        const normalizedError = backendError.toLowerCase();
        if (normalizedError.includes('desactivada') || normalizedError.includes('deleted')) {
          throw new AccountDeactivatedError(backendError);
        }
        throw new Error(backendError);
      }

      // ----------------------------------------------------------------------
      // NATIVE V2 CHECK:
      // If the backend says this user is V2 Native (e.g. New User or Migrated),
      // we MUST ensure the V2 Master Secret exists locally.
      // If it's missing (New Device / New User), we generate/restore it here
      // so that deriveWalletV2 is used instead of Legacy V1 fallback.
      // ----------------------------------------------------------------------
      if (authData.isKeylessMigrated) {
        console.log('[AuthService] ⚡️ User is V2 Native (Flag=True). Verifying Master Secret...');
        try {
          const { getOrCreateMasterSecret } = await import('./secureDeterministicWallet');
          // This call will Retrieve OR Generate (if missing).
          // For NEW users -> Generates Random.
          // For RESTORING users -> Checks storage (if missing -> Generates NEW, handling backup loss scenario by resetting).
          // Now passing googleSubject to namespace the secret properly
          await getOrCreateMasterSecret(googleSubject);
          console.log('[AuthService] ✅ V2 Master Secret verified/created.');
        } catch (v2Err) {
          console.error('[AuthService] ⚠️ Failed to verify V2 Master Secret:', v2Err);
          // We continue, but createOrRestoreWallet might fall back to V1 or fail.
        }
      }
      // ----------------------------------------------------------------------

      // Store Django JWT tokens for authenticated requests using Keychain (store BEFORE any further GraphQL)
      if (authData.accessToken) {
        console.log('About to store tokens in Keychain:', {
          service: AUTH_KEYCHAIN_SERVICE,
          username: AUTH_KEYCHAIN_USERNAME,
          hasAccessToken: !!authData.accessToken,
          hasRefreshToken: !!authData.refreshToken,
          accessTokenLength: authData.accessToken?.length,
          refreshTokenLength: authData.refreshToken?.length
        });

        try {
          await Keychain.setGenericPassword(
            AUTH_KEYCHAIN_USERNAME,
            JSON.stringify({
              accessToken: authData.accessToken,
              refreshToken: authData.refreshToken
            }),
            {
              service: AUTH_KEYCHAIN_SERVICE,
              username: AUTH_KEYCHAIN_USERNAME,
              accessible: Keychain.ACCESSIBLE.WHEN_UNLOCKED
            }
          );

          // Verify token was stored
          const checkCredentials = await Keychain.getGenericPassword({
            service: AUTH_KEYCHAIN_SERVICE,
            username: AUTH_KEYCHAIN_USERNAME
          });

          if (checkCredentials === false) {
            console.log('JWT in Keychain right after saving: No credentials');
            throw new Error('Failed to verify token storage in Keychain');
          } else {
            console.log('JWT in Keychain right after saving:', {
              hasCredentials: true,
              hasPassword: !!checkCredentials.password,
              passwordLength: checkCredentials.password.length
            });
            if (!checkCredentials.password) {
              throw new Error('Failed to verify token storage in Keychain');
            }
          }
        } catch (error) {
          console.error('Error storing or verifying tokens:', error);
          throw error;
        }
      } else {
        console.error('No auth tokens received from Web3Auth login');
        throw new Error('No auth tokens received from server');
      }



      // 7) Now derive Algorand wallet (pepper fetch requires JWT)
      const algorandService = (await import('./algorandService')).default;
      const algorandAddress = await algorandService.createOrRestoreWallet(firebaseToken, googleSubject);
      console.log('Algorand wallet created:', algorandAddress);
      perfLog('Algorand wallet created');

      // Update server with derived address (pass isV2Wallet if V2 sync succeeded)
      try {
        const { UPDATE_ACCOUNT_ALGORAND_ADDRESS } = await import('../apollo/queries');
        const updRes = await apolloClient.mutate({ mutation: UPDATE_ACCOUNT_ALGORAND_ADDRESS, variables: { algorandAddress, isV2Wallet: driveSyncSucceeded } });
        console.log('Updated server with Algorand address');
        // If server prepared opt-in transactions (CONFIO/cUSD), sign and submit now
        try {
          const payload = updRes?.data?.updateAccountAlgorandAddress;
          const needsOptIn = payload?.needsOptIn as number[] | undefined;
          const txns = payload?.optInTransactions as string | any[] | undefined;
          if (needsOptIn && needsOptIn.length > 0 && txns) {
            const groups = typeof txns === 'string' ? JSON.parse(txns) : txns;
            console.log('Processing server-prepared opt-in transactions...', { assets: needsOptIn });
            await algorandService.processSponsoredOptIn(groups);
            console.log('Server-prepared asset opt-ins submitted');
          }
        } catch (e) {
          console.error('Opt-in post-update handling failed (non-fatal):', e);
        }
      } catch (e) {
        console.error('Failed updating server with Algorand address:', e);
      }


      // Now that tokens are stored, process any required opt-ins for PERSONAL accounts only
      // Business accounts handle opt-ins separately during payment flow
      const accountManager = AccountManager.getInstance();
      const activeContext = await accountManager.getActiveAccountContext();
      if (activeContext.type === 'personal' && authData.needsOptIn && authData.needsOptIn.length > 0) {
        console.log('Personal account needs to opt-in to assets:', authData.needsOptIn);
        if (authData.optInTransactions && authData.optInTransactions.length > 0) {
          console.log('Processing opt-in transactions for personal account...');
          try {
            const optInTxns = typeof authData.optInTransactions === 'string'
              ? JSON.parse(authData.optInTransactions)
              : authData.optInTransactions;
            const ok = await algorandService.processSponsoredOptIn(optInTxns);
            if (ok) {
              console.log('Successfully processed opt-in transactions for personal account');
            } else {
              console.error('Opt-in transactions were not confirmed');
            }
          } catch (optInError) {
            console.error('Failed to process opt-in transactions:', optInError);
            // Don't fail login if opt-in fails - user can retry later
          }
        }
      }

      // 8) Set default personal account context
      console.log('Setting default personal account context...');
      try {
        const accountManager = AccountManager.getInstance();
        await accountManager.setActiveAccountContext({
          type: 'personal',
          index: 0
        });
        console.log('Set default personal account context (personal_0)');

        // Store the Algorand address for the personal account
        const defaultAccountContext: AccountContext = {
          type: 'personal',
          index: 0
        };
        await this.storeAlgorandAddress(algorandAddress, defaultAccountContext);
      } catch (accountError) {
        console.error('Error creating default account:', accountError);
        // Don't throw here - account creation failure shouldn't break the sign-in flow
      }

      // 9) Get user info for return
      const [firstName, ...lastNameParts] = user.displayName?.split(' ') || [];
      const lastName = lastNameParts.join(' ');
      const isPhoneVerified = authData.user?.isPhoneVerified || false;
      console.log('Phone verification status from backend:', isPhoneVerified);

      // 10) Return user info with Algorand address
      const result = {
        userInfo: {
          email: user.email,
          firstName: firstName || '',
          lastName: lastName || '',
          photoURL: user.photoURL
        },
        walletData: {
          algorandAddress: null,
          isPhoneVerified
        }
      };
      perfLog('Total sign-in time');
      console.log('Sign-in process completed successfully:', result);

      // Report backup status only if Drive was enabled AND sync actually succeeded
      if (enableDrive && driveSyncSucceeded) {
        try {
          const { reportBackupStatus } = await import('./secureDeterministicWallet');
          await reportBackupStatus('google_drive');
          console.log('[AuthService] Backup status reported for Google sign-in');
        } catch (e) {
          console.warn('[AuthService] Failed to report backup status:', e);
        }
      }

      return result;
    } catch (error) {
      console.error('Error signing in with Google:', error);
      throw error;
    }
  }


  // Apple Sign-In
  public async signInWithApple(onProgress?: (message: string) => void) {
    if (Platform.OS !== 'ios') {
      throw new Error('Apple Sign In is only supported on iOS');
    }

    try {
      // Don't show progress during Apple modal
      if (!apolloClient) {
        throw new Error('Apollo client not initialized');
      }

      // Apple Sign In flow
      console.log('Starting Apple Sign In...');
      const { appleAuth } = await import('@invertase/react-native-apple-authentication');

      // Perform Apple auth (nonce will be auto-generated by the library)
      const appleAuthResponse = await appleAuth.performRequest({
        requestedOperation: appleAuth.Operation.LOGIN,
        requestedScopes: [appleAuth.Scope.EMAIL, appleAuth.Scope.FULL_NAME]
      });

      if (!appleAuthResponse.identityToken) {
        throw new Error('No identity token received from Apple');
      }

      // NOW show loading - Apple modal is closed
      onProgress?.('Verificando tu identidad con Apple...');

      // Sign in with Firebase
      const appleCredential = auth.AppleAuthProvider.credential(appleAuthResponse.identityToken, appleAuthResponse.nonce);
      const userCredential = await this.auth.signInWithCredential(appleCredential);
      const firebaseToken = await userCredential.user.getIdToken();

      console.log('Firebase sign-in successful');

      // Collect device fingerprint
      console.log('Collecting device fingerprint (Apple)...');
      let deviceFingerprint = null;
      try {
        deviceFingerprint = await DeviceFingerprint.generateFingerprint();
        console.log('Device fingerprint collected successfully (Apple)');
      } catch (error) {
        console.error('Error collecting device fingerprint (Apple):', error);
      }

      // Defer Algorand wallet derivation until after backend JWT is obtained
      onProgress?.('Preparando tu cuenta segura...');
      console.log('Deferring Algorand wallet derivation until after backend auth...');

      // Use Apple user ID directly from the auth response
      let appleSub = appleAuthResponse.user;
      if (!appleSub) {
        // Fallback: decode the token if user field is not available (happens on subsequent sign-ins)
        const decodedAppleToken = jwtDecode<{ sub: string }>(appleAuthResponse.identityToken);
        appleSub = decodedAppleToken.sub;
      }

      // Store OAuth subject securely for future account switching
      const { oauthStorage } = await import('./oauthStorageService');
      await oauthStorage.storeOAuthSubject(appleSub, 'apple');
      console.log('Stored Apple OAuth subject securely for future use');

      // Authenticate with backend using Web3Auth (no address yet)
      console.log('Authenticating with backend (Apple)...');
      const { WEB3AUTH_LOGIN } = await import('../apollo/mutations');
      const { data: { web3AuthLogin: authData } } = await apolloClient.mutate({
        mutation: WEB3AUTH_LOGIN,
        variables: {
          firebaseIdToken: firebaseToken,
          algorandAddress: null,
          deviceFingerprint: deviceFingerprint ? JSON.stringify(deviceFingerprint) : null,
          platformOs: Platform.OS
        }
      });

      if (!authData || !authData.success) {
        const backendError = authData?.error || 'Backend authentication failed';
        const normalizedError = backendError.toLowerCase();
        if (normalizedError.includes('desactivada') || normalizedError.includes('deleted')) {
          throw new AccountDeactivatedError(backendError);
        }
        throw new Error(backendError);
      }

      // Store Django JWT tokens immediately so subsequent GraphQL is authenticated
      if (authData.accessToken) {
        try {
          await Keychain.setGenericPassword(
            AUTH_KEYCHAIN_USERNAME,
            JSON.stringify({
              accessToken: authData.accessToken,
              refreshToken: authData.refreshToken
            }),
            {
              service: AUTH_KEYCHAIN_SERVICE,
              username: AUTH_KEYCHAIN_USERNAME,
              accessible: Keychain.ACCESSIBLE.WHEN_UNLOCKED
            }
          );
          console.log('Stored JWT tokens in Keychain before processing opt-ins (Apple)');
        } catch (e) {
          console.error('Failed to store tokens before opt-ins (Apple):', e);
          // Continue, but follow-up GraphQL may fail if tokens missing
        }
      }



      // Now derive Algorand wallet (pepper fetch requires JWT)
      const algorandService = (await import('./algorandService')).default;
      const algorandAddress = await algorandService.createOrRestoreWallet(firebaseToken, appleSub);
      console.log('Algorand wallet created (Apple):', algorandAddress);

      // Update server with derived address (iOS uses V2 architecture via iCloud Keychain)
      try {
        const { UPDATE_ACCOUNT_ALGORAND_ADDRESS } = await import('../apollo/queries');
        const updRes = await apolloClient.mutate({ mutation: UPDATE_ACCOUNT_ALGORAND_ADDRESS, variables: { algorandAddress, isV2Wallet: true } });
        console.log('Updated server with Algorand address (Apple)');
        // If server prepared opt-in transactions (CONFIO/cUSD), sign and submit now
        try {
          const payload = updRes?.data?.updateAccountAlgorandAddress;
          const needsOptIn = payload?.needsOptIn as number[] | undefined;
          const txns = payload?.optInTransactions as string | any[] | undefined;
          if (needsOptIn && needsOptIn.length > 0 && txns) {
            const groups = typeof txns === 'string' ? JSON.parse(txns) : txns;
            console.log('Processing server-prepared opt-in transactions (Apple)...', { assets: needsOptIn });
            await algorandService.processSponsoredOptIn(groups);
            console.log('Server-prepared asset opt-ins submitted (Apple)');
          }
        } catch (e) {
          console.error('Opt-in post-update handling (Apple) failed (non-fatal):', e);
        }
      } catch (e) {
        console.error('Failed updating server with Algorand address (Apple):', e);
      }


      // Tokens already stored above for Apple flow

      // Check if PERSONAL account needs to opt-in to assets (Apple Sign-In)
      // Business accounts handle opt-ins separately during payment flow
      const accountMgr = AccountManager.getInstance();
      const activeCtx = await accountMgr.getActiveAccountContext();
      if (activeCtx.type === 'personal' && authData.needsOptIn && authData.needsOptIn.length > 0) {
        console.log('Personal account needs to opt-in to assets (Apple):', authData.needsOptIn);
        if (authData.optInTransactions && authData.optInTransactions.length > 0) {
          console.log('Processing opt-in transactions for personal account (Apple)...');
          try {
            // Parse the opt-in transactions (it's a JSONString from GraphQL)
            const optInTxns = typeof authData.optInTransactions === 'string'
              ? JSON.parse(authData.optInTransactions)
              : authData.optInTransactions;
            console.log('Parsed opt-in transactions (Apple):', JSON.stringify(optInTxns, null, 2));
            // Process the opt-in transactions using the updated method
            const ok = await algorandService.processSponsoredOptIn(optInTxns);
            if (ok) {
              console.log('Successfully processed opt-in transactions for personal account (Apple)');
            } else {
              console.error('Opt-in transactions were not confirmed (Apple)');
            }
          } catch (optInError) {
            console.error('Failed to process opt-in transactions (Apple):', optInError);
            // Don't fail login if opt-in fails - user can retry later
          }
        }
      }

      // Set default personal account context
      console.log('Setting default personal account context (Apple)...');
      try {
        const accountManager = AccountManager.getInstance();
        await accountManager.setActiveAccountContext({
          type: 'personal',
          index: 0
        });
        console.log('Set default personal account context (personal_0)');

        // Store the Algorand address for the personal account
        const defaultAccountContext: AccountContext = {
          type: 'personal',
          index: 0
        };
        await this.storeAlgorandAddress(algorandAddress, defaultAccountContext);
      } catch (accountError) {
        console.error('Error creating default account (Apple):', accountError);
        // Don't throw here - account creation failure shouldn't break the sign-in flow
      }

      // Get user info for return
      const [firstName, ...lastNameParts] = userCredential.user.displayName?.split(' ') || [];
      const lastName = lastNameParts.join(' ');
      const isPhoneVerified = authData.user?.isPhoneVerified || false;
      console.log('Phone verification status from backend (Apple):', isPhoneVerified);

      // Return user info with Algorand address
      const result = {
        userInfo: {
          email: userCredential.user.email,
          firstName: firstName || '',
          lastName: lastName || '',
          photoURL: userCredential.user.photoURL
        },
        walletData: {
          algorandAddress: null,
          isPhoneVerified // Use the actual value from backend
        },
        algorandAddress: algorandAddress // Also store at top level for compatibility
      };
      console.log('Apple sign-in process completed successfully:', result);

      // Report iCloud backup status for iOS users (Apple Sign-In uses iCloud Keychain)
      if (Platform.OS === 'ios') {
        try {
          const { reportBackupStatus } = await import('./secureDeterministicWallet');
          await reportBackupStatus('icloud');
          console.log('[AuthService] iCloud backup status reported for Apple sign-in');
        } catch (e) {
          console.warn('[AuthService] Failed to report iCloud backup status:', e);
        }
      }

      return result;
    } catch (error) {
      console.error('Apple Sign In Error:', error);
      throw error;
    }
  }




  // Get the user's Algorand address (renamed from Sui/Aptos address)
  public async getAlgorandAddress(context?: AccountContext): Promise<string> {
    if (!this.firebaseIsInitialized) {
      await this.initialize();
    }

    // Get current account context - prefer explicit context, fallback to stored
    const accountManager = AccountManager.getInstance();
    let accountContext: AccountContext;

    if (context) {
      accountContext = context;
    } else {
      accountContext = await accountManager.getActiveAccountContext();
    }

    console.log('🔎 getAlgorandAddress - Account context:', {
      type: accountContext.type,
      index: accountContext.index,
      businessId: accountContext.businessId,
      source: context ? 'explicit' : 'stored'
    });

    // Generate cache key for this account
    let cacheKey: string;
    if (accountContext.type === 'business' && accountContext.businessId) {
      cacheKey = `algo_address_business_${accountContext.businessId}_${accountContext.index}`;
    } else {
      cacheKey = `algo_address_${accountContext.type}_${accountContext.index}`;
    }

    // Use a unique service per account to avoid overwrites
    const serviceName = `com.confio.algorand.addresses.${cacheKey}`;
    console.log('🔑 getAlgorandAddress - Using service:', serviceName);

    // Try to get the stored address for this account from Keychain (per-service entry)
    try {
      const credentials = await Keychain.getGenericPassword({ service: serviceName });

      if (credentials && credentials.password) {
        const address = credentials.password;
        console.log('Retrieved stored Algorand address for account:', {
          accountType: accountContext.type,
          accountIndex: accountContext.index,
          businessId: accountContext.businessId,
          address: address
        });
        return address;
      }
    } catch (error) {
      console.log('No stored address found, will need to regenerate during sign-in');
    }

    // No stored address for this account - compute it now
    console.log('No Algorand address found in keychain, computing it now:', {
      accountType: accountContext.type,
      accountIndex: accountContext.index,
      businessId: accountContext.businessId,
      cacheKey: cacheKey
    });

    // Compute and store the address (this will also cache it in Keychain)
    try {
      const computedAddress = await this.computeAndStoreAlgorandAddress(accountContext);
      if (computedAddress) {
        console.log('Successfully computed and stored address:', computedAddress);
        return computedAddress;
      }
    } catch (error) {
      console.error('Failed to compute address:', error);
    }

    // Only return empty if we truly can't derive the address
    return ''; // Return empty string to indicate no address yet
  }

  /**
   * Store Algorand address for a specific account context
   */
  async computeAndStoreAlgorandAddress(accountContext: AccountContext): Promise<string> {
    try {
      console.log('🔐 Computing Algorand address for account context:', accountContext);

      // Ensure we have JWT tokens before attempting pepper-protected derivation
      try {
        const creds = await Keychain.getGenericPassword({
          service: AUTH_KEYCHAIN_SERVICE,
          username: AUTH_KEYCHAIN_USERNAME
        });
        if (!creds || !creds.password) {
          console.log('No JWT found in Keychain; skipping wallet derivation until after login');
          return '';
        }
      } catch (_) {
        console.log('Keychain not ready for JWT; skipping wallet derivation until after login');
        return '';
      }

      // Get the Firebase ID token (should be present post-login)
      const currentUser = this.auth.currentUser;
      if (!currentUser) {
        console.error('No authenticated Firebase user; skipping derivation');
        return '';
      }
      const firebaseIdToken = await currentUser.getIdToken();

      // Get OAuth subject from keychain
      const { oauthStorage } = await import('./oauthStorageService');
      const oauthData = await oauthStorage.getOAuthSubject();

      if (!oauthData || !oauthData.subject) {
        console.error('No OAuth subject found in keychain');
        return '';
      }

      const oauthSubject = oauthData.subject;
      const provider = oauthData.provider;

      // Use the secure deterministic wallet service to generate address for this account
      const { SecureDeterministicWalletService } = await import('./secureDeterministicWallet');
      const secureDeterministicWallet = SecureDeterministicWalletService.getInstance();

      console.log('🔐 Calling createOrRestoreWallet with:', {
        accountType: accountContext.type,
        accountIndex: accountContext.index,
        businessId: accountContext.businessId,
        provider: provider,
        oauthSubject: oauthSubject.substring(0, 20) + '...'
      });

      // Determine issuer and audience consistently (same as switchAccount)
      const GOOGLE_WEB_CLIENT_ID = GOOGLE_CLIENT_IDS.production.web;
      const iss = provider === 'google' ? 'https://accounts.google.com' : 'https://appleid.apple.com';
      const aud = provider === 'google' ? GOOGLE_WEB_CLIENT_ID : 'com.confio.app';

      const wallet = await secureDeterministicWallet.createOrRestoreWallet(
        iss,                    // OAuth issuer
        oauthSubject,           // OAuth subject
        aud,                    // OAuth audience
        provider,               // Provider
        accountContext.type,
        accountContext.index,
        accountContext.businessId
      );

      console.log('🎯 Generated Algorand address for account:', {
        accountType: accountContext.type,
        accountIndex: accountContext.index,
        businessId: accountContext.businessId,
        algorandAddress: wallet.address,
      });

      // Store the address for this account
      await this.storeAlgorandAddress(wallet.address, accountContext);

      // Also update on server
      try {
        const { UPDATE_ACCOUNT_ALGORAND_ADDRESS } = await import('../apollo/queries');
        await apolloClient.mutate({
          mutation: UPDATE_ACCOUNT_ALGORAND_ADDRESS,
          variables: { algorandAddress: wallet.address }
        });
        console.log('Updated server with new address');
      } catch (error) {
        console.error('Failed to update server with address:', error);
        // Continue even if server update fails
      }

      return wallet.address;
    } catch (error) {
      console.error('Error computing Algorand address:', error);
      return '';
    }
  }

  private async storeAlgorandAddress(address: string, accountContext: AccountContext): Promise<void> {
    // Generate cache key for this account
    let cacheKey: string;
    if (accountContext.type === 'business' && accountContext.businessId) {
      cacheKey = `algo_address_business_${accountContext.businessId}_${accountContext.index}`;
    } else {
      cacheKey = `algo_address_${accountContext.type}_${accountContext.index}`;
    }

    // Use a unique service per account to avoid overwrites
    const serviceName = `com.confio.algorand.addresses.${cacheKey}`;

    console.log('📝 STORING Algorand address:', {
      service: serviceName,
      cacheKey: cacheKey,
      address: address,
      accountType: accountContext.type,
      accountIndex: accountContext.index,
      businessId: accountContext.businessId
    });

    try {
      await Keychain.setGenericPassword(
        cacheKey,  // username (informational)
        address,   // password - the actual data to store
        {
          service: serviceName,
          accessible: Keychain.ACCESSIBLE.WHEN_UNLOCKED
        }
      );
      console.log('✅ Successfully stored Algorand address for account');
    } catch (error) {
      console.error('❌ Error storing Algorand address:', error);
    }
  }

  /**
   * Force update the local stored Algorand address for synchronization with backend.
   */
  public async forceUpdateLocalAlgorandAddress(address: string, accountContext: AccountContext): Promise<void> {
    await this.storeAlgorandAddress(address, accountContext);
    const { DeviceEventEmitter } = require('react-native');
    DeviceEventEmitter.emit('ALGORAND_ADDRESS_UPDATED', address);
    console.log('📢 Emitted ALGORAND_ADDRESS_UPDATED event');
  }

  private async getStoredAlgorandAddress(accountContext: AccountContext): Promise<string | null> {
    // Generate cache key for this account
    let cacheKey: string;
    if (accountContext.type === 'business' && accountContext.businessId) {
      cacheKey = `algo_address_business_${accountContext.businessId}_${accountContext.index}`;
    } else {
      cacheKey = `algo_address_${accountContext.type}_${accountContext.index}`;
    }

    const serviceName = `com.confio.algorand.addresses.${cacheKey}`;
    console.log('🔍 RETRIEVING Algorand address from service:', serviceName);

    try {
      const credentials = await Keychain.getGenericPassword({ service: serviceName });

      if (credentials && credentials.password) {
        console.log('✅ Found stored Algorand address:', {
          service: serviceName,
          cacheKey: cacheKey,
          address: credentials.password,
          accountType: accountContext.type,
          accountIndex: accountContext.index,
          businessId: accountContext.businessId
        });
        return credentials.password;
      }

      console.log('⚠️ No stored address found for service:', serviceName);
      return null;
    } catch (error) {
      console.error('❌ Error retrieving stored Algorand address:', error);
      return null;
    }
  }

  // Debug utility to clear all Algorand addresses
  async debugClearAllAddresses(): Promise<void> {
    const { clearAllAlgorandAddresses, listStoredAlgorandAddresses } = await import('../utils/clearAlgorandAddresses');
    await listStoredAlgorandAddresses();
    await clearAllAlgorandAddresses();
  }

  // Sign out
  async signOut() {
    try {
      console.log('Starting sign out process...');

      // 1. Sign out from Firebase (if there's a current user)
      const currentUser = this.auth.currentUser;
      if (currentUser) {
        await this.auth.signOut();
        console.log('Firebase sign out complete');
      } else {
        console.log('No Firebase user to sign out');
      }

      // 2. Sign out from Google (if applicable)
      try {
        await GoogleSignin.signOut();
        console.log('Google sign out complete');
      } catch (error) {
        console.log('Google sign out skipped or failed:', error);
      }


      // 4. Get accounts before clearing (for efficient address cleanup)
      const accountManager = AccountManager.getInstance();
      const accounts = await accountManager.getStoredAccounts();

      // 5. Clear Algorand wallet data (including encrypted seed cache and stored addresses)
      try {
        const algorandService = (await import('./algorandService')).default;
        await algorandService.clearWallet();
        console.log('Algorand wallet cleared');

        // Clear stored Algorand addresses - pass accounts for efficient cleanup
        const { clearAllStoredAlgorandAddresses } = await import('../utils/clearStoredAddresses');
        await clearAllStoredAlgorandAddresses(accounts);
      } catch (error) {
        console.error('Error clearing Algorand wallet:', error);
        // Continue with sign out even if Algorand clearing fails
      }

      // 6. Clear account data
      await accountManager.clearAllAccounts();

      // 7. Clear stored OAuth subject
      try {
        const { oauthStorage } = await import('./oauthStorageService');
        await oauthStorage.clearOAuthSubject();
        console.log('Cleared stored OAuth subject');
      } catch (error) {
        console.error('Error clearing OAuth subject:', error);
      }

      // 8. Clear business opt-in cache
      try {
        const businessOptInService = (await import('./businessOptInService')).default;
        await businessOptInService.clearOptInStatus(); // Clear all businesses
        console.log('Cleared business opt-in cache');
      } catch (error) {
        console.error('Error clearing business opt-in cache:', error);
      }

      // 9. Clear local state
      this.firebaseIsInitialized = false;
      console.log('Local state cleared');

      // 10. Clear all stored credentials from Keychain
      try {
        // Check tokens before clearing
        const preReset = await Keychain.getGenericPassword({
          service: AUTH_KEYCHAIN_SERVICE,
          username: AUTH_KEYCHAIN_USERNAME
        });
        if (preReset === false) {
          console.log('JWT before reset: No credentials');
        } else {
          console.log('JWT before reset:', {
            hasCredentials: true,
            hasPassword: !!preReset.password,
            passwordLength: preReset.password.length
          });
        }


        // Clear auth tokens (cover both API variants: with and without username)
        // Pass username explicitly to ensure the exact entry is removed
        try {
          await Keychain.resetGenericPassword({
            service: AUTH_KEYCHAIN_SERVICE,
            username: AUTH_KEYCHAIN_USERNAME
          });
          console.log('Cleared auth tokens with service+username');
        } catch (e) {
          console.log('Reset with service+username not supported or failed, will try service-only:', e);
        }
        try {
          await Keychain.resetGenericPassword({
            service: AUTH_KEYCHAIN_SERVICE
          });
          console.log('Cleared auth tokens with service-only');
        } catch (e) {
          console.log('Reset with service-only not supported or failed:', e);
        }

        // Verify tokens are cleared
        const postReset = await Keychain.getGenericPassword({
          service: AUTH_KEYCHAIN_SERVICE,
          username: AUTH_KEYCHAIN_USERNAME
        });
        if (postReset === false) {
          console.log('JWT after reset: No credentials');
        } else {
          console.log('JWT after reset:', {
            hasCredentials: true,
            hasPassword: !!postReset.password,
            passwordLength: postReset.password.length
          });
          if (postReset.password) {
            console.warn('Auth tokens still present after reset, attempting explicit overwrite');
            try {
              // Overwrite with empty payload to ensure credential entry is invalidated
              await Keychain.setGenericPassword(
                AUTH_KEYCHAIN_USERNAME,
                '',
                {
                  service: AUTH_KEYCHAIN_SERVICE,
                  username: AUTH_KEYCHAIN_USERNAME,
                  accessible: Keychain.ACCESSIBLE.WHEN_UNLOCKED
                }
              );
              await Keychain.resetGenericPassword({
                service: AUTH_KEYCHAIN_SERVICE,
                username: AUTH_KEYCHAIN_USERNAME
              });
              console.log('Successfully overwrote and cleared lingering tokens');
            } catch (overwriteError) {
              console.error('Failed to overwrite lingering tokens:', overwriteError);
            }
          }
        }

        // Final sanity check: also try service-only read
        try {
          const postResetServiceOnly = await Keychain.getGenericPassword({ service: AUTH_KEYCHAIN_SERVICE } as any);
          if (postResetServiceOnly && (postResetServiceOnly as any).password) {
            console.warn('Service-only credential still present; forcing service-only reset');
            await Keychain.resetGenericPassword({ service: AUTH_KEYCHAIN_SERVICE } as any);
          }
        } catch (_) { /* ignore */ }
      } catch (keychainError) {
        console.error('Error clearing Keychain:', keychainError);
        // Continue with sign out even if Keychain clearing fails
      }

      console.log('Sign out process completed successfully');
    } catch (error) {
      console.error('Sign Out Error:', error);
      // Don't throw the error, just log it and continue with cleanup
      console.log('Continuing with cleanup despite error...');

      // Ensure we still clear local state and credentials even if sign out fails
      this.firebaseIsInitialized = false;

      // Attempt to clear all Keychain data even if previous operations failed
      // v10 API: resetGenericPassword accepts options object
      try {
        await Keychain.resetGenericPassword({
          service: AUTH_KEYCHAIN_SERVICE
        });
      } catch (keychainError) {
        console.error('Error clearing Keychain during error recovery:', keychainError);
      }
    }
  }





  async getOrCreateSuiAddress(userData: any): Promise<string> {
    try {
      // First, check if user already has a Sui address
      const existingAddress = await this.getUserSuiAddress(userData.uid);
      if (existingAddress) {
        return existingAddress;
      }

      // If no address exists, generate a new one
      const newAddress = await this.generateSuiAddress(userData);

      // Store the new address
      await this.storeUserSuiAddress(userData.uid, newAddress);

      return newAddress;
    } catch (error) {
      console.error('Error in getOrCreateSuiAddress:', error);
      throw error;
    }
  }

  private async getUserSuiAddress(userId: string): Promise<string | null> {
    // TODO: Implement fetching from your backend
    return null;
  }

  private async generateSuiAddress(userData: any): Promise<string> {
    // TODO: Implement Sui address generation
    // This should use the Sui SDK to generate a new address
    return '0x' + Math.random().toString(16).substring(2, 42); // Placeholder
  }

  private async storeUserSuiAddress(userId: string, address: string): Promise<void> {
    // TODO: Implement storing in your backend
    console.log(`Storing Sui address ${address} for user ${userId}`);
  }



  private async storeTokens(tokens: TokenStorage): Promise<void> {
    try {
      console.log('Storing tokens:', {
        hasAccessToken: !!tokens.accessToken,
        hasRefreshToken: !!tokens.refreshToken,
        accessTokenLength: tokens.accessToken?.length,
        refreshTokenLength: tokens.refreshToken?.length
      });

      // First verify the tokens before storing
      if (!tokens.accessToken || !tokens.refreshToken) {
        throw new Error('Invalid token format: missing access or refresh token');
      }

      // Verify token types
      try {
        const accessDecoded = jwtDecode<CustomJwtPayload>(tokens.accessToken);
        const refreshDecoded = jwtDecode<CustomJwtPayload>(tokens.refreshToken);

        if (accessDecoded.type !== 'access' || refreshDecoded.type !== 'refresh') {
          throw new Error('Invalid token types');
        }
      } catch (error) {
        console.error('Error verifying token types:', error);
        throw new Error('Invalid token format or type');
      }

      // Store the tokens
      const result = await Keychain.setGenericPassword(
        AUTH_KEYCHAIN_USERNAME,
        JSON.stringify(tokens),
        {
          service: AUTH_KEYCHAIN_SERVICE,
          username: AUTH_KEYCHAIN_USERNAME,
          accessible: Keychain.ACCESSIBLE.WHEN_UNLOCKED
        }
      );

      console.log('Token storage result:', result);

      // Verify the tokens were stored correctly
      const stored = await Keychain.getGenericPassword({
        service: AUTH_KEYCHAIN_SERVICE,
        username: AUTH_KEYCHAIN_USERNAME
      });

      if (stored === false) {
        throw new Error('Failed to verify token storage');
      } else {
        const storedTokens = JSON.parse(stored.password);
        if (!storedTokens.accessToken || !storedTokens.refreshToken) {
          throw new Error('Invalid token format in storage');
        }
        console.log('Tokens stored and verified successfully:', {
          hasAccessToken: !!storedTokens.accessToken,
          hasRefreshToken: !!storedTokens.refreshToken,
          accessTokenLength: storedTokens.accessToken.length,
          refreshTokenLength: storedTokens.refreshToken.length
        });
      }
    } catch (error) {
      console.error('Error storing tokens:', error);
      throw error;
    }
  }

  private async getStoredTokens(): Promise<TokenStorage | null> {
    try {
      console.log('Attempting to retrieve tokens from Keychain');

      const credentials = await Keychain.getGenericPassword({
        service: AUTH_KEYCHAIN_SERVICE,
        username: AUTH_KEYCHAIN_USERNAME
      });

      if (credentials === false) {
        console.log('No credentials found in Keychain');
        return null;
      } else {
        const { password } = credentials;
        console.log('Found credentials in Keychain:', {
          hasPassword: !!password,
          passwordLength: password.length
        });

        const tokens = JSON.parse(password);

        console.log('Parsed tokens:', {
          hasAccessToken: !!tokens.accessToken,
          hasRefreshToken: !!tokens.refreshToken,
          accessTokenLength: tokens.accessToken?.length,
          refreshTokenLength: tokens.refreshToken?.length
        });

        if (!tokens.accessToken || !tokens.refreshToken) {
          console.error('Invalid token format: missing access or refresh token');
          return null;
        }

        // Verify token types
        try {
          const accessDecoded = jwtDecode<CustomJwtPayload>(tokens.accessToken);
          const refreshDecoded = jwtDecode<CustomJwtPayload>(tokens.refreshToken);

          if (accessDecoded.type !== 'access' || refreshDecoded.type !== 'refresh') {
            console.error('Invalid token types:', {
              accessType: accessDecoded.type,
              refreshType: refreshDecoded.type
            });
            return null;
          }

          console.log('Tokens verified successfully');
          return tokens;
        } catch (error) {
          console.error('Error verifying token types:', error);
          return null;
        }
      }
    } catch (error) {
      console.error('Error retrieving tokens:', error);
      return null;
    }
  }

  public async getToken(): Promise<string | null> {
    try {
      const credentials = await Keychain.getGenericPassword({
        service: AUTH_KEYCHAIN_SERVICE,
        username: AUTH_KEYCHAIN_USERNAME
      });

      if (credentials === false) {
        return null;
      }

      const tokens = JSON.parse(credentials.password);
      return tokens.accessToken || null;
    } catch (error) {
      console.error('Error getting token:', error);
      return null;
    }
  }

  // Account Management Methods

  /**
   * Get the currently active account context
   */
  public async getActiveAccountContext(): Promise<AccountContext> {
    const accountManager = AccountManager.getInstance();
    try {
      return await accountManager.getActiveAccountContext();
    } catch (error) {
      console.error('Error getting active account context, returning default (persisting storage):', error);
      // Do NOT reset corrupted active account data on read error
      // This prevents transient keychain errors from wiping user preference

      // Return default context temporarily
      return accountManager.getDefaultAccountContext();
    }
  }

  /**
   * Set the active account context
   */
  public async setActiveAccountContext(context: AccountContext): Promise<void> {
    const accountManager = AccountManager.getInstance();
    await accountManager.setActiveAccountContext(context);
  }

  /**
   * Get all stored accounts
   */
  public async getStoredAccounts(): Promise<any[]> {
    const accountManager = AccountManager.getInstance();
    return await accountManager.getStoredAccounts();
  }

  /**
   * Create a new account
   * NOTE: This method is deprecated. Account creation should be done through server mutations.
   * This method is kept for backward compatibility but should not be used for new business accounts.
   */
  public async createAccount(
    name: string,
    avatar: string,
    phone?: string,
    category?: string
  ): Promise<any> {
    console.warn('AuthService.createAccount is deprecated. Use server mutations for account creation.');

    // For backward compatibility, return a mock account
    // This should not be used for actual account creation
    return {
      id: 'deprecated_method',
      type: 'business',
      index: 0,
      name: name,
      avatar: avatar,
      phone: phone,
      category: category
    };
  }

  /**
   * Switch to a different account
   * Note: Wallet data is user-level, not account-level, so we don't clear it
   */
  public async switchAccount(accountId: string, apolloClient?: any): Promise<void> {
    const accountManager = AccountManager.getInstance();

    console.log('AuthService - switchAccount called with accountId:', accountId);

    // Parse the account ID to extract type, businessId (if present), and index
    let accountContext: AccountContext;

    if (accountId === 'personal_0') {
      // Personal account
      accountContext = {
        type: 'personal',
        index: 0
      };
    } else if (accountId.startsWith('business_')) {
      // Business account format: business_{businessId}_0
      const parts = accountId.split('_');
      if (parts.length >= 3) {
        const businessId = parts[1];
        const index = parseInt(parts[2]) || 0;

        accountContext = {
          type: 'business',
          index: index,
          businessId: businessId // Required for salt generation
        };

        console.log('AuthService - Parsed business account with businessId:', {
          accountId,
          businessId,
          index,
          contextBusinessId: accountContext.businessId
        });
      } else {
        // Fallback for simple business_0 format
        accountContext = {
          type: 'business',
          index: 0
        };

        console.log('AuthService - Fallback business account (no businessId):', {
          accountId,
          type: 'business',
          index: 0
        });
      }
    } else {
      // Fallback - extract type and index
      const [accountType, indexStr] = accountId.split('_');
      const accountIndex = parseInt(indexStr) || 0;

      accountContext = {
        type: accountType as 'personal' | 'business',
        index: accountIndex
      };
    }

    console.log('AuthService - Parsed account context:', {
      accountId: accountId,
      accountType: accountContext.type,
      accountIndex: accountContext.index,
      note: accountContext.type === 'personal' ? 'Personal account (index 0)' : `Business account (index ${accountContext.index})`
    });

    // Set the new active account context
    await accountManager.setActiveAccountContext(accountContext);

    console.log('AuthService - Active account context set');

    // If apolloClient is provided, get a new JWT token with the updated account context
    if (apolloClient) {
      try {
        const { SWITCH_ACCOUNT_TOKEN } = await import('../apollo/queries');

        const variables: any = {
          accountType: accountContext.type,
          accountIndex: accountContext.index
        };

        // Add businessId for employee accounts switching to business accounts
        if (accountContext.businessId) {
          variables.businessId = accountContext.businessId;
          console.log('AuthService - Added businessId to variables:', {
            businessId: accountContext.businessId,
            businessIdType: typeof accountContext.businessId
          });
        } else {
          console.log('AuthService - No businessId in accountContext:', {
            accountContextType: accountContext.type,
            accountContextIndex: accountContext.index,
            accountContextBusinessId: accountContext.businessId,
            hasBusinessId: !!accountContext.businessId
          });
        }

        console.log('AuthService - Calling SWITCH_ACCOUNT_TOKEN with variables:', variables);

        const { data } = await apolloClient.mutate({
          mutation: SWITCH_ACCOUNT_TOKEN,
          variables
        });

        if (data?.switchAccountToken?.token) {
          console.log('AuthService - Got new JWT token with account context');

          // Store opt-in info for later processing (owners only)
          if (data.switchAccountToken.optInRequired && data.switchAccountToken.optInTransactions) {
            console.log('AuthService - Business account needs opt-in to assets (will process when wallet connects)');

            // Check if this is an owner switching to their business
            const payload = data.switchAccountToken.payload;
            const isOwner = !payload.is_employee || payload.employee_role === 'owner';

            if (isOwner) {
              // Store opt-in transactions for processing when wallet connects
              // This will be handled by the business account first-use logic
              console.log('AuthService - Owner account detected, opt-in will be processed on first use');
            } else {
              console.log('AuthService - Employee account detected, skipping opt-in (no access to business private key)');
            }
          }

          // Get existing refresh token
          const credentials = await Keychain.getGenericPassword({
            service: AUTH_KEYCHAIN_SERVICE,
            username: AUTH_KEYCHAIN_USERNAME
          });

          let refreshToken = '';
          if (credentials && credentials.password) {
            try {
              const tokens = JSON.parse(credentials.password);
              refreshToken = tokens.refreshToken || '';
            } catch (e) {
              console.error('Error parsing existing tokens:', e);
            }
          }

          // Store the new access token with the existing refresh token
          await Keychain.setGenericPassword(
            AUTH_KEYCHAIN_USERNAME,
            JSON.stringify({
              accessToken: data.switchAccountToken.token,
              refreshToken: refreshToken
            }),
            {
              service: AUTH_KEYCHAIN_SERVICE,
              username: AUTH_KEYCHAIN_USERNAME,
              accessible: Keychain.ACCESSIBLE.WHEN_UNLOCKED
            }
          );

          console.log('AuthService - Updated JWT token stored');

          // Ensure businessId is present in context after switch (owner path may omit it in input)
          try {
            const payload = data.switchAccountToken.payload || {};
            const businessIdFromToken: any = (payload.business_id ?? payload.businessId);
            if (accountContext.type === 'business' && !accountContext.businessId && businessIdFromToken) {
              accountContext.businessId = String(businessIdFromToken);
              console.log('AuthService - Enriched account context with businessId from token payload:', {
                businessId: accountContext.businessId
              });
              // Persist updated active context for consistent cache keys and salt generation
              await accountManager.setActiveAccountContext(accountContext);
            }
          } catch (e) {
            console.warn('AuthService - Could not enrich account context with businessId from token payload:', e);
          }
        }
      } catch (error) {
        console.error('Error getting new JWT token for account switch:', error);
        // Continue anyway - the account context is set locally
      }
    }

    // Note: We do NOT clear wallet data because:
    // 1. Wallet authentication is user-level, not account-level
    // 2. The same user can have multiple accounts (personal + business)
    // 3. All accounts share the same wallet authentication

    // Generate new Algorand address for the switched account context
    try {
      console.log('AuthService - Generating Algorand address for account:', {
        accountId: accountId,
        accountType: accountContext.type,
        accountIndex: accountContext.index,
        businessId: accountContext.businessId
      });

      // Generate address for the new account

      // First, try to retrieve stored address for this account
      const storedAddress = await this.getStoredAlgorandAddress(accountContext);

      if (storedAddress) {
        console.log('AuthService - Using stored Algorand address for account:', {
          accountId: accountId,
          address: storedAddress
        });

        // One-time migration: if no encrypted seed exists for this account scope,
        // derive pepper-based wallet and update stored address if needed.
        let finalAddress = storedAddress;
        try {
          // Build seed cache key consistent with SecureDeterministicWallet
          const accountIdForSeed = accountContext.businessId
            ? `${accountContext.type}_${accountContext.businessId}_${accountContext.index}`
            : `${accountContext.type}_${accountContext.index}`;
          const seedUsername = accountIdForSeed.replace(/[^a-zA-Z0-9_]/g, '_');
          const seedServer = 'wallet.confio.app';

          // Check if seed cache exists
          const seedCreds = await Keychain.getInternetCredentials(seedServer as any);
          const hasSeed = !!(seedCreds && (seedCreds as any).password && (seedCreds as any).username === seedUsername);
          if (!hasSeed) {
            console.log('AuthService - No seed cache found for scope, deriving pepper-based wallet to migrate address');

            // Gather OAuth inputs for derivation
            const { oauthStorage } = await import('./oauthStorageService');
            const oauthData = await oauthStorage.getOAuthSubject();
            if (oauthData && oauthData.subject) {
              const oauthSubject = oauthData.subject;
              const provider = oauthData.provider;
              const { GOOGLE_CLIENT_IDS } = await import('../config/env');
              const GOOGLE_WEB_CLIENT_ID = GOOGLE_CLIENT_IDS.production.web;
              const iss = provider === 'google' ? 'https://accounts.google.com' : 'https://appleid.apple.com';
              const aud = provider === 'google' ? GOOGLE_WEB_CLIENT_ID : 'com.confio.app';

              const { SecureDeterministicWalletService } = await import('./secureDeterministicWallet');
              const secureDeterministicWallet = SecureDeterministicWalletService.getInstance();
              const wallet = await secureDeterministicWallet.createOrRestoreWallet(
                iss,
                oauthSubject,
                aud,
                provider,
                accountContext.type,
                accountContext.index,
                accountContext.businessId
              );

              if (wallet && wallet.address) {
                if (wallet.address !== storedAddress) {
                  console.log('AuthService - Migrated to pepper-based address (updating cache and backend):', {
                    previous: storedAddress,
                    next: wallet.address
                  });
                  finalAddress = wallet.address;
                  await this.storeAlgorandAddress(finalAddress, accountContext);
                } else {
                  console.log('AuthService - Pepper-based derivation matches stored address; seed cached.');
                  finalAddress = storedAddress;
                }
              }
            } else {
              console.warn('AuthService - Missing OAuth subject; skipping migration to pepper-based address');
            }
          }
        } catch (migrationError) {
          console.warn('AuthService - Seed migration check/derivation failed (non-fatal):', migrationError);
        }

        // Update the backend with the final address (stored or migrated)
        if (apolloClient) {
          try {
            const { UPDATE_ACCOUNT_ALGORAND_ADDRESS } = await import('../apollo/queries');
            await apolloClient.mutate({
              mutation: UPDATE_ACCOUNT_ALGORAND_ADDRESS,
              variables: { algorandAddress: finalAddress }
            });
            console.log('AuthService - Updated backend with stored/migrated Algorand address');
          } catch (updateError) {
            console.error('AuthService - Error updating backend with Algorand address:', updateError);
          }
        }
        return; // Address already exists (possibly migrated), no need to generate further
      }

      // Get OAuth subject from secure storage (only needed if no stored address)
      const { oauthStorage } = await import('./oauthStorageService');
      const oauthData = await oauthStorage.getOAuthSubject();

      if (!oauthData) {
        console.error('No OAuth subject found in secure storage - cannot generate address for new account');
        return; // Cannot generate without OAuth subject
      }

      const oauthSubject = oauthData.subject;
      const provider = oauthData.provider;

      // Use the secure deterministic wallet service to generate address for this account
      const { SecureDeterministicWalletService } = await import('./secureDeterministicWallet');
      const secureDeterministicWallet = SecureDeterministicWalletService.getInstance();

      // Get the actual Google web client ID from environment config
      const { GOOGLE_CLIENT_IDS } = await import('../config/env');
      const GOOGLE_WEB_CLIENT_ID = GOOGLE_CLIENT_IDS.production.web;

      // Determine the OAuth issuer and audience based on provider
      const iss = provider === 'google' ? 'https://accounts.google.com' : 'https://appleid.apple.com';
      const aud = provider === 'google' ? GOOGLE_WEB_CLIENT_ID : 'com.confio.app';

      console.log('🔐 CALLING createOrRestoreWallet with OAuth claims:', {
        iss,
        sub: oauthSubject.substring(0, 20) + '...',
        aud: aud.substring(0, 20) + '...',
        accountType: accountContext.type,
        accountIndex: accountContext.index,
        businessId: accountContext.businessId,
        provider: provider
      });

      const wallet = await secureDeterministicWallet.createOrRestoreWallet(
        iss,                    // OAuth issuer
        oauthSubject,           // OAuth subject
        aud,                    // OAuth audience (Google web client ID or Apple bundle ID)
        provider,
        accountContext.type,    // Use the actual account type (personal or business)
        accountContext.index,   // Use the actual account index
        accountContext.businessId // Pass the businessId for business accounts
      );

      console.log('🎯 GENERATED NEW Algorand address for account:', {
        accountId: accountId,
        accountType: accountContext.type,
        accountIndex: accountContext.index,
        businessId: accountContext.businessId,
        algorandAddress: wallet.address,
        provider: provider,
        isUnique: wallet.address !== 'U3A3SWOU7NHMS6UWZ3KCE5DHNYIFYQ2F4GASYJXCTYUQZ7FLUFD2ICVXUU' ? '✅ UNIQUE' : '❌ DUPLICATE'
      });

      // Store the address in keychain for future use
      await this.storeAlgorandAddress(wallet.address, accountContext);

      // Update the current account's Algorand address in the backend if needed
      if (apolloClient) {
        try {
          const { UPDATE_ACCOUNT_ALGORAND_ADDRESS } = await import('../apollo/queries');
          await apolloClient.mutate({
            mutation: UPDATE_ACCOUNT_ALGORAND_ADDRESS,
            variables: { algorandAddress: wallet.address }
          });
          console.log('AuthService - Updated backend with new Algorand address');
        } catch (updateError) {
          console.error('AuthService - Error updating backend with Algorand address:', updateError);
          // Non-fatal error - continue
        }
      }
    } catch (error) {
      console.error('AuthService - Error generating Algorand address for account switch:', error);
      // Non-fatal error - continue with the switch
    }

    // Verify that the address changes for the new account context
    try {
      const newAlgorandAddress = await this.getAlgorandAddress();
      console.log('AuthService - Account switch completed with address:', {
        accountId: accountId,
        accountType: accountContext.type,
        accountIndex: accountContext.index,
        address: newAlgorandAddress,
        note: accountContext.type === 'personal' ? 'Personal account (index 0)' : `Business account (index ${accountContext.index})`
      });
    } catch (error) {
      console.error('AuthService - Error getting new address after account switch:', error);
    }
  }

  /**
   * Initialize default account if no accounts exist
   */
  public async initializeDefaultAccount(): Promise<any> {
    const accountManager = AccountManager.getInstance();
    return await accountManager.initializeDefaultAccount();
  }

  /**
   * Check if we need to initialize a default account and create one if needed
   * This should only be called after proper authentication
   */
  private async initializeDefaultAccountIfNeeded(): Promise<void> {
    try {
      const accountManager = AccountManager.getInstance();
      const storedAccounts = await accountManager.getStoredAccounts();

      console.log('AuthService - Checking if default account initialization is needed:', {
        storedAccountsCount: storedAccounts.length,
        storedAccounts: storedAccounts.map(acc => ({ id: acc.id, type: acc.type, index: acc.index }))
      });

      // Also check if there's an active account context that might indicate an account exists
      try {
        const activeContext = await accountManager.getActiveAccountContext();
        console.log('AuthService - Current active account context:', {
          activeContextType: activeContext.type,
          activeContextIndex: activeContext.index,
          activeAccountId: accountManager.generateAccountId(activeContext.type, activeContext.index)
        });
      } catch (error) {
        console.log('AuthService - No active account context found');
      }

      if (storedAccounts.length === 0) {
        console.log('AuthService - No accounts found, but not creating default account');
        console.log('AuthService - Note: Accounts should only be created after proper authentication');
        return;
      } else {
        console.log('AuthService - Accounts already exist, no default initialization needed');
      }
    } catch (error) {
      console.error('AuthService - Error checking default account initialization:', error);
      // Don't throw error, just log it
    }
  }

  public async signIn(email: string, password: string): Promise<void> {
    try {
      // TODO: Replace with actual API call
      const response = await fetch('YOUR_API_ENDPOINT/login', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ email, password }),
      });

      if (!response.ok) {
        throw new Error('Login failed');
      }

      const data = await response.json();
      await this.storeTokens({
        accessToken: data.token,
        refreshToken: data.refreshToken
      });
    } catch (error) {
      console.error('Sign in error:', error);
      throw error;
    }
  }
}

// Export a singleton instance
const authService = AuthService.getInstance();
export default authService; 
