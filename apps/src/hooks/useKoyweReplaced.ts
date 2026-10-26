import { useQuery } from '@apollo/client';
import { BOLIVIA_QR_KOYWE_REPLACED } from '../services/boliviaQr';

/**
 * Which Koywe rows QR Bolivia replaces for this person right now (the server
 * decides: their country, the switches, this build). Fails soft: an older
 * server or a network error replaces nothing.
 */
export function useKoyweReplaced(): { topUp: boolean; withdraw: boolean } {
  const { data } = useQuery(BOLIVIA_QR_KOYWE_REPLACED, { fetchPolicy: 'cache-and-network', errorPolicy: 'all' });
  const replaced = data?.boliviaQrKoyweReplaced;
  return { topUp: !!replaced?.topUp, withdraw: !!replaced?.withdraw };
}
