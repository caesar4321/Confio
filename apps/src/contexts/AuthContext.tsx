import React, { createContext, useContext, useState, useEffect, RefObject } from 'react';
import { AuthService } from '../services/authService';
import { NavigationContainerRef } from '@react-navigation/native';
import { RootStackParamList } from '../types/navigation';
import { useApolloClient } from '@apollo/client';
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

  // Set up navigation ready listener and check auth state
  useEffect(() => {
    if (navigationRef.current) {
      console.log('Navigation is ready, checking auth state...');
      setIsNavigationReady(true);
      checkAuthState();
    }
  }, [navigationRef.current]);

  const navigateToScreen = (screenName: keyof RootStackParamList) => {
    if (!isNavigationReady || !navigationRef.current) {
      console.log('Navigation not ready yet, will navigate when ready');
      return;
    }
    
    console.log(`[navigateToScreen] Navigating to ${screenName}`);
    
    // Properly set up params for nested navigators
    const route: any = { name: screenName };
    
    if (screenName === 'Auth') {
      // Auth navigator expects params for its nested screens
      route.params = {
        screen: 'Login'
      };
    } else if (screenName === 'Main') {
      // Main navigator expects params for its nested screens
      route.params = {
        screen: 'BottomTabs',
        params: {
          screen: 'Home'
        }
      };
    }
    
    console.log('[navigateToScreen] Route object:', JSON.stringify(route));
    
    try {
      navigationRef.current.reset({
        index: 0,
        routes: [route],
      });
      console.log('[navigateToScreen] Navigation reset completed successfully');
    } catch (navError) {
      console.error('[navigateToScreen] Navigation reset error:', navError);
      console.error('[navigateToScreen] Error stack:', navError.stack);
    }
    
    // After navigating to Main, process any pending push notifications
    if (screenName === 'Main') {
      console.log('[AuthContext] Navigated to Main, processing pending notifications...');
      setTimeout(() => {
        pushNotificationService.processPendingNotification();
      }, 1000); // Give time for Main navigator to mount
    }
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
        
        // Validate phone verification status and sync with Keyless data
        const serverPhoneVerified = data?.me?.phoneNumber && data?.me?.phoneCountry;
        console.log('Profile refresh - Server phone verification status:', serverPhoneVerified);
        
        try {
          const authService = AuthService.getInstance();
          const keylessData = await authService.getStoredKeylessData();
          
          if (keylessData) {
            // Store phone verification status in the stored data
            const updatedData = {
              ...keylessData,
              isPhoneVerified: serverPhoneVerified
            };
            
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
        } catch (syncError) {
          console.error('Error syncing phone verification status:', syncError);
        }
        
        setProfileData({
          userProfile: data?.me || null,
          businessProfile: undefined,
          currentAccountType: 'personal'
        });
      } else if (accountType === 'business' && businessId) {
        // Fetch business profile
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
          
          if (accountContext.type === 'business') {
            // For business accounts, we need to get the business ID from the server
            // We'll load the personal profile first, then the business profile will be loaded
            // when the account manager loads the accounts from the server
            await refreshProfile('personal');
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

  const handleSuccessfulLogin = async (isPhoneVerified: boolean) => {
    try {
      console.log('Handling successful login...');
      console.log('Phone verified status:', isPhoneVerified);
      
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
      const authService = AuthService.getInstance();
      
      // Initialize auth service
      await authService.initialize();
      
      // Check if there's a stored Keyless account
      const keylessData = await authService.getStoredKeylessData();
      
      if (keylessData) {
        // Check if we have a valid token
        const token = await authService.getToken();
        
        if (token) {
          console.log('Found valid authentication token');
          
          // Validate token with server and get user profile
          try {
            const { data } = await apolloClient.query({
              query: GET_ME,
              fetchPolicy: 'network-only',
            });
            
            if (data?.me) {
              const hasVerifiedPhone = data.me.phoneNumber && data.me.phoneCountry;
              console.log('User profile loaded, phone verified:', hasVerifiedPhone);
              
              if (hasVerifiedPhone) {
                setIsAuthenticated(true);
                setProfileData({
                  userProfile: data.me,
                  businessProfile: undefined,
                  currentAccountType: 'personal'
                });
                navigateToScreen('Main');
              } else {
                console.log('User needs phone verification');
                setIsAuthenticated(false);
                navigateToScreen('Auth');
              }
            } else {
              console.log('No user profile found');
              setIsAuthenticated(false);
              navigateToScreen('Auth');
            }
          } catch (error) {
            console.error('Error validating token:', error);
            setIsAuthenticated(false);
            navigateToScreen('Auth');
          }
        } else {
          console.log('No valid token found');
          setIsAuthenticated(false);
          navigateToScreen('Auth');
        }
      } else {
        console.log('No Keyless data found');
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
      const authService = AuthService.getInstance();
      const keylessData = await authService.getStoredKeylessData();
      const token = await authService.getToken();
      
      return !!(keylessData && token);
    } catch (error) {
      console.error('Error checking local auth state:', error);
      return false;
    }
  };

  const signOut = async () => {
    try {
      setIsLoading(true);
      console.log('[AuthContext] Starting signOut process...');
      
      // Unregister FCM token before signing out
      console.log('[AuthContext] Unregistering FCM token before sign out...');
      try {
        const { default: messagingService } = await import('../services/messagingService');
        await messagingService.unregisterTokenOnSignOut();
      } catch (fcmError) {
        console.error('[AuthContext] Failed to unregister FCM token:', fcmError);
        // Don't block sign out if FCM unregistration fails
      }
      
      console.log('[AuthContext] Calling authService.signOut()...');
      const authService = AuthService.getInstance();
      
      // Call signOut but don't let it fail the whole process
      try {
        await authService.signOut();
        console.log('[AuthContext] authService.signOut() completed');
      } catch (signOutError) {
        console.error('[AuthContext] authService.signOut() error:', signOutError);
        // Continue with logout even if signOut fails
      }
      
      // Clear Apollo cache
      console.log('[AuthContext] Clearing Apollo cache...');
      await apolloClient.clearStore();
      console.log('[AuthContext] Apollo cache cleared');
      
      // Clear all state
      console.log('[AuthContext] Clearing state...');
      setIsAuthenticated(false);
      setProfileData(null);
      
      console.log('[AuthContext] Sign out complete, about to navigate to Auth screen');
      console.log('[AuthContext] navigationRef.current exists:', !!navigationRef.current);
      console.log('[AuthContext] isNavigationReady:', isNavigationReady);
      navigateToScreen('Auth');
      console.log('[AuthContext] navigateToScreen completed');
    } catch (error) {
      console.error('[AuthContext] Error signing out:', error);
      console.error('[AuthContext] Error stack:', error.stack);
      // Force navigation to Auth even if sign out fails
      setIsAuthenticated(false);
      setProfileData(null);
      navigateToScreen('Auth');
    } finally {
      setIsLoading(false);
    }
  };

  const completePhoneVerification = async () => {
    try {
      console.log('Phone verification completed');
      setIsAuthenticated(true);
      await refreshProfile('personal'); // Refresh profile after phone verification
      
      // Register FCM token after phone verification
      console.log('[AuthContext] Registering FCM token after phone verification...');
      try {
        const { default: messagingService } = await import('../services/messagingService');
        await messagingService.ensureTokenRegisteredForCurrentUser();
      } catch (fcmError) {
        console.error('[AuthContext] Failed to register FCM token after phone verification:', fcmError);
        // Don't block the flow if FCM registration fails
      }
      
      navigateToScreen('Main');
    } catch (error) {
      console.error('Error completing phone verification:', error);
      setIsAuthenticated(false);
      navigateToScreen('Auth');
    }
  };

  const value: AuthContextType = {
    isAuthenticated,
    isLoading,
    signOut,
    checkLocalAuthState,
    handleSuccessfulLogin,
    completePhoneVerification,
    profileData,
    isProfileLoading,
    refreshProfile,
    // Backward compatibility - expose user profile directly
    userProfile: profileData?.userProfile,
    isUserProfileLoading: isProfileLoading && profileData?.currentAccountType === 'personal',
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};