// The live voice call lives outside the chat sheet: "abre QR para pagar"
// closes the sheet to show the screen while the call keeps going, and the
// bubble shows it's live. One call at a time.
import { useSyncExternalStore } from 'react';
import type { ApolloClient } from '@apollo/client';
import { VoiceCall, type CallState, type Caption } from './realtime';

type Snapshot = {
  state: CallState | 'idle';
  captions: Caption[];
  muted: boolean;
  minutesLeft: number | null;
  error: string | null;
};

let snapshot: Snapshot = { state: 'idle', captions: [], muted: false, minutesLeft: null, error: null };
let call: VoiceCall | null = null;
const listeners = new Set<() => void>();

function set(patch: Partial<Snapshot>) {
  snapshot = { ...snapshot, ...patch };
  listeners.forEach((l) => l());
}

export function useCall() {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    () => snapshot,
  );
}

export function isCallLive() {
  return snapshot.state !== 'idle' && snapshot.state !== 'ended';
}

export async function startCall(
  client: ApolloClient<any>,
  opts: { screen?: string; timezone?: string; isBusiness?: boolean; onNavigate?: () => void },
) {
  if (isCallLive()) {
    return;
  }
  set({ state: 'connecting', captions: [], muted: false, error: null });
  call = new VoiceCall(
    client,
    {
      onState: (state) => set({ state }),
      onCaption: (caption) => set({ captions: [...snapshot.captions, caption].slice(-12) }),
      onEnded: (reason) => {
        call = null;
        set({ state: 'idle', error: reason ?? null });
      },
      onMinutesLeft: (minutesLeft) => set({ minutesLeft }),
      onNavigate: opts.onNavigate,
    },
    opts,
  );
  await call.start();
}

export function hangUp() {
  call?.hangUp();
}

export function toggleMute() {
  if (!call) {
    return;
  }
  call.setMuted(!call.isMuted);
  set({ muted: call.isMuted });
}

export function clearCallError() {
  set({ error: null });
}
