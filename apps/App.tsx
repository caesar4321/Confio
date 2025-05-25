/**
 * Sample React Native App
 * https://github.com/facebook/react-native
 *
 * @format
 */

import React from 'react';
import { SafeAreaView, StatusBar } from 'react-native';
import { AuthScreen } from './src/screens/AuthScreen';

function App(): React.JSX.Element {
  return (
    <SafeAreaView style={{ flex: 1 }}>
      <StatusBar barStyle="dark-content" />
      <AuthScreen />
    </SafeAreaView>
  );
}

export default App;
