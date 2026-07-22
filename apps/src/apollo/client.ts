import { ApolloClient, InMemoryCache, createHttpLink, from, FetchResult, ApolloLink } from '@apollo/client';
import { onError, ErrorResponse } from '@apollo/client/link/error';
import { setContext } from '@apollo/client/link/context';
import * as Keychain from 'react-native-keychain';
import { jwtDecode } from 'jwt-decode';
import { getApiUrl } from '../config/env';
import { gql } from '@apollo/client';
import { Observable as ApolloObservable } from '@apollo/client/utilities';
import { AccountManager } from '../utils/accountManager';
import appCheckService from '../services/appCheckService';

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

// Single-flight refresh mutex shared across links
let refreshPromise: Promise<string> | null = null;

async function getStoredTokens(): Promise<{ accessToken?: string; refreshToken?: string; } | null> {
  try {
    const credentials = await Keychain.getGenericPassword({
      service: AUTH_KEYCHAIN_SERVICE,
      username: AUTH_KEYCHAIN_USERNAME
    });
    if (!credentials) return null;
    const parsed = JSON.parse((credentials as any).password || '{}');
    return { accessToken: parsed.accessToken, refreshToken: parsed.refreshToken };
  } catch (e) {
    return null;
  }
}

async function performRefreshWithFetch(rt: string): Promise<string> {
  const startTime = Date.now();
  const body = {
    query: `mutation RefreshToken($refreshToken: String!) {\n      refreshToken(refreshToken: $refreshToken) {\n        token\n        payload\n        refreshExpiresIn\n      }\n    }`,
    variables: { refreshToken: rt },
  };
  const res = await fetch(getApiUrl(), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' }, // no Authorization
    body: JSON.stringify(body),
  } as any);
  if (res.status === 403) {
    // Raw fetch bypasses the error link; catch the security middleware's
    // ban response here too (it 403s token refresh like everything else).
    const text = await res.text();
    import('../services/emergencyExit/banSignal').then(async ({ looksLikeBanResponse, markBanSignal }) => {
      if (looksLikeBanResponse(403, text)) {
        const { emergencyStore } = await import('../services/emergencyExit/store');
        if (await markBanSignal(emergencyStore)) {
          const { navigate } = await import('../navigation/RootNavigation');
          navigate('BlockedAccount');
        }
      }
    }).catch(() => {});
    throw new Error('Failed to refresh token');
  }
  const json = await res.json();
  const newAccess = json?.data?.refreshToken?.token;
  if (!newAccess) throw new Error('Failed to refresh token');
  await Keychain.setGenericPassword(
    AUTH_KEYCHAIN_USERNAME,
    JSON.stringify({ accessToken: newAccess, refreshToken: rt }),
    {
      service: AUTH_KEYCHAIN_SERVICE,
      username: AUTH_KEYCHAIN_USERNAME,
      accessible: Keychain.ACCESSIBLE.AFTER_FIRST_UNLOCK
    }
  );
  return newAccess as string;
}

function stringifyHeaderValue(value: unknown): string | undefined {
  if (value == null) return undefined;
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function sanitizeHeaders(headers: Record<string, unknown> = {}): Record<string, string> {
  const sanitized: Record<string, string> = {};
  Object.entries(headers || {}).forEach(([key, value]) => {
    const stringValue = stringifyHeaderValue(value);
    if (stringValue !== undefined) {
      sanitized[key] = stringValue;
    }
  });
  return sanitized;
}

// Un-ban detection: any successful GraphQL round-trip proves the security
// middleware let us through, so a previously flagged ban is over. The
// banSignal module's in-memory mirror makes the repeated calls free.
const banClearLink = new ApolloLink((operation, forward) =>
  forward(operation).map((result) => {
    import('../services/emergencyExit/banSignal').then(async ({ clearBanSignal }) => {
      const { emergencyStore } = await import('../services/emergencyExit/store');
      await clearBanSignal(emergencyStore);
    }).catch(() => {});
    return result;
  }),
);

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

      // Check for token version mismatch or invalidation - force logout
      if (err.message === 'Token has been invalidated' ||
        err.message === 'Token version mismatch' ||
        err.message.includes('Invalid token payload')) {
        // Clear stored credentials immediately
        Keychain.resetGenericPassword({ service: AUTH_KEYCHAIN_SERVICE }).catch(console.error);
        // Don't retry - user must log in again
        return;
      }

      if (err.message === 'Signature has expired' || err.message === 'Invalid payload') {
        // Token has expired or is invalid, perform a single-flight refresh
        return new ApolloObservable<FetchResult>((observer) => {
          (async () => {
            try {
              const stored = await getStoredTokens();
              const rt = stored?.refreshToken;
              if (!rt) throw new Error('No refresh token found');

              if (!refreshPromise) {
                refreshPromise = (async () => {
                  try {
                    return await performRefreshWithFetch(rt);
                  } finally {
                    // Do not null here; let awaiters read the resolved token and then clear below
                  }
                })();
              }

              const newToken = await refreshPromise;
              // Clear the promise for next time
              refreshPromise = null;

              // Retry the original operation with new token. Auth link will attach it.
              forward(operation).subscribe(observer);
            } catch (error) {
              // Only clear tokens if refresh token is expired or invalid
              if (error instanceof Error &&
                (error.message.includes('expired') ||
                  error.message.includes('Invalid refresh token') ||
                  error.message.includes('No refresh token found'))) {
                await Keychain.resetGenericPassword({ service: AUTH_KEYCHAIN_SERVICE });
              }
              observer.error(error);
            }
          })();
        });
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
      // Security-middleware ban signature (403 + suspension text): flag it
      // so the emergency exit skips the cooloff — a banned user facing a
      // 24h wait would be a de-facto freeze. Fire-and-forget; can only
      // accelerate the exit, never delay anything.
      const bodyText = (networkError as any).bodyText ?? (networkError as any).result;
      import('../services/emergencyExit/banSignal').then(async ({ looksLikeBanResponse, markBanSignal }) => {
        if (looksLikeBanResponse(403, typeof bodyText === 'string' ? bodyText : networkError.message)) {
          const { emergencyStore } = await import('../services/emergencyExit/store');
          const newlyMarked = await markBanSignal(emergencyStore);
          if (newlyMarked) {
            // Announcement first (BlockedAccountScreen), exit as its CTA —
            // a banned user's normal UI is unusable, so we take them there.
            const { navigate } = await import('../navigation/RootNavigation');
            navigate('BlockedAccount');
          }
        }
      }).catch(() => {});
    } else if ((networkError as any).statusCode === 404) {
      console.error('[404 Not Found]: The requested resource was not found');
    } else if ((networkError as any).statusCode === 500) {
      console.error('[500 Internal Server Error]: Server error occurred');
    }
  }
});

const authLink = setContext(async (operation, previousContext) => {
  // Extract headers from previous context
  const { headers = {} } = previousContext || {};

  // No per-request account override: JWT must always match active account context

  // Initialize headers object
  const nextHeaders: Record<string, string> = {
    ...sanitizeHeaders(headers),
    'Content-Type': 'application/json',
  };

  // 1. ALWAYS Try to attach Firebase App Check header (Public or Private)
  try {
    const appCheckToken = await appCheckService.getTokenForHeader();
    if (appCheckToken) {
      nextHeaders['X-Firebase-AppCheck'] = appCheckToken;
    } else {
      const appCheckDebugError = appCheckService.getLastErrorForDebug();
      if (appCheckDebugError) {
        nextHeaders['X-AppCheck-Debug-Error'] = appCheckDebugError;
      }
    }
  } catch (acError: any) {
    // DEBUG: Send error to backend to see why it failed
    nextHeaders['X-AppCheck-Debug-Error'] = acError?.message || String(acError);
  }

  // Check if we should skip authentication (for login mutations)
  if (previousContext?.skipAuth) {
    return { headers: nextHeaders };
  }

  // Skip token refresh/auth for the refresh token mutation itself
  if (operation.operationName === 'RefreshToken') {
    return { headers: nextHeaders };
  }

  try {
    let credentials;
    try {
      credentials = await Keychain.getGenericPassword({
        service: AUTH_KEYCHAIN_SERVICE,
        username: AUTH_KEYCHAIN_USERNAME
      });
    } catch (keychainError: any) {
      if (keychainError?.message?.includes('No entry found')) {
        credentials = false;
      } else {
        console.error('Keychain error:', keychainError?.message);
        credentials = false;
      }
    }

    if (!credentials) {
      return { headers: nextHeaders };
    }

    // Type assertion to handle the false | UserCredentials type
    const userCredentials = credentials as any;

    let token: string;
    let refreshToken: string;

    try {
      // Parse tokens from JSON
      const tokens = JSON.parse(userCredentials.password);
      if (!tokens.accessToken || !tokens.refreshToken) {
        throw new Error('Invalid token format');
      }
      token = tokens.accessToken;
      refreshToken = tokens.refreshToken;
    } catch (error) {
      console.error('Error parsing tokens:', error);
      await Keychain.resetGenericPassword({
        service: AUTH_KEYCHAIN_SERVICE
      });
      return { headers: nextHeaders };
    }

    // Check if token is expired or about to expire (within 5 minutes)
    try {
      let decoded = jwtDecode<CustomJwtPayload>(token);

      const ctx = (typeof (operation as any).getContext === 'function') ? (operation as any).getContext() : previousContext;
      const hardSkipForAccounts = operation.operationName === 'GetUserAccounts';
      const shouldSkipProactive = hardSkipForAccounts || !!(ctx?.skipProactiveRefresh);

      const currentTime = Date.now() / 1000;
      const fiveMinutes = 5 * 60; // 5 minutes in seconds

      // For GetUserAccounts we do not refresh here; allow request to hit server first
      if (!hardSkipForAccounts && decoded.exp && (decoded.exp < currentTime || decoded.exp - currentTime < fiveMinutes)) {
        try {
          if (!refreshPromise) {
            refreshPromise = (async () => {
              return await performRefreshWithFetch(refreshToken);
            })();
          }
          const newAccess = await refreshPromise;
          refreshPromise = null;

          nextHeaders['Authorization'] = `JWT ${newAccess}`;
          return { headers: nextHeaders };
        } catch (error) {
          console.error('Token refresh failed:', error);
          try { await Keychain.resetGenericPassword({ service: AUTH_KEYCHAIN_SERVICE }); } catch { }
          return { headers: nextHeaders };
        }
      }

      // Verify token has required fields
      if (!decoded.user_id || decoded.type !== 'access') {
        await Keychain.resetGenericPassword({
          service: AUTH_KEYCHAIN_SERVICE,
          username: AUTH_KEYCHAIN_USERNAME
        });
        return { headers: nextHeaders };
      }

      // Proactively refresh if access token is expired or near expiry
      if (hardSkipForAccounts) {
        nextHeaders['Authorization'] = `JWT ${token}`;
        return { headers: nextHeaders } as any;
      }

      if (!shouldSkipProactive) {
        try {
          const now = Math.floor(Date.now() / 1000);
          const exp = (decoded as any)?.exp ?? 0;
          const willExpireSoon = exp <= now + 30; // 30s safety window
          if (willExpireSoon) {
            const credentialsForRefresh = await Keychain.getGenericPassword({
              service: AUTH_KEYCHAIN_SERVICE,
              username: AUTH_KEYCHAIN_USERNAME
            });
            if (credentialsForRefresh && (credentialsForRefresh as any).password) {
              const stored = JSON.parse((credentialsForRefresh as any).password);
              const rt = stored.refreshToken;
              if (rt) {
                const { data } = await apolloClient.mutate({
                  mutation: REFRESH_TOKEN,
                  variables: { refreshToken: rt },
                  context: { skipAuth: true }
                });
                if (data?.refreshToken?.token) {
                  const newAccess = data.refreshToken.token;
                  await Keychain.setGenericPassword(
                    AUTH_KEYCHAIN_USERNAME,
                    JSON.stringify({ accessToken: newAccess, refreshToken: rt }),
                    {
                      service: AUTH_KEYCHAIN_SERVICE,
                      username: AUTH_KEYCHAIN_USERNAME,
                      accessible: Keychain.ACCESSIBLE.AFTER_FIRST_UNLOCK
                    }
                  );
                  // Replace local token/decoded with refreshed values
                  token = newAccess;
                }
              }
            }
          }
        } catch (refreshError) {
          console.error('Proactive refresh error:', refreshError);
        }
      }

      // Always include the token in the header for authenticated requests
      nextHeaders['Authorization'] = `JWT ${token}`;

      return { headers: nextHeaders };

    } catch (error) {
      console.error('Error decoding token:', error);
      await Keychain.resetGenericPassword({
        service: AUTH_KEYCHAIN_SERVICE
      });
      return { headers: nextHeaders };
    }
  } catch (error) {
    console.error('Error in authLink:', error);
    return { headers: nextHeaders };
  }
});

export const apolloClient = new ApolloClient({
  link: from([authLink, errorLink, banClearLink, httpLink]),
  cache: new InMemoryCache({
    typePolicies: {
      // cusdPlusSummary is an id-less singleton queried with DIFFERENT field
      // subsets (portfolio hub vs the APY split card). Without merge, the
      // smaller result REPLACES the cached object, the hub loses
      // stocksEnabled/netApyPct/balanceUsd, and renders 0% with the GM
      // section fail-closed hidden.
      Query: {
        fields: {
          cusdPlusSummary: {
            merge: true,
          },
        },
      },
      MessageInboxType: {
        keyFields: false,
      },
      MessageChannelType: {
        keyFields: false,
      },
      MessageThreadItemType: {
        keyFields: false,
      },
    },
  }),
  defaultOptions: {
    watchQuery: {
      fetchPolicy: 'network-only',
    },
  },
});

export default apolloClient;
