import { ApolloClient, InMemoryCache, createHttpLink, from } from '@apollo/client';
import { setContext } from '@apollo/client/link/context';
import { onError } from '@apollo/client/link/error';
import auth from '@react-native-firebase/auth';
import { Platform } from 'react-native';

const getApiUrl = () => {
  if (__DEV__) {
    return Platform.OS === 'ios' 
      ? 'http://localhost:8000/graphql'
      : 'http://10.0.2.2:8000/graphql';
  }
  return 'https://confio.lat/graphql';
};

const apiUrl = getApiUrl();
console.log('Using API URL:', apiUrl);

const httpLink = createHttpLink({
  uri: apiUrl,
  credentials: 'include',
});

const authLink = setContext(async (_, { headers }) => {
  try {
    const token = await auth().currentUser?.getIdToken();
    console.log('Auth token:', token ? 'Present' : 'Not present');
    return {
      headers: {
        ...headers,
        authorization: token ? `Bearer ${token}` : '',
      },
    };
  } catch (error) {
    console.error('Error getting auth token:', error);
    return { headers };
  }
});

const errorLink = onError(({ graphQLErrors, networkError, operation }) => {
  console.log('GraphQL Operation:', operation.operationName);
  if (graphQLErrors) {
    graphQLErrors.forEach(({ message, locations, path }) =>
      console.log(
        `[GraphQL error]: Message: ${message}, Location: ${locations}, Path: ${path}`,
      ),
    );
  }
  if (networkError) {
    console.log(`[Network error]: ${networkError}`);
    console.log('Network error details:', {
      message: networkError.message,
      name: networkError.name,
      stack: networkError.stack,
    });
  }
});

const client = new ApolloClient({
  link: from([errorLink, authLink, httpLink]),
  cache: new InMemoryCache(),
  defaultOptions: {
    watchQuery: {
      fetchPolicy: 'network-only',
    },
  },
});

export default client; 