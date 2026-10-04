// Background duties of Confío IA while the user is signed in:
//  - load the IA+ plan,
//  - hand store transactions (renewals, purchases finished later) to the
//    server for verification,
//  - run the "Confío" wake word (IA+, opted in, app in foreground, no call,
//    chat closed so the mic is free for voice notes).
import { useEffect, useRef } from 'react';
import { AppState } from 'react-native';
import { useApolloClient, useQuery } from '@apollo/client';
import { useAccount } from '../contexts/AccountContext';
import { useAuth } from '../contexts/AuthContext';
import { GET_CONFIO_IA_PLAN, GET_CONFIO_IA_THREAD, GET_CONFIO_IA_WAKE_WORD } from './api';
import { listenForStoreTransactions } from './billingClient';
import { hangUp, useCall } from './callStore';
import { useConfioIa } from './ConfioIaContext';
import { WakeWordListener } from './wakeWord';

export default function ConfioIaServices() {
  const client = useApolloClient();
  const { isAuthenticated, isLoading } = useAuth();
  const { plan, setPlan, isOpen, open, setInCall, aiEnabled, micBusy } = useConfioIa();
  const call = useCall();
  const enabled = isAuthenticated && !isLoading && aiEnabled;
  const { activeAccount } = useAccount();
  const accountId = activeAccount?.id;
  const listener = useRef<WakeWordListener | null>(null);

  const { data: planData } = useQuery(GET_CONFIO_IA_PLAN, {
    skip: !enabled,
    fetchPolicy: 'network-only',
    errorPolicy: 'ignore',
  });
  useEffect(() => {
    if (planData?.confioIaPlan) {
      setPlan(planData.confioIaPlan);
    }
  }, [planData, setPlan]);

  // Store transactions only matter while IA+ is on sale.
  const salesOn = !!plan?.plusSalesEnabled;
  useEffect(() => {
    if (!enabled || !salesOn) {
      return undefined;
    }
    return listenForStoreTransactions(client, setPlan);
  }, [enabled, salesOn, client, setPlan]);

  const live = call.state !== 'idle' && call.state !== 'ended';

  // A call belongs to the account it started on: switching accounts ends it
  // (the server would refuse its tools anyway). Signing out or leaving the
  // signed-in app ends it too, so no microphone outlives the session.
  const firstAccount = useRef(accountId);
  useEffect(() => {
    if (firstAccount.current !== accountId) {
      firstAccount.current = accountId;
      hangUp();
    }
  }, [accountId]);
  useEffect(() => {
    if (!isAuthenticated) {
      hangUp();
    }
  }, [isAuthenticated]);
  useEffect(() => () => hangUp(), []);
  useEffect(() => {
    setInCall(live);
  }, [live, setInCall]);

  const { data: profileData } = useQuery(GET_CONFIO_IA_THREAD, {
    variables: { limit: 1, contextKey: accountId || 'no-account' },
    fetchPolicy: 'cache-only',
    skip: !enabled,
  });
  const wakeWordWanted =
    enabled && !!plan?.wakeWordAvailable && !!profileData?.confioIaThread?.profile?.wakeWordEnabled;
  const { data: keyData } = useQuery(GET_CONFIO_IA_WAKE_WORD, {
    skip: !wakeWordWanted,
    fetchPolicy: 'network-only',
    errorPolicy: 'ignore',
  });
  const accessKey = keyData?.confioIaWakeWord?.accessKey as string | undefined;

  useEffect(() => {
    if (!wakeWordWanted || !accessKey) {
      void listener.current?.release();
      listener.current = null;
      return undefined;
    }
    // "Confío" → the box opens on Confío IA and records a voice note (cheap;
    // realtime calls stay dark).
    listener.current = new WakeWordListener(accessKey, () => open({ channel: 'ia', voiceNote: true }));
    return () => {
      void listener.current?.release();
      listener.current = null;
    };
  }, [wakeWordWanted, accessKey, open]);

  // Listen only when nobody else needs the microphone.
  useEffect(() => {
    const sync = () => {
      const l = listener.current;
      if (!l) {
        return;
      }
      if (AppState.currentState === 'active' && !isOpen && !live && !micBusy) {
        void l.start();
      } else {
        void l.stop();
      }
    };
    sync();
    const sub = AppState.addEventListener('change', sync);
    return () => sub.remove();
  }, [isOpen, live, micBusy, accessKey, wakeWordWanted]);

  return null;
}
