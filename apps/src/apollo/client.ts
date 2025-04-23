import { ApolloClient, InMemoryCache, createHttpLink } from '@apollo/client';
import { setContext } from '@apollo/client/link/context';
import { getApiUrl } from '../config/env';

let apolloClient: ApolloClient<any> | null = null;

// Create a function to initialize the Apollo client
export const createApolloClient = () => {
  const uri = getApiUrl();
  
  const httpLink = createHttpLink({
    uri,
  });

  const authLink = setContext((_operation, prevContext) => {
    const { headers = {} } = prevContext;
    return {
      headers: {
        ...headers,
        // Add any auth headers here if needed
      }
    };
  });

  const client = new ApolloClient({
    link: authLink.concat(httpLink),
    cache: new InMemoryCache(),
  }); 

  return client;
};

// Export a function to get the Apollo client
export const getApolloClient = () => {
  if (!apolloClient) {
    apolloClient = createApolloClient();
  }
  return apolloClient;
};

// Initialize the Apollo client immediately
try {
  apolloClient = createApolloClient();
} catch (error) {
  console.error('Failed to initialize Apollo client:', error);
}

// Export the apolloClient variable
export { apolloClient }; 