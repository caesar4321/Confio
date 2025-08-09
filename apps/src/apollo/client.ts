import { ApolloClient, InMemoryCache, createHttpLink, from, FetchResult } from '@apollo/client';
import { onError, ErrorResponse } from '@apollo/client/link/error';
import { setContext } from '@apollo/client/link/context';
import * as Keychain from 'react-native-keychain';
import { jwtDecode } from 'jwt-decode';
import { getApiUrl } from '../config/env';
import { gql } from '@apollo/client';
import { Observable as ApolloObservable } from '@apollo/client/utilities';
import { AccountManager } from '../utils/accountManager';

// Extract constants to avoid circular dependency
export const AUTH_KEYCHAIN_SERVICE = 'com.confio.auth';
export const AUTH_KEYCHAIN_USERNAME = 'auth_tokens';

interface CustomJwtPayload {
  user_id: number;
  username: string;
  exp: number;
  origIat: number;
  auth_token_version: number;
  type: 'access' | 'refresh';
  account_type?: string;
  account_index?: number;
  business_id?: string;
}

const REFRESH_TOKEN = gql`
  mutation RefreshToken($refreshToken: String!) {
    refreshToken(refreshToken: $refreshToken) {
      token
      payload
      refreshExpiresIn
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
        operation: operation.operationName,
        variables: operation.variables
      });

      // Handle specific error codes
      if (err.extensions?.code) {
        console.error(`[GraphQL error code]: ${err.extensions.code}`);
      }

      if (err.message === 'Signature has expired' || err.message === 'Invalid payload') {
        // Token has expired or is invalid, try to refresh
        if (!isRefreshing) {
          isRefreshing = true;
          
          return new ApolloObservable<FetchResult>((observer) => {
            (async () => {
              try {
                const credentials = await Keychain.getGenericPassword({
                  service: AUTH_KEYCHAIN_SERVICE,
                  username: AUTH_KEYCHAIN_USERNAME
                });
                
                if (!credentials) {
                  throw new Error('No refresh token found');
                }

                // Parse tokens from JSON
                const tokens = JSON.parse(credentials.password);
                if (!tokens.refreshToken) {
                  throw new Error('No refresh token found in stored data');
                }
                const refreshToken = tokens.refreshToken;
                const decoded = jwtDecode<CustomJwtPayload>(refreshToken);
                
                if (decoded.type !== 'refresh') {
                  throw new Error('Invalid refresh token type');
                }

                // Check if refresh token is expired
                const currentTime = Date.now() / 1000;
                if (decoded.exp && decoded.exp < currentTime) {
                  throw new Error('Refresh token expired');
                }

                const { data } = await apolloClient.mutate({
                  mutation: REFRESH_TOKEN,
                  variables: { refreshToken: refreshToken }
                });

                if (data?.refreshToken?.token) {
                  // Store new access token while keeping the existing refresh token
                  const newTokens = {
                    accessToken: data.refreshToken.token,
                    refreshToken: refreshToken
                  };
                  
                  await Keychain.setGenericPassword(
                    AUTH_KEYCHAIN_USERNAME,
                    JSON.stringify(newTokens),
                    {
                      service: AUTH_KEYCHAIN_SERVICE,
                      username: AUTH_KEYCHAIN_USERNAME,
                      accessible: Keychain.ACCESSIBLE.WHEN_UNLOCKED
                    }
                  );
                  
                  // Add the first request to the queue and process all requests
                  pendingRequests.push((token: string | null) => {
                    if (token) {
                      forward(operation).subscribe(observer);
                    } else {
                      observer.error(new Error('Token refresh failed'));
                    }
                  });
                  processQueue(null, data.refreshToken.token);
                } else {
                  throw new Error('Failed to refresh token');
                }
              } catch (error) {
                processQueue(error);
                // Only clear tokens if refresh token is expired or invalid
                if (error instanceof Error && 
                    (error.message === 'Refresh token expired' || 
                     error.message === 'Invalid refresh token type' ||
                     error.message === 'No refresh token found' ||
                     error.message.includes('Invalid refresh token') ||
                     error.message === 'Invalid payload')) {
                  await Keychain.resetGenericPassword({ 
                    service: AUTH_KEYCHAIN_SERVICE,
                    username: AUTH_KEYCHAIN_USERNAME
                  });
                }
                observer.error(error);
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
                observer.error(new Error('Token refresh failed'));
              }
            });
          });
        }
      }
    }
    }
    if (networkError) {
    console.error('[Network error]:', {
      message: networkError.message,
      name: networkError.name,
      stack: networkError.stack,
      statusCode: (networkError as any).statusCode,
      operation: operation.operationName,
      variables: operation.variables
    });
    
    // Handle specific network error codes
    if ((networkError as any).statusCode === 400) {
      console.error('[400 Bad Request]: The server could not understand the request');
    } else if ((networkError as any).statusCode === 401) {
      console.error('[401 Unauthorized]: Authentication required');
    } else if ((networkError as any).statusCode === 403) {
      console.error('[403 Forbidden]: Access denied');
    } else if ((networkError as any).statusCode === 404) {
      console.error('[404 Not Found]: The requested resource was not found');
    } else if ((networkError as any).statusCode === 500) {
      console.error('[500 Internal Server Error]: Server error occurred');
    }
  }
});

const authLink = setContext(async (operation, previousContext) => {
  console.log('AuthLink called for operation:', operation.operationName);
  
  // Extract headers from previous context
  const { headers = {} } = previousContext || {};

  // Check if we should skip authentication (for login mutations)
  // The custom context is passed through previousContext when using mutation context option
  if (previousContext?.skipAuth) {
    console.log('Skipping authentication for operation:', operation.operationName);
    return { 
      headers: {
        ...headers,
        // Ensure basic headers are always present
        'Content-Type': 'application/json',
      }
    };
  }

  // Skip token refresh for the refresh token mutation itself
  if (operation.operationName === 'RefreshToken') {
    console.log('Skipping token refresh for RefreshToken operation');
    return { 
      headers: {
        ...headers,
        'Content-Type': 'application/json',
      }
    };
  }

  try {
    console.log('Attempting to retrieve tokens from Keychain:', {
      service: AUTH_KEYCHAIN_SERVICE,
      username: AUTH_KEYCHAIN_USERNAME
    });

    const credentials = await Keychain.getGenericPassword({
      service: AUTH_KEYCHAIN_SERVICE,
      username: AUTH_KEYCHAIN_USERNAME
    });

    console.log('Fetched credentials at authLink:', {
      hasCredentials: !!credentials,
      hasPassword: !!credentials?.password,
      passwordLength: credentials?.password?.length,
      operation: operation.operationName
    });

    if (!credentials) {
      console.log('No credentials found in Keychain');
      return { 
        headers: {
          ...headers,
          'Content-Type': 'application/json',
        }
      };
    }

    // Type assertion to handle the false | UserCredentials type
    const userCredentials = credentials as any;
    
    console.log('Found credentials in Keychain:', {
      hasPassword: !!userCredentials.password,
      passwordLength: userCredentials.password?.length
    });

    let token: string;
    let refreshToken: string;

    try {
      // Parse tokens from JSON
      const tokens = JSON.parse(userCredentials.password);
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
      await Keychain.resetGenericPassword({ 
        service: AUTH_KEYCHAIN_SERVICE,
        username: AUTH_KEYCHAIN_USERNAME
      });
      return { 
        headers: {
          ...headers,
          'Content-Type': 'application/json',
        }
      };
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
              variables: { refreshToken: refreshToken }
            });

            if (data?.refreshToken?.token) {
              // Store new tokens in JSON format
              await Keychain.setGenericPassword(
                AUTH_KEYCHAIN_USERNAME,
                JSON.stringify({
                  accessToken: data.refreshToken.token,
                  refreshToken: refreshToken // Keep the existing refresh token
                }),
                {
                  service: AUTH_KEYCHAIN_SERVICE,
                  username: AUTH_KEYCHAIN_USERNAME,
                  accessible: Keychain.ACCESSIBLE.WHEN_UNLOCKED
                }
              );
              
              // Use the new token for this request
              return {
                headers: {
                  ...headers,
                  Authorization: `JWT ${data.refreshToken.token}`
                  // Account context is embedded in the JWT token
                }
              };
            } else {
              throw new Error('Failed to refresh token');
            }
          } catch (error) {
            console.error('Token refresh failed:', error);
            // Only clear tokens if refresh token is expired or invalid
            if (error instanceof Error && 
                (error.message === 'Refresh token expired' || 
                 error.message === 'Invalid refresh token type' ||
                 error.message === 'No refresh token found' ||
                 error.message.includes('Invalid refresh token'))) {
              await Keychain.resetGenericPassword({ 
                service: AUTH_KEYCHAIN_SERVICE,
                username: AUTH_KEYCHAIN_USERNAME
              });
            }
            return { 
              headers: {
                ...headers,
                'Content-Type': 'application/json',
              }
            };
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
                    Authorization: `JWT ${token}`
                    // Account context is embedded in the JWT token
                  }
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
        await Keychain.resetGenericPassword({ 
          service: AUTH_KEYCHAIN_SERVICE,
          username: AUTH_KEYCHAIN_USERNAME
        });
        return { 
          headers: {
            ...headers,
            'Content-Type': 'application/json',
          }
        };
      }

      // Always include the token in the header for authenticated requests
      console.log('Including JWT token in request header');
      
      // Log the token payload to verify account context
      console.log('Token contains account context:', {
        account_type: decoded.account_type || 'not present',
        account_index: decoded.account_index || 'not present',
        business_id: decoded.business_id || 'not present'
      });
      
      return {
        headers: {
          ...headers,
          Authorization: `JWT ${token}`
          // Account context is embedded in the JWT token
        }
      };
    } catch (error) {
      console.error('Error decoding token:', error);
      await Keychain.resetGenericPassword({ 
        service: AUTH_KEYCHAIN_SERVICE,
        username: AUTH_KEYCHAIN_USERNAME
      });
      return { 
        headers: {
          ...headers,
          'Content-Type': 'application/json',
        }
      };
    }
  } catch (error) {
    console.error('Error in authLink:', error);
    return { 
      headers: {
        ...headers,
        'Content-Type': 'application/json',
      }
    };
  }
});

export const apolloClient = new ApolloClient({
  link: from([authLink, errorLink, httpLink]),
  cache: new InMemoryCache(),
  defaultOptions: {
    watchQuery: {
      fetchPolicy: 'network-only',
    },
  },
});

console.log('Apollo client initialized successfully');

export default apolloClient;