/**
 * @format
 */

// MUST be the very first line of your app's entry point:
require("./polyfills.js");

// Enable screens before any other imports
import { enableScreens } from 'react-native-screens';
enableScreens();

// Apollo Client setup and error messages
import { ApolloClient, InMemoryCache, ApolloProvider } from '@apollo/client';
import { loadErrorMessages, loadDevMessages } from "@apollo/client/dev";
import { getApiUrl } from './src/config/env';

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

// Now you can import the rest of your app
import { AppRegistry } from 'react-native';
import { name as appName } from './app.json';
import * as suiUtils from '@mysten/sui/utils';
import { Buffer } from 'buffer';

// Monkey-patch the Sui helpers to use Buffer directly
global.Buffer = Buffer;
suiUtils.fromB64 = (str) => Buffer.from(str, 'base64');
suiUtils.toB64 = (bytes) => Buffer.from(bytes).toString('base64');

// Import App component
import App from './src/App';

// Wrap your app with ApolloProvider
const AppWithApollo = () => (
  <ApolloProvider client={client}>
    <App />
  </ApolloProvider>
);

// Register the app
AppRegistry.registerComponent(appName, () => AppWithApollo);
