import { ApolloClient, InMemoryCache, createHttpLink } from '@apollo/client';
import { setContext } from '@apollo/client/link/context';
import { getApiUrl } from '../config/env';
import { onError } from '@apollo/client/link/error';

let apolloClient: ApolloClient<any> | null = null;

// Create a function to initialize the Apollo client
export const createApolloClient = () => {
  const uri = getApiUrl();
  console.log('Initializing Apollo client with URI:', uri);
  
  const httpLink = createHttpLink({
    uri,
  });

  // Add error handling
  const errorLink = onError(({ graphQLErrors, networkError }) => {
    if (graphQLErrors) {
      graphQLErrors.forEach(({ message, locations, path }) => {
        console.error(
          `[GraphQL error]: Message: ${message}, Location: ${locations}, Path: ${path}`
        );
      });
    }
    if (networkError) {
      console.error(`[Network error]: ${networkError}`);
      console.error('Network error details:', networkError);
    }
  });

  const authLink = setContext((_operation, prevContext) => {
    const { headers = {} } = prevContext;
    console.log('Setting context with headers:', headers);
    return {
      headers: {
        ...headers,
        // Add any auth headers here if needed
      }
    };
  });

  const client = new ApolloClient({
    link: errorLink.concat(authLink.concat(httpLink)),
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
  console.log('Apollo client initialized successfully');
} catch (error) {
  console.error('Failed to initialize Apollo client:', error);
}

// Export the apolloClient variable
export { apolloClient }; 