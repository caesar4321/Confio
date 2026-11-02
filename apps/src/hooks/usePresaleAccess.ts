// Who may buy the presale, as the server decides it (country, IP and the
// admin's US switch). The built-in country rules below only cover a server
// that has not answered yet or predates presaleAccess; the purchase and
// waitlist mutations re-check on the server either way.
import { Alert } from 'react-native';
import { useQuery } from '@apollo/client';
import { GET_PRESALE_ACCESS } from '../apollo/queries';
import { useCountry } from '../contexts/CountryContext';

export type PresaleAccess = 'buy' | 'us_waitlist' | 'blocked';

const FALLBACK_BLOCKS: Record<string, string> = {
  KR: 'Lo sentimos, la preventa no está disponible en tu país.',
  GB: 'Lo sentimos, los residentes del Reino Unido no pueden participar en la preventa.',
};

export const usePresaleAccess = () => {
  // Residence, not selectedCountry: the exchange pickers change that one.
  const { userCountry } = useCountry();
  const { data } = useQuery(GET_PRESALE_ACCESS, { fetchPolicy: 'cache-and-network' });
  const server = data?.presaleAccess;
  const iso = userCountry?.[2] || '';

  const access: PresaleAccess = server?.access
    ?? (iso === 'US' ? 'us_waitlist' : FALLBACK_BLOCKS[iso] ? 'blocked' : 'buy');
  const message: string = server?.message
    || FALLBACK_BLOCKS[iso]
    || 'Lo sentimos, la preventa no está disponible en tu país.';

  return {
    access,
    // 'open' once the admin lets US residents buy; unknown counts as closed.
    usOpen: server?.usAccess === 'open',
    notUsAttestationRequired: server?.notUsAttestationRequired !== false,
    /** True when the user may go on to buy; otherwise explains why not. */
    checkCanBuy: (): boolean => {
      if (access === 'buy') return true;
      Alert.alert('Restricción', access === 'us_waitlist'
        ? 'La preventa aún no está abierta para residentes de EE. UU.'
        : message);
      return false;
    },
  };
};
