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
    // Disable autolinking for all packages since we're linking manually
    '@invertase/react-native-apple-authentication': {
      platforms: {
        android: null,
        ios: null
      }
    },
    '@notifee/react-native': {
      platforms: {
        android: null,
        ios: null
      }
    },
    '@react-native-camera-roll/camera-roll': {
      platforms: {
        android: null,
        ios: null
      }
    },
    '@react-native-firebase/app': {
      platforms: {
        android: null,
        ios: null
      }
    },
    '@react-native-firebase/auth': {
      platforms: {
        android: null,
        ios: null
      }
    },
    '@react-native-firebase/messaging': {
      platforms: {
        android: null,
        ios: null
      }
    },
    '@react-native-google-signin/google-signin': {
      platforms: {
        android: null,
        ios: null
      }
    },
    'react-native-contacts': {
      platforms: {
        android: null,
        ios: null
      }
    },
    'react-native-device-info': {
      platforms: {
        android: null,
        ios: null
      }
    },
    'react-native-fs': {
      platforms: {
        android: null,
        ios: null
      }
    },
    'react-native-get-random-values': {
      platforms: {
        android: null,
        ios: null
      }
    },
    'react-native-keychain': {
      platforms: {
        android: null,
        ios: null
      }
    },
    'react-native-reanimated': {
      platforms: {
        android: null,
        ios: null
      }
    },
    'react-native-safe-area-context': {
      platforms: {
        android: null,
        ios: null
      }
    },
    'react-native-screens': {
      platforms: {
        android: null,
        ios: null
      }
    },
    'react-native-svg': {
      platforms: {
        android: null,
        ios: null
      }
    },
    'react-native-vector-icons': {
      platforms: {
        android: null,
        ios: null
      }
    },
    'react-native-view-shot': {
      platforms: {
        android: null,
        ios: null
      }
    },
    'react-native-vision-camera': {
      platforms: {
        android: null,
        ios: null
      }
    },
    'react-native-worklets-core': {
      platforms: {
        android: null,
        ios: null
      }
    }
  },
}; 