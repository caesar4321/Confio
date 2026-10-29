import Geolocation from '@react-native-community/geolocation';
import { PermissionsAndroid, Platform } from 'react-native';
import { androidCurrentPosition, nativeLocationAvailable } from './androidLocation';

export type Pin = { latitude: number; longitude: number };
export type PreciseFix = { pin: Pin } | { error: 'denied' | 'disabled' | 'unavailable' };

const TIMEOUT_MS = 15_000;
// GPS can take half a minute for its first good fix (Bre-B waits 60 s).
const NATIVE_TIMEOUT_MS = 30_000;
// A hard stop over the whole lookup: a call that never answers must never
// leave the map waiting.
const HARD_STOP_MS = 35_000;

const androidFinePermission = async (): Promise<boolean> => {
  const fine = PermissionsAndroid.PERMISSIONS.ACCESS_FINE_LOCATION;
  const coarse = PermissionsAndroid.PERMISSIONS.ACCESS_COARSE_LOCATION;
  if (await PermissionsAndroid.check(fine)) return true;
  // Android 12+ ignores a request for fine location alone (and when only
  // upgrading Comprar's coarse grant): ask for both, then read fine.
  const granted = await PermissionsAndroid.requestMultiple([fine, coarse]);
  return granted[fine] === PermissionsAndroid.RESULTS.GRANTED;
};

/**
 * One precise position for a delivery pin (door-level, unlike Comprar's
 * city-level browsing fix). An error when denied, location is off, or no
 * good fix came in time: the buyer then moves the map by hand.
 */
export const getPreciseFix = async (): Promise<PreciseFix> => {
  if (Platform.OS === 'android' && !(await androidFinePermission())) return { error: 'denied' };
  const work: Promise<PreciseFix> = nativeLocationAvailable()
    ? androidCurrentPosition({ precise: true, maxAgeMs: 2 * 60 * 1000, maxAccuracyM: 100, timeoutMs: NATIVE_TIMEOUT_MS })
      .then((r) => ('fix' in r ? { pin: { latitude: r.fix.latitude, longitude: r.fix.longitude } } : r))
    : new Promise<PreciseFix>((resolve) => {
      Geolocation.getCurrentPosition(
        (pos) => resolve({ pin: { latitude: pos.coords.latitude, longitude: pos.coords.longitude } }),
        (err) => resolve({ error: err?.code === 1 ? 'denied' : 'unavailable' }),
        { enableHighAccuracy: true, timeout: TIMEOUT_MS, maximumAge: 60 * 1000 },
      );
    });
  let timer: ReturnType<typeof setTimeout> | undefined;
  const stop = new Promise<PreciseFix>((resolve) => {
    timer = setTimeout(() => resolve({ error: 'unavailable' }), HARD_STOP_MS);
  });
  return Promise.race([work, stop]).finally(() => clearTimeout(timer));
};

/** A maps link any phone opens (Google Maps, Yango, inDrive, WhatsApp…). */
export const mapsLink = (pin: Pin): string =>
  `https://www.google.com/maps/search/?api=1&query=${pin.latitude.toFixed(6)},${pin.longitude.toFixed(6)}`;
