import React, { createContext, useContext, useState, useEffect, RefObject, useRef } from 'react';
import { Alert, AppState, Platform } from 'react-native';
import { AuthService } from '../services/authService';
import { NavigationContainerRef } from '@react-navigation/native';
import { RootStackParamList } from '../types/navigation';
import { useApolloClient, gql } from '@apollo/client';
import * as Keychain from 'react-native-keychain';
import { jwtDecode } from 'jwt-decode';
import { AUTH_KEYCHAIN_SERVICE, AUTH_KEYCHAIN_USERNAME } from '../apollo/client';
import { GET_ME, GET_BUSINESS_PROFILE } from '../apollo/queries';
import { pushNotificationService } from '../services/pushNotificationService';
import { biometricAuthService } from '../services/biometricAuthService';

// Simple auth readiness gate to coordinate token-dependent queries
let __authReady = false;
const __authReadyResolvers: Array<() => void> = [];
export function signalAuthReady() {
  __authReady = true;
  while (__authReadyResolvers.length) {
    try { __authReadyResolvers.pop()?.(); } catch { }
  }
}
export async function waitForAuthReady() {
  if (__authReady) return;
  await new Promise<void>(res => __authReadyResolvers.push(res));
}

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
  handleSuccessfulLogin: (isPhoneVerified: boolean) => Promise<void>;
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
      console.log('AuthContext - Prefetched userAccounts (' + reason + ')');
    } catch (prefetchErr) {
      console.warn('AuthContext - Failed to prefetch userAccounts (' + reason + '):', prefetchErr);
    }
  };

  // Mutation for token refresh (used on resume)
  const REFRESH_TOKEN = gql`
    mutation RefreshToken($refreshToken: String!) {
      refreshToken(refreshToken: $refreshToken) {
        token
        refreshExpiresIn
      }
    }
  `;

  // Set up navigation ready listener and check auth state
  useEffect(() => {
    if (navigationRef.current) {
      console.log('Navigation is ready, checking auth state...');
      setIsNavigationReady(true);
      if (!bootstrapAuthRanRef.current) {
        bootstrapAuthRanRef.current = true;
        checkAuthState();
      } else {
        console.log('Auth bootstrap already executed; skipping duplicate checkAuthState');
      }
    }
  }, [navigationRef.current]);

  const navigateToScreen = (screenName: keyof RootStackParamList) => {
    console.log(`[NAV] navigateToScreen called for ${screenName}`, {
      isNavigationReady,
      hasNavigationRef: !!navigationRef.current,
      currentRoute: navigationRef.current?.getCurrentRoute()?.name
    });

    if (!isNavigationReady || !navigationRef.current) {
      console.log('[NAV] Navigation not ready yet, queuing navigation');
      // Queue navigation for when ready
      setTimeout(() => {
        if (isNavigationReady && navigationRef.current) {
          console.log(`[NAV] Retrying navigation to ${screenName}`);
          navigateToScreen(screenName);
        }
      }, 100);
      return;
    }

    console.log(`[NAV] Executing navigation to ${screenName}`);

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
        console.log(`[NAV] Navigation reset completed for ${screenName}`);

        // After navigating to Main, process any pending push notifications
        if (screenName === 'Main') {
          console.log('[AuthContext] Navigated to Main, processing pending notifications...');
          setTimeout(() => {
            pushNotificationService.processPendingNotification();
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
          console.log('Profile refresh - Server phone verification status:', serverPhoneVerified);

          // If phone verification was lost on server but user is authenticated, require re-verification
          if (!serverPhoneVerified && isAuthenticated) {
            console.log('Profile refresh - Phone verification lost on server, requiring re-verification');
            setIsAuthenticated(false);
            if (isNavigationReady && navigationRef.current) {
              navigationRef.current.reset({
                index: 0,
                routes: [
                  {
                    name: 'Auth',
                    params: {
                      screen: 'PhoneVerification',
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
          console.warn('AuthContext - Failed to fetch user profile in business mode:', e);
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

          console.log('AuthContext - Loading profile for account type:', accountContext.type);

          // CRITICAL: Sync JWT token with stored active account context on app startup
          // This ensures the JWT has the correct business context after app restart
          if (accountContext.type === 'business' && accountContext.businessId) {
            console.log('AuthContext - Business account detected on startup, syncing JWT token...');
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
                console.log('AuthContext - JWT token synced with business context on startup');
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
                      accessible: Keychain.ACCESSIBLE.WHEN_UNLOCKED
                    }
                  );
                  console.log('AuthContext - Stored updated JWT token with business context');
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
          console.log('[AuthContext] Credentials cleared externally (token invalidated), logging out...');
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
            const { data } = await apolloClient.mutate({
              mutation: REFRESH_TOKEN,
              variables: { refreshToken: rt },
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
                  accessible: Keychain.ACCESSIBLE.WHEN_UNLOCKED,
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

              console.log('[AuthContext] Requesting biometric unlock after', Math.round(awayMs / 1000), 'seconds away');
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
          'Activa tu biometría',
          Platform.OS === 'ios' ? 'Necesitamos Face ID o Touch ID para proteger tus operaciones críticas (envíos, pagos, retiros).' : 'Necesitamos tu huella digital para proteger tus operaciones críticas (envíos, pagos, retiros).',
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
        'Activa tu biometría',
        'No pudimos activar la biometría. Inténtalo nuevamente.',
        [{ text: 'OK' }]
      );
      return { ok: false, alreadyEnabled: false, didAuthenticate: false };
    }
  };

  // Shared post-auth steps after biometrics are satisfied
  const completeAuthenticatedEntry = async (source: 'login' | 'phoneVerification' | 'resume') => {
    setIsAuthenticated(true);
    await refreshProfile('personal');

    // Ensure FCM token is registered for the user
    console.log('[AuthContext] Registering FCM token after auth...');
    try {
      const { default: messagingService } = await import('../services/messagingService');
      await messagingService.ensureTokenRegisteredForCurrentUser();
    } catch (fcmError) {
      console.error('[AuthContext] Failed to register FCM token:', fcmError);
      // Don't block navigation if FCM registration fails
    }

    // Handle auto opt-in after successful auth
    try {
      console.log('[AuthContext] Checking for required asset opt-ins...');

      // Check if user needs opt-ins
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
        // Parse transactions payload defensively; GraphQL JSONString may already be an array in some environments
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
          console.log('[AuthContext] Opt-in transactions needed, processing...');
          const { default: algorandService } = await import('../services/algorandService');
          const optInSuccess = await algorandService.processSponsoredOptIn(transactions);

          if (optInSuccess) {
            console.log('[AuthContext] Auto opt-in completed successfully');
          } else {
            console.error('[AuthContext] Auto opt-in failed');
          }
        } else {
          console.log('[AuthContext] No opt-in transactions returned; user likely already opted in');
        }
      } else if (mutationResult?.success) {
        console.log('[AuthContext] User already opted into all required assets');
      } else {
        console.error('[AuthContext] Failed to generate opt-in transactions:', mutationResult?.error);
      }

    } catch (optInError) {
      console.error('[AuthContext] Error during auto opt-in:', optInError);
      // Don't block login even if backend reports expired credentials; let user proceed
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
      Alert.alert('Biometría requerida', Platform.OS === 'ios' ? 'Confirma con Face ID o Touch ID para continuar.' : 'Confirma con tu huella digital para continuar.', [{ text: 'OK' }]);
      return false;
    }

    lastBiometricSuccessRef.current = Date.now();
    await completeAuthenticatedEntry(source);
    return true;
  };

  const handleSuccessfulLogin = async (isPhoneVerified: boolean) => {
    try {
      console.log('Handling successful login...');
      if (isPhoneVerified) {
        console.log('User has verified phone number');
        // Route to biometric setup screen; completion will trigger the remaining flow
        if (isNavigationReady && navigationRef.current) {
          navigationRef.current.reset({
            index: 0,
            routes: [
              {
                name: 'Auth',
                params: {
                  screen: 'BiometricSetup',
                  params: { origin: 'login' as const },
                },
              },
            ],
          });
        }
      } else {
        console.log('User needs phone verification');
        // Don't set isAuthenticated to true yet - keep user in Auth flow
        if (isNavigationReady && navigationRef.current) {
          navigationRef.current.reset({
            index: 0,
            routes: [
              {
                name: 'Auth',
                params: {
                  screen: 'PhoneVerification',
                },
              },
            ],
          });
        }
      }
    } catch (error) {
      console.error('Error handling successful login:', error);
      setIsAuthenticated(false);
      setProfileData(null);
      navigateToScreen('Auth');
    }
  };

  const checkAuthState = async () => {
    try {
      console.log('Checking auth state...');

      // Check for JWT tokens instead of zkLogin data
      const Keychain = await import('react-native-keychain');
      const credentials = await Keychain.getGenericPassword({
        service: 'com.confio.auth',
        username: 'auth_tokens'
      });

      console.log('Auth state JWT tokens:', {
        hasCredentials: !!credentials,
        credentialType: typeof credentials
      });

      if (credentials && credentials !== false) {
        try {
          const tokens = JSON.parse(credentials.password);
          const hasValidTokens = tokens.accessToken && tokens.refreshToken;
          console.log('Has valid JWT tokens:', hasValidTokens);

          if (hasValidTokens) {
            // Ensure access token is valid (refresh if needed) BEFORE navigating
            const { jwtDecode } = await import('jwt-decode');
            let accessToken = tokens.accessToken;
            const refreshToken = tokens.refreshToken;
            try {
              const decoded: any = jwtDecode(accessToken);
              const nowTs = Math.floor(Date.now() / 1000);
              if (!decoded?.exp || decoded.exp <= nowTs + 30) {
                // Refresh access token first
                const { gql } = await import('@apollo/client');
                const REFRESH_TOKEN = gql`
                  mutation RefreshToken($refreshToken: String!) {
                    refreshToken(refreshToken: $refreshToken) {
                      token
                      refreshExpiresIn
                    }
                  }
                `;
                const { apolloClient } = await import('../apollo/client');
                const { data } = await apolloClient.mutate({
                  mutation: REFRESH_TOKEN,
                  variables: { refreshToken },
                  context: { skipAuth: true },
                });
                if (data?.refreshToken?.token) {
                  accessToken = data.refreshToken.token;
                  await Keychain.setGenericPassword(
                    'auth_tokens',
                    JSON.stringify({ accessToken, refreshToken }),
                    {
                      service: 'com.confio.auth',
                      username: 'auth_tokens',
                      accessible: Keychain.ACCESSIBLE.WHEN_UNLOCKED,
                    }
                  );
                  setAccountContextTick((t) => t + 1);
                }
              }
            } catch (e) {
              console.error('Pre-navigation refresh failed:', e);
            }

            // Align access token context with active account before navigating
            try {
              const authService = AuthService.getInstance();
              const accountContext = await authService.getActiveAccountContext();
              if (accountContext.type === 'business' && accountContext.businessId) {
                const { SWITCH_ACCOUNT_TOKEN } = await import('../apollo/queries');
                const { apolloClient } = await import('../apollo/client');
                const { data } = await apolloClient.mutate({
                  mutation: SWITCH_ACCOUNT_TOKEN,
                  variables: {
                    accountType: accountContext.type,
                    accountIndex: accountContext.index,
                    businessId: accountContext.businessId,
                  },
                });
                if (data?.switchAccountToken?.token) {
                  // Store new access token with the same refresh token
                  await Keychain.setGenericPassword(
                    'auth_tokens',
                    JSON.stringify({ accessToken: data.switchAccountToken.token, refreshToken }),
                    {
                      service: 'com.confio.auth',
                      username: 'auth_tokens',
                      accessible: Keychain.ACCESSIBLE.WHEN_UNLOCKED,
                    }
                  );
                }
              }
            } catch (syncErr) {
              console.error('Failed to sync token to business context before navigation:', syncErr);
            }

            // Require biometric enrollment first, then unlock on app start when session exists
            const enrollmentResult = await enforceBiometricEnrollment({ skipRevalidate: true });
            if (!enrollmentResult.ok) {
              setIsAuthenticated(false);
              navigateToScreen('Auth');
              setIsLoading(false);
              return;
            }

            const biometricOk = enrollmentResult.didAuthenticate
              ? true
              : await biometricAuthService.authenticate('Desbloquea Confío');
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

            // Mark authenticated and go to Main immediately to avoid splash hanging
            setIsAuthenticated(true);
            // Do NOT signal authReady here on cold resume; signal after token is aligned to stored context
            navigateToScreen('Main');

            // Fire-and-forget prefetch of accounts to warm ProfileMenu
            (async () => {
              try {
                const { GET_USER_ACCOUNTS } = await import('../apollo/queries');
                await apolloClient.query({ query: GET_USER_ACCOUNTS, fetchPolicy: 'network-only' });
                console.log('Prefetched userAccounts after navigating to Main');
              } catch (prefetchErr) {
                console.warn('Failed to prefetch userAccounts (post-nav):', prefetchErr);
              }
            })();
          } else {
            console.log('Invalid token structure');
            setIsAuthenticated(false);
            navigateToScreen('Auth');
          }
        } catch (parseError) {
          console.error('Error parsing stored tokens:', parseError);
          setIsAuthenticated(false);
          navigateToScreen('Auth');
        }
      } else {
        console.log('No JWT tokens found, user not authenticated');
        setIsAuthenticated(false);
        navigateToScreen('Auth');
      }
    } catch (error) {
      console.error('Error checking auth state:', error);
      setIsAuthenticated(false);
      navigateToScreen('Auth');
    } finally {
      setIsLoading(false);
    }
  };

  const checkLocalAuthState = async (): Promise<boolean> => {
    try {
      // Check for JWT tokens instead of zkLogin data
      const Keychain = await import('react-native-keychain');
      const credentials = await Keychain.getGenericPassword({
        service: 'com.confio.auth',
        username: 'auth_tokens'
      });

      if (credentials && credentials !== false) {
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
      console.log('Starting sign out process...');
      const authService = AuthService.getInstance();
      await authService.signOut();
      setIsAuthenticated(false);
      setProfileData(null);
      navigateToScreen('Auth');
    } catch (error) {
      console.error('Error signing out:', error);
      setIsAuthenticated(false);
      setProfileData(null);
    }
  };

  const completePhoneVerification = async () => {
    try {
      console.log('Completing phone verification...');
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
