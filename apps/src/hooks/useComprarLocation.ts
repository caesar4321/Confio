import { useCallback, useEffect, useState } from 'react';
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

const askPermission = async (): Promise<boolean> => {
  if (Platform.OS === 'android') {
    const granted = await PermissionsAndroid.request(
      PermissionsAndroid.PERMISSIONS.ACCESS_COARSE_LOCATION,
      {
        title: 'Tu ciudad en Comprar',
        message: 'Usamos tu ubicación para mostrarte tiendas y envíos de tu ciudad.',
        buttonPositive: 'Permitir',
        buttonNegative: 'Ahora no',
      },
    );
    return granted === PermissionsAndroid.RESULTS.GRANTED;
  }
  return new Promise((resolve) => {
    Geolocation.requestAuthorization(() => resolve(true), () => resolve(false));
  });
};

const currentPosition = (): Promise<{ latitude: number; longitude: number; accuracy: number | null } | null> =>
  new Promise((resolve) => {
    Geolocation.getCurrentPosition(
      (pos) => resolve({
        latitude: pos.coords.latitude, longitude: pos.coords.longitude,
        accuracy: pos.coords.accuracy ?? null,
      }),
      () => resolve(null),
      { enableHighAccuracy: false, timeout: 8000, maximumAge: 10 * 60 * 1000 },
    );
  });

/**
 * Comprar's browsing location. Defaults to the city the phone is in (matched
 * server-side against known cities; the reading is kept like Bre-B's location
 * checks, per the Privacy Policy), then the
 * phone country's first live city. Any country/city can be picked, like the
 * Financieras directory; the location only filters, it never gates.
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

  const fallbackToPhoneCountry = useCallback(async () => {
    try {
      const { data } = await client.query({
        query: GET_MARKETPLACE_CITIES,
        variables: { countryCode: phoneCountry },
        fetchPolicy: 'network-only',
      });
      const cities = data?.marketplaceCities || [];
      const live = cities.find((c: any) => c.isLive) || cities[0];
      const loc: ComprarLocation = { countryCode: phoneCountry, city: live?.city || '', source: 'phone' };
      setLocation(loc);
      setHome({ countryCode: phoneCountry, city: '', source: 'phone' });
    } catch {
      setLocation({ countryCode: phoneCountry, city: '', source: 'phone' });
      setHome({ countryCode: phoneCountry, city: '', source: 'phone' });
    }
  }, [client, phoneCountry]);

  const locate = useCallback(async () => {
    setResolving(true);
    try {
      if (await askPermission()) {
        const pos = await currentPosition();
        if (pos) {
          const { data } = await client.mutate({ mutation: LOCATE_MARKETPLACE_CITY, variables: pos });
          const hit = data?.locateMarketplaceCity?.city;
          if (hit) {
            const loc: ComprarLocation = { countryCode: hit.countryCode, city: hit.city, source: 'gps' };
            setLocation(loc);
            setHome(loc);
            return;
          }
        }
      }
      await fallbackToPhoneCountry();
    } catch {
      await fallbackToPhoneCountry();
    } finally {
      setResolving(false);
    }
  }, [client, fallbackToPhoneCountry]);

  useEffect(() => {
    void locate();
  }, [locate]);

  const choose = useCallback((countryCode: string, city: string) => {
    setLocation({ countryCode, city, source: 'manual' });
  }, []);

  return { location, home, resolving, choose, relocate: locate };
};
