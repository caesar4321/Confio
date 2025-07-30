import { gql } from '@apollo/client';

export const REGISTER_FCM_TOKEN = gql`
  mutation RegisterFCMToken(
    $token: String!
    $deviceType: String!
    $deviceId: String!
    $deviceName: String
    $appVersion: String
  ) {
    registerFcmToken(
      token: $token
      deviceType: $deviceType
      deviceId: $deviceId
      deviceName: $deviceName
      appVersion: $appVersion
    ) {
      success
      deviceToken {
        id
        deviceType
        deviceId
        deviceName
        isActive
        lastUsed
      }
    }
  }
`;

export const UNREGISTER_FCM_TOKEN = gql`
  mutation UnregisterFCMToken($deviceId: String!) {
    unregisterFcmToken(deviceId: $deviceId) {
      success
    }
  }
`;

export const SEND_TEST_PUSH_NOTIFICATION = gql`
  mutation SendTestPushNotification {
    sendTestPushNotification {
      success
      sentCount
      failedCount
    }
  }
`;

export const UPDATE_NOTIFICATION_PREFERENCES = gql`
  mutation UpdateNotificationPreferences(
    $pushEnabled: Boolean
    $pushTransactions: Boolean
    $pushP2p: Boolean
    $pushSecurity: Boolean
    $pushPromotions: Boolean
    $pushAnnouncements: Boolean
    $inAppEnabled: Boolean
    $inAppTransactions: Boolean
    $inAppP2p: Boolean
    $inAppSecurity: Boolean
    $inAppPromotions: Boolean
    $inAppAnnouncements: Boolean
  ) {
    updateNotificationPreferences(
      pushEnabled: $pushEnabled
      pushTransactions: $pushTransactions
      pushP2p: $pushP2p
      pushSecurity: $pushSecurity
      pushPromotions: $pushPromotions
      pushAnnouncements: $pushAnnouncements
      inAppEnabled: $inAppEnabled
      inAppTransactions: $inAppTransactions
      inAppP2p: $inAppP2p
      inAppSecurity: $inAppSecurity
      inAppPromotions: $inAppPromotions
      inAppAnnouncements: $inAppAnnouncements
    ) {
      success
      preferences {
        pushEnabled
        pushTransactions
        pushP2p
        pushSecurity
        pushPromotions
        pushAnnouncements
        inAppEnabled
        inAppTransactions
        inAppP2p
        inAppSecurity
        inAppPromotions
        inAppAnnouncements
      }
    }
  }
`;

export const MARK_NOTIFICATION_READ = gql`
  mutation MarkNotificationRead($notificationId: ID!) {
    markNotificationRead(notificationId: $notificationId) {
      success
      notification {
        id
        isRead
      }
    }
  }
`;

export const MARK_ALL_NOTIFICATIONS_READ = gql`
  mutation MarkAllNotificationsRead {
    markAllNotificationsRead {
      success
      markedCount
    }
  }
`;