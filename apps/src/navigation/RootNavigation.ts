import { createNavigationContainerRef } from '@react-navigation/native';

export const navigationRef = createNavigationContainerRef();

function unsafeNavigate(name: string, params?: any) {
  (navigationRef as any).navigate(name, params);
}

export function navigate(name: string, params?: any) {
  // LEGACY FORMAT DETECTION:
  // The code detects if a notification is trying to use the old P2PTradeDetail screen name
  // and automatically converts it to ActiveTrade. This handles old/cached push notifications
  // that were created before the screen was renamed.
  // Old format: navigate('P2PTradeDetail', { tradeId: '26' })
  // New format: navigate('ActiveTrade', { trade: { id: '26' } })
  if (name === 'P2PTradeDetail' && params?.tradeId) {
    name = 'ActiveTrade';
    params = { trade: { id: params.tradeId } };
  }

  if (navigationRef.isReady()) {
    try {
      unsafeNavigate(name, params);
    } catch (error) {
      // If navigation fails, try to navigate to a safe fallback
      if (name.includes('Trade') || name.includes('P2P')) {
        unsafeNavigate('Main', {
          screen: 'BottomTabs',
          params: {
            screen: 'Discover'
          }
        });
      }
    }
  } else {
    // Queue the navigation for when the navigation is ready
    let retryCount = 0;
    const maxRetries = 50; // 5 seconds max

    const tryNavigate = setInterval(() => {
      retryCount++;
      if (navigationRef.isReady()) {
        clearInterval(tryNavigate);
        try {
          unsafeNavigate(name, params);
        } catch (error) {
          // Navigation failed after becoming ready
        }
      } else if (retryCount >= maxRetries) {
        clearInterval(tryNavigate);
      }
    }, 100);
  }
}

export function goBack() {
  if (navigationRef.isReady() && navigationRef.canGoBack()) {
    navigationRef.goBack();
  }
}

export function reset(state: any) {
  if (navigationRef.isReady()) {
    navigationRef.reset(state);
  }
}

/**
 * Navigate as soon as the container is ready. The ban 403 can fire during
 * the very first HomeScreen queries — before or right as the
 * NavigationContainer mounts — so a plain navigate() would be dropped.
 * Polls briefly for readiness, then navigates once.
 */
export function navigateWhenReady(name: string, params?: any, tries = 40) {
  if (navigationRef.isReady()) {
    try {
      (navigationRef as any).navigate(name, params);
      console.warn('[BanSignal] navigateWhenReady dispatched navigate →', name);
    } catch (e) {
      console.warn('[BanSignal] navigateWhenReady navigate THREW for', name, e);
    }
    return;
  }
  if (tries <= 0) {
    console.warn('[BanSignal] navigateWhenReady gave up (never ready) for', name);
    return;
  }
  setTimeout(() => navigateWhenReady(name, params, tries - 1), 150);
}

// Screens where a banned user is already where they belong. Firing the ban
// navigation while one of these is focused is NOT idempotent: from
// EmergencyExit, navigate('BlockedAccount') pops back to the announcement,
// yanking the user out of their own withdrawal mid-flow — every background
// poll's 403 (GetUserAccounts, notification count) did exactly that.
const BAN_SURFACE = new Set(['BlockedAccount', 'EmergencyExit']);

/**
 * The 403 handlers' entry point: unconditional per-403 (never gated on the
 * keychain flag persisting), but screen-aware — a no-op while the user is
 * already on the ban surface.
 */
export function routeToBlockedAccount(tries = 40) {
  if (navigationRef.isReady()) {
    const current = (navigationRef as any).getCurrentRoute?.()?.name;
    if (current && BAN_SURFACE.has(current)) {
      return; // already announced (or mid-exit) — don't yank
    }
  }
  navigateWhenReady('BlockedAccount', undefined, tries);
}
