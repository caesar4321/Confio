import messaging from '@react-native-firebase/messaging';
import notifee, { AndroidImportance, AndroidStyle, EventType } from '@notifee/react-native';
import { Platform } from 'react-native';
import * as Keychain from 'react-native-keychain';
import DeviceInfo from 'react-native-device-info';
import { apolloClient } from '../apollo/client';
import { REGISTER_FCM_TOKEN, UNREGISTER_FCM_TOKEN } from '../graphql/mutations/notifications';
import { navigationRef } from '../navigation/RootNavigation';
import notificationDedup from './notificationDeduplication';

const FCM_TOKEN_SERVICE = 'confio_fcm_token';
const DEVICE_ID_SERVICE = 'confio_device_id';

// Global singleton to prevent multiple instances across reloads
let globalMessagingInstance: MessagingService | null = null;

class MessagingService {
  private static instance: MessagingService;
  private fcmToken: string | null = null;
  private deviceId: string | null = null;
  private displayedMessageIds: Set<string> = new Set();
  private displayedNotificationIds: Set<string> = new Set();
  private messageHandlersSetup: boolean = false;
  private unsubscribeHandlers: (() => void)[] = [];
  private instanceId: string;
  private channelCreated: boolean = false;

  constructor() {
    this.instanceId = `msg_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
    console.log(`[MessagingService] Creating instance: ${this.instanceId}`);
  }

  static getInstance(): MessagingService {
    // Use global singleton to persist across hot reloads
    if (!globalMessagingInstance) {
      globalMessagingInstance = new MessagingService();
      // Store reference on window for debugging
      if (typeof window !== 'undefined') {
        (window as any).__messagingService = globalMessagingInstance;
      }
    }
    return globalMessagingInstance;
  }

  async initialize(forceTokenRefresh: boolean = false) {
    try {
      console.log(`[MessagingService] Initializing with forceTokenRefresh=${forceTokenRefresh}`);
      
      // Check current permission status
      const authStatus = await messaging().hasPermission();
      const enabled =
        authStatus === messaging.AuthorizationStatus.AUTHORIZED ||
        authStatus === messaging.AuthorizationStatus.PROVISIONAL;

      if (!enabled) {
        console.log('[MessagingService] Notification permission not granted, skipping initialization');
        return;
      }

      // For iOS, also ensure Notifee permissions
      if (Platform.OS === 'ios') {
        await notifee.requestPermission();
      }

      // Get or generate device ID
      this.deviceId = await this.getOrCreateDeviceId();
      console.log(`[MessagingService] Using device ID: ${this.deviceId}`);

      // Always get a fresh token and register it for the current user
      // This is crucial for multi-user support on the same device
      console.log('[MessagingService] Getting FCM token for current user...');
      await this.getFCMToken();

      // Set up message handlers only once
      if (!this.messageHandlersSetup) {
        this.setupMessageHandlers();
      }

      // Create notification channel for Android
      if (Platform.OS === 'android' && !this.channelCreated) {
        await this.createNotificationChannel();
        this.channelCreated = true;
      }

      console.log('[MessagingService] Initialization complete');
    } catch (error) {
      console.error('[MessagingService] Error during initialization:', error);
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
      
      // For iOS, we need to register for remote notifications first
      if (Platform.OS === 'ios') {
        await messaging().registerDeviceForRemoteMessages();
      }
      
      // Get APNs token for iOS (required for Firebase to work)
      if (Platform.OS === 'ios') {
        const apnsToken = await messaging().getAPNSToken();
        if (!apnsToken) {
          console.log('Failed to get APNs token - notifications may not work');
        }
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
      
      await Keychain.resetInternetCredentials({ server: FCM_TOKEN_SERVICE });
      this.fcmToken = null;
      
      console.log('FCM token unregistered successfully');
    } catch (error) {
      console.error('Error unregistering FCM token:', error);
    }
  }

  async ensureTokenRegisteredForCurrentUser() {
    try {
      console.log('[MessagingService] Ensuring token is registered for current user...');
      
      // Check if we have permission
      const authStatus = await messaging().hasPermission();
      const enabled =
        authStatus === messaging.AuthorizationStatus.AUTHORIZED ||
        authStatus === messaging.AuthorizationStatus.PROVISIONAL;

      if (!enabled) {
        console.log('[MessagingService] No notification permission, skipping token registration');
        return false;
      }

      // Get device ID
      if (!this.deviceId) {
        this.deviceId = await this.getOrCreateDeviceId();
      }

      // Get current FCM token from Firebase
      const currentToken = await messaging().getToken();
      if (!currentToken) {
        console.log('[MessagingService] No FCM token available');
        return false;
      }

      // Register the token for the current user
      console.log('[MessagingService] Registering FCM token for current user...');
      await this.registerToken(currentToken);
      
      // Store the token locally
      this.fcmToken = currentToken;
      await Keychain.setInternetCredentials(
        FCM_TOKEN_SERVICE,
        'fcm_token',
        currentToken
      );

      console.log('[MessagingService] Token successfully registered for current user');
      return true;
    } catch (error) {
      console.error('[MessagingService] Error ensuring token registration:', error);
      return false;
    }
  }

  private setupMessageHandlers() {
    console.log(`[${this.instanceId}] Setting up message handlers`);
    
    // Always clean up previous handlers first
    this.cleanup();
    
    // Check if another instance already has handlers set up
    if (typeof window !== 'undefined' && (window as any).__activeMessagingInstance) {
      const activeInstance = (window as any).__activeMessagingInstance;
      if (activeInstance !== this.instanceId) {
        console.log(`[${this.instanceId}] Another instance (${activeInstance}) is already handling messages, skipping setup`);
        return;
      }
    }
    
    // Mark this instance as the active one
    if (typeof window !== 'undefined') {
      (window as any).__activeMessagingInstance = this.instanceId;
    }
    
    this.messageHandlersSetup = true;

    // Handle messages when app is in foreground
    const unsubscribeOnMessage = messaging().onMessage(async remoteMessage => {
      const timestamp = new Date().toISOString();
      const messageId = remoteMessage.data?.message_id;
      const notificationId = remoteMessage.data?.notification_id;
      const firebaseMessageId = remoteMessage.messageId; // This is the unique ID from Firebase
      
      console.log(`[${timestamp}] [${this.instanceId}] Foreground message received:`, {
        messageId,
        notificationId,
        firebaseMessageId,
        title: remoteMessage.notification?.title,
        sentTime: remoteMessage.sentTime,
        data: remoteMessage.data
      });
      
      // CRITICAL: Use Firebase messageId for deduplication since it's always present
      const deduplicationKey = firebaseMessageId || notificationId || `${timestamp}_${remoteMessage.notification?.title}`;
      
      console.log(`[${timestamp}] [${this.instanceId}] Checking global dedup with key:`, deduplicationKey);
      
      if (notificationDedup.isDuplicate(deduplicationKey, notificationId)) {
        console.log(`[${timestamp}] [${this.instanceId}] Global dedup: Duplicate notification detected, skipping`);
        return;
      }
      
      // Still check local cache as backup
      if (messageId && this.displayedMessageIds.has(messageId)) {
        console.log(`[${timestamp}] Local dedup: Duplicate notification detected with message_id: ${messageId}, skipping`);
        return;
      }
      
      if (notificationId && this.displayedNotificationIds.has(notificationId)) {
        console.log(`[${timestamp}] Local dedup: Duplicate notification detected with notification_id: ${notificationId}, skipping`);
        return;
      }
      
      // Add to local cache as well
      if (messageId) {
        this.displayedMessageIds.add(messageId);
        setTimeout(() => this.displayedMessageIds.delete(messageId), 5 * 60 * 1000);
      }
      
      if (notificationId) {
        this.displayedNotificationIds.add(notificationId);
        setTimeout(() => this.displayedNotificationIds.delete(notificationId), 5 * 60 * 1000);
      }
      
      await this.displayNotification(remoteMessage);
      
      // Trigger notification count update
      this.triggerNotificationCountUpdate();
    });
    this.unsubscribeHandlers.push(unsubscribeOnMessage);

    // Handle notification opened from background state
    const unsubscribeOnNotificationOpened = messaging().onNotificationOpenedApp(remoteMessage => {
      console.log('[MessagingService] ===== NOTIFICATION OPENED FROM BACKGROUND =====');
      console.log('[MessagingService] Remote message:', JSON.stringify(remoteMessage, null, 2));
      this.handleNotificationOpen(remoteMessage);
    });
    this.unsubscribeHandlers.push(unsubscribeOnNotificationOpened);

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
    const unsubscribeOnTokenRefresh = messaging().onTokenRefresh(async token => {
      console.log('FCM token refreshed:', token);
      await this.registerToken(token);
      await Keychain.setInternetCredentials(
        FCM_TOKEN_SERVICE,
        'fcm_token',
        token
      );
      this.fcmToken = token;
    });
    this.unsubscribeHandlers.push(unsubscribeOnTokenRefresh);

    // Handle Notifee events
    notifee.onForegroundEvent(({ type, detail }) => {
      console.log('[MessagingService] ===== NOTIFEE FOREGROUND EVENT =====');
      console.log('[MessagingService] Event type:', type);
      console.log('[MessagingService] Event detail:', JSON.stringify(detail, null, 2));
      
      if (type === EventType.PRESS) {
        console.log('[MessagingService] Notifee notification pressed:', detail.notification);
        if (detail.notification?.data) {
          this.handleNotificationData(detail.notification.data);
        }
      }
    });
  }

  private async displayNotification(remoteMessage: any) {
    const timestamp = new Date().toISOString();
    const messageId = remoteMessage.data?.message_id;
    const notificationId = remoteMessage.data?.notification_id || messageId || `notif_${Date.now()}`;
    
    console.log(`[${timestamp}] displayNotification called with:`, {
      notificationId,
      messageId,
      title: remoteMessage.notification?.title
    });

    // For Android, ensure channel exists
    if (Platform.OS === 'android') {
      await notifee.createChannel({
        id: 'default',
        name: 'Default Channel',
        importance: AndroidImportance.HIGH,
      });
    }

    try {
      // Display the notification
      await notifee.displayNotification({
        id: notificationId, // Set explicit ID to prevent duplicates
        title: remoteMessage.notification?.title || 'Confío',
        body: remoteMessage.notification?.body || '',
        data: remoteMessage.data,
        android: {
          channelId: 'default',
          smallIcon: 'ic_stat_ic_notification',
          largeIcon: 'ic_launcher',
          color: '#8b5cf6',  // Confío violet accent color
          pressAction: {
            id: 'default',
          },
          // Group notifications properly
          groupId: 'confio_notifications',
          groupSummary: false,  // Individual notifications should not be summaries
          // Use tag to replace existing notification with same ID
          tag: notificationId,
        },
        ios: {
          foregroundPresentationOptions: {
            badge: true,
            sound: true,
            banner: true,
            list: true,
          },
          categoryId: 'default',
        },
      });
      console.log(`[${timestamp}] Notification displayed successfully with ID: ${notificationId}`);
    } catch (error) {
      console.error(`[${timestamp}] Error displaying notification:`, error);
    }
  }

  private async createNotificationChannel() {
    // Create default notification channel for Android
    await notifee.createChannel({
      id: 'default',
      name: 'Confío Notifications',
      importance: AndroidImportance.HIGH,
      sound: 'default',
      vibration: true,
      lights: true,
      lightColor: '#72D9BC',  // Notification mint color for LED
    });
  }

  private handleNotificationOpen(remoteMessage: any) {
    console.log('Notification opened:', remoteMessage);
    const data = remoteMessage.data;
    if (data) {
      console.log('Notification data:', data);
      this.handleNotificationData(data);
    } else {
      console.log('No data in notification');
    }
  }

  private async handleNotificationData(data: any, skipAccountCheck: boolean = false) {
    console.log('[MessagingService] handleNotificationData called with:', data, { skipAccountCheck });
    
    // LEGACY FORMAT DETECTION:
    // Handle old push notifications that may have been sent with the previous screen name.
    // Some notifications in the system might still reference 'P2PTradeDetail' which no longer exists.
    // We convert these to the proper action_url format that will navigate to ActiveTrade.
    // This ensures users with old notifications can still open them without errors.
    if (data.name === 'P2PTradeDetail' && data.params?.tradeId) {
      console.log('[MessagingService] Handling legacy P2PTradeDetail navigation');
      // Convert to new format
      data.action_url = `confio://p2p/trade/${data.params.tradeId}`;
      delete data.name;
      delete data.params;
    }
    
    // Extract account context from notification data
    const accountContext = data.account_context;
    const businessId = data.business_id;
    const accountType = data.account_type;
    const accountIndex = data.account_index;
    
    console.log('[MessagingService] Account context from notification:', {
      accountContext,
      businessId,
      accountType,
      accountIndex
    });
    
    // For foreground notifications, also defer account switching
    // to avoid conflicts with UI state
    if (accountContext && !skipAccountCheck) {
      try {
        // Import AuthService to check current context
        const { AuthService } = await import('./authService');
        const { PushNotificationService } = await import('./pushNotificationService');
        const authService = new AuthService();
        
        // Get current active account context
        const currentContext = await authService.getActiveAccountContext();
        console.log('[MessagingService] Current active account context:', {
          type: currentContext?.type,
          index: currentContext?.index,
          businessId: currentContext?.businessId
        });
        
        // Check if we need to switch
        let needSwitch = false;
        let targetAccountId = '';
        
        if (accountContext === 'business' && businessId) {
          // Check if current account is the correct business account
          needSwitch = currentContext?.type !== 'business' || 
                      currentContext?.businessId !== businessId;
                      
          if (needSwitch) {
            // Business account ID format: business_{businessId}_0
            targetAccountId = `business_${businessId}_0`;
            console.log('[MessagingService] Need to switch to business account:', targetAccountId);
          }
        } else if (accountContext === 'personal') {
          // Check if current account is a personal account
          needSwitch = currentContext?.type !== 'personal';
          
          if (needSwitch) {
            // Personal account ID format: personal_{index}
            const index = accountIndex || '0';
            targetAccountId = `personal_${index}`;
            console.log('[MessagingService] Need to switch to personal account:', targetAccountId);
          }
        }
        
        // Store the account switch for HomeScreen to handle
        if (needSwitch && targetAccountId) {
          console.log('[MessagingService] Storing pending account switch for HomeScreen:', {
            targetAccountId,
            needSwitch
          });
          PushNotificationService.pendingAccountSwitchGlobal = targetAccountId;
          
          // Store the navigation to execute after account switch
          PushNotificationService.pendingNavigationAfterSwitch = () => {
            console.log('[MessagingService] Executing deferred navigation after account switch');
            // Re-process the notification data for navigation, skipping account check
            this.handleNotificationData(data, true);
          };
          
          // Navigate to HomeScreen first to trigger account switch
          console.log('[MessagingService] Navigating to HomeScreen for account switch');
          if (navigationRef.current && navigationRef.current.isReady()) {
            navigationRef.current.navigate('Main' as never, {
              screen: 'BottomTabs',
              params: {
                screen: 'Home'
              }
            } as never);
          }
          
          // Don't continue with normal navigation
          return;
        }
      } catch (error) {
        console.error('[MessagingService] Error checking account context:', error);
        // Continue with navigation even if account check fails
      }
    }
    
    // Navigate based on notification data
    const { action_url, notification_type, related_type, related_id } = data;

    // Extract transaction data from data_ prefixed fields
    const transactionData: any = {};
    Object.keys(data).forEach(key => {
      if (key.startsWith('data_')) {
        const actualKey = key.substring(5); // Remove 'data_' prefix
        transactionData[actualKey] = data[key];
      }
    });
    
    // Also include the notification_type in transaction data for type detection
    if (notification_type) {
      transactionData.notification_type = notification_type;
    }

    console.log('[MessagingService] Extracted transaction data:', transactionData);
    console.log('[MessagingService] Navigation params:', { action_url, notification_type, related_type, related_id });

    // Ensure navigation is ready before attempting to navigate
    const attemptNavigation = () => {
      if (!navigationRef.current || !navigationRef.current.isReady()) {
        console.log('Navigation not ready, retrying in 100ms...');
        setTimeout(attemptNavigation, 100);
        return;
      }

      if (action_url) {
        // Parse deep link and navigate
        this.navigateToDeepLink(action_url, transactionData);
      } else if (related_type && related_id) {
        // Navigate based on related object
        this.navigateToRelatedObject(related_type, related_id, transactionData);
      } else if (notification_type) {
        // Navigate to notifications screen using nested navigation
        navigationRef.current?.navigate('Main' as never, {
          screen: 'Notifications'
        } as never);
      }
    };

    attemptNavigation();
  }

  private navigateToDeepLink(url: string, transactionData?: any) {
    console.log('[MessagingService] navigateToDeepLink called with:', { url, transactionData });
    
    // Parse deep link format: confio://screen/params OR /screen/params
    let path = url;
    
    // Handle confio:// prefix if present
    const confioMatch = url.match(/confio:\/\/(.+)/);
    if (confioMatch) {
      path = confioMatch[1];
    } else if (url.startsWith('/')) {
      // Handle URLs that start with / (like /transaction/123)
      path = url.substring(1); // Remove leading slash
    }
    
    const parts = path.split('/');
    console.log('[MessagingService] Parsed path parts:', parts);
    
    if (parts.length > 0) {
      switch (parts[0]) {
        case 'transaction':
          if (parts[1]) {
            // Navigate with transaction data if available, otherwise minimal data
            const navData = transactionData && Object.keys(transactionData).length > 0 
              ? transactionData 
              : { id: parts[1] };
            
            // Determine transaction type
            let transactionType = transactionData?.transaction_type || 'send';
            
            // Check if this is a payment transaction based on notification data
            const notificationType = transactionData?.notification_type;
            if (notificationType === 'PAYMENT_SENT' || notificationType === 'PAYMENT_RECEIVED') {
              transactionType = 'payment';
            }
            
            // Check if this is a USDC transaction
            if (notificationType === 'USDC_DEPOSIT_COMPLETED') {
              transactionType = 'deposit';
            } else if (notificationType === 'USDC_WITHDRAWAL_COMPLETED') {
              transactionType = 'withdrawal';
            } else if (notificationType === 'CONVERSION_COMPLETED') {
              transactionType = 'conversion';
            }
            
            console.log('[MessagingService] Navigating to TransactionDetail:', {
              transactionType,
              navData,
              notificationType
            });
            
            // Use nested navigation for TransactionDetail
            navigationRef.current?.navigate('Main' as never, {
              screen: 'TransactionDetail',
              params: { 
                transactionType,
                transactionData: navData
              }
            } as never);
          }
          break;
        case 'p2p':
          if (parts[1] === 'trade' && parts[2]) {
            navigationRef.current?.navigate('Main' as never, {
              screen: 'ActiveTrade',
              params: { 
                trade: { 
                  id: parts[2] 
                } 
              }
            } as never);
          } else if (parts[1] === 'offer' && parts[2]) {
            // For now, navigate to Exchange tab as there's no dedicated offer detail screen
            navigationRef.current?.navigate('Main' as never, {
              screen: 'BottomTabs',
              params: {
                screen: 'Exchange'
              }
            } as never);
          }
          break;
        case 'business':
          if (parts[1]) {
            // Navigate to Business tab for business-related notifications
            navigationRef.current?.navigate('Main' as never, {
              screen: 'BottomTabs',
              params: {
                screen: 'Business'
              }
            } as never);
          }
          break;
        case 'settings':
          if (parts[1] === 'security') {
            // Navigate to Settings tab
            navigationRef.current?.navigate('Main' as never, {
              screen: 'BottomTabs',
              params: {
                screen: 'Settings'
              }
            } as never);
          }
          break;
        case 'achievements':
          // Navigate to Achievements screen
          navigationRef.current?.navigate('Main' as never, {
            screen: 'Achievements'
          } as never);
          break;
        default:
          navigationRef.current?.navigate('Main' as never, {
            screen: 'Notifications'
          } as never);
      }
    }
  }

  private navigateToRelatedObject(type: string, id: string, transactionData?: any) {
    console.log('[MessagingService] navigateToRelatedObject called with:', { type, id, transactionData });
    
    // Handle legacy P2PTradeDetail navigation (for old notifications)
    if (type === 'P2PTradeDetail') {
      console.log('[MessagingService] Redirecting legacy P2PTradeDetail to ActiveTrade');
      type = 'P2PTrade';
    }
    
    switch (type) {
      case 'SendTransaction':
      case 'PaymentTransaction':
      case 'payment':
        // Navigate with transaction data if available, otherwise minimal data
        const navData = transactionData && Object.keys(transactionData).length > 0 
          ? { ...transactionData, id } 
          : { id };
        
        // Determine transaction type
        let transactionType = transactionData?.transaction_type || 'send';
        const notifType = transactionData?.notification_type;
        // Force receiver perspective for invitation received
        if (notifType === 'INVITE_RECEIVED' || notifType === 'SEND_RECEIVED') {
          transactionType = 'received';
          navData.transaction_type = 'received';
          navData.type = 'received';
        }
        if (type === 'PaymentTransaction' || type === 'payment') {
          transactionType = 'payment';
        }
        
        navigationRef.current?.navigate('Main' as never, {
          screen: 'TransactionDetail',
          params: { 
            transactionType,
            transactionData: navData
          }
        } as never);
        break;
      case 'P2PTrade':
        navigationRef.current?.navigate('Main' as never, {
          screen: 'ActiveTrade',
          params: { 
            trade: { 
              id: id 
            } 
          }
        } as never);
        break;
      case 'P2POffer':
        // Navigate to Exchange tab as there's no dedicated offer detail screen
        navigationRef.current?.navigate('Main' as never, {
          screen: 'BottomTabs',
          params: {
            screen: 'Exchange'
          }
        } as never);
        break;
      case 'Business':
        // Navigate to Business tab
        navigationRef.current?.navigate('Main' as never, {
          screen: 'BottomTabs',
          params: {
            screen: 'Business'
          }
        } as never);
        break;
      default:
        navigationRef.current?.navigate('Main' as never, {
          screen: 'Notifications'
        } as never);
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

  // Clean up handlers to prevent duplicates
  private triggerNotificationCountUpdate() {
    try {
      console.log('[MessagingService] Triggering notification count update...');
      
      // Use Apollo Client to refetch the notification count
      apolloClient.refetchQueries({
        include: ['GetUnreadNotificationCount'],
      }).then(() => {
        console.log('[MessagingService] Notification count refetch triggered');
      }).catch(error => {
        console.error('[MessagingService] Error refetching notification count:', error);
      });
    } catch (error) {
      console.error('[MessagingService] Error triggering notification count update:', error);
    }
  }

  private cleanup() {
    console.log(`[${this.instanceId}] Cleaning up messaging handlers`);
    
    // Clear active instance marker if it's this instance
    if (typeof window !== 'undefined' && (window as any).__activeMessagingInstance === this.instanceId) {
      (window as any).__activeMessagingInstance = null;
    }
    
    this.unsubscribeHandlers.forEach(unsubscribe => {
      try {
        unsubscribe();
      } catch (error) {
        console.error('Error unsubscribing handler:', error);
      }
    });
    this.unsubscribeHandlers = [];
    this.messageHandlersSetup = false;
  }
}

export default MessagingService.getInstance();
