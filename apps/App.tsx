/**
 * Sample React Native App
 * https://github.com/facebook/react-native
 *
 * @format
 */

import React, { useEffect } from 'react';
import { SafeAreaView, StatusBar } from 'react-native';
import { AuthScreen } from './src/components/auth/AuthScreen';
import auth from '@react-native-firebase/auth';

function App(): React.JSX.Element {
  useEffect(() => {
    // Initialize Firebase Auth
    const initializeFirebase = async () => {
      try {
        // Firebase Auth is automatically initialized when the app starts
        // We just need to check if it's ready
        const currentUser = auth().currentUser;
        console.log('Firebase Auth initialized successfully');
      } catch (error) {
        console.error('Error initializing Firebase Auth:', error);
      }
    };

    initializeFirebase();
  }, []);

  return (
    <SafeAreaView style={{ flex: 1 }}>
      <StatusBar barStyle="dark-content" />
      <AuthScreen />
    </SafeAreaView>
  );
}

export default App;
