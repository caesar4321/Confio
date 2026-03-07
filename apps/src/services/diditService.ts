type DiditSdkModule = {
  startVerification?: (sessionToken: string, config?: Record<string, unknown> | null) => Promise<any>;
  default?: {
    startVerification?: (sessionToken: string, config?: Record<string, unknown> | null) => Promise<any>;
  };
};

import { NativeModules, Platform } from 'react-native';

function resolveDiditStartFunction(): (sessionToken: string) => Promise<any> {
  if (Platform.OS === 'ios') {
    const nativeModule = NativeModules?.SdkReactNative;
    const startVerification = nativeModule?.startVerification;

    if (!startVerification) {
      throw new Error('Didit SDK is not installed in the iOS app build.')
    }

    return (sessionToken: string) => startVerification.call(nativeModule, sessionToken, null);
  }

  let sdkModule: DiditSdkModule;
  try {
    sdkModule = require('@didit-protocol/sdk-react-native');
  } catch (error) {
    throw new Error('Didit SDK is not installed in the mobile app build.')
  }

  const startVerification =
    sdkModule?.startVerification ||
    sdkModule?.default?.startVerification;

  if (!startVerification) {
    throw new Error(`Didit SDK startVerification(sessionToken) is unavailable on ${Platform.OS}.`)
  }

  return (sessionToken: string) => startVerification(sessionToken, undefined);
}

export async function startDiditVerification(sessionToken: string): Promise<any> {
  if (!sessionToken) {
    throw new Error('Didit session token is required.')
  }

  const startVerification = resolveDiditStartFunction();
  return startVerification(sessionToken);
}

export function getDiditResultSessionId(result: any, fallbackSessionId?: string | null): string | null {
  return (
    result?.sessionId ||
    result?.session_id ||
    result?.data?.sessionId ||
    result?.data?.session_id ||
    fallbackSessionId ||
    null
  );
}
