import { getDeviceFix } from '../services/location';

export type Pin = { latitude: number; longitude: number };
export type PreciseFix = { pin: Pin } | { error: 'denied' | 'disabled' | 'unavailable' };

/**
 * One precise position for a delivery pin (door-level, unlike Comprar's
 * city-level browsing fix). An error when denied, location is off, or no
 * good fix came in time: the buyer then moves the map by hand.
 */
export const getPreciseFix = async (): Promise<PreciseFix> => {
  // GPS can take half a minute for its first good fix (Bre-B waits 60 s).
  const r = await getDeviceFix({
    precise: true, maxAgeMs: 2 * 60 * 1000, maxAccuracyM: 100, timeoutMs: 30_000, hardStopMs: 35_000, prompt: true,
  });
  return 'fix' in r ? { pin: { latitude: r.fix.latitude, longitude: r.fix.longitude } } : r;
};

/** A maps link any phone opens (Google Maps, Yango, inDrive, WhatsApp…). */
export const mapsLink = (pin: Pin): string =>
  `https://www.google.com/maps/search/?api=1&query=${pin.latitude.toFixed(6)},${pin.longitude.toFixed(6)}`;
