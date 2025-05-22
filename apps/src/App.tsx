import React, { useRef } from 'react';
import { enableScreens } from 'react-native-screens';
import { ApolloProvider } from '@apollo/client';
import { ApolloClient, NormalizedCacheObject } from '@apollo/client';
import { NavigationContainer, NavigationContainerRef } from '@react-navigation/native';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { apolloClient } from './apollo/client';
import { View, ActivityIndicator } from 'react-native';
import { ThemeProvider } from './theme';
import { AuthProvider, useAuth } from './contexts/AuthContext';
import { AuthScreen } from './screens/AuthScreen';
import { HomeScreen } from './screens/HomeScreen';
import PhoneVerificationScreen from './screens/PhoneVerificationScreen';

// Enable screens before any navigation setup
enableScreens();

type RootStackParamList = {
  Auth: undefined;
  PhoneVerification: undefined;
  Home: undefined;
};

const Stack = createNativeStackNavigator<RootStackParamList>();

function Navigation() {
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
        animation: 'none', // Disable animations for initial screen
        presentation: 'transparentModal' // Use modal presentation to prevent slide animation
      }}
    >
      <Stack.Screen name="Auth" component={AuthScreen} />
      <Stack.Screen name="PhoneVerification" component={PhoneVerificationScreen} />
      <Stack.Screen name="Home" component={HomeScreen} />
    </Stack.Navigator>
  );
}

function AppContent() {
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
  }

export default function App() {
  const [client] = React.useState<ApolloClient<NormalizedCacheObject>>(apolloClient);
  console.log('App render');

  return (
    <ApolloProvider client={client}>
      <ThemeProvider>
        <AppContent />
      </ThemeProvider>
    </ApolloProvider>
  );
} 