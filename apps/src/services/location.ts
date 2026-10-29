// Device location, in one place (server: security/location.py). Every feature
// that needs where the phone is (Comprar's city, the delivery pin, residence)
// gets permission and a fix here, and readings go to the server through one
// record. Bre-B keeps its own attested flow (BrebLocationGate) and its
// readings land in the same server record.

import Geolocation from '@react-native-community/geolocation';
import { NativeModules, PermissionsAndroid, Platform } from 'react-native';
import { gql } from '@apollo/client';
import { androidCurrentPosition, nativeLocationAvailable } from '../utils/androidLocation';

// When-in-use only; the library must not reach for "always" just because the
// plist also carries the Always purpose string. One permission owner per
// platform: on Android this module asks, so the library must not ask again;
// on iOS the library's own request is the prompt.
Geolocation.setRNConfiguration?.({
  skipPermissionRequests: Platform.OS === 'android',
  authorizationLevel: 'whenInUse',
  enableBackgroundLocationUpdates: false,
  locationProvider: 'auto',
});

export type DeviceFix = {
  latitude: number;
  longitude: number;
  accuracy: number | null;
  /** Device time of the fix, ms since epoch. */
  timestamp: number;
  /** Android's mock-provider flag; null where the platform does not say. */
  mocked: boolean | null;
  provider: string;
};
export type FixError = 'denied' | 'disabled' | 'unavailable';
export type FixResult = { fix: DeviceFix } | { error: FixError };

export type FixOptions = {
  /** Door-level (delivery pin) rather than city-level. */
  precise: boolean;
  maxAgeMs: number;
  maxAccuracyM: number;
  timeoutMs: number;
  /** A hard stop over the whole lookup: a call that never answers must never
   *  leave a screen waiting. */
  hardStopMs: number;
  /** false: never show a permission prompt (silent residence reading). */
  prompt: boolean;
};

/** iOS authorization without a prompt (BrebAppleLocation.permissionStatus);
 *  null on builds without it: no silent reading there. */
const iosPermissionStatus = async (): Promise<string | null> => {
  const module = NativeModules.BrebAppleLocation;
  if (typeof module?.permissionStatus !== 'function') return null;
  try {
    return await module.permissionStatus();
  } catch {
    return null;
  }
};

/** Whether a fix can be taken without asking the person. */
export const hasLocationPermission = async (precise = false): Promise<boolean> => {
  if (Platform.OS === 'android') {
    const fine = PermissionsAndroid.PERMISSIONS.ACCESS_FINE_LOCATION;
    const coarse = PermissionsAndroid.PERMISSIONS.ACCESS_COARSE_LOCATION;
    return (await PermissionsAndroid.check(fine)) || (!precise && (await PermissionsAndroid.check(coarse)));
  }
  const status = await iosPermissionStatus();
  return status === 'granted' || (!precise && status === 'reduced');
};

/** Android: ask (both at once: Android 12+ ignores fine alone). iOS asks
 *  inside the fix itself. */
const androidPermission = async (precise: boolean): Promise<boolean> => {
  const fine = PermissionsAndroid.PERMISSIONS.ACCESS_FINE_LOCATION;
  const coarse = PermissionsAndroid.PERMISSIONS.ACCESS_COARSE_LOCATION;
  if (await hasLocationPermission(precise)) return true;
  const granted = await PermissionsAndroid.requestMultiple([fine, coarse]);
  return granted[fine] === PermissionsAndroid.RESULTS.GRANTED
    || (!precise && granted[coarse] === PermissionsAndroid.RESULTS.GRANTED);
};

export const getDeviceFix = async (options: FixOptions): Promise<FixResult> => {
  if (!options.prompt && !(await hasLocationPermission(options.precise))) return { error: 'denied' };
  if (Platform.OS === 'android' && options.prompt && !(await androidPermission(options.precise))) {
    return { error: 'denied' };
  }
  const work: Promise<FixResult> = nativeLocationAvailable()
    ? androidCurrentPosition(options).then((r) => ('fix' in r ? { fix: {
      latitude: r.fix.latitude, longitude: r.fix.longitude, accuracy: r.fix.accuracy,
      timestamp: Date.now() - (r.fix.ageMs || 0), mocked: r.fix.mocked, provider: r.fix.provider || '',
    } } : r))
    : new Promise<FixResult>((resolve) => {
      Geolocation.getCurrentPosition(
        (pos) => resolve({ fix: {
          latitude: pos.coords.latitude, longitude: pos.coords.longitude,
          accuracy: pos.coords.accuracy ?? null, timestamp: pos.timestamp || Date.now(),
          mocked: (pos as any).mocked ?? null, provider: '',
        } }),
        (err) => resolve({ error: err?.code === 1 ? 'denied' : 'unavailable' }),
        { enableHighAccuracy: options.precise, timeout: Math.min(options.timeoutMs, 15_000), maximumAge: options.maxAgeMs },
      );
    });
  let timer: ReturnType<typeof setTimeout> | undefined;
  const stop = new Promise<FixResult>((resolve) => {
    timer = setTimeout(() => resolve({ error: 'unavailable' }), options.hardStopMs);
  });
  return Promise.race([work, stop]).finally(() => clearTimeout(timer));
};

const RECORD_LOCATION = gql`
  mutation RecordLocation($latitude: Float!, $longitude: Float!, $accuracy: Float, $timestamp: Float,
    $mocked: Boolean, $provider: String, $platform: String) {
    recordLocation(latitude: $latitude, longitude: $longitude, accuracy: $accuracy, timestamp: $timestamp,
      mocked: $mocked, provider: $provider, platform: $platform) { success error }
  }
`;

// Residence needs about one reading a day (users/residence.py counts days).
const RESIDENCE_EVERY_MS = 20 * 60 * 60 * 1000;
let lastResidenceReport = 0;

/**
 * Where the phone is, for residence: at most once a day, only when location
 * permission was already granted (never a prompt), city-level precision.
 * Silent: any failure just waits for the next day.
 */
export const reportResidenceLocation = async (client: { mutate: (options: any) => Promise<any> }) => {
  if (Date.now() - lastResidenceReport < RESIDENCE_EVERY_MS) return;
  lastResidenceReport = Date.now();
  try {
    const result = await getDeviceFix({
      precise: false, maxAgeMs: 30 * 60 * 1000, maxAccuracyM: 5000, timeoutMs: 20_000, hardStopMs: 25_000,
      prompt: false,
    });
    if (!('fix' in result)) return;
    const { fix } = result;
    await client.mutate({
      mutation: RECORD_LOCATION,
      variables: {
        latitude: fix.latitude, longitude: fix.longitude, accuracy: fix.accuracy, timestamp: fix.timestamp,
        mocked: fix.mocked, provider: fix.provider || null, platform: Platform.OS,
      },
    });
  } catch {
    // Next day.
  }
};
