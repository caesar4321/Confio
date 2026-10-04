// Data for the Home hero line "Octubre · Entró US$420 · Salió US$310 ›".
//
// Layout stability (design 2A / D8): the line sits ABOVE Enviar/Recibir, so
// a late network answer must never insert it while the user may be reaching
// for those buttons. On every Home focus we render only what is already in
// the Apollo cache, then refresh the cache in the background for the NEXT
// focus. Exception (eng C7): if the account or the month changed, the shown
// data belongs to the wrong context, so it is replaced as soon as fresh data
// arrives (the hero is re-rendering for the switch anyway).
//
// Account switches: some switch paths update activeAccount BEFORE the new
// JWT exists and the cache is cleared, so during `switching` the cache and
// any request still answer for the previous account. The line hides on the
// account change, reads/fetches nothing until the switch settles, and drops
// any answer that was requested for an earlier account or month.
//
// Cache: the hero only shows totals (which categories never change) and
// keeps its own per-account/month answers, fetched with 'no-cache'. It must
// not write the shared summary cache: a hero request finishing after a
// category save would put the pre-save category split back for Tu mes.
//
// Month rollover: Home can stay focused across midnight on the 1st, so the
// month is re-checked when the app returns to the foreground and at the
// local month boundary while it is open.
import { useCallback, useEffect, useRef, useState } from 'react';
import { AppState } from 'react-native';
import { useApolloClient } from '@apollo/client';
import { useFocusEffect } from '@react-navigation/native';
import { GET_MONTH_SUMMARY, type MonthSummary } from '../apollo/monthSummary';
import { currentYearMonth, deviceTimezone } from '../utils/monthSummary';

export const HERO_LINE_MIN_MOVEMENTS = 3;
const MAX_TIMEOUT_MS = 2 ** 31 - 1;

function msUntilNextMonth(now = new Date()) {
  const next = new Date(now.getFullYear(), now.getMonth() + 1, 1, 0, 0, 1);
  return Math.min(MAX_TIMEOUT_MS, Math.max(1000, next.getTime() - now.getTime()));
}

export function useMonthHeroLine(accountKey: string | null | undefined, enabled: boolean, switching = false) {
  const client = useApolloClient();
  const [summary, setSummary] = useState<MonthSummary | null>(null);
  const shownKey = useRef<string | null>(null);
  // The context whose fresh answer may replace the line as soon as it lands.
  // Kept until that answer arrives, so a repeated load cannot lose it.
  const replaceKey = useRef<string | null>(null);
  const request = useRef(0);
  const focused = useRef(false);
  const fresh = useRef(new Map<string, MonthSummary | null>());
  // Only the very first eligible load of this Home is a cold start; later
  // context changes (incl. returning from an employee account) replace.
  const started = useRef(false);

  // Another account's numbers must never stay on screen, even for a frame
  // while the switch is still in flight.
  const lastAccount = useRef(accountKey);
  if (lastAccount.current !== accountKey) {
    lastAccount.current = accountKey;
    request.current += 1;
    if (summary !== null) setSummary(null);
  }

  const load = useCallback(() => {
    if (!enabled || !accountKey) {
      request.current += 1;
      setSummary(null);
      shownKey.current = null;
      replaceKey.current = null;
      return;
    }
    if (switching) return; // cache + JWT may still be the previous account's
    const { year, month } = currentYearMonth();
    const variables = { year, month, timezone: deviceTimezone() };
    const key = `${accountKey}:${year}-${month}`;
    // The very first Home render never inserts the line late (cold cache).
    if (started.current && shownKey.current !== key) replaceKey.current = key;
    started.current = true;

    // Own answers first; else whatever Tu mes already cached for this month.
    let cached: MonthSummary | null = fresh.current.get(key) ?? null;
    if (!cached) {
      try {
        cached = client.readQuery<{ monthSummary: MonthSummary | null }>({ query: GET_MONTH_SUMMARY, variables })
          ?.monthSummary ?? null;
      } catch {
        cached = null;
      }
    }
    if (cached || shownKey.current !== key) {
      setSummary(cached);
      shownKey.current = key;
    }
    if (cached && replaceKey.current === key) replaceKey.current = null;

    const id = ++request.current;
    client
      .query<{ monthSummary: MonthSummary | null }>({ query: GET_MONTH_SUMMARY, variables, fetchPolicy: 'no-cache' })
      .then(({ data }) => {
        if (id !== request.current) return; // asked for an earlier account/month
        fresh.current.set(key, data?.monthSummary ?? null);
        // Fresh data waits for the next focus, unless the line had to be
        // cleared for a new account/month (then stale is worse than a move).
        if (replaceKey.current === key) {
          replaceKey.current = null;
          setSummary(data?.monthSummary ?? null);
        }
      })
      .catch(() => {
        // The hero line is optional: on error it simply stays as it was.
      });
  }, [client, accountKey, enabled, switching]);

  // One loader: runs on focus and again whenever its inputs change while
  // focused (useFocusEffect re-runs on a new callback).
  useFocusEffect(useCallback(() => {
    focused.current = true;
    load();
    return () => { focused.current = false; };
  }, [load]));

  useEffect(() => {
    const sub = AppState.addEventListener('change', (state) => {
      if (state === 'active' && focused.current) load();
    });
    let timer: ReturnType<typeof setTimeout>;
    const schedule = () => {
      timer = setTimeout(() => {
        if (focused.current) load();
        schedule();
      }, msUntilNextMonth());
    };
    schedule();
    return () => {
      sub.remove();
      clearTimeout(timer);
    };
  }, [load]);

  const visible = Boolean(summary && summary.current.movementCount >= HERO_LINE_MIN_MOVEMENTS);
  return { summary: visible ? summary : null };
}
