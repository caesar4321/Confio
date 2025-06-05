import { ApolloClient, InMemoryCache, createHttpLink, from } from '@apollo/client';
import { onError } from '@apollo/client/link/error';
import { setContext } from '@apollo/client/link/context';

// Error handling link
const errorLink = onError(({ graphQLErrors, networkError, operation, forward }) => {
  if (graphQLErrors) {
    for (let err of graphQLErrors) {
      console.error(
        `[GraphQL error]: Message: ${err.message}, Location: ${err.locations}, Path: ${err.path}, Code: ${err.extensions?.code}`,
        err
      );

      // Handle specific error codes
      switch (err.extensions?.code) {
        case 'DOCUMENT_TYPE_REQUIRED':
          console.error('Document type is required');
          break;
        case 'INVALID_DOCUMENT_TYPE':
          console.error(`Invalid document type. Valid types are: ${err.extensions?.params?.valid_types?.join(', ')}`);
          break;
        case 'INVALID_DOCUMENT_STRUCTURE':
          console.error('Document structure is invalid');
          break;
        case 'INTERNAL_SERVER_ERROR':
          console.error('An unexpected error occurred');
          break;
        default:
          console.error('An error occurred while fetching the legal document');
      }
    }
  }

  if (networkError) {
    console.error(`[Network error]: ${networkError}`);
  }
});

// HTTP link
const httpLink = createHttpLink({
  uri: process.env.REACT_APP_GRAPHQL_URL || 'http://localhost:8000/graphql/',
});

// Auth link for adding headers
const authLink = setContext((_, { headers }) => {
  // Get the authentication token from local storage if it exists
  const token = localStorage.getItem('token');
  
  // Return the headers to the context so httpLink can read them
  return {
    headers: {
      ...headers,
      authorization: token ? `JWT ${token}` : "",
    }
  };
});

// Create the Apollo Client
const client = new ApolloClient({
  link: from([errorLink, authLink, httpLink]),
  cache: new InMemoryCache(),
  defaultOptions: {
    watchQuery: {
      fetchPolicy: 'cache-and-network',
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

export default client; 