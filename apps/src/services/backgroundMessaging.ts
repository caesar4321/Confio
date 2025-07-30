import messaging from '@react-native-firebase/messaging';

// Register background handler
messaging().setBackgroundMessageHandler(async remoteMessage => {
  console.log('Message handled in the background!', remoteMessage);
  
  // Note: FCM automatically displays notifications when app is in background
  // The notification will be shown with the title and body from the message
  // No additional code needed for basic functionality
  
  // If you need custom notification handling, consider installing @notifee/react-native
  // or implementing native code for advanced features
});