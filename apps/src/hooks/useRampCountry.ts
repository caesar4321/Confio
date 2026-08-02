import { useCallback, useMemo } from 'react';
import { Alert } from 'react-native';
import { useQuery } from '@apollo/client';
import { useNavigation } from '@react-navigation/native';

import { GET_ME } from '../apollo/queries';
import { useAuth } from '../contexts/AuthContext';
import { isRampBlockedCountry } from '../config/env';
import { getCountryByIso } from '../utils/countries';

/**
 * Which country a ramp order belongs to is a fact about the USER — their
 * verified phone country — and nothing else.
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

  const countryCode = useMemo(() => {
    const raw = String(userProfile?.phoneCountry || meData?.me?.phoneCountry || '')
      .trim()
      .toUpperCase();
    // Only an ISO-2 we can actually resolve counts as known. phone_country
    // tolerates a calling code being written into it (see users/models.py),
    // and a calling code is ambiguous (+1 is a dozen countries) — never let
    // one pick a country for us.
    return raw && getCountryByIso(raw) ? raw : null;
  }, [meData?.me?.phoneCountry, userProfile?.phoneCountry]);

  const loading = !countryCode && (Boolean(isUserProfileLoading) || meLoading);
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
            ? 'Las recargas con proveedores aún no están disponibles en tu país. En el menú Efectivo encuentras financieras locales verificadas cerca de ti.'
            : 'Los retiros con proveedores aún no están disponibles en tu país. En el menú Efectivo encuentras financieras locales verificadas cerca de ti.',
          [
            { text: 'Cancelar', style: 'cancel' },
            { text: 'Ir a Efectivo', onPress: () => navigation.navigate('Financieras') },
          ],
        );
        return;
      }
      navigation.navigate(screen, params as any);
    },
    [isBlocked, navigation],
  );

  return { countryCode, loading, isBlocked, navigateToRampOrEfectivo };
};
