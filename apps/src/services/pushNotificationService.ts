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
    if (this.isInitialized) return;

    try {
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
  private async savePermissionStatus(status: 'granted' | 'denied' | 'not_asked'): Promise<void> {
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
      // Check if permission was already asked
      const permissionStatus = await this.getStoredPermissionStatus();
      if (permissionStatus === 'granted' || permissionStatus === 'denied') {
        return false;
      }

      // Check if prompt was already shown
      const promptShown = await Keychain.getInternetCredentials(NOTIFICATION_PROMPT_SHOWN_KEY);
      if (promptShown && promptShown.password === 'true') {
        return false;
      }

      return true;
    } catch (error) {
      console.error('Failed to check if should show prompt:', error);
      return false;
    }
  }

  /**
   * Mark that the permission prompt was shown
   */
  async markPromptAsShown(): Promise<void> {
    try {
      await Keychain.setInternetCredentials(
        NOTIFICATION_PROMPT_SHOWN_KEY,
        'prompt_shown',
        'true'
      );
      
      // Also save timestamp
      await Keychain.setInternetCredentials(
        NOTIFICATION_PROMPT_TIMESTAMP_KEY,
        'timestamp',
        new Date().toISOString()
      );
    } catch (error) {
      console.error('Failed to mark prompt as shown:', error);
    }
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