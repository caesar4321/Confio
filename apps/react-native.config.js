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
    // Autolinking is ON for both platforms (re-enabled 2026-07 after the
    // RN 0.7x-era bugs that forced manual Android linking were fixed).
    // Only deliberate exclusions live here:
    'react-native-worklets-core': {
      platforms: {
        ios: null, // only needed for Android frame processors
      },
    },
    '@didit-protocol/sdk-react-native': {
      // Manual on both platforms: needs a custom maven repo on Android
      // (settings.gradle) and a remote podspec on iOS (Podfile).
      platforms: {
        android: null,
        ios: null,
      },
    },
  },
};
