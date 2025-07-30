import { gql } from '@apollo/client';

export const GET_NOTIFICATION_PREFERENCES = gql`
  query GetNotificationPreferences {
    notificationPreferences {
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
`;

export const GET_FCM_DEVICE_TOKENS = gql`
  query GetFCMDeviceTokens {
    fcmDeviceTokens {
      id
      deviceType
      deviceId
      deviceName
      appVersion
      isActive
      lastUsed
      createdAt
    }
  }
`;