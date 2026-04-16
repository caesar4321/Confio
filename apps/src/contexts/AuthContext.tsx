import React, { createContext, useContext, useState, useEffect, RefObject, useRef } from 'react';
import { Alert, AppState, Platform } from 'react-native';
import { AuthService } from '../services/authService';
import { NavigationContainerRef } from '@react-navigation/native';
import { AuthStackParamList, RootStackParamList } from '../types/navigation';
import { useApolloClient, gql } from '@apollo/client';
import * as Keychain from 'react-native-keychain';
import { jwtDecode } from 'jwt-decode';
import { AUTH_KEYCHAIN_SERVICE, AUTH_KEYCHAIN_USERNAME } from '../apollo/client';
import { GET_ME, GET_BUSINESS_PROFILE } from '../apollo/queries';
import { pushNotificationService } from '../services/pushNotificationService';
import { biometricAuthService } from '../services/biometricAuthService';
import { deepLinkHandler } from '../utils/deepLinkHandler';

// Simple auth readiness gate to coordinate token-dependent queries
let __authReady = false;
const __authReadyResolvers: Array<() => void> = [];
// React state listeners for isAuthReady
let __authReadySetters: Array<(v: boolean) => void> = [];
export function signalAuthReady() {
  __authReady = true;
  while (__authReadyResolvers.length) {
    try { __authReadyResolvers.pop()?.(); } catch { }
  }
  // Notify React state listeners
  for (const setter of __authReadySetters) {
    try { setter(true); } catch { }
  }
}
export function resetAuthReady() {
  __authReady = false;
  // Notify React state listeners
  for (const setter of __authReadySetters) {
    try { setter(false); } catch { }
  }
}
export async function waitForAuthReady() {
  if (__authReady) return;
  await new Promise<void>(res => __authReadyResolvers.push(res));
}
/**
 * React hook that returns true once signalAuthReady() has been called.
 * Useful for skipping GraphQL queries until the JWT token is fully ready
 * (refreshed + synced to the correct account context).
 */
export function useAuthReady(): boolean {
  const [ready, setReady] = React.useState(__authReady);
  React.useEffect(() => {
    // In case signalAuthReady() was called between render and effect
    if (__authReady) setReady(true);
    __authReadySetters.push(setReady);
    return () => {
      __authReadySetters = __authReadySetters.filter(s => s !== setReady);
    };
  }, []);
  return ready;
}

export type StatusTier = 'member' | 'early_supporter' | 'community_builder' | 'embajador';

interface UserProfile {
  id: string;
  username: string;
  email: string;
  firstName?: string;
  lastName?: string;
  phoneCountry?: string;
  phoneNumber?: string;
  isIdentityVerified?: boolean;
  lastVerifiedDate?: string;
  verificationStatus?: string;
  backupProvider?: string; // 'google_drive' | 'icloud' | null
  requiresBackupCompletion?: boolean;
  statusTier?: StatusTier;
  referralCount?: number;
  nextTierName?: string;
  nextTierReferralsNeeded?: number;
  isReferralVerified?: boolean;
}

interface BusinessProfile {
  id: string;
  name: string;
  description?: string;
  category: string;
  address?: string;
  businessRegistrationNumber?: string;
  createdAt?: string;
  updatedAt?: string;
}

interface ProfileData {
  userProfile?: UserProfile;
  businessProfile?: BusinessProfile;
  currentAccountType: 'personal' | 'business';
}

interface AuthContextType {
  isAuthenticated: boolean;
  isLoading: boolean;
  signOut: () => Promise<void>;
  checkLocalAuthState: () => Promise<boolean>;
  handleSuccessfulLogin: (isPhoneVerified: boolean, requiresBackupCompletion?: boolean) => Promise<void>;
  completePhoneVerification: () => Promise<void>;
  completeBiometricAndEnter: () => Promise<boolean>;
  profileData: ProfileData | null;
  isProfileLoading: boolean;
  refreshProfile: (accountType?: 'personal' | 'business', businessId?: string) => Promise<void>;
  // Direct access to user profile for backward compatibility
  userProfile?: UserProfile;
  isUserProfileLoading: boolean;
  accountContextTick: number;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

interface AuthProviderProps {
  children: React.ReactNode;
  navigationRef: RefObject<NavigationContainerRef<RootStackParamList> | null>;
}

export const AuthProvider = ({ children, navigationRef }: AuthProviderProps) => {
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [isNavigationReady, setIsNavigationReady] = useState(false);
  const [profileData, setProfileData] = useState<ProfileData | null>(null);
  const [isProfileLoading, setIsProfileLoading] = useState(false);
  const [accountContextTick, setAccountContextTick] = useState(0);
  const apolloClient = useApolloClient();
  const lastInactiveAtRef = useRef<number | null>(null);
  const lastBiometricSuccessRef = useRef<number>(0);
  const bootstrapAuthRanRef = useRef<boolean>(false);
  const deferredBootstrapOnActiveRef = useRef(false);

  const perfLog = (_label: string, _startTime: number, _extra?: Record<string, any>) => {};

  const resetAuthStack = (screen: keyof AuthStackParamList, params?: AuthStackParamList[keyof AuthStackParamList]) => {
    if (!isNavigationReady || !navigationRef.current) return;
    navigationRef.current.reset({
      index: 0,
      routes: [
        {
          name: 'Auth',
          params: {
            screen,
            params,
          },
        },
      ],
    });
  };

  const waitForAppToBeActive = async (timeoutMs = 4000): Promise<boolean> => {
    if (AppState.currentState === 'active') {
      return true;
    }

    return await new Promise<boolean>((resolve) => {
      let settled = false;
      const timeout = setTimeout(() => {
        if (!settled) {
          settled = true;
          subscription.remove();
          resolve(AppState.currentState === 'active');
        }
      }, timeoutMs);

      const subscription = AppState.addEventListener('change', (state) => {
        if (!settled && state === 'active') {
          settled = true;
          clearTimeout(timeout);
          subscription.remove();
          resolve(true);
        }
      });
    });
  };

  const getStoredAuthCredentials = async (
    retries = Platform.OS === 'ios' ? 3 : 1,
    retryDelayMs = 300
  ) => {
    let lastError: unknown;

    for (let attempt = 0; attempt < retries; attempt += 1) {
      try {
        const credentials = await Keychain.getGenericPassword({
          service: AUTH_KEYCHAIN_SERVICE,
          username: AUTH_KEYCHAIN_USERNAME,
        });

        if (credentials && 'password' in credentials && credentials.password) {
          return credentials;
        }
      } catch (error) {
        lastError = error;
      }

      if (attempt < retries - 1) {
        await new Promise(resolve => setTimeout(resolve, retryDelayMs));
      }
    }

    if (lastError) {
      throw lastError;
    }

    return false;
  };

  // Reset auth gate on mount so cold starts don't inherit a stale ready state
  useEffect(() => {
    try { (function resetGate() { /* scoped */ })(); __authReady = false; } catch { }
  }, []);

  // Helper to prefetch accounts immediately after auth is aligned
  const prefetchUserAccounts = async (reason: string) => {
    try {
      const { GET_USER_ACCOUNTS } = await import('../apollo/queries');
      await apolloClient.query({
        query: GET_USER_ACCOUNTS,
        fetchPolicy: 'network-only',
        context: { skipProactiveRefresh: true },
      });
    } catch (prefetchErr) {
    }
  };

  // Mutation for token refresh (used on resume)
  const REFRESH_TOKEN = gql`
    mutation RefreshToken($refreshToken: String!, $accountType: String, $accountIndex: Int, $businessId: ID) {
      refreshToken(refreshToken: $refreshToken, accountType: $accountType, accountIndex: $accountIndex, businessId: $businessId) {
        token
        refreshExpiresIn
      }
    }
  `;

  // Set up navigation ready listener and check auth state
  useEffect(() => {
    if (navigationRef.current) {
      setIsNavigationReady(true);
      if (!bootstrapAuthRanRef.current) {
        bootstrapAuthRanRef.current = true;
        checkAuthState();
      }
    }
  }, [navigationRef.current]);

  const navigateToScreen = (screenName: keyof RootStackParamList) => {
    if (!isNavigationReady || !navigationRef.current) {
      // Queue navigation for when ready
      setTimeout(() => {
        if (isNavigationReady && navigationRef.current) {
          navigateToScreen(screenName);
        }
      }, 100);
      return;
    }

    // Use setTimeout to ensure navigation happens on next tick
    // This fixes Android navigation freeze issue
    setTimeout(() => {
      try {
        navigationRef.current?.reset({
          index: 0,
          routes: [{
            name: screenName,
            params: undefined,
            state: undefined
          }],
        });

        // After navigating to Main, process any pending push notifications
        if (screenName === 'Main') {
          setTimeout(() => {
            pushNotificationService.processPendingNotification();
            deepLinkHandler.checkDeferredLinks().catch(error => {
              console.error('[AuthContext] Failed to process deferred deep link:', error);
            });
            import('../services/messagingService')
              .then(({ default: messagingService }) => {
                messagingService.processPendingNotification();
              })
              .catch(error => {
                console.error('[AuthContext] Failed to process messagingService pending notification:', error);
              });
          }, 1000); // Give time for Main navigator to mount
        }
      } catch (error) {
        console.error(`[NAV] Navigation error:`, error);
      }
    }, 0);
  };

  // Fetch profile from server based on account type
  const refreshProfile = async (accountType: 'personal' | 'business' = 'personal', businessId?: string) => {
    setIsProfileLoading(true);
    try {
      if (accountType === 'personal') {
        // Fetch user profile
        const { data } = await apolloClient.query({
          query: GET_ME,
          fetchPolicy: 'network-only',
        });

        // Check phone verification status from server ONLY if we got a valid profile
        // If data.me is null (e.g. auth error), we should NOT assume phone is unverified
        // Instead, we let the auth error handlers/checkAuthState deal with the invalid session
        if (data?.me) {
          const serverPhoneVerified = data.me.phoneNumber && data.me.phoneCountry;

          // If phone verification was lost on server but user is authenticated, require re-verification
          if (!serverPhoneVerified && isAuthenticated) {
            setIsAuthenticated(false);
            if (isNavigationReady && navigationRef.current) {
              navigationRef.current.reset({
                index: 0,
                routes: [
                  {
                    name: 'Auth',
                    params: {
                      screen: 'Login',
                    },
                  },
                ],
              });
            }
            return; // Exit early to prevent setting profile data
          }
        }

        setProfileData({
          userProfile: data?.me || null,
          businessProfile: undefined,
          currentAccountType: 'personal'
        });
      } else if (accountType === 'business' && businessId) {
        // Fetch business profile
        const { data: businessData } = await apolloClient.query({
          query: GET_BUSINESS_PROFILE,
          variables: { businessId },
          fetchPolicy: 'network-only',
        });

        // ALSO fetch user profile to keep phone/country info available
        // This is required for ProfileScreen logic (e.g. payment methods visibility)
        let userProfile = null;
        try {
          const { data: userData } = await apolloClient.query({
            query: GET_ME,
            fetchPolicy: 'network-only',
          });
          userProfile = userData?.me || null;
        } catch (e) {
          // Fallback: keep existing user profile if available
          userProfile = profileData?.userProfile || null;
        }

        setProfileData({
          userProfile: userProfile,
          businessProfile: businessData?.business || null,
          currentAccountType: 'business'
        });
      }
    } catch (error) {
      console.error('Error fetching profile:', error);
      setProfileData(null);
    } finally {
      setIsProfileLoading(false);
    }
  };

  // Fetch appropriate profile based on current account type
  useEffect(() => {
    const loadProfileForCurrentAccount = async () => {
      if (isAuthenticated) {
        try {
          const authService = AuthService.getInstance();
          const accountContext = await authService.getActiveAccountContext();

          // CRITICAL: Sync JWT token with stored active account context on app startup
          // This ensures the JWT has the correct business context after app restart
          if (accountContext.type === 'business' && accountContext.businessId) {
            try {
              const { SWITCH_ACCOUNT_TOKEN } = await import('../apollo/queries');
              const { data } = await apolloClient.mutate({
                mutation: SWITCH_ACCOUNT_TOKEN,
                variables: {
                  accountType: accountContext.type,
                  accountIndex: accountContext.index,
                  businessId: accountContext.businessId
                }
              });

              if (data?.switchAccountToken?.token) {
                // Update stored tokens with the new JWT that has business context
                const Keychain = await import('react-native-keychain');
                const AUTH_KEYCHAIN_SERVICE = 'com.confio.auth';
                const AUTH_KEYCHAIN_USERNAME = 'auth_tokens';

                // Get existing refresh token
                const credentials = await Keychain.getGenericPassword({
                  service: AUTH_KEYCHAIN_SERVICE,
                  username: AUTH_KEYCHAIN_USERNAME
                });

                if (credentials) {
                  const tokens = JSON.parse(credentials.password);
                  // Update with new access token while keeping refresh token
                  await Keychain.setGenericPassword(
                    AUTH_KEYCHAIN_USERNAME,
                    JSON.stringify({
                      accessToken: data.switchAccountToken.token,
                      refreshToken: tokens.refreshToken
                    }),
                    {
                      service: AUTH_KEYCHAIN_SERVICE,
                      username: AUTH_KEYCHAIN_USERNAME,
                      accessible: Keychain.ACCESSIBLE.AFTER_FIRST_UNLOCK
                    }
                  );
                  setAccountContextTick((t) => t + 1);
                  // Now signal that auth is ready: final token is aligned with stored business context
                  try { signalAuthReady(); } catch { }
                  // Warm user accounts using the new token/context
                  prefetchUserAccounts('post-business-switch');
                }
              }
            } catch (syncError) {
              console.error('AuthContext - Error syncing JWT token on startup:', syncError);
              // Don't fail the app startup, but operations requiring business context may fail
            }
          }

          // Load the correct profile for the active context to avoid a "personal" flash
          if (accountContext.type === 'business' && accountContext.businessId) {
            await refreshProfile('business', accountContext.businessId);
          } else {
            await refreshProfile('personal');
          }
          // By this point, token is either aligned to business (signaled above) or personal; unblock dependents.
          try { signalAuthReady(); } catch { }
          prefetchUserAccounts('post-profile-load');
        } catch (error) {
          console.error('Error determining account type for profile loading:', error);
          // Fallback to personal profile
          await refreshProfile('personal');
          try { signalAuthReady(); } catch { }
          prefetchUserAccounts('post-profile-fallback');
        }
      } else {
        setProfileData(null);
      }
    };

    loadProfileForCurrentAccount();
  }, [isAuthenticated]);

  // Monitor for credential invalidation (e.g., token version mismatch on server)
  useEffect(() => {
    if (!isAuthenticated) return;

    const checkInterval = setInterval(async () => {
      try {
        const credentials = await Keychain.getGenericPassword({
          service: AUTH_KEYCHAIN_SERVICE,
          username: AUTH_KEYCHAIN_USERNAME,
        });

        // If credentials are gone but we're still marked as authenticated, log out
        if (!credentials && isAuthenticated) {
          setIsAuthenticated(false);
          setProfileData(null);

          // Navigate directly to Login screen (not phone verification)
          if (isNavigationReady && navigationRef.current) {
            navigationRef.current.reset({
              index: 0,
              routes: [
                {
                  name: 'Auth',
                  params: {
                    screen: 'Login',
                  },
                },
              ],
            });
          }
        }
      } catch (error) {
        console.error('[AuthContext] Error checking credentials:', error);
      }
    }, 1000); // Check every second

    return () => clearInterval(checkInterval);
  }, [isAuthenticated, isNavigationReady]);

  // Refresh on resume to ensure valid access token before UI queries
  useEffect(() => {
    let isAuthenticating = false;
    let lastAuthAttempt = 0;
    const BIOMETRIC_DEBOUNCE_MS = 2000; // Prevent multiple prompts within 2 seconds
    let appStateCycle = 0; // Tracks background/foreground cycles to avoid double prompts per resume
    let lastPromptedCycle = -1;

    const sub = AppState.addEventListener('change', async (state) => {
      if (state === 'background' || state === 'inactive') {
        lastInactiveAtRef.current = Date.now();
        appStateCycle += 1;
      }

      if (state === 'active') {
        const currentCycle = appStateCycle;
        if (lastPromptedCycle === currentCycle) {
          return; // Already prompted for this resume cycle
        }
        const sinceLastBiometric = Date.now() - lastBiometricSuccessRef.current;
        if (sinceLastBiometric < 5000) {
          lastPromptedCycle = currentCycle; // Mark this cycle as satisfied
          return;
        }
        try {
          const creds = await Keychain.getGenericPassword({
            service: AUTH_KEYCHAIN_SERVICE,
            username: AUTH_KEYCHAIN_USERNAME,
          });
          if (!creds || !creds.password) return;
          const tokens = JSON.parse(creds.password);
          const at = tokens.accessToken;
          const rt = tokens.refreshToken;
          if (!at || !rt) return;
          const decoded: any = jwtDecode(at);
          const now = Math.floor(Date.now() / 1000);
          if ((decoded?.exp ?? 0) <= now + 30) {
            // Retrieve current active context to preserve session state
            let contextArgs = {};
            try {
              const activeCtx = await AuthService.getInstance().getActiveAccountContext();
              if (activeCtx) {
                contextArgs = {
                  accountType: activeCtx.type,
                  accountIndex: activeCtx.index,
                  businessId: activeCtx.businessId
                };
              }
            } catch (err) {
            }

            const { data } = await apolloClient.mutate({
              mutation: REFRESH_TOKEN,
              variables: {
                refreshToken: rt,
                ...contextArgs
              },
              context: { skipAuth: true },
            });
            const newAccess = data?.refreshToken?.token;
            if (newAccess) {
              await Keychain.setGenericPassword(
                AUTH_KEYCHAIN_USERNAME,
                JSON.stringify({ accessToken: newAccess, refreshToken: rt }),
                {
                  service: AUTH_KEYCHAIN_SERVICE,
                  username: AUTH_KEYCHAIN_USERNAME,
                  accessible: Keychain.ACCESSIBLE.AFTER_FIRST_UNLOCK,
                }
              );
            }
          }

          // Require biometric on resume if user was away for a bit
          const lastInactive = lastInactiveAtRef.current;
          const awayMs = lastInactive ? Date.now() - lastInactive : 0;
          const timeSinceLastAuth = Date.now() - lastAuthAttempt;

          // Only prompt if authenticated, was away > 10s, not currently authenticating, and debounce passed
          if (isAuthenticated && awayMs > 10000 && !isAuthenticating && timeSinceLastAuth > BIOMETRIC_DEBOUNCE_MS) {
            const supported = await biometricAuthService.isSupported();
            const enabled = await biometricAuthService.isEnabled();

            if (supported && enabled) {
              isAuthenticating = true;
              lastAuthAttempt = Date.now();
              lastPromptedCycle = currentCycle;
              const ok = await biometricAuthService.authenticate('Desbloquea Confío');
              isAuthenticating = false;

              if (!ok) {
                Alert.alert(
                  'Confirma con biometría',
                  Platform.OS === 'ios' ? 'Usa Face ID o Touch ID para continuar.' : 'Usa tu huella digital para continuar.'
                );
                setIsAuthenticated(false);
                setProfileData(null);
                navigateToScreen('Auth');
                return;
              }
              if (ok) {
                lastBiometricSuccessRef.current = Date.now();
              }
            }
          }
        } catch (e) {
          isAuthenticating = false;
          console.error('[AuthContext] Refresh-on-resume failed:', e);
        }
      }
    });
    return () => sub.remove();
  }, [apolloClient, isAuthenticated]);

  // Enforce biometric enrollment on supported devices; returns if enrollment is ready
  const enforceBiometricEnrollment = async (options?: { skipRevalidate?: boolean }): Promise<{ ok: boolean; alreadyEnabled: boolean; didAuthenticate: boolean }> => {
    const skipRevalidate = options?.skipRevalidate === true;
    try {
      const supported = await biometricAuthService.isSupported();
      if (!supported) return { ok: true, alreadyEnabled: true, didAuthenticate: false };

      const alreadyEnabled = await biometricAuthService.isEnabled();
      if (alreadyEnabled) {
        if (skipRevalidate) {
          return { ok: true, alreadyEnabled: true, didAuthenticate: false };
        }
        // Re-validate in case biometrics were disabled in device settings
        const stillValid = await biometricAuthService.authenticate(
          'Valida tu biometría para continuar',
          true,
          true
        );
        if (stillValid) {
          lastBiometricSuccessRef.current = Date.now();
          return { ok: true, alreadyEnabled: true, didAuthenticate: true };
        }
        await biometricAuthService.disable();
      }

      const enabledNow = await biometricAuthService.enable();
      if (!enabledNow) {
        Alert.alert(
          'Autenticación requerida',
          Platform.OS === 'ios' ? 'Necesitamos tu autenticación (Biometría o Código) para proteger tus operaciones críticas.' : 'Necesitamos tu autenticación (Biometría, PIN o Patrón) para proteger tus operaciones críticas.',
          [{ text: 'OK' }]
        );
        return { ok: false, alreadyEnabled: false, didAuthenticate: false };
      }
      // enable() already performed a biometric prompt, so avoid prompting again
      lastBiometricSuccessRef.current = Date.now();
      return { ok: true, alreadyEnabled: false, didAuthenticate: true };
    } catch (error) {
      console.error('[AuthContext] Failed to enforce biometric enrollment:', error);
      Alert.alert(
        'Seguridad requerida',
        'No pudimos activar la seguridad. Inténtalo nuevamente.',
        [{ text: 'OK' }]
      );
      return { ok: false, alreadyEnabled: false, didAuthenticate: false };
    }
  };

  // Shared opt-in logic: ensures user has all required asset opt-ins.
  // Called from both fresh login (completeAuthenticatedEntry) and cold start (checkAuthState)
  // so that a silently-failed initial opt-in is retried on subsequent app opens.
  const ensureAssetOptIns = async () => {
    try {
      const GENERATE_OPT_IN_TRANSACTIONS = gql`
        mutation GenerateOptInTransactions {
          generateOptInTransactions {
            success
            error
            transactions
          }
        }
      `;

      const { data } = await apolloClient.mutate({
        mutation: GENERATE_OPT_IN_TRANSACTIONS
      });

      const mutationResult = data?.generateOptInTransactions;
      if (mutationResult?.success && mutationResult?.transactions) {
        // Parse transactions payload defensively; GraphQL JSONString may already be an array
        let transactions: any = mutationResult.transactions;
        if (typeof transactions === 'string') {
          try {
            transactions = JSON.parse(transactions);
          } catch (parseError) {
            console.error('[AuthContext] Failed to parse opt-in transactions payload:', parseError);
            transactions = null;
          }
        }

        if (Array.isArray(transactions) && transactions.length > 0) {
          const { default: algorandService } = await import('../services/algorandService');
          const optInSuccess = await algorandService.processSponsoredOptIn(transactions);

          if (optInSuccess) {
            console.log('[AuthContext] Asset opt-in completed successfully');
          } else {
            console.error('[AuthContext] Auto opt-in failed — will retry on next app open');
          }
        }
        // else: no transactions needed (already opted in) — success
      } else if (mutationResult?.error) {
        console.error('[AuthContext] Failed to generate opt-in transactions:', mutationResult.error);
      }
    } catch (optInError) {
      console.error('[AuthContext] Error during auto opt-in:', optInError);
      // Don't block login/startup even if opt-in fails; will retry on next app open
    }
  };

  // Shared post-auth steps after biometrics are satisfied
  const completeAuthenticatedEntry = async (source: 'login' | 'phoneVerification' | 'resume') => {
    setIsAuthenticated(true);
    await refreshProfile('personal');

    // Ensure FCM token is registered for the user
    try {
      const { default: messagingService } = await import('../services/messagingService');
      await messagingService.ensureTokenRegisteredForCurrentUser();
    } catch (fcmError) {
      console.error('[AuthContext] Failed to register FCM token:', fcmError);
      // Don't block navigation if FCM registration fails
    }

    // Handle auto opt-in after successful auth
    await ensureAssetOptIns();



    // On iOS, Implicitly Report Safety (iCloud Keychain is auto-synced)
    if (Platform.OS === 'ios') {
      import('../services/secureDeterministicWallet').then(({ reportBackupStatus }) => {
        reportBackupStatus('icloud').catch(() => {});
      });
    }

    try { signalAuthReady(); } catch { }
    prefetchUserAccounts(`post-${source}`);
    navigateToScreen('Main');
  };

  const completeBiometricAndEnter = async (source: 'login' | 'phoneVerification' = 'login'): Promise<boolean> => {
    const supported = await biometricAuthService.isSupported();
    if (!supported) {
      Alert.alert('Biometría no disponible', 'Este dispositivo no tiene biometría disponible para proteger tu cuenta.', [{ text: 'OK' }]);
      return false;
    }

    const biometricResult = await enforceBiometricEnrollment();
    if (!biometricResult.ok) {
      return false;
    }

    // If enrollment flow already performed a successful prompt, avoid asking again here
    const authOk = biometricResult.didAuthenticate
      ? true
      : await biometricAuthService.authenticate(
        'Confirma tu biometría para continuar',
        true,
        true
      );
    if (!authOk) {
      Alert.alert('Autenticación requerida', Platform.OS === 'ios' ? 'Confirma con Biometría o Código para continuar.' : 'Confirma con tu biometría o código del dispositivo para continuar.', [{ text: 'OK' }]);
      return false;
    }

    lastBiometricSuccessRef.current = Date.now();
    await completeAuthenticatedEntry(source);
    return true;
  };

  const handleSuccessfulLogin = async (isPhoneVerified: boolean, requiresBackupCompletion: boolean = false) => {
    try {
      if (requiresBackupCompletion) {
        resetAuthStack('BackupCompletion');
        return;
      }

      if (isPhoneVerified) {
        // Route to biometric setup screen; completion will trigger the remaining flow
        resetAuthStack('BiometricSetup', { origin: 'login' as const });
      } else {
        // Don't set isAuthenticated to true yet - keep user in Auth flow
        resetAuthStack('PhoneVerification');
      }
    } catch (error) {
      console.error('Error handling successful login:', error);
      setIsAuthenticated(false);
      setProfileData(null);
      navigateToScreen('Auth');
    }
  };

  const checkAuthState = async () => {
    const checkAuthStateStart = Date.now();
    let shouldKeepLoading = false;
    try {
      // Check for JWT tokens instead of zkLogin data
      const keychainReadStart = Date.now();
      const credentials = await getStoredAuthCredentials();
      perfLog('Keychain.getGenericPassword during checkAuthState', keychainReadStart, {
        hasCredentials: !!credentials,
      });

      if (credentials) {
        try {
          const parseStart = Date.now();
          const tokens = JSON.parse(credentials.password);
          perfLog('JSON.parse stored auth tokens', parseStart);
          const hasValidTokens = tokens.accessToken && tokens.refreshToken;

          if (hasValidTokens) {
            let accessToken = tokens.accessToken;
            const refreshToken = tokens.refreshToken;
            let startupAccountContext: {
              type: 'personal' | 'business';
              index: number;
              businessId?: string;
            } | null = null;

            try {
              startupAccountContext = await AuthService.getInstance().getActiveAccountContext();
            } catch (contextError) {
              console.warn('[AuthContext] Failed to load active account context before startup refresh:', contextError);
            }

            // Show biometric prompt FIRST — it's local and doesn't need a valid token.
            // Token refresh happens in parallel so it's ready by the time biometric completes.
            const biometricStateStart = Date.now();
            const bioEnabled = await biometricAuthService.isEnabled();
            perfLog('biometricAuthService.isEnabled on startup', biometricStateStart, {
              bioEnabled,
            });
            if (bioEnabled) {
              const waitActiveStart = Date.now();
              const appIsActive = await waitForAppToBeActive();
              perfLog('waitForAppToBeActive before startup biometric prompt', waitActiveStart, {
                appIsActive,
              });
              if (!appIsActive) {
                shouldKeepLoading = true;
                setProfileData(null);
                if (!deferredBootstrapOnActiveRef.current) {
                  deferredBootstrapOnActiveRef.current = true;
                  const subscription = AppState.addEventListener('change', (state) => {
                    if (state === 'active') {
                      subscription.remove();
                      deferredBootstrapOnActiveRef.current = false;
                      void checkAuthState();
                    }
                  });
                }
                return;
              }
            }

            // Start token refresh in the background while biometric prompt is shown
            const tokenRefreshPromise = (async () => {
              try {
                const { jwtDecode } = await import('jwt-decode');
                const decodeStart = Date.now();
                const decoded: any = jwtDecode(accessToken);
                perfLog('jwtDecode access token', decodeStart, {
                  exp: decoded?.exp,
                });
                const nowTs = Math.floor(Date.now() / 1000);
                if (!decoded?.exp || decoded.exp <= nowTs + 30) {
                  const { gql } = await import('@apollo/client');
                  const REFRESH_TOKEN = gql`
                    mutation RefreshToken($refreshToken: String!, $accountType: String, $accountIndex: Int, $businessId: ID) {
                      refreshToken(refreshToken: $refreshToken, accountType: $accountType, accountIndex: $accountIndex, businessId: $businessId) {
                        token
                        refreshExpiresIn
                      }
                    }
                  `;
                  const { apolloClient } = await import('../apollo/client');
                  const refreshVariables: Record<string, any> = { refreshToken };
                  if (startupAccountContext) {
                    refreshVariables.accountType = startupAccountContext.type;
                    refreshVariables.accountIndex = startupAccountContext.index;
                    if (startupAccountContext.businessId) {
                      refreshVariables.businessId = startupAccountContext.businessId;
                    }
                  }
                  const refreshStart = Date.now();
                  const { data } = await apolloClient.mutate({
                    mutation: REFRESH_TOKEN,
                    variables: refreshVariables,
                    context: { skipAuth: true },
                  });
                  perfLog('Startup RefreshToken mutation', refreshStart, {
                    hasToken: !!data?.refreshToken?.token,
                  });
                  if (data?.refreshToken?.token) {
                    accessToken = data.refreshToken.token;
                    const keychainWriteStart = Date.now();
                    await Keychain.setGenericPassword(
                      'auth_tokens',
                      JSON.stringify({ accessToken, refreshToken }),
                      {
                        service: 'com.confio.auth',
                        username: 'auth_tokens',
                        accessible: Keychain.ACCESSIBLE.AFTER_FIRST_UNLOCK,
                      }
                    );
                    perfLog('Persist refreshed access token to Keychain', keychainWriteStart);
                    setAccountContextTick((t) => t + 1);
                  }
                }
              } catch (e) {
                console.error('Pre-navigation refresh failed:', e);
              }
            })();

            // Run biometric auth and token refresh in parallel
            try {
              if (bioEnabled) {
                const startupBiometricStart = Date.now();
                const bioOk = await biometricAuthService.authenticate('Desbloquea Confío');
                perfLog('Startup biometricAuthService.authenticate', startupBiometricStart, {
                  bioOk,
                });
                if (!bioOk) {
                  setIsAuthenticated(false);
                  setProfileData(null);
                  navigateToScreen('Auth');
                  return;
                }
                lastBiometricSuccessRef.current = Date.now();
              }

              // Wait for token refresh to complete before proceeding with account context
              await tokenRefreshPromise;

              const authService = AuthService.getInstance();
              const activeContextStart = Date.now();
              const accountContext = startupAccountContext || await authService.getActiveAccountContext();
              perfLog('AuthService.getActiveAccountContext on startup', activeContextStart, {
                type: accountContext?.type,
                businessId: accountContext?.businessId,
                index: accountContext?.index,
              });
              if (accountContext.type === 'business' && accountContext.businessId) {
                const { SWITCH_ACCOUNT_TOKEN } = await import('../apollo/queries');
                const { apolloClient } = await import('../apollo/client');
                const switchTokenStart = Date.now();
                const { data } = await apolloClient.mutate({
                  mutation: SWITCH_ACCOUNT_TOKEN,
                  variables: {
                    accountType: accountContext.type,
                    accountIndex: accountContext.index,
                    businessId: accountContext.businessId,
                  },
                });
                perfLog('Startup SWITCH_ACCOUNT_TOKEN mutation', switchTokenStart, {
                  hasToken: !!data?.switchAccountToken?.token,
                });
                if (data?.switchAccountToken?.token) {
                  const businessKeychainWriteStart = Date.now();
                  await Keychain.setGenericPassword(
                    'auth_tokens',
                    JSON.stringify({ accessToken: data.switchAccountToken.token, refreshToken }),
                    {
                      service: 'com.confio.auth',
                      username: 'auth_tokens',
                      accessible: Keychain.ACCESSIBLE.AFTER_FIRST_UNLOCK,
                    }
                  );
                  perfLog('Persist business-context access token to Keychain', businessKeychainWriteStart);
                }
              }
            } catch (syncErr) {
              console.error('Failed to sync token to business context before navigation:', syncErr);
            }

            // Require biometric enrollment first, then unlock on app start when session exists
            const enrollmentStart = Date.now();
            const enrollmentResult = await enforceBiometricEnrollment({ skipRevalidate: true });
            perfLog('enforceBiometricEnrollment on startup', enrollmentStart, {
              ok: enrollmentResult.ok,
              alreadyEnabled: enrollmentResult.alreadyEnabled,
              didAuthenticate: enrollmentResult.didAuthenticate,
            });
            if (!enrollmentResult.ok) {
              setIsAuthenticated(false);
              navigateToScreen('Auth');
              setIsLoading(false);
              return;
            }

            const unlockPromptStart = Date.now();
            const biometricOk = bioEnabled
              ? true
              : enrollmentResult.didAuthenticate
                ? true
                : await biometricAuthService.authenticate('Desbloquea Confío');
            perfLog('Fallback startup biometricAuthService.authenticate', unlockPromptStart, {
              biometricOk,
              skippedBecauseBioEnabled: bioEnabled,
              skippedBecauseEnrollmentAuthenticated: enrollmentResult.didAuthenticate,
            });
            if (!biometricOk) {
              Alert.alert(
                'Confirma con biometría',
                Platform.OS === 'ios' ? 'Usa Face ID o Touch ID para continuar.' : 'Usa tu huella digital para continuar.',
                [{ text: 'OK' }]
              );
              setIsAuthenticated(false);
              navigateToScreen('Auth');
              setIsLoading(false);
              return;
            }
            lastBiometricSuccessRef.current = Date.now();

            let requiresBackupCompletion = false;
            try {
              const meStart = Date.now();
              const { data } = await apolloClient.query({
                query: GET_ME,
                fetchPolicy: 'network-only',
              });
              perfLog('GET_ME during startup auth checkpoint', meStart, {
                requiresBackupCompletion: !!data?.me?.requiresBackupCompletion,
              });
              const me = data?.me || null;
              setProfileData(me ? {
                userProfile: me,
                businessProfile: undefined,
                currentAccountType: 'personal'
              } : null);
              requiresBackupCompletion = !!me?.requiresBackupCompletion;
            } catch (profileErr) {
            }

            if (requiresBackupCompletion) {
              setIsAuthenticated(false);
              resetAuthStack('BackupCompletion');
              setIsLoading(false);
              return;
            }

            // Mark authenticated and go to Main immediately to avoid splash hanging
            setIsAuthenticated(true);
            // Do NOT signal authReady here on cold resume; signal after token is aligned to stored context
            navigateToScreen('Main');

            // Fire-and-forget: retry asset opt-ins in case they failed on initial login
            ensureAssetOptIns().catch(() => {});

            // Fire-and-forget prefetch of accounts to warm ProfileMenu
            (async () => {
              try {
                const { GET_USER_ACCOUNTS } = await import('../apollo/queries');
                const prefetchStart = Date.now();
                await apolloClient.query({ query: GET_USER_ACCOUNTS, fetchPolicy: 'network-only' });
                perfLog('Prefetch userAccounts after navigating to Main', prefetchStart);
              } catch (prefetchErr) {}
            })();
          } else {
            setIsAuthenticated(false);
            navigateToScreen('Auth');
          }
        } catch (parseError) {
          console.error('Error parsing stored tokens:', parseError);
          setIsAuthenticated(false);
          navigateToScreen('Auth');
        }
      } else {
        setIsAuthenticated(false);
        navigateToScreen('Auth');
      }
    } catch (error) {
      console.error('Error checking auth state:', error);
      setIsAuthenticated(false);
      navigateToScreen('Auth');
    } finally {
      perfLog('checkAuthState total', checkAuthStateStart, {
        finalIsAuthenticated: isAuthenticated,
      });
      if (!shouldKeepLoading) {
        setIsLoading(false);
      }
    }
  };

  const checkLocalAuthState = async (): Promise<boolean> => {
    try {
      // Check for JWT tokens instead of zkLogin data
      const credentials = await getStoredAuthCredentials();

      if (credentials) {
        const tokens = JSON.parse(credentials.password);
        const hasValidTokens = tokens.accessToken && tokens.refreshToken;
        setIsAuthenticated(hasValidTokens);
        return hasValidTokens;
      } else {
        setIsAuthenticated(false);
        return false;
      }
    } catch (error) {
      console.error('Error checking local auth state:', error);
      setIsAuthenticated(false);
      return false;
    }
  };

  const signOut = async () => {
    try {
      resetAuthReady();
      const authService = AuthService.getInstance();
      await authService.signOut();
      setIsAuthenticated(false);
      setProfileData(null);
      navigateToScreen('Auth');
    } catch (error) {
      console.error('Error signing out:', error);
      resetAuthReady();
      setIsAuthenticated(false);
      setProfileData(null);
    }
  };

  const completePhoneVerification = async () => {
    try {
      // After phone verification, send user to biometric setup flow
      if (isNavigationReady && navigationRef.current) {
        navigationRef.current.reset({
          index: 0,
          routes: [
            {
              name: 'Auth',
              params: {
                screen: 'BiometricSetup',
                params: { origin: 'phoneVerification' as const },
              },
            },
          ],
        });
      }
    } catch (error) {
      console.error('Error completing phone verification:', error);
    }
  };



  return (
    <AuthContext.Provider value={{
      isAuthenticated,
      isLoading,
      signOut,
      checkLocalAuthState,
      handleSuccessfulLogin,
      completePhoneVerification,
      completeBiometricAndEnter,
      profileData,
      isProfileLoading,
      refreshProfile,
      userProfile: profileData?.userProfile,
      isUserProfileLoading: isProfileLoading && profileData?.currentAccountType === 'personal',
      accountContextTick,
    }}>
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};
const isExpiredCredentialsError = (error: any): boolean => {
  const msg = (error?.message || error?.toString?.() || '').toString().toLowerCase();
  return msg.includes('credentials were refreshed') && msg.includes('expired');
};
