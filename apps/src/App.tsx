import React, { useRef, useEffect } from 'react';
import { ApolloProvider } from '@apollo/client';
import { NavigationContainer, NavigationContainerRef } from '@react-navigation/native';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { View, ActivityIndicator, Text } from 'react-native';
import apolloClient from './apollo/client';
import { AuthProvider, useAuth } from './contexts/AuthContext';
import { HeaderProvider } from './contexts/HeaderContext';
import { ScanProvider } from './contexts/ScanContext';
import { AccountProvider } from './contexts/AccountContext';
import { CountryProvider } from './contexts/CountryContext';
import { AuthNavigator } from './navigation/AuthNavigator';
import { MainNavigator } from './navigation/MainNavigator';
import { RootStackParamList } from './types/navigation';
import { initializeApp } from './services/appInitializer';
import messagingService from './services/messagingService';
import { pushNotificationService } from './services/pushNotificationService';
import { navigationRef } from './navigation/RootNavigation';
import { initializeNotifee } from './services/notifeeConfig';

// Native screens are enabled in bootstrap.ts for better performance

// Initialize app services immediately
console.log('[PERF] App.tsx loaded, initializing app services');
initializeApp();

// Initialize Notifee
initializeNotifee().catch(error => {
  console.error('Failed to initialize Notifee:', error);
});

const Stack = createNativeStackNavigator<RootStackParamList>();

const Navigation: React.FC = () => {
  const { isAuthenticated, isLoading } = useAuth();
  console.log('Navigation render:', { isAuthenticated, isLoading });

  useEffect(() => {
    if (isAuthenticated) {
      // Initialize messaging service when user is authenticated
      // Force token refresh to ensure new users get registered
      console.log('[App] User authenticated, initializing messaging service...');
      messagingService.initialize(true).catch(error => {
        console.error('Failed to initialize messaging service:', error);
      });
      
      // Initialize push notification service
      console.log('[App] Initializing push notification service...');
      pushNotificationService.initialize().catch(error => {
        console.error('Failed to initialize push notification service:', error);
      });
      
      // Also ensure token is registered for the current user
      // This handles the case where permissions are already granted
      messagingService.ensureTokenRegisteredForCurrentUser().catch(error => {
        console.error('Failed to ensure token registration:', error);
      });
    }
  }, [isAuthenticated]);

  if (isLoading) {
    console.log('Showing loading indicator');
    return (
      <View style={{ flex: 1, justifyContent: 'center', alignItems: 'center' }}>
        <ActivityIndicator size="large" />
      </View>
    );
  }

  console.log('Rendering navigation stack, isAuthenticated:', isAuthenticated);
  
  return (
    <Stack.Navigator
      screenOptions={{
        headerShown: false,
        animation: 'none'
      }}
    >
      {!isAuthenticated ? (
        <Stack.Screen name="Auth" component={AuthNavigator} />
      ) : (
        <Stack.Screen name="Main" component={MainNavigator} />
      )}
    </Stack.Navigator>
  );
};

const AppContent: React.FC = () => {
  return (
    <NavigationContainer ref={navigationRef}>
      <AuthProvider 
        navigationRef={navigationRef as any}
      >
        <AccountProvider>
          <CountryProvider>
            <HeaderProvider>
              <ScanProvider>
              <Navigation />
              </ScanProvider>
            </HeaderProvider>
          </CountryProvider>
        </AccountProvider>
      </AuthProvider>
    </NavigationContainer>
  );
};

const App: React.FC = () => {
  console.log('App render, apolloClient:', apolloClient);
  if (!apolloClient) {
    console.error('Apollo client is undefined');
    return null;
  }

  return (
    <ApolloProvider client={apolloClient}>
      <AppContent />
    </ApolloProvider>
  );
};

export default App; 