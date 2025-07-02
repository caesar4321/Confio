import React, { createContext, useContext, useState, useEffect, RefObject } from 'react';
import { AuthService } from '../services/authService';
import { NavigationContainerRef } from '@react-navigation/native';
import { RootStackParamList } from '../types/navigation';
import { useApolloClient } from '@apollo/client';
import { GET_USER_PROFILE } from '../apollo/queries';

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

interface AuthContextType {
  isAuthenticated: boolean;
  isLoading: boolean;
  signOut: () => Promise<void>;
  checkLocalAuthState: () => Promise<boolean>;
  handleSuccessfulLogin: (isPhoneVerified: boolean) => Promise<void>;
  userProfile: UserProfile | null;
  isUserProfileLoading: boolean;
  refreshUserProfile: () => Promise<void>;
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
  const [userProfile, setUserProfile] = useState<UserProfile | null>(null);
  const [isUserProfileLoading, setIsUserProfileLoading] = useState(false);
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
  };

  // Fetch user profile from server
  const refreshUserProfile = async () => {
    setIsUserProfileLoading(true);
    try {
      const { data } = await apolloClient.query({
        query: GET_USER_PROFILE,
        fetchPolicy: 'network-only',
      });
      setUserProfile(data?.me || null);
    } catch (error) {
      console.error('Error fetching user profile:', error);
      setUserProfile(null);
    } finally {
      setIsUserProfileLoading(false);
    }
  };

  // Fetch user profile after login
  useEffect(() => {
    if (isAuthenticated) {
      refreshUserProfile();
    } else {
      setUserProfile(null);
    }
  }, [isAuthenticated]);

  const handleSuccessfulLogin = async (isPhoneVerified: boolean) => {
    try {
      console.log('Handling successful login...');
      setIsAuthenticated(true);
      await refreshUserProfile();
      if (isPhoneVerified) {
        console.log('User has verified phone number');
        navigateToScreen('Main');
      } else {
        console.log('User needs phone verification');
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
      setUserProfile(null);
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
        
        if (hasRequiredFields) {
          console.log('Valid zkLogin data found');
          setIsAuthenticated(true);
          navigateToScreen('Main');
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
      setUserProfile(null);
      navigateToScreen('Auth');
    } catch (error) {
      console.error('Error signing out:', error);
      setIsAuthenticated(false);
      setUserProfile(null);
    }
  };

  return (
    <AuthContext.Provider value={{ isAuthenticated, isLoading, signOut, checkLocalAuthState, handleSuccessfulLogin, userProfile, isUserProfileLoading, refreshUserProfile }}>
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