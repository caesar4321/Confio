import { useState, useEffect, useRef } from 'react';
import { AppState, AppStateStatus } from 'react-native';
import { pushNotificationService } from '../services/pushNotificationService';

const PROMPT_DELAY_MS = 30000; // 30 seconds delay before showing prompt
const SESSION_TIME_THRESHOLD_MS = 20000; // Show after 20 seconds of active use

interface UsePushNotificationPromptReturn {
  showModal: boolean;
  handleAllow: () => Promise<void>;
  handleDeny: () => Promise<void>;
}

export function usePushNotificationPrompt(): UsePushNotificationPromptReturn {
  const [showModal, setShowModal] = useState(false);
  const [hasChecked, setHasChecked] = useState(false);
  const sessionStartTime = useRef<Date>(new Date());
  const appStateRef = useRef<AppStateStatus>(AppState.currentState);
  const timeoutRef = useRef<NodeJS.Timeout | null>(null);
  const activeTimeRef = useRef<number>(0);

  useEffect(() => {
    console.log('[PushNotification] Hook initialized');
    // Initialize push notification service
    pushNotificationService.initialize();

    // Check if we should show the prompt
    const checkPromptStatus = async () => {
      if (hasChecked) return;
      
      console.log('[PushNotification] Checking prompt status...');
      const shouldShow = await pushNotificationService.shouldShowPermissionPrompt();
      console.log('[PushNotification] Should show prompt:', shouldShow);
      
      if (!shouldShow) {
        setHasChecked(true);
        return;
      }

      // Set up the delayed prompt
      console.log('[PushNotification] Scheduling prompt...');
      schedulePrompt();
      setHasChecked(true);
    };

    // Handle app state changes to track active usage time
    const handleAppStateChange = (nextAppState: AppStateStatus) => {
      if (appStateRef.current.match(/inactive|background/) && nextAppState === 'active') {
        // App has come to foreground
        sessionStartTime.current = new Date();
      } else if (appStateRef.current === 'active' && nextAppState.match(/inactive|background/)) {
        // App has gone to background
        const sessionDuration = new Date().getTime() - sessionStartTime.current.getTime();
        activeTimeRef.current += sessionDuration;
      }
      appStateRef.current = nextAppState;
    };

    const appStateSubscription = AppState.addEventListener('change', handleAppStateChange);

    // Schedule the prompt
    const schedulePrompt = () => {
      // Clear any existing timeout
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
      }

      // Set up new timeout
      console.log(`[PushNotification] Setting timeout for ${PROMPT_DELAY_MS}ms (${PROMPT_DELAY_MS/1000} seconds)`);
      timeoutRef.current = setTimeout(async () => {
        // Check if user has been active enough
        const currentSessionDuration = new Date().getTime() - sessionStartTime.current.getTime();
        const totalActiveTime = activeTimeRef.current + currentSessionDuration;
        console.log(`[PushNotification] Timeout fired! Active time: ${totalActiveTime}ms, Threshold: ${SESSION_TIME_THRESHOLD_MS}ms`);

        if (totalActiveTime >= SESSION_TIME_THRESHOLD_MS) {
          // User has been active enough, show the prompt
          console.log('[PushNotification] User has been active enough, checking if should show...');
          const shouldShow = await pushNotificationService.shouldShowPermissionPrompt();
          console.log('[PushNotification] Should show (in timeout):', shouldShow);
          if (shouldShow) {
            console.log('[PushNotification] Showing modal!');
            setShowModal(true);
            await pushNotificationService.markPromptAsShown();
          }
        } else {
          // User hasn't been active enough, reschedule
          const remainingTime = SESSION_TIME_THRESHOLD_MS - totalActiveTime;
          console.log(`[PushNotification] User not active enough, rescheduling for ${remainingTime}ms`);
          timeoutRef.current = setTimeout(async () => {
            const shouldShow = await pushNotificationService.shouldShowPermissionPrompt();
            if (shouldShow) {
              console.log('[PushNotification] Showing modal after reschedule!');
              setShowModal(true);
              await pushNotificationService.markPromptAsShown();
            }
          }, remainingTime);
        }
      }, PROMPT_DELAY_MS);
    };

    checkPromptStatus();

    return () => {
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
      }
      appStateSubscription.remove();
    };
  }, [hasChecked]);

  const handleAllow = async () => {
    try {
      const granted = await pushNotificationService.requestPermission();
      if (granted) {
        console.log('Push notifications enabled');
        // You might want to subscribe to topics here
        await pushNotificationService.subscribeToTopic('general');
        await pushNotificationService.subscribeToTopic('transactions');
      }
    } catch (error) {
      console.error('Failed to enable push notifications:', error);
    } finally {
      setShowModal(false);
    }
  };

  const handleDeny = async () => {
    try {
      // Mark as denied in storage
      await pushNotificationService.markPromptAsShown();
    } catch (error) {
      console.error('Failed to save denial:', error);
    } finally {
      setShowModal(false);
    }
  };

  return {
    showModal,
    handleAllow,
    handleDeny,
  };
}