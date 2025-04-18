/**
 * @format
 */

// MUST be the very first line of your app's entry point:
require("./polyfills.js");

// Apollo Client setup and error messages
import { ApolloClient, InMemoryCache, ApolloProvider } from '@apollo/client';
import { loadErrorMessages, loadDevMessages } from "@apollo/client/dev";

if (__DEV__) {
  // Adds messages only in a dev environment
  loadDevMessages();
  loadErrorMessages();
}

// Create Apollo Client instance
const client = new ApolloClient({
  uri: 'YOUR_GRAPHQL_ENDPOINT', // Replace with your GraphQL endpoint
  cache: new InMemoryCache(),
});

// Now you can import the rest of your app
import { AppRegistry } from 'react-native';
import App from './App';
import { name as appName } from './app.json';

// Wrap your app with ApolloProvider
const AppWithApollo = () => (
  <ApolloProvider client={client}>
    <App />
  </ApolloProvider>
);

AppRegistry.registerComponent(appName, () => AppWithApollo);
