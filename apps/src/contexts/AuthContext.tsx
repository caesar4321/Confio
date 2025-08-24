import React, { createContext, useContext, useState, useEffect, RefObject } from 'react';
import { AuthService } from '../services/authService';
import { NavigationContainerRef } from '@react-navigation/native';
import { RootStackParamList } from '../types/navigation';
import { useApolloClient, gql } from '@apollo/client';
import * as Keychain from 'react-native-keychain';
import { jwtDecode } from 'jwt-decode';
import { AppState } from 'react-native';
import { AUTH_KEYCHAIN_SERVICE, AUTH_KEYCHAIN_USERNAME } from '../apollo/client';
import { GET_ME, GET_BUSINESS_PROFILE } from '../apollo/queries';
import { pushNotificationService } from '../services/pushNotificationService';

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
  profileData: ProfileData | null;
  isProfileLoading: boolean;
  refreshProfile: (accountType?: 'personal' | 'business', businessId?: string) => Promise<void>;
  // Direct access to user profile for backward compatibility
  userProfile?: UserProfile;
  isUserProfileLoading: boolean;
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
  const apolloClient = useApolloClient();

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
      checkAuthState();
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
        
        // Check phone verification status from server
        const serverPhoneVerified = data?.me?.phoneNumber && data?.me?.phoneCountry;
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
        
        setProfileData({
          userProfile: data?.me || null,
          businessProfile: undefined,
          currentAccountType: 'personal'
        });
      } else if (accountType === 'business' && businessId) {
        // Fetch only business profile in business context
        const { data } = await apolloClient.query({
          query: GET_BUSINESS_PROFILE,
          variables: { businessId },
          fetchPolicy: 'network-only',
        });
        setProfileData({
          userProfile: undefined,
          businessProfile: data?.business || null,
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
        } catch (error) {
          console.error('Error determining account type for profile loading:', error);
          // Fallback to personal profile
          await refreshProfile('personal');
        }
      } else {
        setProfileData(null);
      }
    };
    
    loadProfileForCurrentAccount();
  }, [isAuthenticated]);

  // Refresh on resume to ensure valid access token before UI queries
  useEffect(() => {
    const sub = AppState.addEventListener('change', async (state) => {
      if (state === 'active') {
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
        } catch (e) {
          console.error('[AuthContext] Refresh-on-resume failed:', e);
        }
      }
    });
    return () => sub.remove();
  }, [apolloClient]);

  const handleSuccessfulLogin = async (isPhoneVerified: boolean) => {
    try {
      console.log('Handling successful login...');
      if (isPhoneVerified) {
        console.log('User has verified phone number');
        setIsAuthenticated(true);
        await refreshProfile('personal'); // Refresh personal profile after successful login
        
        // Ensure FCM token is registered for the new user
        console.log('[AuthContext] Registering FCM token for logged in user...');
        try {
          const { default: messagingService } = await import('../services/messagingService');
          await messagingService.ensureTokenRegisteredForCurrentUser();
        } catch (fcmError) {
          console.error('[AuthContext] Failed to register FCM token:', fcmError);
          // Don't block login if FCM registration fails
        }
        
        navigateToScreen('Main');
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

            // Only now mark authenticated and go to Main
            setIsAuthenticated(true);
            navigateToScreen('Main');
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
      
      // With Web3Auth, phone verification completion should be handled by the backend
      // We just need to set the authentication state and navigate to Main
      setIsAuthenticated(true);
      await refreshProfile('personal');
      
      // Ensure FCM token is registered after phone verification
      console.log('[AuthContext] Registering FCM token after phone verification...');
      try {
        const { default: messagingService } = await import('../services/messagingService');
        await messagingService.ensureTokenRegisteredForCurrentUser();
      } catch (fcmError) {
        console.error('[AuthContext] Failed to register FCM token:', fcmError);
        // Don't block navigation if FCM registration fails
      }
      
      navigateToScreen('Main');
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
      profileData, 
      isProfileLoading, 
      refreshProfile,
      userProfile: profileData?.userProfile,
      isUserProfileLoading: isProfileLoading && profileData?.currentAccountType === 'personal'
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
