import messaging from '@react-native-firebase/messaging';
import notifee, { AndroidImportance, EventType } from '@notifee/react-native';
import notificationDedup from './notificationDeduplication';

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

  // Generate unique notification ID
  const notifId = notificationId || messageId || firebaseMessageId || `bg_${Date.now()}`;

  await notifee.displayNotification({
    id: notifId, // Set explicit ID to prevent duplicates
    title: remoteMessage.notification?.title || 'Confío',
    body: remoteMessage.notification?.body || '',
    data: remoteMessage.data,
    android: {
      channelId,
      importance: AndroidImportance.HIGH,
      pressAction: {
        id: 'default',
      },
      tag: notifId, // Use tag to replace existing notification
    },
    ios: {
      sound: 'default',
    },
  });
});

// Background event handler for Notifee
notifee.onBackgroundEvent(async ({ type, detail }) => {  if (type === EventType.PRESS && detail.notification) {
  }
});
