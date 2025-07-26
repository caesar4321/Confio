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
    // Initialize push notification service
    pushNotificationService.initialize();

    // Check if we should show the prompt
    const checkPromptStatus = async () => {
      if (hasChecked) return;
      
      const shouldShow = await pushNotificationService.shouldShowPermissionPrompt();
      if (!shouldShow) {
        setHasChecked(true);
        return;
      }

      // Set up the delayed prompt
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
      timeoutRef.current = setTimeout(async () => {
        // Check if user has been active enough
        const currentSessionDuration = new Date().getTime() - sessionStartTime.current.getTime();
        const totalActiveTime = activeTimeRef.current + currentSessionDuration;

        if (totalActiveTime >= SESSION_TIME_THRESHOLD_MS) {
          // User has been active enough, show the prompt
          const shouldShow = await pushNotificationService.shouldShowPermissionPrompt();
          if (shouldShow) {
            setShowModal(true);
            await pushNotificationService.markPromptAsShown();
          }
        } else {
          // User hasn't been active enough, reschedule
          const remainingTime = SESSION_TIME_THRESHOLD_MS - totalActiveTime;
          timeoutRef.current = setTimeout(async () => {
            const shouldShow = await pushNotificationService.shouldShowPermissionPrompt();
            if (shouldShow) {
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