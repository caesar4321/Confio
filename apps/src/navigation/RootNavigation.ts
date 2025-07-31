import { createNavigationContainerRef } from '@react-navigation/native';

export const navigationRef = createNavigationContainerRef();

export function navigate(name: string, params?: any) {
  console.log('[RootNavigation] navigate called:', { name, params, isReady: navigationRef.isReady() });
  
  if (navigationRef.isReady()) {
    try {
      navigationRef.navigate(name as never, params as never);
      console.log('[RootNavigation] Navigation successful');
    } catch (error) {
      console.error('[RootNavigation] Navigation error:', error);
    }
  } else {
    console.log('[RootNavigation] Navigation not ready, queuing navigation...');
    // Queue the navigation for when the navigation is ready
    let retryCount = 0;
    const maxRetries = 50; // 5 seconds max
    
    const tryNavigate = setInterval(() => {
      retryCount++;
      if (navigationRef.isReady()) {
        console.log('[RootNavigation] Navigation ready after retry, navigating...');
        clearInterval(tryNavigate);
        try {
          navigationRef.navigate(name as never, params as never);
          console.log('[RootNavigation] Delayed navigation successful');
        } catch (error) {
          console.error('[RootNavigation] Delayed navigation error:', error);
        }
      } else if (retryCount >= maxRetries) {
        console.error('[RootNavigation] Navigation failed - timeout waiting for navigation to be ready');
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