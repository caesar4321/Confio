type DiditSdkModule = {
  startVerification?: (sessionToken: string, config?: Record<string, unknown> | null) => Promise<any>;
  default?: {
    startVerification?: (sessionToken: string, config?: Record<string, unknown> | null) => Promise<any>;
  };
};

import { NativeModules, Platform } from 'react-native';

function normalizeDiditSessionToken(sessionToken: unknown): string {
  if (typeof sessionToken === 'string') {
    const trimmed = sessionToken.trim();
    if (trimmed) {
      return trimmed;
    }
  }

  if (sessionToken && typeof sessionToken === 'object') {
    const nestedToken = (sessionToken as Record<string, unknown>).sessionToken
      ?? (sessionToken as Record<string, unknown>).token
      ?? (sessionToken as Record<string, unknown>).value;

    if (typeof nestedToken === 'string' && nestedToken.trim()) {
      return nestedToken.trim();
    }
  }

  throw new Error('Didit session token is missing or invalid.');
}

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

export async function startDiditVerification(sessionToken: unknown): Promise<any> {
  const normalizedSessionToken = normalizeDiditSessionToken(sessionToken);

  const startVerification = resolveDiditStartFunction();
  return startVerification(normalizedSessionToken);
}

export function getDiditResultSessionId(result: any, fallbackSessionId?: string | null): string | null {
  return (
    result?.sessionId ||
    result?.session_id ||
    // The JS wrapper (Android) nests it: { type, session: { sessionId, status } }.
    result?.session?.sessionId ||
    result?.data?.sessionId ||
    result?.data?.session_id ||
    fallbackSessionId ||
    null
  );
}

// iOS resolves the native result ({ errorType }); the Android JS wrapper maps it
// to { error: { type } }. The SDK's own messages are English, so only known
// types get a Spanish message; anything else falls back to the caller's text.
const DIDIT_ERROR_MESSAGES: Record<string, string> = {
  sessionExpired: 'La sesión de verificación expiró. Inténtalo de nuevo.',
  networkError: 'Revisa tu conexión a internet e inténtalo de nuevo.',
  cameraAccessDenied: 'Permite el acceso a la cámara en los ajustes de tu teléfono para continuar.',
  // Android only: the iOS bridge reports it as 'unknown'.
  retryBlocked: 'Alcanzaste el máximo de intentos de verificación. Contacta a soporte para continuar.',
};

export function getDiditErrorMessage(result: any): string | null {
  const type = result?.errorType || result?.error?.type;
  return (type && DIDIT_ERROR_MESSAGES[type]) || null;
}
