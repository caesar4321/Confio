import React, { useEffect, useState } from 'react';
import { ApolloProvider } from '@apollo/client';
import { ApolloClient, NormalizedCacheObject } from '@apollo/client';
import { apolloClient } from './apollo/client';
import { StatusBar } from 'react-native';
import { ThemeProvider } from './theme';
import { AuthProvider } from './contexts/AuthContext';
import { AuthScreen } from './components/auth/AuthScreen';

export default function App() {
  const [client, setClient] = useState<ApolloClient<NormalizedCacheObject> | null>(null);

  useEffect(() => {
    if (apolloClient) {
      setClient(apolloClient);
    }
  }, []);

  if (!client) {
    return null; // Or a loading screen
  }

  return (
    <ApolloProvider client={client}>
      <ThemeProvider>
        <AuthProvider>
          <StatusBar barStyle="dark-content" />
          <AuthScreen />
        </AuthProvider>
      </ThemeProvider>
    </ApolloProvider>
  );
} 