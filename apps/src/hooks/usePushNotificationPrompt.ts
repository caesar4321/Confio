import { useState, useEffect } from 'react';
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
      console.log('[PushNotification] Initializing service...');
      pushNotificationService.initialize();
      setHasInitialized(true);
    }
  }, [hasInitialized]);

  // Function to check and show prompt
  const checkAndShowPrompt = async () => {
    console.log('[PushNotification] checkAndShowPrompt called');
    
    try {
      // First check if we already have permission
      const hasPermission = await pushNotificationService.hasPermission();
      console.log('[PushNotification] Has permission:', hasPermission);
      
      if (hasPermission) {
        // Permission already granted - ensure FCM token is registered for current user
        console.log('[PushNotification] Permission already granted, ensuring FCM token is registered');
        
        // Get and save the FCM token for the current user
        const token = await pushNotificationService.getAndSaveFCMToken();
        if (token) {
          console.log('[PushNotification] FCM token obtained and saved for current user');
          
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
      console.log('[PushNotification] Should show prompt:', shouldShow);
      
      if (shouldShow) {
        // Check if iOS user needs to go to settings
        const requiresSettings = await pushNotificationService.needsToOpenSettings();
        setNeedsSettings(requiresSettings);
        console.log('[PushNotification] Needs settings:', requiresSettings);
        
        console.log('[PushNotification] Showing modal immediately');
        setShowModal(true);
      }
    } catch (error) {
      console.error('[PushNotification] Error checking prompt status:', error);
    }
  };

  const handleAllow = async () => {
    try {
      console.log('[PushNotification] User clicked allow');
      
      // If iOS needs settings, open settings instead
      if (needsSettings && Platform.OS === 'ios') {
        console.log('[PushNotification] Opening iOS settings...');
        Linking.openSettings();
      } else {
        const granted = await pushNotificationService.requestPermission();
        if (granted) {
          console.log('[PushNotification] Push notifications enabled');
          // Subscribe to topics
          await pushNotificationService.subscribeToTopic('general');
          await pushNotificationService.subscribeToTopic('transactions');
          
          // Also ensure messaging service is initialized with the new permission
          const { default: messagingService } = await import('../services/messagingService');
          await messagingService.initialize();
        } else {
          console.log('[PushNotification] Permission was not granted');
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
  };

  const handleDeny = async () => {
    try {
      // Just close the modal - we'll ask again next time
      // For a finance app, push notifications are too important to give up
      console.log('[PushNotification] User denied, but we\'ll ask again');
      
      // Only save denied status if this was the first time asking
      // This prevents iOS from being permanently blocked
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
  };

  return {
    showModal,
    handleAllow,
    handleDeny,
    checkAndShowPrompt,
    needsSettings,
  };
}