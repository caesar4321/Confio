// bootstrap.ts - Ensures polyfills are loaded before any other imports
import './src/setup/polyfills';   // URL, crypto, slice, Buffer - MUST be first
import './src/setup/silenceLogs'; // Silence noisy logs early in app boot

// Apollo Client setup and error messages (after polyfills)
import { loadErrorMessages, loadDevMessages } from "@apollo/client/dev";
import { Buffer } from 'buffer';

// @ts-ignore
if (__DEV__) {
  // Adds messages only in a dev environment
  loadDevMessages();
  loadErrorMessages();
}

// Apollo is provided inside App.tsx using the project-authenticated client

// Import React Native components
import { AppRegistry, Platform, UIManager } from 'react-native';
import { name as appName } from './app.json';

// Ensure Buffer is available globally before anything else
global.Buffer = Buffer;

// Import App component
import App from './src/App';
import React from 'react';

// Register the app
AppRegistry.registerComponent(appName, () => App);

// Configure react-native-screens defensively to avoid sheet prop crashes
try {
  // Require lazily so it doesn't throw if not present
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  const Screens = require('react-native-screens');
  // Enable native screens for better performance with native stacks
  Screens.enableScreens(true);
  const cfg = UIManager.getViewManagerConfig('RNSScreen');
  const nativeProps = new Set(Object.keys((cfg && (cfg as any).NativeProps) || {}));
  const supportsSheet = nativeProps.has('sheetLargestUndimmedDetent') || nativeProps.has('sheetLargestUndimmedDetentIndex');
  console.log('[RNScreens] enabled:', Screens.screensEnabled(), 'supportsSheet:', supportsSheet, 'hasViewManager:', !!cfg);
} catch (_e) {
  // If screens isn't available, proceed without enabling it
}

try {
  require('./src/services/backgroundMessaging');
  console.log('Background messaging registered successfully');
} catch (error) {
  console.warn('Failed to register background messaging:', error);
}

// Pre-initialize algosdk to avoid dynamic import delay during sign-in
try {
  const algorandService = require('./src/services/algorandService').default;
  // Trigger initialization but don't await - let it happen in background
  algorandService.preInitialize().catch(console.warn);
  console.log('Algorand SDK pre-initialization started');
} catch (error) {
  console.warn('Failed to pre-initialize Algorand SDK:', error);
}
