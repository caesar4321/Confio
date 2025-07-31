import messaging, { FirebaseMessagingTypes } from '@react-native-firebase/messaging';
import { Platform, PermissionsAndroid } from 'react-native';
import * as Keychain from 'react-native-keychain';
import * as RootNavigation from '../navigation/RootNavigation';

const NOTIFICATION_PERMISSION_KEY = 'push_notification_permission';
const NOTIFICATION_TOKEN_KEY = 'push_notification_token';
const NOTIFICATION_PROMPT_SHOWN_KEY = 'push_notification_prompt_shown';
const NOTIFICATION_PROMPT_TIMESTAMP_KEY = 'push_notification_prompt_timestamp';

export class PushNotificationService {
  private static instance: PushNotificationService;
  private isInitialized = false;
  private pendingNotification: FirebaseMessagingTypes.RemoteMessage | null = null;

  private constructor() {}

  static getInstance(): PushNotificationService {
    if (!PushNotificationService.instance) {
      PushNotificationService.instance = new PushNotificationService();
    }
    return PushNotificationService.instance;
  }

  /**
   * Process any pending notification navigation
   * This should be called after the app is fully initialized and authenticated
   */
  processPendingNotification(): void {
    console.log('[PushNotificationService] processPendingNotification called', {
      hasPending: !!this.pendingNotification
    });
    
    if (this.pendingNotification) {
      const notification = this.pendingNotification;
      this.pendingNotification = null;
      
      // Delay slightly to ensure navigation is fully ready
      setTimeout(() => {
        this.handleNotificationNavigation(notification);
      }, 500);
    }
  }

  /**
   * Handle notification navigation based on data payload
   */
  private handleNotificationNavigation(remoteMessage: FirebaseMessagingTypes.RemoteMessage): void {
    console.log('[PushNotificationService] Handling notification navigation:', {
      data: remoteMessage.data,
      notification: remoteMessage.notification
    });
    
    if (!remoteMessage.data) {
      console.log('[PushNotificationService] No data in remote message');
      return;
    }
    
    // Wait for navigation to be ready
    const attemptNavigation = () => {
      if (!RootNavigation.navigationRef.isReady()) {
        console.log('[PushNotificationService] Navigation not ready, retrying...');
        setTimeout(attemptNavigation, 100);
        return;
      }
      
      const { action_url, extra_type, extra_transactionType, notification_type } = remoteMessage.data;
      
      console.log('[PushNotificationService] Processing notification navigation:', {
        action_url,
        extra_type,
        extra_transactionType,
        notification_type
      });
      
      // Parse action URL if it exists
      if (action_url) {
        if (action_url.includes('p2p/trade/')) {
          const tradeId = action_url.split('p2p/trade/')[1];
          console.log('[PushNotificationService] Navigating to ActiveTrade:', tradeId);
          RootNavigation.navigate('Main', {
            screen: 'ActiveTrade',
            params: { tradeId }
          });
        } else if (action_url.includes('transaction/')) {
          const transactionId = action_url.split('transaction/')[1];
          
          // Reconstruct transaction data from notification data fields
          const transactionData: any = {};
          
          // Copy all data_ prefixed fields to transaction data
          Object.keys(remoteMessage.data).forEach(key => {
            if (key.startsWith('data_')) {
              const fieldName = key.substring(5); // Remove 'data_' prefix
              let value = remoteMessage.data[key];
              
              // Parse boolean strings
              if (value === 'true' || value === 'True') {
                value = true;
              } else if (value === 'false' || value === 'False') {
                value = false;
              }
              
              transactionData[fieldName] = value;
              
              // Log boolean fields for debugging
              if (fieldName === 'is_external_address' || fieldName === 'is_invited_friend') {
                console.log(`[PushNotificationService] Boolean field ${fieldName}:`, {
                  original: remoteMessage.data[key],
                  parsed: value,
                  type: typeof value
                });
              }
            }
          });
          
          // Determine transaction type
          let transactionType = extra_transactionType || extra_type || 'send';
          
          // Map notification types to transaction types if needed
          if (notification_type === 'PAYMENT_SENT' || notification_type === 'PAYMENT_RECEIVED') {
            transactionType = 'payment';
            // For payment transactions, ensure we have the correct transaction ID
            if (!transactionData.id && transactionData.payment_transaction_id) {
              transactionData.id = transactionData.payment_transaction_id;
            }
          }
          
          console.log('[PushNotificationService] Navigating to TransactionDetail:', {
            transactionType,
            transactionData,
            transactionId,
            notification_type
          });
          
          // Navigate to Main stack first, then to TransactionDetail
          // This ensures we're in the correct navigator
          RootNavigation.navigate('Main', {
            screen: 'TransactionDetail',
            params: {
              transactionType,
              transactionData: { 
                ...transactionData,
                id: transactionId,
                transaction_type: transactionType
              }
            }
          });
        } else {
          console.log('[PushNotificationService] Unknown action URL format:', action_url);
          // Fallback to NotificationScreen
          RootNavigation.navigate('Main', {
            screen: 'Notifications'
          });
        }
      } else {
        console.log('[PushNotificationService] No action URL, navigating to NotificationScreen');
        // Fallback to NotificationScreen if no specific action
        RootNavigation.navigate('Main', {
          screen: 'Notifications'
        });
      }
    };
    
    // Start navigation attempt
    attemptNavigation();
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
        // For background state, the app is already initialized so we can navigate
        // But we should still check if navigation is ready
        setTimeout(() => {
          this.handleNotificationNavigation(remoteMessage);
        }, 500);
      });

      // Check whether an initial notification is available
      const initialNotification = await messaging().getInitialNotification();
      if (initialNotification) {
        console.log('Notification caused app to open from quit state:', initialNotification.notification);
        // Store the notification to be processed after app is fully initialized
        this.pendingNotification = initialNotification;
        console.log('[PushNotificationService] Stored initial notification as pending');
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