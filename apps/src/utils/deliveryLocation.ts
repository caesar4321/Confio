import Geolocation from '@react-native-community/geolocation';
import { PermissionsAndroid, Platform } from 'react-native';

export type Pin = { latitude: number; longitude: number };

const TIMEOUT_MS = 15_000;
// A hard stop over the whole lookup: a call that never answers must never
// leave the map waiting.
const HARD_STOP_MS = 20_000;

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
 * city-level browsing fix). Null when denied, unavailable or too slow: the
 * buyer then moves the map by hand.
 */
export const getPreciseFix = async (): Promise<Pin | null> => {
  if (Platform.OS === 'android' && !(await androidFinePermission())) return null;
  const work = new Promise<Pin | null>((resolve) => {
    Geolocation.getCurrentPosition(
      (pos) => resolve({ latitude: pos.coords.latitude, longitude: pos.coords.longitude }),
      () => resolve(null),
      { enableHighAccuracy: true, timeout: TIMEOUT_MS, maximumAge: 60 * 1000 },
    );
  });
  let timer: ReturnType<typeof setTimeout> | undefined;
  const stop = new Promise<null>((resolve) => { timer = setTimeout(() => resolve(null), HARD_STOP_MS); });
  return Promise.race([work, stop]).finally(() => clearTimeout(timer));
};

/** A maps link any phone opens (Google Maps, Yango, inDrive, WhatsApp…). */
export const mapsLink = (pin: Pin): string =>
  `https://www.google.com/maps/search/?api=1&query=${pin.latitude.toFixed(6)},${pin.longitude.toFixed(6)}`;
