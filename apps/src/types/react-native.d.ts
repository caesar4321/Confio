import 'react-native';

declare module 'react-native' {
  import * as React from 'react';
  import * as ReactNative from 'react-native';

  export interface ReactNativePublicAPI extends ReactNative.ReactNativePublicAPI {
    Platform: {
      OS: 'ios' | 'android' | 'windows' | 'macos' | 'web';
      Version: number;
      select<T>(specifics: { [platform in NodeJS.Platform]?: T }): T;
    };
  }

  const RN: ReactNativePublicAPI;
  export default RN;
} 