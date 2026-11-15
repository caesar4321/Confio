import { useCallback, useEffect, useRef } from 'react';
import { gql } from '@apollo/client';

/**
 * "Why did you leave without topping up?" — one tap, after the person looked
 * at a top-up price (any rail, any currency) and closed the screen without
 * ordering. Asked by the single TopUpExitQuestionHost (mounted once above the
 * navigator) right after the screen closes, so every way out counts: back
 * button, swipe, Android back. At most once per device-day.
 */

// Its own operation: an older server without it fails only this answer. The
// server files it on the person's latest top-up price view; no rail or account
// is ever sent.
export const RECORD_TOP_UP_EXIT_REASON = gql`mutation RecordTopUpExitReason($reason: String!) {
  recordTopUpExitReason(reason: $reason) { success }
}`;

/** One-tap answers; the keys are the server's (ramps/ve_funnel.py EXIT_REASONS). */
export const TOP_UP_EXIT_REASONS = [
  ['looking', 'Solo estaba viendo el precio'],
  ['no_money', 'No tengo el dinero ahora'],
  ['receive_less', 'Recibo menos de lo que esperaba'],
  ['limits', 'El mínimo o el máximo no me sirve'],
  ['pay_method', 'Quiero pagar de otra forma'],
  ['trust', 'Todavía no confío en la app'],
  ['loan', 'Buscaba un préstamo'],
  ['other', 'Otra cosa'],
] as const;

/** Asked, and closed without answering. */
export const TOP_UP_EXIT_SKIPPED = 'skipped';

export type TopUpExitReason = (typeof TOP_UP_EXIT_REASONS)[number];

/** Every answer in a fresh random order, so no answer wins by its place; 'other' stays last. */
export function shuffledExitReasons(random: () => number = Math.random): TopUpExitReason[] {
  const rest = TOP_UP_EXIT_REASONS.filter(([id]) => id !== 'other');
  const other = TOP_UP_EXIT_REASONS.filter(([id]) => id === 'other');
  for (let i = rest.length - 1; i > 0; i -= 1) {
    const j = Math.floor(random() * (i + 1));
    [rest[i], rest[j]] = [rest[j], rest[i]];
  }
  return [...rest, ...other];
}

const dayKey = (now: Date) => `${now.getFullYear()}-${now.getMonth() + 1}-${now.getDate()}`;

/** A refused amount the server records as a look at the price (min/max copy). */
export function isLimitRefusal(message?: string | null): boolean {
  return /m[ií]nimo|m[aá]ximo/i.test(message || '');
}

/** Where the asked-on day lives, so an app restart does not ask again the same day. */
type DayStore = { read: () => Promise<string>; write: (day: string) => Promise<void> };

const KEYCHAIN_SERVICE = 'confio_top_up_exit_day';
const keychainStore: DayStore = {
  read: async () => {
    const Keychain = await import('react-native-keychain');
    const stored = await Keychain.getGenericPassword({ service: KEYCHAIN_SERVICE });
    return stored ? stored.password : '';
  },
  write: async (day) => {
    const Keychain = await import('react-native-keychain');
    await Keychain.setGenericPassword('day', day, { service: KEYCHAIN_SERVICE });
  },
};

let store: DayStore = keychainStore;
let askedOn = '';
// The stored day, once read; null until then. Read when a top-up screen opens
// (never at startup: keystore reads can take seconds on some Android phones),
// so closing it decides without waiting on the keystore.
let storedDay: string | null = null;
let storedRead: Promise<string> | null = null;
let listener: (() => void) | null = null;

// The server files an answer only on a price seen in the last 2 hours
// (ramps/ve_funnel.py EXIT_WINDOW); an older look is not asked about.
export const PRICE_FRESH_MS = 2 * 60 * 60 * 1000 - 5 * 60 * 1000;

/** Start reading the stored day; harmless to call again. */
export function preloadTopUpExitDay(): Promise<string> {
  if (storedDay !== null) return Promise.resolve(storedDay);
  if (!storedRead) {
    storedRead = store.read().catch(() => '').then(day => {
      storedDay = day;
      return day;
    });
  }
  return storedRead;
}

/** The host registers itself; returns the unsubscribe. */
export function subscribeTopUpExitQuestion(next: () => void): () => void {
  listener = next;
  return () => {
    if (listener === next) listener = null;
  };
}

/**
 * Ask, unless no host is mounted or this device was already asked today. Runs
 * a tick later: when the whole navigator is torn down (logout) the screen's
 * cleanup runs before the host's, and the day must not be spent on a sheet
 * that never shows. Resolves true when the sheet was shown.
 */
export function requestTopUpExitQuestion(now: Date = new Date()): Promise<boolean> {
  const day = dayKey(now);
  return new Promise(resolve => {
    setTimeout(async () => {
      try {
        if (!listener || askedOn === day) return resolve(false);
        const stored = storedDay !== null ? storedDay : await preloadTopUpExitDay();
        if (stored === day) {
          askedOn = day;
          return resolve(false);
        }
        if (!listener || askedOn === day) return resolve(false);
        askedOn = day;
        storedDay = day;
        listener();
        void store.write(day).catch(() => {});
        resolve(true);
      } catch {
        resolve(false);
      }
    }, 0);
  });
}

export function resetTopUpExitQuestionForTests(testStore?: DayStore): void {
  askedOn = '';
  storedDay = null;
  storedRead = null;
  listener = null;
  store = testStore || keychainStore;
}

type Flag = { current: boolean };

/**
 * For a top-up screen: asks once it closes, if the person saw a price (or was
 * refused one for the minimum/maximum) in the last ~2 hours and never ordered.
 * priceKey names the price on screen (null when none); the clock starts when it
 * changes, never on a re-render, like the server's last_seen_at.
 * "Ordered" sticks for the visit. Call the returned markOrdered() before navigating away with an
 * order — a replace() closes the screen before any state update renders.
 * creating: the screen's in-flight flag for creating an order; leaving while
 * it is set is not leaving the price (the order may still land).
 */
export function useAskWhyOnLeave(priceKey: string | null, ordered = false, creating?: Flag): () => void {
  const sawAt = useRef(0);
  const placed = useRef(false);
  const inFlight = useRef<Flag | undefined>(creating);
  inFlight.current = creating;
  if (ordered) placed.current = true;
  useEffect(() => {
    if (priceKey) sawAt.current = Date.now();
  }, [priceKey]);
  useEffect(() => {
    void preloadTopUpExitDay();
    return () => {
      const fresh = sawAt.current > 0 && Date.now() - sawAt.current < PRICE_FRESH_MS;
      if (fresh && !placed.current && !inFlight.current?.current) void requestTopUpExitQuestion();
    };
  }, []);
  return useCallback(() => {
    placed.current = true;
  }, []);
}
