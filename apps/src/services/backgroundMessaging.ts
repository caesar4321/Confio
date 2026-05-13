import messaging from '@react-native-firebase/messaging';
import notifee, { AndroidImportance, EventType } from '@notifee/react-native';
import notificationDedup from './notificationDeduplication';
import { savePendingNotificationOpen } from './notificationOpenStore';
import { describeTypes, logBreadcrumb, recordCrashError } from './crashLog';

// Register background handler
messaging().setBackgroundMessageHandler(async remoteMessage => {
  // Check for duplicates using global deduplication
  const messageId = remoteMessage.data?.message_id;
  const notificationId = remoteMessage.data?.notification_id;
  const firebaseMessageId = remoteMessage.messageId;

  if (notificationDedup.isDuplicate(messageId || firebaseMessageId, notificationId)) {
    return;
  }

  // Display notification using Notifee
  const channelId = await notifee.createChannel({
    id: 'default',
    name: 'Default Channel',
    importance: AndroidImportance.HIGH,
  });

  // Generate unique notification ID — coerce to string defensively in case any
  // upstream value is unexpectedly an object on this Android build.
  const rawNotifId = notificationId || messageId || firebaseMessageId || `bg_${Date.now()}`;
  const notifId = typeof rawNotifId === 'string' ? rawNotifId : String(rawNotifId);
  const title = String(remoteMessage.notification?.title || 'Confío');
  const body = String(remoteMessage.notification?.body || '');

  logBreadcrumb(
    `bgMessage.displayNotification | ${describeTypes({
      notifId,
      title,
      body,
      hasData: remoteMessage.data != null,
    })}`
  );

  try {
    await notifee.displayNotification({
      id: notifId,
      title,
      body,
      data: remoteMessage.data,
      android: {
        channelId,
        importance: AndroidImportance.HIGH,
        pressAction: { id: 'default' },
        tag: notifId,
      },
      ios: {
        sound: 'default',
        categoryId: 'default',
      },
    });
  } catch (error) {
    recordCrashError(error);
    throw error;
  }
});

// Background event handler for Notifee
notifee.onBackgroundEvent(async ({ type, detail }) => {
  if (type === EventType.PRESS && detail.notification) {
    logBreadcrumb(
      `notifee.onBackgroundEvent.PRESS | ${describeTypes({
        title: detail.notification.title,
        body: detail.notification.body,
        hasData: detail.notification.data != null,
      })}`
    );
    await savePendingNotificationOpen({
      data: (detail.notification.data || undefined) as Record<string, string> | undefined,
      title: detail.notification.title,
      body: detail.notification.body,
    });
  }
});
