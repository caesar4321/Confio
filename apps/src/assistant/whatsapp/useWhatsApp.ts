import { useEffect, useState } from 'react';
import { useQuery, type WatchQueryFetchPolicy } from '@apollo/client';

import { GET_WHATSAPP, type WhatsAppLink } from './api';
import { pollFor } from './rules';

/** Null with no data (an older server, a business account, an error): the WhatsApp row doesn't show.
 * `polling`: the open sheet polls while the code is up (it changes, and the link happens there). */
export function useWhatsApp(userId: string | null, fetchPolicy: WatchQueryFetchPolicy, polling = false) {
  const [interval, setPollInterval] = useState(0);
  const { data, refetch } = useQuery(GET_WHATSAPP, {
    skip: !userId,
    fetchPolicy,
    nextFetchPolicy: polling ? 'network-only' : 'cache-first',
    errorPolicy: 'ignore',
    pollInterval: interval,
  });
  const link: WhatsAppLink | null = data?.whatsAppLink ?? null;
  const state = link?.state;
  useEffect(() => {
    setPollInterval(polling ? pollFor(link) : 0);
    // Only the state decides it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [polling, state]);
  return { link, refetch };
}
