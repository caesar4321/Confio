import { ApolloClient, InMemoryCache, createHttpLink, from, FetchResult, ApolloLink } from '@apollo/client';
import { onError, ErrorResponse } from '@apollo/client/link/error';
import { setContext } from '@apollo/client/link/context';
import * as Keychain from 'react-native-keychain';
import { jwtDecode } from 'jwt-decode';
import { getApiUrl } from '../config/env';
import { appCheckDiagnosticCode } from '../utils/appCheckDiagnostics';
import { Observable as ApolloObservable } from '@apollo/client/utilities';
import appCheckService from '../services/appCheckService';
import { shouldSkipStoredJwt } from './authPolicy';
// RN-free module — safe to import statically (heavier emergencyExit modules
// like the keychain store stay behind dynamic imports).
import { successProvesUnbanned } from '../services/emergencyExit/banSignal';
import DeviceInfo from 'react-native-device-info';
import { Platform } from 'react-native';

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

const httpLink = createHttpLink({
  uri: getApiUrl(),
});

type SessionTokens = { accessToken: string; refreshToken: string };
// Coalesce requests only for the same session AND account context.
const refreshPromises = new Map<string, Promise<string>>();

// Only an explicit rejection of the refresh credential ends the session.
// Transport failures, App Check errors and server outages are retryable.
class InvalidRefreshTokenError extends Error {}
class SessionChangedError extends Error {
  constructor() { super('Session changed during token refresh'); }
}

const INVALID_REFRESH_MESSAGES = new Set([
  'Signature has expired',
  'Invalid payload',
  'Invalid refresh token',
  'Token has been invalidated',
  'Token version mismatch',
  'User not found',
  'User account is inactive',
]);

function refreshAccessToken(tokens: SessionTokens): Promise<string> {
  const key = JSON.stringify(tokens);
  let promise = refreshPromises.get(key);
  if (!promise) {
    promise = performRefreshWithFetch(tokens).finally(() => {
      // A rejected promise must not poison all subsequent refresh attempts.
      refreshPromises.delete(key);
    });
    refreshPromises.set(key, promise);
  }
  return promise;
}

async function getStoredTokens(): Promise<SessionTokens | null> {
  try {
    const credentials = await Keychain.getGenericPassword({
      service: AUTH_KEYCHAIN_SERVICE,
      username: AUTH_KEYCHAIN_USERNAME
    });
    if (!credentials) return null;
    const parsed = JSON.parse((credentials as any).password || '{}');
    if (typeof parsed.accessToken !== 'string' || typeof parsed.refreshToken !== 'string') return null;
    return { accessToken: parsed.accessToken, refreshToken: parsed.refreshToken };
  } catch (e) {
    return null;
  }
}

async function assertCurrentSession(expected: SessionTokens): Promise<void> {
  const current = await getStoredTokens();
  if (current?.accessToken !== expected.accessToken || current?.refreshToken !== expected.refreshToken) {
    throw new SessionChangedError();
  }
}

async function clearRejectedSession(expected: SessionTokens): Promise<void> {
  await assertCurrentSession(expected);
  await Keychain.resetGenericPassword({ service: AUTH_KEYCHAIN_SERVICE });
}

async function performRefreshWithFetch(tokens: SessionTokens): Promise<string> {
  const decoded = jwtDecode<CustomJwtPayload>(tokens.accessToken);
  const body = {
    operationName: 'RefreshToken',
    query: `mutation RefreshToken($refreshToken: String!, $accountType: String, $accountIndex: Int, $businessId: ID) {
      refreshToken(refreshToken: $refreshToken, accountType: $accountType, accountIndex: $accountIndex, businessId: $businessId) {
        token
      }
    }`,
    variables: {
      refreshToken: tokens.refreshToken,
      accountType: decoded.account_type || 'personal',
      accountIndex: decoded.account_index ?? 0,
      businessId: decoded.business_id,
    },
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
        // Same decoupling as the error link: route first (screen-aware, so
        // it never yanks a user already on the ban surface), persist after.
        const { routeToBlockedAccount } = await import('../navigation/RootNavigation');
        routeToBlockedAccount();
        const { emergencyStore } = await import('../services/emergencyExit/store');
        await markBanSignal(emergencyStore);
      }
    }).catch(() => {});
    throw new Error('Failed to refresh token');
  }
  if (!res.ok) throw new Error('Failed to refresh token');
  const json = await res.json();
  const newAccess = json?.data?.refreshToken?.token;
  if (typeof newAccess !== 'string' || !newAccess) {
    const rejected = json?.errors?.some((error: { message?: string }) =>
      INVALID_REFRESH_MESSAGES.has(error.message || '') ||
      error.message?.startsWith('Invalid token payload'),
    );
    if (rejected) throw new InvalidRefreshTokenError('Invalid refresh token');
    throw new Error('Failed to refresh token');
  }
  // Sign-out, fresh login and account switching may happen during fetch.
  // Never restore or overwrite the credentials that replaced this pair.
  await assertCurrentSession(tokens);
  await Keychain.setGenericPassword(
    AUTH_KEYCHAIN_USERNAME,
    JSON.stringify({ accessToken: newAccess, refreshToken: tokens.refreshToken }),
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

// Un-ban detection: a successful AUTHENTICATED round-trip proves the
// security middleware let us through, so a previously flagged ban is over.
// "Authenticated" is read off the request's own headers (this link sits
// downstream of authLink, so the operation context already carries what
// authLink attached) — see successProvesUnbanned for why anonymous 200s
// must never clear: each false clear re-armed the once-per-episode ban
// navigation and the next 403 yanked the user from EmergencyExit back to
// BlockedAccount.
const banClearLink = new ApolloLink((operation, forward) =>
  forward(operation).map((result) => {
    if (successProvesUnbanned(operation.getContext().headers)) {
      import('../services/emergencyExit/banSignal').then(async ({ clearBanSignal }) => {
        const { emergencyStore } = await import('../services/emergencyExit/store');
        await clearBanSignal(emergencyStore);
      }).catch(() => {});
    }
    return result;
  }),
);

// Apollo 3's error-link teardown does not reliably unsubscribe an async
// retry. Track the original request so cancellation also prevents replay.
const requestLifetimeLink = new ApolloLink((operation, forward) =>
  new ApolloObservable((observer) => {
    let active = true;
    operation.setContext({ authRequestIsActive: () => active });
    const subscription = forward(operation).subscribe(observer);
    return () => {
      active = false;
      subscription.unsubscribe();
    };
  }),
);

const errorLink = onError(({ graphQLErrors, networkError, operation, forward }: ErrorResponse): void | ApolloObservable<FetchResult> => {
  const isMembershipClaim = operation.operationName === 'ClaimInstitutionMembership';
  if (graphQLErrors) {
    for (const err of graphQLErrors) {
      console.error('[GraphQL error]:', {
        message: isMembershipClaim ? 'Membership claim failed' : err.message,
        locations: err.locations,
        path: err.path,
        extensions: isMembershipClaim ? undefined : err.extensions,
        operation: operation.operationName,
        variables: isMembershipClaim ? '[REDACTED]' : operation.variables
      });

      // Handle specific error codes
      if (err.extensions?.code) {
        console.error(`[GraphQL error code]: ${err.extensions.code}`);
      }

      const context = operation.getContext();
      // Pinned requests must never change identity. Public auth operations
      // establish their own identity and must not refresh/replay another one.
      if (context.pinnedAuthToken || shouldSkipStoredJwt(operation.operationName, !!context.skipAuth)) {
        continue;
      }
      const tokens = context.sessionTokens as SessionTokens | undefined;
      const invalidated = err.message === 'Token has been invalidated' ||
        err.message === 'Token version mismatch' || err.message.startsWith('Invalid token payload');
      const expired = err.message === 'Signature has expired' || err.message === 'Invalid payload';
      if (tokens && (invalidated || expired)) {
        return new ApolloObservable<FetchResult>((observer) => {
          let cancelled = false;
          const isCancelled = () => cancelled || context.authRequestIsActive?.() === false;
          let retry: { unsubscribe: () => void } | undefined;
          void (async () => {
            try {
              await assertCurrentSession(tokens);
              if (isCancelled()) return;
              if (invalidated) throw new InvalidRefreshTokenError(err.message);
              const newToken = await refreshAccessToken(tokens);
              if (isCancelled()) return;
              const refreshedTokens = { ...tokens, accessToken: newToken };
              await assertCurrentSession(refreshedTokens);
              if (isCancelled()) return;
              // forward starts downstream of authLink, so replace the header.
              operation.setContext(({ headers = {} }: { headers?: Record<string, string> }) => ({
                headers: { ...headers, Authorization: `JWT ${newToken}` },
                sessionTokens: refreshedTokens,
              }));
              retry = forward(operation).subscribe(observer);
            } catch (error) {
              if (error instanceof InvalidRefreshTokenError) {
                try { await clearRejectedSession(tokens); }
                catch (storageError) { console.warn('[Auth] Could not clear rejected session:', storageError); }
              }
              if (!isCancelled()) observer.error(error);
            }
          })();
          return () => {
            cancelled = true;
            retry?.unsubscribe();
          };
        });
      }
    }
  }
  if (networkError) {
    const ne = networkError as any;
    console.error('[Network error]:', {
      message: isMembershipClaim ? 'Membership claim request failed' : networkError.message,
      name: networkError.name,
      stack: isMembershipClaim ? undefined : networkError.stack,
      statusCode: ne.statusCode,
      operation: operation.operationName,
      variables: isMembershipClaim ? '[REDACTED]' : operation.variables
    });

    // Ban detection. Real-device ground truth (2026-07-22): the middleware's
    // text/html 403 surfaces as an Apollo ServerError with statusCode 403;
    // the body may or may not be reachable via .result/.bodyText depending
    // on the parse path. So: prefer the "suspended" text when present, but
    // FALL BACK to statusCode 403 itself — in this app every GraphQL 403
    // originates from SecurityMiddleware (ban or IP block), never a resolver,
    // so a 403 is a reliable "you're locked out, here's your exit" signal.
    const banBody = [
      typeof ne.bodyText === 'string' ? ne.bodyText : '',
      typeof ne.result === 'string' ? ne.result : (ne.result ? JSON.stringify(ne.result) : ''),
      networkError.message || '',
    ].join(' ').toLowerCase();
    if (banBody.includes('suspended') || ne.statusCode === 403) {
      // Loud, greppable marker so a device log proves this path ran.
      console.warn('[BanSignal] 403 lockout detected on', operation.operationName, '→ routing to BlockedAccount');
      // Route IMMEDIATELY and INDEPENDENTLY of keychain persistence. The
      // old code gated navigate() on markBanSignal() succeeding, so any
      // throw in the keychain write (or its import chain) was swallowed by
      // .catch and the user never left HomeScreen. Per-403 firing is fine
      // ONLY through routeToBlockedAccount: a bare navigate is not
      // idempotent from EmergencyExit (it pops back to the announcement,
      // so every background poll's 403 yanked the user out of their exit).
      import('../navigation/RootNavigation')
        .then(({ routeToBlockedAccount }) => routeToBlockedAccount())
        .catch((e) => console.warn('[BanSignal] nav import failed', e));
      // Persist the flag best-effort (cold-start routing) — decoupled.
      import('../services/emergencyExit/banSignal')
        .then(async ({ markBanSignal }) => {
          const { emergencyStore } = await import('../services/emergencyExit/store');
          const newlyMarked = await markBanSignal(emergencyStore);
          console.warn('[BanSignal] markBanSignal newlyMarked =', newlyMarked);
        })
        .catch((e) => console.warn('[BanSignal] mark failed', e));
    }

    // Handle specific network error codes
    if (ne.statusCode === 400) {
      console.error('[400 Bad Request]: The server could not understand the request');
    } else if (ne.statusCode === 401) {
      console.error('[401 Unauthorized]: Authentication required');
    } else if (ne.statusCode === 403) {
      console.error('[403 Forbidden]: Access denied');
    } else if (ne.statusCode === 404) {
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
    'X-Confio-Platform': Platform.OS,
    'X-Confio-Build': DeviceInfo.getBuildNumber(),
    // Capability, not authorization. Legacy builds omit it and remain
    // operational with their old gross-output withdrawal semantics.
    'X-Confio-Fee-Capable': '1',
  };

  // 1. ALWAYS Try to attach Firebase App Check header (Public or Private)
  try {
    const appCheckToken = await appCheckService.getTokenForHeader();
    if (appCheckToken) {
      nextHeaders['X-Firebase-AppCheck'] = appCheckToken;
    } else {
      const appCheckDebugError = appCheckService.getLastErrorForDebug();
      if (appCheckDebugError) {
        nextHeaders['X-AppCheck-Debug-Error'] = appCheckDiagnosticCode(appCheckDebugError);
      }
    }
  } catch (acError: any) {
    // DEBUG: Send error to backend to see why it failed
    nextHeaders['X-AppCheck-Debug-Error'] = appCheckDiagnosticCode(acError?.message);
  }

  // Session-establishing operations must be independent of any stale JWT
  // left in Keychain. App Check above still applies to these requests.
  if (shouldSkipStoredJwt(operation.operationName, !!previousContext?.skipAuth)) {
    return { headers: nextHeaders };
  }

  // Pinned token: send exactly the JWT the caller verified, with no Keychain
  // reread and no proactive refresh.
  //
  // For most operations, rereading is right — it picks up the freshest token.
  // For an operation whose effect is bound to the token's ACCOUNT and cannot be
  // undone, it is wrong: this link awaits App Check above, and an account
  // switch landing in that window swaps the token between the caller's check
  // and this read. updateAccountBscAddress writes to the JWT's account and
  // refuses corrections forever, so it pins instead. Opt-in — nothing else
  // changes behaviour.
  const pinnedToken = previousContext?.pinnedAuthToken;
  if (pinnedToken) {
    nextHeaders['Authorization'] = `JWT ${pinnedToken}`;
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

    const tokens: SessionTokens = { accessToken: token, refreshToken };
    let decoded: CustomJwtPayload;
    try {
      decoded = jwtDecode<CustomJwtPayload>(token);
    } catch (error) {
      await clearRejectedSession(tokens);
      return { headers: nextHeaders };
    }
    if (!decoded.user_id || decoded.type !== 'access') {
      await clearRejectedSession(tokens);
      return { headers: nextHeaders };
    }

    const skipProactive = operation.operationName === 'GetUserAccounts' || !!previousContext?.skipProactiveRefresh;
    const expiresSoon = !decoded.exp || decoded.exp <= Date.now() / 1000 + 5 * 60;
    if (!skipProactive && expiresSoon) {
      try {
        token = await refreshAccessToken(tokens);
      } catch (error) {
        if (error instanceof SessionChangedError) throw error;
        if (error instanceof InvalidRefreshTokenError) {
          await clearRejectedSession(tokens);
          throw error;
        }
        // Temporary refresh failures do not invalidate the existing token.
        // Check that an intervening sign-out/account switch did not replace it.
        await assertCurrentSession(tokens);
        console.error('Token refresh failed:', error);
      }
    }
    const activeTokens = { ...tokens, accessToken: token };
    await assertCurrentSession(activeTokens);
    nextHeaders['Authorization'] = `JWT ${token}`;
    return { headers: nextHeaders, sessionTokens: activeTokens };

  } catch (error) {
    console.error('Error in authLink:', error);
    throw error;
  }
});

export const apolloClient = new ApolloClient({
  link: from([requestLifetimeLink, authLink, errorLink, banClearLink, httpLink]),
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
