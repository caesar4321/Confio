import { useCallback, useEffect, useRef, useState } from 'react';
import { PermissionsAndroid, Platform } from 'react-native';
import Geolocation from '@react-native-community/geolocation';
import { useApolloClient } from '@apollo/client';
import { useCountry } from '../contexts/CountryContext';
import { GET_MARKETPLACE_CITIES, LOCATE_MARKETPLACE_CITY } from '../services/comprar';

export type ComprarLocation = {
  countryCode: string;
  city: string;
  /** 'gps' = matched from the phone's position; 'manual' = picked by the user. */
  source: 'gps' | 'manual' | 'phone';
};

/** What a "Usar mi ubicación" attempt ended in — the UI tells the user.
 *  'stale' = superseded (a manual choice, a newer lookup, or the screen left):
 *  nothing to show. */
export type LocateOutcome = 'found' | 'no_city' | 'denied' | 'unavailable' | 'stale';

// When-in-use only; the library must not reach for "always" just because the
// plist also carries the Always purpose string. One permission owner per
// platform: on Android this hook asks (coarse is enough for a city), so the
// library must not ask again for fine; on iOS the library's own request is
// the prompt.
Geolocation.setRNConfiguration({
  skipPermissionRequests: Platform.OS === 'android',
  authorizationLevel: 'whenInUse',
  enableBackgroundLocationUpdates: false,
  locationProvider: 'auto',
});

const POSITION_TIMEOUT_MS = 15_000;
// A hard stop over the WHOLE lookup (permission, fix, city match): a call that
// never answers must never leave the screen waiting forever.
const HARD_STOP_MS = 25_000;

type Fix = { latitude: number; longitude: number; accuracy: number | null };
type FixResult = { fix: Fix } | { error: 'denied' | 'unavailable' };

const androidPermission = async (): Promise<boolean> => {
  const coarse = PermissionsAndroid.PERMISSIONS.ACCESS_COARSE_LOCATION;
  if (await PermissionsAndroid.check(coarse)) return true;
  const granted = await PermissionsAndroid.request(coarse, {
    title: 'Tu ciudad en Comprar',
    message: 'Usamos tu ubicación para mostrarte tiendas y envíos de tu ciudad.',
    buttonPositive: 'Permitir',
    buttonNegative: 'Ahora no',
  });
  return granted === PermissionsAndroid.RESULTS.GRANTED;
};

/**
 * One position fix. On iOS the request itself shows the permission prompt
 * (requestAuthorization's callbacks are not guaranteed to fire when the
 * status is already decided, which used to leave this hanging).
 */
const getFix = async (): Promise<FixResult> => {
  if (Platform.OS === 'android' && !(await androidPermission())) return { error: 'denied' };
  return new Promise<FixResult>((resolve) => {
    Geolocation.getCurrentPosition(
      (pos) => resolve({ fix: {
        latitude: pos.coords.latitude, longitude: pos.coords.longitude,
        accuracy: pos.coords.accuracy ?? null,
      } }),
      (err) => resolve({ error: err?.code === 1 ? 'denied' : 'unavailable' }),
      { enableHighAccuracy: false, timeout: POSITION_TIMEOUT_MS, maximumAge: 5 * 60 * 1000 },
    );
  });
};

const withDeadline = <T,>(work: Promise<T>, fallback: T): Promise<T> => {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const stop = new Promise<T>((resolve) => { timer = setTimeout(() => resolve(fallback), HARD_STOP_MS); });
  return Promise.race([work, stop]).finally(() => clearTimeout(timer));
};

/**
 * Comprar's browsing location. Defaults to the city the phone is in (matched
 * server-side against known cities; the reading is kept like Bre-B's location
 * checks, per the Privacy Policy), then the phone country's first live city.
 * Any country/city can be picked, like the Financieras directory; the
 * location only filters, it never gates.
 *
 * The automatic first lookup is silent. "Usar mi ubicación" (relocate)
 * returns an outcome the screen shows, and never silently replaces the city
 * the user is browsing when the phone's position cannot be matched.
 */
export const useComprarLocation = () => {
  const client = useApolloClient();
  const { userCountry } = useCountry();
  const phoneCountry = userCountry ? String(userCountry[2]) : 'BO';
  const [location, setLocation] = useState<ComprarLocation | null>(null);
  // Where the user IS (GPS, else phone country) — pinned first in the picker
  // even after they browse elsewhere.
  const [home, setHome] = useState<ComprarLocation | null>(null);
  const [resolving, setResolving] = useState(true);
  // Every lookup and every manual choice takes a new generation; a lookup
  // commits only if it is still the latest and the screen is still mounted.
  const generation = useRef(0);
  const mounted = useRef(true);
  useEffect(() => () => { mounted.current = false; }, []);
  // Reads refs only, so it is safe inside the memoized callbacks below.
  const isCurrent = (gen: number) => mounted.current && gen === generation.current;

  const fallbackToPhoneCountry = useCallback(async (gen: number) => {
    let city = '';
    try {
      const { data } = await client.query({
        query: GET_MARKETPLACE_CITIES,
        variables: { countryCode: phoneCountry },
        fetchPolicy: 'network-only',
      });
      const cities = data?.marketplaceCities || [];
      city = (cities.find((c: any) => c.isLive) || cities[0])?.city || '';
    } catch {
      // keep the country with no city; the picker is one tap away
    }
    if (!isCurrent(gen)) return;
    setLocation({ countryCode: phoneCountry, city, source: 'phone' });
    setHome((h) => h ?? { countryCode: phoneCountry, city: '', source: 'phone' });
  }, [client, phoneCountry]);

  /** Fix → known city. Does not touch state; callers decide what to show. */
  const lookUp = useCallback((): Promise<{ outcome: LocateOutcome; loc?: ComprarLocation }> => {
    const work = (async (): Promise<{ outcome: LocateOutcome; loc?: ComprarLocation }> => {
      let result: FixResult;
      try {
        result = await getFix();
      } catch {
        // A rejected permission request or native error is an outcome, never
        // an exception that skips the fallback and leaves resolving on.
        return { outcome: 'unavailable' };
      }
      if ('error' in result) return { outcome: result.error };
      try {
        const { data } = await client.mutate({ mutation: LOCATE_MARKETPLACE_CITY, variables: result.fix });
        const hit = data?.locateMarketplaceCity?.city;
        if (!hit) return { outcome: 'no_city' };
        return { outcome: 'found', loc: { countryCode: hit.countryCode, city: hit.city, source: 'gps' } };
      } catch {
        return { outcome: 'unavailable' };
      }
    })();
    return withDeadline(work, { outcome: 'unavailable' as LocateOutcome });
  }, [client]);

  // First open: silent, falls back to the phone country.
  useEffect(() => {
    const gen = ++generation.current;
    (async () => {
      setResolving(true);
      const { outcome, loc } = await lookUp();
      if (!isCurrent(gen)) return;
      if (outcome === 'found' && loc) {
        setLocation(loc);
        setHome(loc);
        setResolving(false);
        return;
      }
      // Settle now with the phone country; the city list fills it in after,
      // so a slow fallback query never extends the wait.
      setLocation({ countryCode: phoneCountry, city: '', source: 'phone' });
      setHome((h) => h ?? { countryCode: phoneCountry, city: '', source: 'phone' });
      setResolving(false);
      await fallbackToPhoneCountry(gen);
    })();
  }, [lookUp, fallbackToPhoneCountry, phoneCountry]);

  /** "Usar mi ubicación": returns what happened so the screen can say so
   *  ('stale' when superseded or the screen left — show nothing). */
  const relocate = useCallback(async (): Promise<LocateOutcome> => {
    const gen = ++generation.current;
    setResolving(true);
    const { outcome, loc } = await lookUp();
    if (!isCurrent(gen)) return 'stale';
    if (outcome === 'found' && loc) {
      setLocation(loc);
      setHome(loc);
    }
    setResolving(false);
    return outcome;
  }, [lookUp]);

  /** A manual pick beats any lookup still in flight. */
  const choose = useCallback((countryCode: string, city: string) => {
    generation.current += 1;
    setResolving(false);
    setLocation({ countryCode, city, source: 'manual' });
  }, []);

  return { location, home, resolving, choose, relocate };
};
