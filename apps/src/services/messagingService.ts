import messaging from '@react-native-firebase/messaging';
import { Platform, Alert } from 'react-native';
import * as Keychain from 'react-native-keychain';
import DeviceInfo from 'react-native-device-info';
import { apolloClient } from '../apollo/client';
import { REGISTER_FCM_TOKEN, UNREGISTER_FCM_TOKEN } from '../graphql/mutations/notifications';
import { navigationRef } from '../navigation/RootNavigation';

const FCM_TOKEN_SERVICE = 'confio_fcm_token';
const DEVICE_ID_SERVICE = 'confio_device_id';

class MessagingService {
  private static instance: MessagingService;
  private fcmToken: string | null = null;
  private deviceId: string | null = null;

  static getInstance(): MessagingService {
    if (!MessagingService.instance) {
      MessagingService.instance = new MessagingService();
    }
    return MessagingService.instance;
  }

  async initialize() {
    try {
      // Request permission
      const authStatus = await messaging().requestPermission();
      const enabled =
        authStatus === messaging.AuthorizationStatus.AUTHORIZED ||
        authStatus === messaging.AuthorizationStatus.PROVISIONAL;

      if (!enabled) {
        console.log('Notification permission denied');
        return;
      }

      // Get or generate device ID
      this.deviceId = await this.getOrCreateDeviceId();

      // Get FCM token
      await this.getFCMToken();

      // Set up message handlers
      this.setupMessageHandlers();

      // Note: Android notification channels are handled by Firebase by default

      console.log('Messaging service initialized');
    } catch (error) {
      console.error('Error initializing messaging service:', error);
    }
  }

  private async getOrCreateDeviceId(): Promise<string> {
    try {
      // Try to get stored device ID from keychain
      const credentials = await Keychain.getInternetCredentials(DEVICE_ID_SERVICE);
      
      if (credentials && credentials.password) {
        return credentials.password;
      }
      
      // Generate new device ID
      const deviceId = await DeviceInfo.getUniqueId();
      await Keychain.setInternetCredentials(
        DEVICE_ID_SERVICE,
        'device_id',
        deviceId
      );
      
      return deviceId;
    } catch (error) {
      console.error('Error getting device ID:', error);
      // Fallback to a random ID
      const randomId = `device_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
      await Keychain.setInternetCredentials(
        DEVICE_ID_SERVICE,
        'device_id',
        randomId
      );
      return randomId;
    }
  }

  async getFCMToken(): Promise<string | null> {
    try {
      // Check if we have a stored token
      let storedToken: string | null = null;
      try {
        const credentials = await Keychain.getInternetCredentials(FCM_TOKEN_SERVICE);
        if (credentials && credentials.password) {
          storedToken = credentials.password;
        }
      } catch (e) {
        // No stored token
      }
      
      // Get current token from Firebase
      const currentToken = await messaging().getToken();
      
      // If token changed or new token, register it
      if (currentToken && currentToken !== storedToken) {
        await this.registerToken(currentToken);
        await Keychain.setInternetCredentials(
          FCM_TOKEN_SERVICE,
          'fcm_token',
          currentToken
        );
        this.fcmToken = currentToken;
      }
      
      return currentToken;
    } catch (error) {
      console.error('Error getting FCM token:', error);
      return null;
    }
  }

  private async registerToken(token: string) {
    try {
      if (!this.deviceId) {
        console.error('No device ID available');
        return;
      }

      const deviceName = await DeviceInfo.getDeviceName();
      const appVersion = DeviceInfo.getVersion();
      
      await apolloClient.mutate({
        mutation: REGISTER_FCM_TOKEN,
        variables: {
          token,
          deviceType: Platform.OS,
          deviceId: this.deviceId,
          deviceName,
          appVersion,
        },
      });
      
      console.log('FCM token registered successfully');
    } catch (error) {
      console.error('Error registering FCM token:', error);
    }
  }

  async unregisterToken() {
    try {
      if (!this.deviceId) {
        return;
      }

      await apolloClient.mutate({
        mutation: UNREGISTER_FCM_TOKEN,
        variables: {
          deviceId: this.deviceId,
        },
      });
      
      await Keychain.resetInternetCredentials(FCM_TOKEN_SERVICE);
      this.fcmToken = null;
      
      console.log('FCM token unregistered successfully');
    } catch (error) {
      console.error('Error unregistering FCM token:', error);
    }
  }

  private setupMessageHandlers() {
    // Handle messages when app is in foreground
    messaging().onMessage(async remoteMessage => {
      console.log('Foreground message received:', remoteMessage);
      // Display a simple alert for foreground notifications
      // In production, you might want to use a custom in-app notification component
      if (remoteMessage.notification) {
        Alert.alert(
          remoteMessage.notification.title || 'Notification',
          remoteMessage.notification.body || '',
          [
            { text: 'Dismiss', style: 'cancel' },
            { 
              text: 'View', 
              onPress: () => this.handleNotificationOpen(remoteMessage)
            }
          ]
        );
      }
    });

    // Handle notification opened from background state
    messaging().onNotificationOpenedApp(remoteMessage => {
      console.log('Notification opened from background:', remoteMessage);
      this.handleNotificationOpen(remoteMessage);
    });

    // Check if app was opened from a notification (killed state)
    messaging()
      .getInitialNotification()
      .then(remoteMessage => {
        if (remoteMessage) {
          console.log('App opened from notification (killed state):', remoteMessage);
          this.handleNotificationOpen(remoteMessage);
        }
      });

    // Handle token refresh
    messaging().onTokenRefresh(async token => {
      console.log('FCM token refreshed:', token);
      await this.registerToken(token);
      await Keychain.setInternetCredentials(
        FCM_TOKEN_SERVICE,
        'fcm_token',
        token
      );
      this.fcmToken = token;
    });

    // Note: For advanced notification handling, consider installing @notifee/react-native
  }

  // Note: displayNotification method removed - using Alert for foreground notifications
  // Background notifications are handled automatically by FCM

  // Note: Android notification channels are created automatically by FCM
  // For custom channels, you would need to configure them in your Android native code
  // or install @notifee/react-native

  private handleNotificationOpen(remoteMessage: any) {
    const data = remoteMessage.data;
    if (data) {
      this.handleNotificationData(data);
    }
  }

  private handleNotificationData(data: any) {
    // Navigate based on notification data
    const { action_url, notification_type, related_type, related_id } = data;

    if (action_url) {
      // Parse deep link and navigate
      this.navigateToDeepLink(action_url);
    } else if (related_type && related_id) {
      // Navigate based on related object
      this.navigateToRelatedObject(related_type, related_id);
    } else if (notification_type) {
      // Navigate to notifications screen
      navigationRef.current?.navigate('Notifications');
    }
  }

  private navigateToDeepLink(url: string) {
    // Parse deep link format: confio://screen/params
    const match = url.match(/confio:\/\/(.+)/);
    if (match) {
      const path = match[1];
      const parts = path.split('/');
      
      switch (parts[0]) {
        case 'transaction':
          if (parts[1]) {
            navigationRef.current?.navigate('TransactionDetail', { id: parts[1] });
          }
          break;
        case 'p2p':
          if (parts[1] === 'trade' && parts[2]) {
            navigationRef.current?.navigate('P2PTradeDetail', { tradeId: parts[2] });
          } else if (parts[1] === 'offer' && parts[2]) {
            navigationRef.current?.navigate('P2POfferDetail', { offerId: parts[2] });
          }
          break;
        case 'business':
          if (parts[1]) {
            navigationRef.current?.navigate('BusinessDetail', { businessId: parts[1] });
          }
          break;
        case 'settings':
          if (parts[1] === 'security') {
            navigationRef.current?.navigate('SecuritySettings');
          }
          break;
        default:
          navigationRef.current?.navigate('Notifications');
      }
    }
  }

  private navigateToRelatedObject(type: string, id: string) {
    switch (type) {
      case 'SendTransaction':
      case 'PaymentTransaction':
        navigationRef.current?.navigate('TransactionDetail', { id });
        break;
      case 'P2PTrade':
        navigationRef.current?.navigate('P2PTradeDetail', { tradeId: id });
        break;
      case 'P2POffer':
        navigationRef.current?.navigate('P2POfferDetail', { offerId: id });
        break;
      case 'Business':
        navigationRef.current?.navigate('BusinessDetail', { businessId: id });
        break;
      default:
        navigationRef.current?.navigate('Notifications');
    }
  }

  // Check if notifications are enabled
  async areNotificationsEnabled(): Promise<boolean> {
    const authStatus = await messaging().hasPermission();
    return authStatus === messaging.AuthorizationStatus.AUTHORIZED ||
           authStatus === messaging.AuthorizationStatus.PROVISIONAL;
  }

  // Request notification permissions
  async requestPermissions(): Promise<boolean> {
    try {
      const authStatus = await messaging().requestPermission();
      const enabled =
        authStatus === messaging.AuthorizationStatus.AUTHORIZED ||
        authStatus === messaging.AuthorizationStatus.PROVISIONAL;

      if (enabled) {
        // Re-initialize to register token
        await this.initialize();
      }

      return enabled;
    } catch (error) {
      console.error('Error requesting permissions:', error);
      return false;
    }
  }
}

export default MessagingService.getInstance();