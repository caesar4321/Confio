import { useQuery, type WatchQueryFetchPolicy } from '@apollo/client';

import { useAccount } from '../../contexts/AccountContext';
import { useAuth } from '../../contexts/AuthContext';
import { calendarSupported } from '../calendar/deviceCalendar';
import { ASSISTANT_CALENDAR_ENABLED } from '../calendar/flag';
import { ASSISTANT_MAIL_ENABLED } from '../mail/flag';
import { GET_CONNECTIONS, type Connections } from './api';
import type { Build } from './rules';

/** Personal account only. */
export function useViewer(): string | null {
  const { userProfile } = useAuth();
  const { activeAccount } = useAccount();
  return userProfile?.id && activeAccount?.type === 'personal' ? String(userProfile.id) : null;
}

/** No data (an older server, the switch off, an error) shows nothing. */
export function useConnections(userId: string, fetchPolicy: WatchQueryFetchPolicy) {
  const { data, refetch } = useQuery(GET_CONNECTIONS, {
    skip: !userId,
    fetchPolicy,
    nextFetchPolicy: 'cache-first',
    errorPolicy: 'ignore',
  });
  const connections: Connections | null = data?.assistantMailConnections ?? null;
  const build: Build = {
    mail: ASSISTANT_MAIL_ENABLED,
    calendar: ASSISTANT_CALENDAR_ENABLED && calendarSupported(),
  };
  return { connections, build, refetch };
}
