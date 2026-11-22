// What must survive the app lock lives outside React: it unmounts every Modal's children.
import { useSyncExternalStore } from 'react';
import * as Keychain from 'react-native-keychain';

import { SNOOZE_DAYS } from './rules';

/** The assistant is mounted twice (Inicio and the box): a sheet opens only over the one it was opened from. */
export type Where = 'home' | 'box';

let openFor: string | null = null;
const drafts = new Map<string, string>();
const listeners = new Set<() => void>();
const subscribe = (listener: () => void) => {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
};

export function openConnections(userId: string, where: Where) {
  openFor = `${where}:${userId}`;
  listeners.forEach((listener) => listener());
}

export function closeConnections() {
  openFor = null;
  drafts.clear();
  listeners.forEach((listener) => listener());
}

export const useConnectionsOpen = (userId: string | null, where: Where) =>
  useSyncExternalStore(subscribe, () => !!userId && openFor === `${where}:${userId}`);

/** The address being typed: leaving to copy it must not put the sign-in Gmail back. */
export const typedEmail = (userId: string) => drafts.get(userId);
export const keepTypedEmail = (userId: string, email: string) => {
  drafts.set(userId, email);
};

// "Ahora no", on this phone. Read once: the keystore has one lock and can be slow.
const SERVICE = 'com.confio.assistant.connections.snooze';
const known = new Map<string, number>();

/** undefined until read. Every mounted prompt follows it. */
export const useKnownSnooze = (userId: string) => useSyncExternalStore(subscribe, () => known.get(userId));
const emit = () => listeners.forEach((listener) => listener());

export async function readSnooze(userId: string): Promise<number> {
  let until = known.get(userId);
  if (until === undefined) {
    try {
      const stored = await Keychain.getGenericPassword({ service: SERVICE });
      until = stored && stored.username === userId ? Number(stored.password) || 0 : 0;
    } catch {
      until = 0;
    }
    known.set(userId, until);
    emit();
  }
  return until;
}

export async function snooze(userId: string): Promise<number> {
  const until = Date.now() + SNOOZE_DAYS * 86400000;
  known.set(userId, until);
  emit();
  try {
    await Keychain.setGenericPassword(userId, String(until), { service: SERVICE });
  } catch {
    // It comes back next time, nothing worse.
  }
  return until;
}
