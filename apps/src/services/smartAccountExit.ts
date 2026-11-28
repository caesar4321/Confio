import { useEffect, useRef } from 'react';
import { gql } from '@apollo/client';

/**
 * "What made you wait?" — one tap, after the person spent a moment on the
 * Cuenta inteligente subscribe screen and closed it without opening the
 * account. Asked by the single SmartAccountExitQuestionHost (mounted once above
 * the navigator) right after the screen closes. At most once a week per device.
 * Worded as a light question, not a survey: no "help us improve" line.
 */

// Its own operation: an older server without it fails only this answer.
export const RECORD_SMART_ACCOUNT_EXIT_REASON = gql`mutation RecordSmartAccountExitReason($reason: String!, $plan: String) {
  recordSmartAccountExitReason(reason: $reason, plan: $plan) { success }
}`;

export const SMART_ACCOUNT_EXIT_TITLE = '¿Qué te hizo esperar?';

/** One-tap answers; the keys are the server's (smart_account/funnel.py EXIT_REASONS). */
export const SMART_ACCOUNT_EXIT_REASONS = [
  ['later', 'La veo con calma más adelante'],
  ['money', 'Ahora no me alcanza'],
  ['value', 'No sé si la usaría'],
  ['plan', 'No sé qué plan me conviene'],
  ['trust', 'Quiero conocer mejor Confío primero'],
  ['verify', 'Me falta verificarme'],
  ['other', 'Otra cosa'],
] as const;

export const SMART_ACCOUNT_EXIT_SKIPPED = 'skipped';

export type SmartAccountExitReason = (typeof SMART_ACCOUNT_EXIT_REASONS)[number];
export type SmartAccountExitAsk = { reasons: SmartAccountExitReason[]; plan: string | null };

/**
 * The answers in a fresh random order ('other' last). "Me falta verificarme"
 * only for someone the screen told to verify first.
 */
export function smartAccountExitReasons(needsVerify: boolean, random: () => number = Math.random): SmartAccountExitReason[] {
  const rest = SMART_ACCOUNT_EXIT_REASONS.filter(([id]) => id !== 'other' && (needsVerify || id !== 'verify'));
  const other = SMART_ACCOUNT_EXIT_REASONS.filter(([id]) => id === 'other');
  for (let i = rest.length - 1; i > 0; i -= 1) {
    const j = Math.floor(random() * (i + 1));
    [rest[i], rest[j]] = [rest[j], rest[i]];
  }
  return [...rest, ...other];
}

// A quick back tap is not a decision: only a visit at least this long is asked about.
export const MIN_VISIT_MS = 4000;
const WEEK_MS = 7 * 24 * 60 * 60 * 1000;

type AskedStore = { read: () => Promise<number>; write: (at: number) => Promise<void> };

const KEYCHAIN_SERVICE = 'confio_smart_account_exit_at';
const keychainStore: AskedStore = {
  read: async () => {
    const Keychain = await import('react-native-keychain');
    const stored = await Keychain.getGenericPassword({ service: KEYCHAIN_SERVICE });
    const at = stored ? Number(stored.password) : 0;
    return Number.isFinite(at) ? at : 0;
  },
  write: async (at) => {
    const Keychain = await import('react-native-keychain');
    await Keychain.setGenericPassword('at', String(at), { service: KEYCHAIN_SERVICE });
  },
};

let store: AskedStore = keychainStore;
// When this device was last asked, once read; null until then. Read when the
// screen opens (never at startup: keystore reads can be slow on some phones).
let askedAt: number | null = null;
let askedRead: Promise<number> | null = null;
let listener: ((ask: SmartAccountExitAsk) => void) | null = null;

export function preloadSmartAccountExitAsked(): Promise<number> {
  if (askedAt !== null) return Promise.resolve(askedAt);
  if (!askedRead) {
    askedRead = store.read().catch(() => 0).then((at) => {
      if (askedAt === null) askedAt = at;
      return askedAt;
    });
  }
  return askedRead;
}

/** The host registers itself; returns the unsubscribe. */
export function subscribeSmartAccountExitQuestion(next: (ask: SmartAccountExitAsk) => void): () => void {
  listener = next;
  return () => {
    if (listener === next) listener = null;
  };
}

/**
 * Ask, unless no host is mounted or this device was asked in the last week.
 * Runs a tick later so a torn-down navigator (logout) never spends the week on
 * a sheet that never shows. Resolves true when the sheet was shown.
 */
export function requestSmartAccountExitQuestion(
  needsVerify: boolean, plan: string | null, now: number = Date.now(),
): Promise<boolean> {
  return new Promise((resolve) => {
    setTimeout(async () => {
      try {
        if (!listener) return resolve(false);
        const last = askedAt !== null ? askedAt : await preloadSmartAccountExitAsked();
        if (!listener || now - last < WEEK_MS) return resolve(false);
        askedAt = now;
        listener({ reasons: smartAccountExitReasons(needsVerify), plan });
        void store.write(now).catch(() => {});
        resolve(true);
      } catch {
        resolve(false);
      }
    }, 0);
  });
}

export function resetSmartAccountExitForTests(testStore?: AskedStore): void {
  askedAt = null;
  askedRead = null;
  listener = null;
  store = testStore || keychainStore;
}

type Flag = { current: boolean };

/**
 * For the subscribe screen: asks once it closes, when the offer was on screen
 * for MIN_VISIT_MS and the person neither continued nor went to verify (both
 * set `stayed`). `ready` is true once the offer shows; the visit clock starts then.
 */
export function useAskWhyOnSmartAccountLeave(
  ready: boolean, stayed: Flag, context: { current: { needsVerify: boolean; plan: string | null; eligible: boolean } },
): void {
  const shownAt = useRef(0);
  useEffect(() => {
    if (ready && !shownAt.current) shownAt.current = Date.now();
  }, [ready]);
  useEffect(() => {
    void preloadSmartAccountExitAsked();
    return () => {
      const long = shownAt.current > 0 && Date.now() - shownAt.current >= MIN_VISIT_MS;
      if (long && !stayed.current && context.current.eligible) {
        void requestSmartAccountExitQuestion(context.current.needsVerify, context.current.plan);
      }
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
}
