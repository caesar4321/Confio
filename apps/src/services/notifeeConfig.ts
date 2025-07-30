import notifee from '@notifee/react-native';
import { Platform } from 'react-native';

export async function initializeNotifee() {
  // Request permissions for iOS
  if (Platform.OS === 'ios') {
    const settings = await notifee.requestPermission();
    console.log('iOS notification permissions:', settings);
    
    // Set foreground notification presentation options
    await notifee.setNotificationCategories([
      {
        id: 'default',
        actions: [
          {
            id: 'open',
            title: 'Open',
            foreground: true,
          },
        ],
      },
    ]);
  }

  // Set up initial notification settings
  await notifee.setBadgeCount(0);
}