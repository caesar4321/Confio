import { Platform } from 'react-native';
import DeviceInfo from 'react-native-device-info';
import { getKeychainDiagnostic } from './keychainDiagnostic';

// Compatibility hints only: the backend independently requires and grades
// Rekognition sessions. Never send a client-side "face passed" assertion.
export const mobileClientHeaders = (): Record<string, string> => {
  const headers: Record<string, string> = {
    'X-Confio-Platform': Platform.OS,
    'X-Confio-Version': DeviceInfo.getVersion(),
    'X-Confio-Build': DeviceInfo.getBuildNumber(),
    'X-Confio-Face-Capable': '1',
  };
  // How long this phone's keystore took to hand over the session, so a
  // phone where it is slow shows up in the server log (timings only).
  const keychainDiagnostic = getKeychainDiagnostic();
  if (keychainDiagnostic) headers['X-Confio-KC-Diag'] = keychainDiagnostic;
  return headers;
};

export const createMobileWebSocket = (url: string): WebSocket => {
  // React Native supports request headers in argument 3. The project's DOM
  // WebSocket declaration only describes browsers, so type the native overload
  // here rather than weakening each financial transport with `any`.
  const NativeWebSocket = WebSocket as unknown as {
    new (uri: string, protocols: undefined, options: { headers: Record<string, string> }): WebSocket;
  };
  return new NativeWebSocket(url, undefined, { headers: mobileClientHeaders() });
};
