import messaging, { FirebaseMessagingTypes } from '@react-native-firebase/messaging';
import { Platform, PermissionsAndroid } from 'react-native';
import * as Keychain from 'react-native-keychain';

const NOTIFICATION_PERMISSION_KEY = 'push_notification_permission';
const NOTIFICATION_TOKEN_KEY = 'push_notification_token';
const NOTIFICATION_PROMPT_SHOWN_KEY = 'push_notification_prompt_shown';
const NOTIFICATION_PROMPT_TIMESTAMP_KEY = 'push_notification_prompt_timestamp';

export class PushNotificationService {
  private static instance: PushNotificationService;
  private isInitialized = false;

  private constructor() {}

  static getInstance(): PushNotificationService {
    if (!PushNotificationService.instance) {
      PushNotificationService.instance = new PushNotificationService();
    }
    return PushNotificationService.instance;
  }

  /**
   * Initialize push notification service
   */
  async initialize(): Promise<void> {
    if (this.isInitialized) {
      console.log('[PushNotificationService] Already initialized, skipping');
      return;
    }

    try {
      console.log('[PushNotificationService] Initializing push notification service...');
      
      // Register background handler
      messaging().setBackgroundMessageHandler(async (remoteMessage) => {
        console.log('Message handled in the background!', remoteMessage);
        // Handle background message
      });

      // Handle foreground messages
      const unsubscribe = messaging().onMessage(async (remoteMessage) => {
        console.log('A new FCM message arrived!', remoteMessage);
        // Handle foreground message - you might want to show a local notification here
      });

      // Handle notification opened app
      messaging().onNotificationOpenedApp((remoteMessage) => {
        console.log('Notification caused app to open from background state:', remoteMessage.notification);
        // Navigate to specific screen based on notification data
      });

      // Check whether an initial notification is available
      const initialNotification = await messaging().getInitialNotification();
      if (initialNotification) {
        console.log('Notification caused app to open from quit state:', initialNotification.notification);
        // Navigate to specific screen based on notification data
      }

      this.isInitialized = true;
      console.log('[PushNotificationService] Initialization complete');
    } catch (error) {
      console.error('Failed to initialize push notifications:', error);
    }
  }

  /**
   * Request notification permission
   */
  async requestPermission(): Promise<boolean> {
    try {
      if (Platform.OS === 'android') {
        // Android 13+ requires explicit permission
        if (Platform.Version >= 33) {
          const granted = await PermissionsAndroid.request(
            PermissionsAndroid.PERMISSIONS.POST_NOTIFICATIONS,
            {
              title: 'Notificaciones',
              message: 'Confío necesita tu permiso para enviarte notificaciones importantes sobre tus transacciones.',
              buttonPositive: 'Permitir',
              buttonNegative: 'Denegar',
            }
          );
          if (granted !== PermissionsAndroid.RESULTS.GRANTED) {
            await this.savePermissionStatus('denied');
            return false;
          }
        }
      }

      // Request permission from Firebase
      const authStatus = await messaging().requestPermission();
      const enabled =
        authStatus === messaging.AuthorizationStatus.AUTHORIZED ||
        authStatus === messaging.AuthorizationStatus.PROVISIONAL;

      if (enabled) {
        console.log('Authorization status:', authStatus);
        await this.savePermissionStatus('granted');
        
        // Get and save FCM token
        const token = await this.getAndSaveFCMToken();
        console.log('FCM Token:', token);
        
        return true;
      } else {
        await this.savePermissionStatus('denied');
        return false;
      }
    } catch (error) {
      console.error('Failed to request notification permission:', error);
      await this.savePermissionStatus('denied');
      return false;
    }
  }

  /**
   * Check if notification permission is granted
   */
  async hasPermission(): Promise<boolean> {
    try {
      const authStatus = await messaging().hasPermission();
      return authStatus === messaging.AuthorizationStatus.AUTHORIZED ||
             authStatus === messaging.AuthorizationStatus.PROVISIONAL;
    } catch (error) {
      console.error('Failed to check notification permission:', error);
      return false;
    }
  }

  /**
   * Check if user needs to go to settings to enable permissions (iOS only)
   */
  async needsToOpenSettings(): Promise<boolean> {
    try {
      if (Platform.OS !== 'ios') {
        return false;
      }
      
      const authStatus = await messaging().hasPermission();
      const storedStatus = await this.getStoredPermissionStatus();
      
      // On iOS, if permission was denied, user must go to settings
      return authStatus === messaging.AuthorizationStatus.DENIED && storedStatus === 'denied';
    } catch (error) {
      console.error('Failed to check if needs settings:', error);
      return false;
    }
  }

  /**
   * Get and save FCM token
   */
  async getAndSaveFCMToken(): Promise<string | null> {
    try {
      const token = await messaging().getToken();
      if (token) {
        await Keychain.setInternetCredentials(
          NOTIFICATION_TOKEN_KEY,
          'fcm_token',
          token
        );
        return token;
      }
      return null;
    } catch (error) {
      console.error('Failed to get FCM token:', error);
      return null;
    }
  }

  /**
   * Save permission status
   */
  async savePermissionStatus(status: 'granted' | 'denied' | 'not_asked'): Promise<void> {
    try {
      await Keychain.setInternetCredentials(
        NOTIFICATION_PERMISSION_KEY,
        'permission_status',
        status
      );
    } catch (error) {
      console.error('Failed to save permission status:', error);
    }
  }

  /**
   * Get stored permission status
   */
  async getStoredPermissionStatus(): Promise<'granted' | 'denied' | 'not_asked' | null> {
    try {
      const credentials = await Keychain.getInternetCredentials(NOTIFICATION_PERMISSION_KEY);
      if (credentials && credentials.password) {
        return credentials.password as 'granted' | 'denied' | 'not_asked';
      }
      return null;
    } catch (error) {
      console.error('Failed to get permission status:', error);
      return null;
    }
  }

  /**
   * Check if we should show the permission prompt
   */
  async shouldShowPermissionPrompt(): Promise<boolean> {
    try {
      console.log('[PushNotificationService] Checking if should show prompt...');
      
      // First check actual system permission status
      const hasSystemPermission = await this.hasPermission();
      console.log('[PushNotificationService] System permission granted:', hasSystemPermission);
      
      if (hasSystemPermission) {
        // Update stored status if needed
        await this.savePermissionStatus('granted');
        console.log('[PushNotificationService] Permission already granted at system level, not showing prompt');
        return false;
      }
      
      // Check if permission was already denied in our storage
      const permissionStatus = await this.getStoredPermissionStatus();
      console.log('[PushNotificationService] Stored permission status:', permissionStatus);
      
      if (permissionStatus === 'granted') {
        console.log('[PushNotificationService] Permission already granted (stored), not showing prompt');
        return false;
      }
      
      // On iOS, check if we've already asked for permission
      // iOS only allows asking once, after that user must go to settings
      if (Platform.OS === 'ios' && permissionStatus === 'denied') {
        const authStatus = await messaging().hasPermission();
        if (authStatus === messaging.AuthorizationStatus.DENIED) {
          console.log('[PushNotificationService] iOS permission permanently denied, cannot show system prompt');
          // Still show our custom prompt to guide user to settings
          return true;
        }
      }

      // For a finance app, we show the prompt until permission is granted
      // Push notifications are critical for transaction alerts and security
      console.log('[PushNotificationService] Should show prompt: true');
      return true;
    } catch (error) {
      console.error('Failed to check if should show prompt:', error);
      return false;
    }
  }

  /**
   * Mark that the permission prompt was shown (deprecated - we no longer track this)
   * Keeping method for backward compatibility but it does nothing
   */
  async markPromptAsShown(): Promise<void> {
    // We no longer mark the prompt as shown since we want to keep asking
    // until the user grants permission for this critical finance app feature
    console.log('[PushNotificationService] markPromptAsShown called (no-op)');
  }

  /**
   * Subscribe to a topic
   */
  async subscribeToTopic(topic: string): Promise<void> {
    try {
      await messaging().subscribeToTopic(topic);
      console.log(`Subscribed to topic: ${topic}`);
    } catch (error) {
      console.error(`Failed to subscribe to topic ${topic}:`, error);
    }
  }

  /**
   * Unsubscribe from a topic
   */
  async unsubscribeFromTopic(topic: string): Promise<void> {
    try {
      await messaging().unsubscribeFromTopic(topic);
      console.log(`Unsubscribed from topic: ${topic}`);
    } catch (error) {
      console.error(`Failed to unsubscribe from topic ${topic}:`, error);
    }
  }

  /**
   * Handle token refresh
   */
  setupTokenRefreshListener(): () => void {
    const unsubscribe = messaging().onTokenRefresh(async (token) => {
      console.log('FCM Token refreshed:', token);
      await Keychain.setInternetCredentials(
        NOTIFICATION_TOKEN_KEY,
        'fcm_token',
        token
      );
      // You might want to send the new token to your backend here
    });

    return unsubscribe;
  }
}

// Export singleton instance
export const pushNotificationService = PushNotificationService.getInstance();