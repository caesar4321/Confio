import { ApolloClient, InMemoryCache, createHttpLink, from, FetchResult } from '@apollo/client';
import { onError, ErrorResponse } from '@apollo/client/link/error';
import { setContext } from '@apollo/client/link/context';
import * as Keychain from 'react-native-keychain';
import { AUTH_KEYCHAIN_SERVICE, AUTH_KEYCHAIN_USERNAME } from '../services/authService';
import { jwtDecode } from 'jwt-decode';
import { getApiUrl } from '../config/env';
import { gql } from '@apollo/client';
import { Observable as ApolloObservable } from '@apollo/client/utilities';

interface CustomJwtPayload {
  user_id: number;
  username: string;
  exp: number;
  origIat: number;
  auth_token_version: number;
  type: 'access' | 'refresh';
}

const REFRESH_TOKEN = gql`
  mutation RefreshToken($refreshToken: String!) {
    refreshToken(refreshToken: $refreshToken) {
      success
      error
      authAccessToken
    }
  }
`;
  
  const httpLink = createHttpLink({
  uri: getApiUrl(),
  });

let isRefreshing = false;
let pendingRequests: any[] = [];

const processQueue = (error: any = null, token: string | null = null) => {
  pendingRequests.forEach(callback => {
    if (error) {
      callback(error);
    } else {
      callback(token);
    }
  });
  pendingRequests = [];
};

const errorLink = onError(({ graphQLErrors, networkError, operation, forward }: ErrorResponse): void | ApolloObservable<FetchResult> => {
    if (graphQLErrors) {
    for (const err of graphQLErrors) {
      console.error('[GraphQL error]:', {
        message: err.message,
        locations: err.locations,
        path: err.path,
        extensions: err.extensions,
        operation: operation.operationName
      });

      if (err.message === 'Signature has expired') {
        // Token has expired, try to refresh
        if (!isRefreshing) {
          isRefreshing = true;
          
          return new ApolloObservable<FetchResult>((observer) => {
            (async () => {
              try {
                const credentials = await Keychain.getGenericPassword({
                  service: AUTH_KEYCHAIN_SERVICE,
                  accessible: Keychain.ACCESSIBLE.WHEN_UNLOCKED
                });
                
                if (!credentials) {
                  throw new Error('No refresh token found');
                }

                const refreshToken = credentials.password;
                const decoded = jwtDecode<CustomJwtPayload>(refreshToken);
                
                if (decoded.type !== 'refresh') {
                  throw new Error('Invalid refresh token type');
                }

                const { data } = await apolloClient.mutate({
                  mutation: REFRESH_TOKEN,
                  variables: { refreshToken }
                });

                if (data?.refreshToken?.success && data?.refreshToken?.auth_access_token) {
                  // Store new access token
                  await Keychain.setGenericPassword(
                    AUTH_KEYCHAIN_USERNAME,
                    data.refreshToken.auth_access_token,
                    {
                      service: AUTH_KEYCHAIN_SERVICE,
                      accessible: Keychain.ACCESSIBLE.WHEN_UNLOCKED
                    }
                  );
                  
                  processQueue(null, data.refreshToken.auth_access_token);
                  forward(operation).subscribe(observer);
                } else {
                  throw new Error(data?.refreshToken?.error || 'Failed to refresh token');
                }
              } catch (error) {
                processQueue(error);
                // Clear tokens and return to login
                await Keychain.resetGenericPassword({ service: AUTH_KEYCHAIN_SERVICE });
                forward(operation).subscribe(observer);
              } finally {
                isRefreshing = false;
              }
            })();
          });
        } else {
          // Add request to pending queue
          return new ApolloObservable<FetchResult>((observer) => {
            pendingRequests.push((token: string | null) => {
              if (token) {
                forward(operation).subscribe(observer);
              } else {
                forward(operation).subscribe(observer);
              }
            });
          });
        }
      }
    }
    }
    if (networkError) {
    console.error('[Network error]:', networkError);
  }
});

const authLink = setContext(async (operation, { headers }) => {
  console.log('AuthLink called for operation:', operation.operationName);

  // Skip token refresh for the refresh token mutation itself
  if (operation.operationName === 'RefreshToken') {
    console.log('Skipping token refresh for RefreshToken operation');
    return { headers };
  }

  try {
    console.log('Attempting to retrieve tokens from Keychain:', {
      service: AUTH_KEYCHAIN_SERVICE,
      username: AUTH_KEYCHAIN_USERNAME
  });

    const credentials = await Keychain.getGenericPassword({
      service: AUTH_KEYCHAIN_SERVICE,
      accessible: Keychain.ACCESSIBLE.WHEN_UNLOCKED
    });

    if (!credentials) {
      console.log('No credentials found in Keychain');
      return { headers };
    }

    console.log('Found credentials in Keychain:', {
      hasPassword: !!credentials.password,
      passwordLength: credentials.password?.length
    });

    let token: string;
    let refreshToken: string;

    try {
      // Parse tokens from JSON
      const tokens = JSON.parse(credentials.password);
      console.log('Parsed tokens:', {
        hasAccessToken: !!tokens.accessToken,
        hasRefreshToken: !!tokens.refreshToken,
        accessTokenLength: tokens.accessToken?.length,
        refreshTokenLength: tokens.refreshToken?.length
      });

      if (!tokens.accessToken || !tokens.refreshToken) {
        throw new Error('Invalid token format');
      }
      token = tokens.accessToken;
      refreshToken = tokens.refreshToken;
    } catch (error) {
      console.error('Error parsing tokens:', error);
      await Keychain.resetGenericPassword({ service: AUTH_KEYCHAIN_SERVICE });
      return { headers };
    }

    // Check if token is expired or about to expire (within 5 minutes)
    try {
      const decoded = jwtDecode<CustomJwtPayload>(token);
      console.log('Decoded token payload:', {
        user_id: decoded.user_id,
        exp: decoded.exp,
        type: decoded.type,
        currentTime: Date.now() / 1000
      });
      
      const currentTime = Date.now() / 1000;
      const fiveMinutes = 5 * 60; // 5 minutes in seconds
      
      if (decoded.exp && (decoded.exp < currentTime || decoded.exp - currentTime < fiveMinutes)) {
        console.log('Token expired or about to expire, refreshing...');
        
        // Only refresh if we're not already refreshing
        if (!isRefreshing) {
          isRefreshing = true;
          
          try {
            const { data } = await apolloClient.mutate({
              mutation: REFRESH_TOKEN,
              variables: { refreshToken }
            });

            if (data?.refreshToken?.success && data?.refreshToken?.authAccessToken) {
              // Store new tokens in JSON format
              await Keychain.setGenericPassword(
                AUTH_KEYCHAIN_USERNAME,
                JSON.stringify({
                  accessToken: data.refreshToken.authAccessToken,
                  refreshToken // Keep the same refresh token
                }),
                {
                  service: AUTH_KEYCHAIN_SERVICE,
                  accessible: Keychain.ACCESSIBLE.WHEN_UNLOCKED
                }
              );
              
              // Use the new token for this request
    return {
      headers: {
        ...headers,
                  Authorization: `JWT ${data.refreshToken.authAccessToken}`,
                },
              };
            } else {
              throw new Error(data?.refreshToken?.error || 'Failed to refresh token');
            }
          } catch (error) {
            console.error('Token refresh failed:', error);
            // Clear tokens and return to login
            await Keychain.resetGenericPassword({ service: AUTH_KEYCHAIN_SERVICE });
            return { headers };
          } finally {
            isRefreshing = false;
          }
        } else {
          // If we're already refreshing, wait for the refresh to complete
          return new Promise((resolve) => {
            pendingRequests.push((token: string | null) => {
              if (token) {
                resolve({
                  headers: {
                    ...headers,
                    Authorization: `JWT ${token}`,
                  },
                });
              } else {
                resolve({ headers });
              }
            });
          });
        }
      }

      // Verify token has required fields
      if (!decoded.user_id || decoded.type !== 'access') {
        console.error('Token missing required fields or wrong type:', {
          hasUserId: !!decoded.user_id,
          type: decoded.type
        });
        await Keychain.resetGenericPassword({ service: AUTH_KEYCHAIN_SERVICE });
        return { headers };
      }

      // Always include the token in the header for authenticated requests
      console.log('Including JWT token in request header');
      return {
        headers: {
          ...headers,
          Authorization: `JWT ${token}`,
        },
      };
    } catch (e) {
      console.error('Error decoding token:', e);
      await Keychain.resetGenericPassword({ service: AUTH_KEYCHAIN_SERVICE });
      return { headers };
    }
  } catch (error) {
    console.error('Error retrieving token:', error);
    return { headers };
  }
});

export const apolloClient = new ApolloClient({
  link: from([errorLink, authLink, httpLink]),
    cache: new InMemoryCache(),
    defaultOptions: {
      watchQuery: {
        fetchPolicy: 'network-only',
      },
    },
  }); 

  console.log('Apollo client initialized successfully');

export default apolloClient; 