// confio://gmail-connect?code=…&state=… from the browser. The deep-link handler
// imports this, so it stays light. The code is worthless without the verifier
// on this phone and the signed-in person who started the attempt.
import { Alert } from 'react-native';

import { ASSISTANT_MAIL_ENABLED } from './flag';
import { isMailSheetOpen } from './session';

export type ConnectResult = { code: string; state: string } | { denied: true; state: string };

const PREFIX = /^confio:\/\/gmail-connect(?:[/?#]|$)/i;

let pending: ConnectResult | null = null;
const listeners = new Set<() => void>();

const param = (query: string, name: string) => {
  const match = new RegExp(`(?:^|&)${name}=([^&]*)`).exec(query);
  try {
    return match ? decodeURIComponent(match[1]) : '';
  } catch {
    return '';
  }
};

/** True when the link was ours, so nothing else logs, stores or routes it. */
export function receiveMailConnectLink(url: string): boolean {
  if (!PREFIX.test(url)) {
    return false;
  }
  const query = (url.split('?')[1] ?? '').split('#')[0];
  const code = param(query, 'code');
  const state = param(query, 'state');
  if (!state || !(code || param(query, 'error'))) {
    return true;
  }
  pending = code ? { code, state } : { denied: true, state };
  listeners.forEach((listener) => listener());
  if (ASSISTANT_MAIL_ENABLED && !listeners.size && !isMailSheetOpen()) {
    // A cold start. The lock holds this alert until the unlock.
    Alert.alert('Gmail', 'Para terminar de conectarlo, abre Confío IA, toca «✨ Tu asistente» y luego «Tu correo».');
  }
  return true;
}

export function takeMailConnectResult(): ConnectResult | null {
  const result = pending;
  pending = null;
  return result;
}

export function onMailConnectResult(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
