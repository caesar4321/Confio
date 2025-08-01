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
    
    console.log(`Navigating to ${screenName}`);
    navigationRef.current.reset({
      index: 0,
      routes: [{ 
        name: screenName,
        params: undefined,
        state: undefined
      }],
    });
    
    // After navigating to Main, process any pending push notifications
    if (screenName === 'Main') {
      console.log('[AuthContext] Navigated to Main, processing pending notifications...');
      setTimeout(async () => {
        await pushNotificationService.processPendingNotification();
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
        
        // Validate phone verification status and sync with zkLogin data
        const serverPhoneVerified = data?.me?.phoneNumber && data?.me?.phoneCountry;
        console.log('Profile refresh - Server phone verification status:', serverPhoneVerified);
        
        try {
          const authService = AuthService.getInstance();
          const zkLoginData = await authService.getStoredZkLoginData();
          
          if (zkLoginData && zkLoginData.isPhoneVerified !== serverPhoneVerified) {
            console.log(`Profile refresh - Syncing zkLogin phone verification: ${zkLoginData.isPhoneVerified} -> ${serverPhoneVerified}`);
            zkLoginData.isPhoneVerified = serverPhoneVerified;
            await authService.storeZkLoginData(zkLoginData);
            
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
      const zkLoginData = await authService.getStoredZkLoginData();
      console.log('Auth state zkLogin data:', JSON.stringify(zkLoginData, null, 2));
      
      if (zkLoginData) {
        const hasRequiredFields = zkLoginData.zkProof && 
                                zkLoginData.salt && 
                                zkLoginData.subject && 
                                zkLoginData.clientId;
        
        console.log('Has required fields:', hasRequiredFields);
        console.log('Is phone verified (from zkLogin):', zkLoginData.isPhoneVerified);
        
        if (hasRequiredFields) {
          if (zkLoginData.isPhoneVerified) {
            console.log('Valid zkLogin data found with verified phone');
            setIsAuthenticated(true);
            navigateToScreen('Main');
          } else {
            console.log('Valid zkLogin data found but phone not verified');
            // Keep user in Auth flow for phone verification
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
          }
        } else {
          console.log('Invalid zkLogin data, missing required fields');
          setIsAuthenticated(false);
          navigateToScreen('Auth');
        }
      } else {
        console.log('No zkLogin data found, setting isAuthenticated to false');
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
      const hasZkLoginData = await authService.getStoredZkLoginData();
      setIsAuthenticated(!!hasZkLoginData);
      return !!hasZkLoginData;
    } catch (error) {
      console.error('Error checking auth state:', error);
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
      
      // Update the stored zkLoginData to mark phone as verified
      const authService = AuthService.getInstance();
      const zkLoginData = await authService.getStoredZkLoginData();
      
      if (zkLoginData) {
        // Update the phone verification status
        zkLoginData.isPhoneVerified = true;
        await authService.storeZkLoginData(zkLoginData);
        console.log('Updated zkLogin data with phone verification status');
      }
      
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