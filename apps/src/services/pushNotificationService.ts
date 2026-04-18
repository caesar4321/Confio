import messaging, { FirebaseMessagingTypes } from '@react-native-firebase/messaging';
import notifee from '@notifee/react-native';
import { Platform, PermissionsAndroid } from 'react-native';
import * as Keychain from 'react-native-keychain';
import * as RootNavigation from '../navigation/RootNavigation';
import {
  clearPendingNotificationOpen,
  loadPendingNotificationOpen,
} from './notificationOpenStore';

const NOTIFICATION_PERMISSION_KEY = 'push_notification_permission';
const NOTIFICATION_TOKEN_KEY = 'push_notification_token';
const NOTIFICATION_PROMPT_SHOWN_KEY = 'push_notification_prompt_shown';
const NOTIFICATION_PROMPT_TIMESTAMP_KEY = 'push_notification_prompt_timestamp';

const normalizeRampNotificationPayload = (data: any, notifType?: string, id?: string) => {
  const direction = (data?.direction || data?.ramp_direction || data?.rampDirection || '').toString().toLowerCase();
  const fiatAmount = data?.ramp_fiat_amount ?? data?.rampFiatAmount;
  const fiatCurrency = data?.ramp_fiat_currency ?? data?.rampFiatCurrency;
  const walletAmount = data?.wallet_amount ?? data?.walletAmount ?? data?.amount;
  const walletCurrency = data?.wallet_currency ?? data?.walletCurrency ?? 'cUSD';

  return {
    ...data,
    ...(id ? { id } : {}),
    notification_type: notifType || data?.notification_type,
    transaction_type: 'ramp',
    ramp_direction: direction,
    rampDirection: direction,
    amount: direction === 'on_ramp' ? (fiatAmount ?? data?.amount) : walletAmount,
    currency: direction === 'on_ramp'
      ? (fiatCurrency ?? data?.currency ?? data?.token_type ?? data?.tokenType)
      : 'cUSD',
    token_type: direction === 'on_ramp'
      ? (fiatCurrency ?? data?.currency ?? data?.token_type ?? data?.tokenType)
      : 'cUSD',
    ramp_fiat_amount: fiatAmount,
    ramp_fiat_currency: fiatCurrency,
    wallet_amount: walletAmount,
    wallet_currency: walletCurrency,
  };
};

export class PushNotificationService {
  private static instance: PushNotificationService;
  private isInitialized = false;
  private pendingNotification: FirebaseMessagingTypes.RemoteMessage | null = null;
  private pendingAccountSwitch: string | null = null;
  public static pendingAccountSwitchGlobal: string | null = null;
  private static pendingNavigationAfterSwitch: (() => void) | null = null;

  private constructor() {}

  static getInstance(): PushNotificationService {
    if (!PushNotificationService.instance) {
      PushNotificationService.instance = new PushNotificationService();
    }
    return PushNotificationService.instance;
  }

  /**
   * Get pending account switch (if any)
   */
  static getPendingAccountSwitch(): string | null {
    console.log('[PushNotificationService] getPendingAccountSwitch:', PushNotificationService.pendingAccountSwitchGlobal);
    return PushNotificationService.pendingAccountSwitchGlobal;
  }

  /**
   * Clear pending account switch
   */
  static clearPendingAccountSwitch(): void {
    console.log('[PushNotificationService] Clearing pending account switch');
    PushNotificationService.pendingAccountSwitchGlobal = null;
  }

  /**
   * Get pending navigation
   */
  static getPendingNavigation(): (() => void) | null {
    return PushNotificationService.pendingNavigationAfterSwitch;
  }

  /**
   * Clear pending navigation
   */
  static clearPendingNavigation(): void {
    PushNotificationService.pendingNavigationAfterSwitch = null;
  }

  /**
   * Process any pending notification navigation
   * This should be called after the app is fully initialized and authenticated
   */
  processPendingNotification(): void {
    console.log('[PushNotificationService] processPendingNotification called', {
      hasPending: !!this.pendingNotification,
      hasPendingAccountSwitch: !!PushNotificationService.pendingAccountSwitchGlobal
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
  private async handleNotificationNavigation(remoteMessage: FirebaseMessagingTypes.RemoteMessage): Promise<void> {
    console.log('[PushNotificationService] Handling notification navigation:', {
      data: remoteMessage.data,
      notification: remoteMessage.notification
    });
    
    if (!remoteMessage.data) {
      console.log('[PushNotificationService] No data in remote message');
      return;
    }
    
    // Extract account context from notification data
    const { account_context, business_id, account_type, account_index } = remoteMessage.data;
    
    console.log('[PushNotificationService] Account context from notification:', {
      account_context,
      business_id,
      account_type,
      account_index
    });
    
    // Check if we need to switch accounts - defer the switch until app is ready
    if (account_context) {
      try {
        // Import AuthService to check current context
        const { AuthService } = await import('./authService');
        const authService = new AuthService();
        
        // Get current active account context
        const currentContext = await authService.getActiveAccountContext();
        console.log('[PushNotificationService] Current active account context:', {
          type: currentContext?.type,
          index: currentContext?.index,
          businessId: currentContext?.businessId
        });
        
        // Check if we need to switch
        let needSwitch = false;
        let targetAccountId = '';
        
        if (account_context === 'business' && business_id) {
          // Check if current account is the correct business account
          needSwitch = currentContext?.type !== 'business' || 
                      currentContext?.businessId !== business_id;
                      
          if (needSwitch) {
            // Business account ID format: business_{businessId}_0
            targetAccountId = `business_${business_id}_0`;
            console.log('[PushNotificationService] Will defer switch to business account:', targetAccountId);
          }
        } else if (account_context === 'personal') {
          // Check if current account is a personal account
          needSwitch = currentContext?.type !== 'personal';
          
          if (needSwitch) {
            // Personal account ID format: personal_{index}
            const index = account_index || '0';
            targetAccountId = `personal_${index}`;
            console.log('[PushNotificationService] Will defer switch to personal account:', targetAccountId);
          }
        }
        
        // Store the account switch for later execution when app is fully ready
        if (needSwitch && targetAccountId) {
          console.log('[PushNotificationService] Storing pending account switch:', {
            targetAccountId,
            needSwitch
          });
          this.pendingAccountSwitch = targetAccountId;
          PushNotificationService.pendingAccountSwitchGlobal = targetAccountId;
          
          // Store the navigation to execute after account switch
          PushNotificationService.pendingNavigationAfterSwitch = () => {
            console.log('[PushNotificationService] Executing deferred navigation after account switch');
            this.performDeferredNavigation(remoteMessage);
          };
          
          // Navigate to HomeScreen first to trigger account switch
          console.log('[PushNotificationService] Navigating to HomeScreen for account switch');
          if (RootNavigation.navigationRef.isReady()) {
            RootNavigation.navigationRef.navigate('Main' as never, {
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
        console.error('[PushNotificationService] Error checking account context:', error);
        // Continue with navigation even if account check fails
      }
    }
    
    // No account switch needed, proceed with normal navigation
    this.performDeferredNavigation(remoteMessage);
  }

  /**
   * Perform the actual navigation
   */
  private performDeferredNavigation(remoteMessage: FirebaseMessagingTypes.RemoteMessage): void {
    const { action_url, extra_type, extra_transactionType, notification_type } = remoteMessage.data;
    
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

      if (action_url?.includes('app/deeplink/')) {
        console.log('[PushNotificationService] Delegating app/deeplink notification to MessagingService');
        const { messagingService } = require('./messagingService');
        messagingService.handleNotificationPayload(remoteMessage.data, true);
        return;
      }
      
      // Parse action URL if it exists
      if (action_url) {
        const pendingAutoSwap =
          remoteMessage.data?.pending_auto_swap === 'true' ||
          remoteMessage.data?.pending_auto_swap === 'True' ||
          remoteMessage.data?.data_pending_auto_swap === 'true' ||
          remoteMessage.data?.data_pending_auto_swap === 'True';

        if (pendingAutoSwap) {
          RootNavigation.navigationRef.navigate('Main' as never, {
            screen: 'BottomTabs',
            params: {
              screen: 'Home',
            },
          } as never);
          return;
        }

        if (action_url.includes('p2p/trade/')) {
          const tradeId = action_url.split('p2p/trade/')[1];
          console.log('[PushNotificationService] Navigating to ActiveTrade:', tradeId);
          // Use the navigation ref directly for nested navigation
          if (RootNavigation.navigationRef.isReady()) {
            RootNavigation.navigationRef.navigate('Main' as never, {
              screen: 'ActiveTrade',
              params: { 
                trade: { 
                  id: tradeId 
                },
                // Allow TradeChatScreen to auto-switch context only for push-origin navigation
                allowAccountSwitch: true
              }
            } as never);
          } else {
            console.log('[PushNotificationService] Navigation not ready, will retry...');
            // Retry after a delay
            setTimeout(() => {
              RootNavigation.navigate('ActiveTrade' as never, { 
                trade: { 
                  id: tradeId 
                },
                allowAccountSwitch: true
              } as never);
            }, 1000);
          }
        } else if (action_url.includes('transaction/') || action_url.includes('send/')) {
          // Handle both confio://transaction/{id} (payments) and confio://send/{id} (sends)
          const transactionId = action_url.includes('transaction/')
            ? action_url.split('transaction/')[1]
            : action_url.split('send/')[1];

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
          } else if (
            notification_type === 'RAMP_PENDING' ||
            notification_type === 'RAMP_PROCESSING' ||
            notification_type === 'RAMP_COMPLETED' ||
            notification_type === 'RAMP_FAILED'
          ) {
            transactionType = 'ramp';
            Object.assign(
              transactionData,
              normalizeRampNotificationPayload(transactionData, notification_type, transactionId),
            );
          }

          // For confirmed transaction notifications (sends & payments), navigate directly
          // to the official receipt. These notifications only fire after Celery confirms
          // the transaction on-chain, so the receipt will show "Confirmado".
          const isConfirmedTxNotification =
            notification_type === 'SEND_SENT' ||
            notification_type === 'SEND_RECEIVED' ||
            notification_type === 'PAYMENT_SENT' ||
            notification_type === 'PAYMENT_RECEIVED';

          if (isConfirmedTxNotification) {
            // Format token type for display (CUSD → cUSD)
            const rawToken = transactionData.token_type || '';
            const currency = rawToken.toUpperCase() === 'CUSD' ? 'cUSD'
              : rawToken.toUpperCase() === 'CONFIO' ? 'CONFIO'
              : rawToken.toUpperCase() === 'USDC' ? 'USDC'
              : rawToken || 'cUSD';

            const isPayment = transactionType === 'payment';
            const receiptType = isPayment ? 'payment' : 'transfer';

            const receiptTransaction = {
              id: transactionData.internal_id || transactionId,
              internalId: transactionData.internal_id || transactionId,
              verificationId: transactionData.internal_id || transactionId,
              transactionHash: transactionData.transaction_hash || '',
              amount: transactionData.amount || '0',
              currency,
              status: 'confirmed',
              date: remoteMessage.data?.created_at || new Date().toISOString(),
              memo: transactionData.memo || '',
              // Sender/recipient names from notification payload
              senderName: transactionData.sender_name || '',
              sender_name: transactionData.sender_name || '',
              recipientName: transactionData.recipient_name || '',
              recipient_name: transactionData.recipient_name || '',
              senderPhone: transactionData.sender_phone || '',
              recipientPhone: transactionData.recipient_phone || '',
              // Payment-specific fields
              ...(isPayment && {
                merchantName: transactionData.recipient_name || '',
                payerName: transactionData.sender_name || '',
              }),
            };

            console.log('[PushNotificationService] Navigating to TransactionReceipt:', {
              receiptType,
              receiptTransaction,
              notification_type,
            });

            const navigateToReceipt = () => {
              const target = RootNavigation.navigationRef.isReady()
                ? RootNavigation.navigationRef
                : null;

              if (target) {
                target.navigate('Main' as never, {
                  screen: 'TransactionReceipt',
                  params: {
                    transaction: receiptTransaction,
                    type: receiptType,
                  },
                } as never);
              } else {
                setTimeout(() => {
                  RootNavigation.navigate('TransactionReceipt' as never, {
                    transaction: receiptTransaction,
                    type: receiptType,
                  } as never);
                }, 1000);
              }
            };

            navigateToReceipt();
          } else {
            // For ramp and other non-confirmed notifications, keep existing TransactionDetail behavior
            console.log('[PushNotificationService] Navigating to TransactionDetail:', {
              transactionType,
              transactionData,
              transactionId,
              notification_type
            });

            if (RootNavigation.navigationRef.isReady()) {
              RootNavigation.navigationRef.navigate('Main' as never, {
                screen: 'TransactionDetail',
                params: {
                  transactionType,
                  transactionData: {
                    ...transactionData,
                    id: transactionId,
                    transaction_type: transactionType
                  }
                }
              } as never);
            } else {
              console.log('[PushNotificationService] Navigation not ready for transaction, will retry...');
              setTimeout(() => {
                RootNavigation.navigate('TransactionDetail' as never, {
                  transactionType,
                  transactionData: {
                    ...transactionData,
                    id: transactionId,
                    transaction_type: transactionType
                  }
                } as never);
              }, 1000);
            }
          }
        } else {
          console.log('[PushNotificationService] Unknown action URL format:', action_url);
          // Fallback to NotificationScreen
          if (RootNavigation.navigationRef.isReady()) {
            RootNavigation.navigationRef.navigate('Main' as never, {
              screen: 'Notifications'
            } as never);
          } else {
            setTimeout(() => {
              RootNavigation.navigate('Notifications' as never);
            }, 1000);
          }
        }
      } else {
        console.log('[PushNotificationService] No action URL, navigating to NotificationScreen');
        // Fallback to NotificationScreen if no specific action
        if (RootNavigation.navigationRef.isReady()) {
          RootNavigation.navigationRef.navigate('Main' as never, {
            screen: 'Notifications'
          } as never);
        } else {
          setTimeout(() => {
            RootNavigation.navigate('Notifications' as never);
          }, 1000);
        }
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
      
      // Clear any stale pending switches from previous app sessions
      PushNotificationService.pendingAccountSwitchGlobal = null;
      PushNotificationService.pendingNavigationAfterSwitch = null;
      this.pendingAccountSwitch = null;
      console.log('[PushNotificationService] Cleared any stale pending switches');
      
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

      if (!this.pendingNotification) {
        const notifeeInitialNotification = await notifee.getInitialNotification();
        if (notifeeInitialNotification?.notification?.data) {
          console.log('[PushNotificationService] Restoring initial notification from Notifee');
          this.pendingNotification = {
            data: notifeeInitialNotification.notification.data as Record<string, string>,
            notification: {
              title: notifeeInitialNotification.notification.title,
              body: notifeeInitialNotification.notification.body,
            },
          } as FirebaseMessagingTypes.RemoteMessage;
          console.log('[PushNotificationService] Stored Notifee initial notification as pending');
        }
      }

      if (!this.pendingNotification) {
        const persistedNotificationOpen = await loadPendingNotificationOpen();
        if (persistedNotificationOpen?.data) {
          console.log('[PushNotificationService] Restoring persisted notification press from background store');
          this.pendingNotification = {
            data: persistedNotificationOpen.data,
            notification: {
              title: persistedNotificationOpen.title,
              body: persistedNotificationOpen.body,
            },
          } as FirebaseMessagingTypes.RemoteMessage;
          await clearPendingNotificationOpen();
          console.log('[PushNotificationService] Stored persisted notification press as pending');
        }
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
