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
