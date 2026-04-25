import { useState, useEffect, useCallback } from 'react';
import { Platform, Linking } from 'react-native';
import { pushNotificationService } from '../services/pushNotificationService';

interface UsePushNotificationPromptReturn {
  showModal: boolean;
  handleAllow: () => Promise<void>;
  handleDeny: () => Promise<void>;
  checkAndShowPrompt: () => Promise<void>;
  needsSettings: boolean;
}

export function usePushNotificationPrompt(): UsePushNotificationPromptReturn {
  const [showModal, setShowModal] = useState(false);
  const [hasInitialized, setHasInitialized] = useState(false);
  const [needsSettings, setNeedsSettings] = useState(false);

  // Initialize the service on mount
  useEffect(() => {
    if (!hasInitialized) {
      pushNotificationService.initialize();
      setHasInitialized(true);
    }
  }, [hasInitialized]);

  // Function to check and show prompt
  const checkAndShowPrompt = useCallback(async () => {
    try {
      // First check if we already have permission
      const hasPermission = await pushNotificationService.hasPermission();
      
      if (hasPermission) {
        // Permission already granted - ensure FCM token is registered for current user
        // Get and save the FCM token for the current user
        const token = await pushNotificationService.getAndSaveFCMToken();
        if (token) {
          // Subscribe to topics
          await pushNotificationService.subscribeToTopic('general');
          await pushNotificationService.subscribeToTopic('transactions');
          
          // Also ensure messaging service is initialized
          const { default: messagingService } = await import('../services/messagingService');
          await messagingService.initialize();
        }
        
        // Don't show modal since permission is already granted
        return;
      }
      
      // If no permission, check if we should show the prompt
      const shouldShow = await pushNotificationService.shouldShowPermissionPrompt();
      
      if (shouldShow) {
        // Check if iOS user needs to go to settings
        const requiresSettings = await pushNotificationService.needsToOpenSettings();
        setNeedsSettings(requiresSettings);
        setShowModal(true);
      }
    } catch (error) {
      console.error('[PushNotification] Error checking prompt status:', error);
    }
  }, []);

  const handleAllow = useCallback(async () => {
    try {
      // If iOS needs settings, open settings instead
      if (needsSettings && Platform.OS === 'ios') {
        Linking.openSettings();
      } else {
        const granted = await pushNotificationService.requestPermission();
        if (granted) {
          // Subscribe to topics
          await pushNotificationService.subscribeToTopic('general');
          await pushNotificationService.subscribeToTopic('transactions');
          
          // Also ensure messaging service is initialized with the new permission
          const { default: messagingService } = await import('../services/messagingService');
          await messagingService.initialize();
        } else {
          // Save denial status so we know to show settings prompt next time on iOS
          await pushNotificationService.savePermissionStatus('denied');
        }
      }
    } catch (error) {
      console.error('[PushNotification] Failed to enable push notifications:', error);
    } finally {
      setShowModal(false);
      setNeedsSettings(false);
    }
  }, [needsSettings]);

  const handleDeny = useCallback(async () => {
    try {
      const storedStatus = await pushNotificationService.getStoredPermissionStatus();
      if (!storedStatus || storedStatus === 'not_asked') {
        await pushNotificationService.savePermissionStatus('denied');
      }
    } catch (error) {
      console.error('[PushNotification] Failed to handle denial:', error);
    } finally {
      setShowModal(false);
      setNeedsSettings(false);
    }
  }, []);

  return {
    showModal,
    handleAllow,
    handleDeny,
    checkAndShowPrompt,
    needsSettings,
  };
}
