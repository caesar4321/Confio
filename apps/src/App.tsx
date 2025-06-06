import React, { useRef } from 'react';
import { enableScreens } from 'react-native-screens';
import { ApolloProvider } from '@apollo/client';
import { NavigationContainer, NavigationContainerRef } from '@react-navigation/native';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { View, ActivityIndicator } from 'react-native';
import apolloClient from './apollo/client';
import { AuthProvider, useAuth } from './contexts/AuthContext';
import { AuthScreen } from './screens/AuthScreen';
import { BottomTabNavigator } from './navigation/BottomTabNavigator';
import PhoneVerificationScreen from './screens/PhoneVerificationScreen';
import LegalDocumentScreen from './screens/LegalDocumentScreen';
import VerificationScreen from './screens/VerificationScreen';

// Enable screens before any navigation setup
enableScreens();

type RootStackParamList = {
  Auth: undefined;
  PhoneVerification: undefined;
  Main: undefined;
  LegalDocument: {
    docType: 'terms' | 'privacy' | 'deletion';
  };
  Verification: undefined;
};

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
      <Stack.Screen name="Auth" component={AuthScreen} />
      <Stack.Screen name="PhoneVerification" component={PhoneVerificationScreen} />
      <Stack.Screen name="Main" component={BottomTabNavigator} />
      <Stack.Screen 
        name="LegalDocument" 
        component={LegalDocumentScreen}
        options={{
          headerShown: false,
        }}
      />
      <Stack.Screen 
        name="Verification" 
        component={VerificationScreen}
        options={{
          headerShown: false,
        }}
      />
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
        <Navigation />
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