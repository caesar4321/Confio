import * as Keychain from 'react-native-keychain';

const PENDING_NOTIFICATION_OPEN_SERVICE = 'confio_pending_notification_open';

export type PendingNotificationOpen = {
  data?: Record<string, string>;
  title?: string;
  body?: string;
};

export async function savePendingNotificationOpen(
  notification: PendingNotificationOpen
): Promise<void> {
  try {
    await Keychain.setInternetCredentials(
      PENDING_NOTIFICATION_OPEN_SERVICE,
      'pending_notification_open',
      JSON.stringify(notification)
    );
    console.log('[NotificationOpenStore] Saved pending notification open');
  } catch (error) {
    console.error('[NotificationOpenStore] Failed to save pending notification open:', error);
  }
}

export async function loadPendingNotificationOpen(): Promise<PendingNotificationOpen | null> {
  try {
    const credentials = await Keychain.getInternetCredentials(PENDING_NOTIFICATION_OPEN_SERVICE);
    if (!credentials?.password) {
      return null;
    }

    const parsed = JSON.parse(credentials.password) as PendingNotificationOpen;
    console.log('[NotificationOpenStore] Loaded pending notification open');
    return parsed;
  } catch (error) {
    console.error('[NotificationOpenStore] Failed to load pending notification open:', error);
    return null;
  }
}

export async function clearPendingNotificationOpen(): Promise<void> {
  try {
    await Keychain.resetInternetCredentials({ server: PENDING_NOTIFICATION_OPEN_SERVICE });
    console.log('[NotificationOpenStore] Cleared pending notification open');
  } catch (error) {
    console.error('[NotificationOpenStore] Failed to clear pending notification open:', error);
  }
}
