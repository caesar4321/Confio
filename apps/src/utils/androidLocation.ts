import { NativeModules, Platform } from 'react-native';

export type AndroidFix = {
  latitude: number;
  longitude: number;
  accuracy: number | null;
  ageMs: number;
  provider: string;
  mocked: boolean;
};

export type AndroidFixError = 'denied' | 'disabled' | 'unavailable';

/**
 * Android only: one fix from the ConfioLocation native module (Bre-B's
 * pattern: LocationManager directly, "location is off" told apart, a fix any
 * provider already has, else a real wait). Null module = an older build:
 * callers fall back to the geolocation library.
 */
export const nativeLocationAvailable = (): boolean =>
  Platform.OS === 'android' && typeof NativeModules.ConfioLocation?.currentPosition === 'function';

export const androidCurrentPosition = async (options: {
  precise: boolean;
  maxAgeMs: number;
  maxAccuracyM: number;
  timeoutMs: number;
}): Promise<{ fix: AndroidFix } | { error: AndroidFixError }> => {
  try {
    const fix: AndroidFix = await NativeModules.ConfioLocation.currentPosition(options);
    return { fix };
  } catch (e: any) {
    if (e?.code === 'LOCATION_PERMISSION') return { error: 'denied' };
    if (e?.code === 'LOCATION_DISABLED') return { error: 'disabled' };
    return { error: 'unavailable' };
  }
};
