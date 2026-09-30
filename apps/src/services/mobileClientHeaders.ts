import { Platform } from 'react-native';
import DeviceInfo from 'react-native-device-info';

// Compatibility hints only: the backend independently requires and grades
// Rekognition sessions. Never send a client-side "face passed" assertion.
export const mobileClientHeaders = (): Record<string, string> => ({
  'X-Confio-Platform': Platform.OS,
  'X-Confio-Version': DeviceInfo.getVersion(),
  'X-Confio-Build': DeviceInfo.getBuildNumber(),
  'X-Confio-Face-Capable': '1',
});

export const createMobileWebSocket = (url: string): WebSocket => {
  // React Native supports request headers in argument 3. The project's DOM
  // WebSocket declaration only describes browsers, so type the native overload
  // here rather than weakening each financial transport with `any`.
  const NativeWebSocket = WebSocket as unknown as {
    new (uri: string, protocols: undefined, options: { headers: Record<string, string> }): WebSocket;
  };
  return new NativeWebSocket(url, undefined, { headers: mobileClientHeaders() });
};
