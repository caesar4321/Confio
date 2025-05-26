import React, { createContext, useContext, useState, useEffect, RefObject } from 'react';
import { AuthService } from '../services/authService';
import { NavigationContainerRef } from '@react-navigation/native';
import { RootStackParamList } from '../types/navigation';

interface AuthContextType {
  isAuthenticated: boolean;
  isLoading: boolean;
  signOut: () => Promise<void>;
  checkServerSession: () => Promise<boolean>;
  handleSuccessfulLogin: (isPhoneVerified: boolean) => Promise<void>;
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

  const handleSuccessfulLogin = async (isPhoneVerified: boolean) => {
    try {
      console.log('Handling successful login...');
      setIsAuthenticated(true);
      if (isPhoneVerified) {
        console.log('User has verified phone number');
        navigateToScreen('Main');
      } else {
        console.log('User needs phone verification');
        navigateToScreen('PhoneVerification');
      }
    } catch (error) {
      console.error('Error handling successful login:', error);
      setIsAuthenticated(false);
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

  const checkServerSession = async (): Promise<boolean> => {
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
      navigateToScreen('Auth');
    } catch (error) {
      console.error('Error signing out:', error);
      setIsAuthenticated(false);
    }
  };

  // Set up periodic session checks
  useEffect(() => {
    if (isAuthenticated) {
      const checkInterval = setInterval(async () => {
        const isValid = await checkServerSession();
        if (!isValid) {
          setIsAuthenticated(false);
          clearInterval(checkInterval);
        }
      }, 60000); // Check every minute

      return () => clearInterval(checkInterval);
    }
  }, [isAuthenticated]);

  return (
    <AuthContext.Provider value={{ isAuthenticated, isLoading, signOut, checkServerSession, handleSuccessfulLogin }}>
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