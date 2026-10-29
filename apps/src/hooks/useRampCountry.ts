import { useCallback, useMemo } from 'react';
import { Alert } from 'react-native';
import { useMutation, useQuery } from '@apollo/client';
import { useNavigation } from '@react-navigation/native';

import { GET_ME, GET_RAIL_COUNTRIES } from '../apollo/queries';
import { SET_PREFERRED_RAIL_COUNTRY } from '../apollo/mutations';
import { userCountryIso } from '../utils/userCountry';
import { useAuth } from '../contexts/AuthContext';
import { isRampBlockedCountry } from '../config/env';
import { getCountryByIso } from '../utils/countries';

/**
 * Which country a ramp order belongs to is a fact about the USER — the first
 * of the server's rail countries (the one they picked in Recargar/Retirar,
 * else where they live, else their documents' country) — and nothing else.
 * Never the phone prefix: phone-less accounts have none.
 *
 * The ramp screens used to resolve it as
 * `phoneCountry || selectedCountry || userCountry || 'AR'`, which is wrong
 * twice over:
 *   - `selectedCountry` is GLOBAL picker state that Exchange (P2P), Crear
 *     oferta, Invitar empleado and Nómina all write to. Browsing offers from
 *     another country silently moved your Recargar to that country.
 *   - both remaining links end in Argentina: CountryContext defaults to
 *     Argentina when the profile hasn't resolved, and the last `|| 'AR'`
 *     catches whatever is left. So any entry point reached before the
 *     profile loads quoted ARS and Argentine payment methods to everyone.
 *
 * Here an unresolved country stays `null` and the caller must render that
 * state. Showing the wrong country's payment methods is worse than showing
 * none: the user would be sent to pay through a rail they cannot use.
 */
export const useRampCountry = () => {
  const navigation = useNavigation<any>();
  const { userProfile, isUserProfileLoading } = useAuth() as any;
  const { data: meData, loading: meLoading } = useQuery(GET_ME);
  // The server's order (ramps/rail_country.py): the country the user picked,
  // then where they live, then their documents' countries.
  const { data: railData, loading: railLoading, refetch: refetchRail } = useQuery(GET_RAIL_COUNTRIES, {
    fetchPolicy: 'cache-and-network',
  });
  const [setPreferredRailCountry] = useMutation(SET_PREFERRED_RAIL_COUNTRY);

  const railCountries: string[] = useMemo(
    () => ((railData?.railCountries || []) as string[])
      .map(code => String(code || '').trim().toUpperCase())
      .filter(code => Boolean(getCountryByIso(code))),
    [railData?.railCountries],
  );

  const countryCode = useMemo(() => {
    if (railCountries.length) return railCountries[0];
    const raw = userCountryIso(userProfile) || userCountryIso(meData?.me);
    // Only an ISO-2 we can actually resolve counts as known — never let an
    // unresolvable value pick a country for us.
    return raw && getCountryByIso(raw) ? raw : null;
  }, [railCountries, meData?.me, userProfile]);

  const loading = !countryCode && (Boolean(isUserProfileLoading) || meLoading || railLoading);

  // The user picked another country in Recargar/Retirar: it leads from now on.
  const setRampCountry = useCallback(async (iso: string) => {
    const result = await setPreferredRailCountry({ variables: { country: iso } });
    if (!result.data?.setPreferredRailCountry?.success) {
      throw new Error(result.data?.setPreferredRailCountry?.error || 'No pudimos cambiar el país');
    }
    await refetchRail();
  }, [refetchRail, setPreferredRailCountry]);
  const isBlocked = isRampBlockedCountry(countryCode);

  // Recargar/Retirar run through ramp providers (Koywe/Guardarian). Where
  // neither operates (VE, NI, PA, CU), block up front and point to the
  // Efectivo directory instead of failing deep inside the provider flow.
  // Every entry point into TopUp/Sell must go through here — Home did this
  // check inline, so the referral and achievement CTAs bypassed it.
  const navigateToRampOrEfectivo = useCallback(
    (screen: 'TopUp' | 'Sell', params?: { destination?: string }) => {
      if (isBlocked) {
        Alert.alert(
          'No disponible en tu país',
          screen === 'TopUp'
            ? 'Las recargas con proveedores aún no están disponibles en tu país. Puedes cambiar efectivo con financieras locales verificadas cerca de ti.'
            : 'Los retiros con proveedores aún no están disponibles en tu país. Puedes cambiar efectivo con financieras locales verificadas cerca de ti.',
          [
            { text: 'Cancelar', style: 'cancel' },
            { text: 'Ver financieras', onPress: () => navigation.navigate('Financieras') },
          ],
        );
        return;
      }
      navigation.navigate(screen, params as any);
    },
    [isBlocked, navigation],
  );

  return { countryCode, railCountries, loading, isBlocked, navigateToRampOrEfectivo, setRampCountry };
};
