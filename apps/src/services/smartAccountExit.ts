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

// The server owns the question (smartAccountExitQuestion, smart_account/funnel.py
// EXIT_OPTIONS) so it can be reworded between releases. Its own query: an older
// server without it only means this built-in copy of the same list is shown.
export const SMART_ACCOUNT_EXIT_QUESTION = gql`query SmartAccountExitQuestion {
  smartAccountExitQuestion { title options { key label } }
}`;

export const SMART_ACCOUNT_EXIT_TITLE = '¿Qué te hizo esperar?';

/** Built-in answers, used only when the server's could not be read; one cause each. */
export const SMART_ACCOUNT_EXIT_REASONS: ReadonlyArray<readonly [string, string]> = [
  ['money', 'Ahora no tengo ese dinero'],
  ['price', 'Me parece caro para lo que ofrece'],
  ['unclear', 'No entendí bien qué hace'],
  ['no_need', 'No necesito pagos ni inversiones automáticas'],
  ['move', 'No quiero mover mi dinero a otra cuenta'],
  ['verify', 'Me falta verificarme'],
  ['other', 'Otra cosa'],
];

export const SMART_ACCOUNT_EXIT_SKIPPED = 'skipped';

export type SmartAccountExitReason = readonly [string, string];
export type SmartAccountExitAsk = { title: string; reasons: SmartAccountExitReason[]; plan: string | null };
type ServerQuestion = { title: string; reasons: SmartAccountExitReason[] };

// The server's question for this person, once read (it already left out "Me falta verificarme"
// when that is not their next step); null until then or when it could not be read.
let serverQuestion: ServerQuestion | null = null;
// Only the latest read may write: an older one answering late (another account's) never does.
let questionRead = 0;

const MAX_OPTIONS = 8;

/** The server's answer, kept only when well formed. */
export function parseExitQuestion(data: any): ServerQuestion | null {
  const q = data?.smartAccountExitQuestion;
  const title = typeof q?.title === 'string' ? q.title.trim() : '';
  const seen = new Set<string>();
  const valid = (Array.isArray(q?.options) ? q.options : [])
    .filter((o: any) => o && typeof o.key === 'string' && /^[a-z_]{1,24}$/.test(o.key)
      && typeof o.label === 'string' && o.label.trim() && !seen.has(o.key) && seen.add(o.key))
    .map((o: any) => [o.key, o.label.trim()] as const);
  // The cap never drops "Otra cosa".
  const other = valid.filter(([id]: readonly [string, string]) => id === 'other');
  const reasons = [...valid.filter(([id]: readonly [string, string]) => id !== 'other').slice(0, MAX_OPTIONS - other.length), ...other];
  return title && reasons.length >= 2 ? { title, reasons } : null;
}

/** Read the server's question for this person; harmless to call again. */
export async function preloadSmartAccountExitQuestion(): Promise<void> {
  // Per person and per visit: never another account's (or an older) answer.
  serverQuestion = null;
  const mine = ++questionRead;
  try {
    const { apolloClient } = await import('../apollo/client');
    const { data } = await apolloClient.query({ query: SMART_ACCOUNT_EXIT_QUESTION, fetchPolicy: 'network-only' });
    const parsed = parseExitQuestion(data);
    if (parsed && mine === questionRead) serverQuestion = parsed;
  } catch {
    // The built-in list stands.
  }
}

/** Shuffled, 'other' kept last, so no answer wins by its place. */
function shuffled(list: ReadonlyArray<SmartAccountExitReason>, random: () => number): SmartAccountExitReason[] {
  const rest = list.filter(([id]) => id !== 'other');
  const other = list.filter(([id]) => id === 'other');
  for (let i = rest.length - 1; i > 0; i -= 1) {
    const j = Math.floor(random() * (i + 1));
    [rest[i], rest[j]] = [rest[j], rest[i]];
  }
  return [...rest, ...other];
}

/**
 * The question to show: the server's when it was read, else the built-in one,
 * where "Me falta verificarme" is only for someone the screen told to verify.
 */
export function smartAccountExitQuestion(needsVerify: boolean, random: () => number = Math.random): {
  title: string; reasons: SmartAccountExitReason[];
} {
  if (serverQuestion) return { title: serverQuestion.title, reasons: shuffled(serverQuestion.reasons, random) };
  return {
    title: SMART_ACCOUNT_EXIT_TITLE,
    reasons: shuffled(SMART_ACCOUNT_EXIT_REASONS.filter(([id]) => needsVerify || id !== 'verify'), random),
  };
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
        listener({ ...smartAccountExitQuestion(needsVerify), plan });
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
  serverQuestion = null;
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
    void preloadSmartAccountExitQuestion();
    return () => {
      const long = shownAt.current > 0 && Date.now() - shownAt.current >= MIN_VISIT_MS;
      if (long && !stayed.current && context.current.eligible) {
        void requestSmartAccountExitQuestion(context.current.needsVerify, context.current.plan);
      }
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
}
