module.exports = {
  project: {
    android: {
      sourceDir: './android',
      appName: 'app',
      packageName: 'com.Confio.Confio',
    },
    ios: {
      sourceDir: './ios',
    },
  },
  dependencies: {
    // Enable all for iOS, disable all for Android
    '@invertase/react-native-apple-authentication': {
      platforms: {
        android: null,
        // ios: enabled (autolinking)
      }
    },
    '@notifee/react-native': {
      platforms: {
        android: null,
        // ios: enabled (autolinking)
      }
    },
    '@react-native-camera-roll/camera-roll': {
      platforms: {
        android: null,
        // ios: enabled (autolinking)
      }
    },
    '@react-native-firebase/app': {
      platforms: {
        android: null,
        // ios: enabled (autolinking)
      }
    },
    '@react-native-firebase/auth': {
      platforms: {
        android: null,
        // ios: enabled (autolinking)
      }
    },
    '@react-native-firebase/messaging': {
      platforms: {
        android: null,
        // ios: enabled (autolinking)
      }
    },
    '@react-native-google-signin/google-signin': {
      platforms: {
        android: null,
        // ios: enabled (autolinking)
      }
    },
    'react-native-contacts': {
      platforms: {
        android: null,
        // ios: enabled (autolinking)
      }
    },
    'react-native-device-info': {
      platforms: {
        android: null,
        // ios: enabled (autolinking)
      }
    },
    'react-native-fs': {
      platforms: {
        android: null,
        // ios: enabled (autolinking)
      }
    },
    'react-native-get-random-values': {
      platforms: {
        android: null,
        // ios: enabled (autolinking)
      }
    },
    'react-native-keychain': {
      platforms: {
        android: null,
        // ios: enabled (autolinking)
      }
    },
    'react-native-reanimated': {
      platforms: {
        android: null,
        // ios: enabled (autolinking)
      }
    },
    'react-native-safe-area-context': {
      platforms: {
        android: null,
        // ios: enabled (autolinking)
      }
    },
    'react-native-screens': {
      platforms: {
        android: null,
        // ios: enabled (autolinking)
      }
    },
    'react-native-svg': {
      platforms: {
        android: null,
        // ios: enabled (autolinking)
      }
    },
    'react-native-vector-icons': {
      platforms: {
        android: null,
        // ios: enabled (autolinking)
      }
    },
    'react-native-view-shot': {
      platforms: {
        android: null,
        // ios: enabled (autolinking)
      }
    },
    'react-native-vision-camera': {
      platforms: {
        android: null,
        // ios: enabled (autolinking)
      }
    },
    'react-native-worklets-core': {
      platforms: {
        android: null,
        ios: null  // Disabled - only needed for Android frame processors
      }
    }
  },
}; 