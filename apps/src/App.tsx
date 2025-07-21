import React, { useRef } from 'react';
import { enableScreens } from 'react-native-screens';
import { ApolloProvider } from '@apollo/client';
import { NavigationContainer, NavigationContainerRef } from '@react-navigation/native';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { View, ActivityIndicator } from 'react-native';
import apolloClient from './apollo/client';
import { AuthProvider, useAuth } from './contexts/AuthContext';
import { HeaderProvider } from './contexts/HeaderContext';
import { ScanProvider } from './contexts/ScanContext';
import { AccountProvider } from './contexts/AccountContext';
import { CountryProvider } from './contexts/CountryContext';
import { AuthNavigator } from './navigation/AuthNavigator';
import { MainNavigator } from './navigation/MainNavigator';
import { RootStackParamList } from './types/navigation';

// Enable screens before any navigation setup
enableScreens();

const Stack = createNativeStackNavigator<RootStackParamList>();

const Navigation: React.FC = () => {
  const { isAuthenticated, isLoading } = useAuth();
  console.log('Navigation render:', { isAuthenticated, isLoading });

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
        animation: 'none',
        presentation: 'transparentModal'
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
  const navigationRef = useRef<NavigationContainerRef<RootStackParamList>>(null);

  return (
    <NavigationContainer ref={navigationRef}>
      <AuthProvider 
        navigationRef={navigationRef as React.RefObject<NavigationContainerRef<RootStackParamList>>}
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