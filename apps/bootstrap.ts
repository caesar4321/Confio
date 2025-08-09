// bootstrap.ts - Ensures polyfills are loaded before any other imports
import './src/setup/polyfills';   // URL, crypto, slice, Buffer - MUST be first

// Apollo Client setup and error messages (after polyfills)
import { ApolloClient, InMemoryCache, ApolloProvider } from '@apollo/client';
import { loadErrorMessages, loadDevMessages } from "@apollo/client/dev";
import { getApiUrl } from './src/config/env';

// @ts-ignore
if (__DEV__) {
  // Adds messages only in a dev environment
  loadDevMessages();
  loadErrorMessages();
}

// Create Apollo Client instance
const client = new ApolloClient({
  uri: getApiUrl(),
  cache: new InMemoryCache(),
  defaultOptions: {
    watchQuery: {
      fetchPolicy: 'network-only',
      errorPolicy: 'all',
    },
    query: {
      fetchPolicy: 'network-only',
      errorPolicy: 'all',
    },
    mutate: {
      errorPolicy: 'all',
    },
  },
});

// Import React Native components
import { AppRegistry, Platform, UIManager } from 'react-native';
import { name as appName } from './app.json';
import * as suiUtils from '@mysten/sui/utils';
import { Buffer } from 'buffer';

// Monkey-patch the Sui helpers to use Buffer directly
global.Buffer = Buffer;
suiUtils.fromB64 = (str) => Buffer.from(str, 'base64');
suiUtils.toB64 = (bytes) => Buffer.from(bytes).toString('base64');

// Import App component
import App from './src/App';
import React from 'react';

// Wrap your app with ApolloProvider
const AppWithApollo = () => (
  React.createElement(ApolloProvider, { client: client },
    React.createElement(App, null)
  )
);

// Register the app
AppRegistry.registerComponent(appName, () => AppWithApollo);

// Configure react-native-screens defensively to avoid sheet prop crashes
try {
  // Require lazily so it doesn't throw if not present
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  const Screens = require('react-native-screens');
  // Enable native screens for better performance with native stacks
  Screens.enableScreens(true);
  const cfg = UIManager.getViewManagerConfig('RNSScreen');
  const nativeProps = new Set(Object.keys((cfg && (cfg as any).NativeProps) || {}));
  const supportsSheet = nativeProps.has('sheetLargestUndimmedDetent') || nativeProps.has('sheetLargestUndimmedDetentIndex');
  console.log('[RNScreens] enabled:', Screens.screensEnabled(), 'supportsSheet:', supportsSheet, 'hasViewManager:', !!cfg);
} catch (_e) {
  // If screens isn't available, proceed without enabling it
}

try {
  require('./src/services/backgroundMessaging');
  console.log('Background messaging registered successfully');
} catch (error) {
  console.warn('Failed to register background messaging:', error);
}

// Pre-initialize algosdk to avoid dynamic import delay during sign-in
try {
  const algorandService = require('./src/services/algorandService').default;
  // Trigger initialization but don't await - let it happen in background
  algorandService.preInitialize().catch(console.warn);
  console.log('Algorand SDK pre-initialization started');
} catch (error) {
  console.warn('Failed to pre-initialize Algorand SDK:', error);
}
