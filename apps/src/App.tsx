import React, { useRef, useEffect } from 'react';
import { ApolloProvider } from '@apollo/client';
import { NavigationContainer, NavigationContainerRef } from '@react-navigation/native';
import { SafeAreaProvider, SafeAreaView } from 'react-native-safe-area-context';
import { StatusBar, StyleSheet, View, ActivityIndicator, Text } from 'react-native';
import { colors } from './config/theme';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
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
import linking from './navigation/linking'; // Import linking config
import { deepLinkHandler } from './utils/deepLinkHandler';
import { PushNotificationProvider } from './hooks/usePushNotificationContext';
// Dev: attach derivation verifier helper
if (__DEV__) {
  import('./dev/derivationVerifier').catch(() => { });
}

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

  console.log('Rendering navigation stack, isAuthenticated:', isAuthenticated, 'isLoading:', isLoading);

  return (
    <View style={{ flex: 1 }}>
      {/* Always mount the navigator to avoid tree swap on Android */}
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
      {/* Loading overlay — covers navigator while auth resolves, then disappears */}
      {isLoading && (
        <View style={[StyleSheet.absoluteFillObject, { justifyContent: 'center', alignItems: 'center', backgroundColor: '#fff', zIndex: 10 }]}>
          <ActivityIndicator size="large" />
        </View>
      )}
    </View>
  );
};

const AppContent: React.FC = () => {
  useEffect(() => {
    console.log('[App] Bootstrapping messaging handlers before auth');
    messagingService.initialize(false, false).catch(error => {
      console.error('Failed to bootstrap messaging handlers:', error);
    });
  }, []);

  return (
    <SafeAreaProvider>
      {/* Global default status bar; individual screens can override */}
      <StatusBar barStyle="dark-content" backgroundColor="#FFFFFF" translucent={false} />
      {/* Apply bottom safe area globally; leave top to headers/screens */}
      <SafeAreaView style={{ flex: 1, backgroundColor: colors.neutralDark }} edges={['bottom']}>
        <NavigationContainer
          ref={navigationRef}
          linking={linking as any}
          onReady={() => {
            console.log('[App] NavigationContainer ready, wiring deep link handler');
            deepLinkHandler.setNavigation(navigationRef as NavigationContainerRef<any>);
            deepLinkHandler.checkDeferredLinks().catch(error => {
              console.error('[App] Failed to process deferred deep link on navigation ready:', error);
            });
          }}
        >
          <AuthProvider
            navigationRef={navigationRef as any}
          >
            <AccountProvider>
              <CountryProvider>
                <HeaderProvider>
                  <ScanProvider>
                    <PushNotificationProvider>
                      <View style={{ flex: 1 }}>
                        <View style={{ flex: 1 }}>
                          <Navigation />
                        </View>
                      </View>
                    </PushNotificationProvider>
                  </ScanProvider>
                </HeaderProvider>
              </CountryProvider>
            </AccountProvider>
          </AuthProvider>
        </NavigationContainer>
      </SafeAreaView>
    </SafeAreaProvider>
  );
};

const App: React.FC = () => {
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
