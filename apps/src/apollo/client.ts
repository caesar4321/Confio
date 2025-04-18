import { ApolloClient, InMemoryCache, createHttpLink } from '@apollo/client';
import { setContext } from '@apollo/client/link/context';
import { getApiUrl } from '../config/env';

const httpLink = createHttpLink({
  uri: getApiUrl(),
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

export const apolloClient = new ApolloClient({
  link: authLink.concat(httpLink),
  cache: new InMemoryCache(),
}); 