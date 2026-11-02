// Who may buy the presale, as the server decides it (country, IP and the
// admin's per-country table). The built-in country rules below only cover a server
// that has not answered yet or predates presaleAccess; the purchase and
// waitlist mutations re-check on the server either way.
import { Alert } from 'react-native';
import { useQuery } from '@apollo/client';
import { GET_PRESALE_ACCESS } from '../apollo/queries';
import { useCountry } from '../contexts/CountryContext';

export type PresaleAccess = 'buy' | 'waitlist' | 'blocked';

const US_WAITLIST_NOTICE = 'La preventa aún no está abierta para residentes de EE. UU. '
  + 'Únete a la lista de espera y te avisaremos si se abre.';

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

  // The server still says 'us_waitlist' for the US, for builds that know
  // no other waitlist value.
  const serverAccess = server?.access === 'us_waitlist' ? 'waitlist' : server?.access;
  const access: PresaleAccess = serverAccess
    ?? (iso === 'US' ? 'waitlist' : FALLBACK_BLOCKS[iso] ? 'blocked' : 'buy');
  const waitlistNotice: string = server?.waitlistNotice || US_WAITLIST_NOTICE;
  const message: string = server?.message
    || FALLBACK_BLOCKS[iso]
    || 'Lo sentimos, la preventa no está disponible en tu país.';

  return {
    access,
    // 'open' once the admin lets US residents buy; unknown counts as closed.
    usOpen: server?.usAccess === 'open',
    notUsAttestationRequired: server?.notUsAttestationRequired !== false,
    waitlistNotice,
    /** True when the user may go on to buy; otherwise explains why not. */
    checkCanBuy: (): boolean => {
      if (access === 'buy') return true;
      Alert.alert('Restricción', access === 'waitlist' ? waitlistNotice : message);
      return false;
    },
  };
};
