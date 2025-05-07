import React, { useEffect, useState, useRef } from 'react';
import { enableScreens } from 'react-native-screens';
import { ApolloProvider } from '@apollo/client';
import { ApolloClient, NormalizedCacheObject } from '@apollo/client';
import { NavigationContainer, NavigationContainerRef } from '@react-navigation/native';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { apolloClient } from './apollo/client';
import { StatusBar, View, ActivityIndicator } from 'react-native';
import { ThemeProvider } from './theme';
import { AuthProvider, useAuth } from './contexts/AuthContext';
import { AuthScreen } from './screens/AuthScreen';
import { HomeScreen } from './screens/HomeScreen';

// Enable screens before any navigation setup
enableScreens();

const Stack = createNativeStackNavigator();

// Create a type for our navigation parameters
type RootStackParamList = {
  Auth: undefined;
  Home: undefined;
};

const Navigation = () => {
  const { isAuthenticated, isLoading } = useAuth();
  const navigationRef = useRef<NavigationContainerRef<RootStackParamList>>(null);

  if (isLoading) {
    return (
      <View style={{ flex: 1, justifyContent: 'center', alignItems: 'center' }}>
        <ActivityIndicator size="large" />
      </View>
    );
  }

  return (
    <Stack.Navigator
      initialRouteName={isAuthenticated ? "Home" : "Auth"}
      screenOptions={{
        headerShown: false,
        animation: 'none',
        headerTintColor: '#000000',
      }}
    >
      <Stack.Screen name="Home" component={HomeScreen} />
      <Stack.Screen name="Auth" component={AuthScreen} />
    </Stack.Navigator>
  );
};

export default function App() {
  const [client, setClient] = useState<ApolloClient<NormalizedCacheObject> | null>(null);
  const navigationRef = useRef<NavigationContainerRef<RootStackParamList>>(null);

  useEffect(() => {
    const initializeApollo = async () => {
      try {
        if (apolloClient) {
          setClient(apolloClient);
          console.log('Apollo client initialized successfully');
        } else {
          console.error('Apollo client is null');
        }
      } catch (error) {
        console.error('Failed to initialize Apollo client:', error);
      }
    };

    initializeApollo();
  }, []);

  if (!client) {
    return (
      <View style={{ flex: 1, justifyContent: 'center', alignItems: 'center' }}>
        <ActivityIndicator size="large" color="#0000ff" />
      </View>
    );
  }

  return (
    <ApolloProvider client={client}>
      <ThemeProvider>
        <AuthProvider navigationRef={navigationRef}>
          <NavigationContainer
            ref={navigationRef}
            theme={{
              dark: false,
              colors: {
                background: '#00000000',
                card: '#FFFFFF',
                text: '#000000',
                border: '#000000',
                notification: '#000000',
                primary: '#000000',
              },
              fonts: {
                regular: {
                  fontFamily: 'System',
                  fontWeight: '400',
                },
                medium: {
                  fontFamily: 'System',
                  fontWeight: '500',
                },
                bold: {
                  fontFamily: 'System',
                  fontWeight: '700',
                },
                heavy: {
                  fontFamily: 'System',
                  fontWeight: '900',
                },
              },
            }}
          >
            <StatusBar barStyle="dark-content" />
            <Navigation />
          </NavigationContainer>
        </AuthProvider>
      </ThemeProvider>
    </ApolloProvider>
  );
} 