import React, { createContext, useContext, useState, useEffect, RefObject } from 'react';
import { AuthService } from '../services/authService';
import { apolloClient } from '../apollo/client';
import { gql } from '@apollo/client';
import { NavigationContainerRef } from '@react-navigation/native';

interface AuthContextType {
  isAuthenticated: boolean;
  isLoading: boolean;
  signOut: () => Promise<void>;
  checkServerSession: () => Promise<boolean>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

const CHECK_SESSION = gql`
  query CheckSession {
    checkSession {
      isValid
      error
    }
  }
`;

type RootStackParamList = {
  Auth: undefined;
  Home: undefined;
};

interface AuthProviderProps {
  children: React.ReactNode;
  navigationRef: RefObject<NavigationContainerRef<RootStackParamList>>;
}

export const AuthProvider = ({ children, navigationRef }: AuthProviderProps) => {
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    checkAuthState();
  }, []);

  // Effect to handle navigation based on auth state
  useEffect(() => {
    if (!isLoading && navigationRef.current) {
      if (isAuthenticated) {
        navigationRef.current.reset({
          index: 0,
          routes: [{ name: 'Home' }],
        });
      } else {
        navigationRef.current.reset({
          index: 0,
          routes: [{ name: 'Auth' }],
        });
      }
    }
  }, [isAuthenticated, isLoading]);

  const checkAuthState = async () => {
    try {
      console.log('Checking auth state...');
      const authService = AuthService.getInstance();
      const zkLoginData = await authService.getStoredZkLoginData();
      console.log('Has zkLogin data:', !!zkLoginData);
      
      if (zkLoginData) {
        const hasRequiredFields = zkLoginData.zkProof && 
                                zkLoginData.salt && 
                                zkLoginData.subject && 
                                zkLoginData.clientId;
        
        if (hasRequiredFields) {
          console.log('Valid zkLogin data found, setting isAuthenticated to true');
          setIsAuthenticated(true);
        } else {
          console.log('Invalid zkLogin data, missing required fields');
          setIsAuthenticated(false);
        }
      } else {
        console.log('No zkLogin data found, setting isAuthenticated to false');
        setIsAuthenticated(false);
      }
    } catch (error) {
      console.error('Error checking auth state:', error);
      setIsAuthenticated(false);
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
    <AuthContext.Provider value={{ isAuthenticated, isLoading, signOut, checkServerSession }}>
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