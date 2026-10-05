// Data for the Home month row (owners only).
//
// The row is ALWAYS present for owners (amendment 2026-10-04: hiding it
// silently made the feature undiscoverable). It has a fixed footprint (see
// HeroMonthLine), so its content can change at any time without moving
// Enviar/Recibir:
//   - loading: a quiet placeholder,
//   - the CURRENT month, always — "Entró US$0 · Salió US$0" on a quiet month
//     (founder decision 2026-10-04: same as Tu mes, real zeros are shown),
//   - the invitation "Tu mes · Mira lo que entra y sale" only when nothing
//     is known (first load failed): never a fake US$0.
//
// Account switches: some switch paths update activeAccount BEFORE the new
// JWT exists and the cache is cleared, so during `switching` the cache and
// any request still answer for the previous account. The row goes back to
// loading on the account change, reads/fetches nothing until the switch
// settles, and drops any answer that was requested for an earlier account
// or month.
//
// Cache: answers are fetched with 'no-cache' and kept per account/month in
// this hook: the hero must not write the shared summary cache (a hero request
// finishing after a category save would put the pre-save split back for Tu
// mes). It only READS that cache as a fast first paint.
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

const MAX_TIMEOUT_MS = 2 ** 31 - 1;

function msUntilNextMonth(now = new Date()) {
  const next = new Date(now.getFullYear(), now.getMonth() + 1, 1, 0, 0, 1);
  return Math.min(MAX_TIMEOUT_MS, Math.max(1000, next.getTime() - now.getTime()));
}

type Summary = { monthSummary: MonthSummary | null };


/** What the row shows. */
export type HeroMonthState =
  | { kind: 'hidden' }
  | { kind: 'loading' }
  | { kind: 'invite' }
  | { kind: 'month'; summary: MonthSummary };

export function useMonthHeroLine(
  accountKey: string | null | undefined,
  enabled: boolean,
  switching = false,
): HeroMonthState {
  const client = useApolloClient();
  // undefined = not known yet (loading); null = known: no month to show.
  const [chosen, setChosen] = useState<MonthSummary | null | undefined>(undefined);
  const request = useRef(0);
  const focused = useRef(false);
  // Chosen month (this or last, or null) per account + current month.
  const fresh = useRef(new Map<string, MonthSummary | null>());

  // Another account's numbers must never stay on screen, even for a frame
  // while the switch is still in flight.
  const lastAccount = useRef(accountKey);
  if (lastAccount.current !== accountKey) {
    lastAccount.current = accountKey;
    request.current += 1;
    if (chosen !== undefined) setChosen(undefined);
  }

  const load = useCallback(() => {
    if (!enabled || !accountKey) {
      request.current += 1;
      setChosen(undefined);
      return;
    }
    if (switching) return; // cache + JWT may still be the previous account's
    const { year, month } = currentYearMonth();
    const timezone = deviceTimezone();
    const key = `${accountKey}:${year}-${month}`;

    const readCached = (y: number, m: number) => {
      try {
        return client.readQuery<Summary>({ query: GET_MONTH_SUMMARY, variables: { year: y, month: m, timezone } })
          ?.monthSummary ?? null;
      } catch {
        return null;
      }
    };
    // Own answers first; else the month Tu mes already cached; otherwise
    // keep what is on screen until the answer lands.
    if (fresh.current.has(key)) {
      setChosen(fresh.current.get(key) ?? null);
    } else {
      const cached = readCached(year, month);
      if (cached) setChosen(cached);
    }

    const fetchMonth = (y: number, m: number) => client
      .query<Summary>({ query: GET_MONTH_SUMMARY, variables: { year: y, month: m, timezone }, fetchPolicy: 'no-cache' })
      .then(({ data }) => data?.monthSummary ?? null);

    const id = ++request.current;
    fetchMonth(year, month)
      .then((answer) => {
        if (id !== request.current) return; // asked for an earlier account/month
        fresh.current.set(key, answer);
        setChosen(answer);
      })
      .catch(() => {
        // Optional row: on error keep what is shown; if nothing was known
        // yet, fall back to the invitation (it still opens Tu mes, which has
        // its own retry) rather than a placeholder forever.
        if (id !== request.current) return;
        setChosen((shown) => (shown === undefined ? null : shown));
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

  if (!enabled || !accountKey) return { kind: 'hidden' };
  if (chosen === undefined) return { kind: 'loading' };
  return chosen ? { kind: 'month', summary: chosen } : { kind: 'invite' };
}
