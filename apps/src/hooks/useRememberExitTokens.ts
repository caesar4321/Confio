// Keeps the Emergency Exit's memory of held tokens current (heldTokens.ts):
// every Ondo stock and crypto/metal token the server sees in this account,
// so the exit covers tokens listed after this app's build. Its own query and
// its own root field: an older server without it fails only this, quietly.
import { useEffect } from 'react';
import { AppState } from 'react-native';
import { useIsFocused } from '@react-navigation/native';
import { gql, useQuery } from '@apollo/client';
import { useAuthReady } from '../contexts/AuthContext';
import { rememberHeldTokens } from '../services/emergencyExit/heldTokens';
import { emergencyStore } from '../services/emergencyExit/store';

export const GET_EXIT_HELD_TOKENS = gql`
  query ExitHeldTokens {
    exitHeldTokens {
      symbol
      address
      kind
    }
  }
`;

export const useRememberExitTokens = () => {
  const authReady = useAuthReady();
  const { data, refetch } = useQuery(GET_EXIT_HELD_TOKENS, {
    fetchPolicy: 'network-only',
    errorPolicy: 'ignore',
    pollInterval: 600_000,
    skip: !authReady,
  });
  // A stock bought elsewhere in the app is held by the time the member is
  // back on Home (or back in the app): read again then, not only every 10 min.
  const isFocused = useIsFocused();
  useEffect(() => {
    if (authReady && isFocused) refetch().catch(() => {});
  }, [authReady, isFocused, refetch]);
  useEffect(() => {
    const subscription = AppState.addEventListener('change', (state) => {
      if (state === 'active' && authReady) refetch().catch(() => {});
    });
    return () => subscription.remove();
  }, [authReady, refetch]);
  const rows = data?.exitHeldTokens;
  useEffect(() => {
    if (Array.isArray(rows) && rows.length) void rememberHeldTokens(emergencyStore, rows);
  }, [rows]);
};
